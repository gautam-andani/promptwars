"""Pipeline orchestration for CultureCompass.

Stage 1 (parallel): three Brave searches + the same recommendation prompt to
Provider A (Gemini) and Provider B (Groq).
Stage 2: a fast, high-RPM Gemini synthesis model deduplicates, ranks, writes
stories, and produces the final response JSON. If synthesis fails, a merged
provider fallback is returned with ``degraded=true``.
Stage 3: Wikipedia thumbnails are hydrated concurrently, the payload is
validated with Pydantic, and the response is returned.
"""

import asyncio
import datetime
import json
import logging
import re
import urllib.parse
from typing import Any, Optional

import httpx
from pydantic import ValidationError

from config import settings
from models.schemas import (
    Attraction,
    LocalEvent,
    NearbyRecommendation,
    SeasonalAlternative,
    Story,
    TravelRequest,
    TravelResponse,
)
from prompts.templates import (
    STRICT_JSON_SUFFIX,
    build_recommender_prompt,
    build_synthesis_prompt,
)
from services import brave_search
from services.gemini_client import GeminiClient
from services.groq_client import GroqClient
from services.llm_base import LLMClient, UpstreamError

logger = logging.getLogger(__name__)

WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/"
WIKIPEDIA_TIMEOUT_S = 5.0
MAX_ATTRACTIONS = 10
MAX_STORIES = 3

_provider_a: Optional[GeminiClient] = None
_provider_b: Optional[LLMClient] = None
_synthesizer: Optional[GeminiClient] = None

_CODE_FENCE_OPEN_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*")
_NAME_KEY_RE = re.compile(r"[^a-z0-9]")


def _build_clients() -> tuple[GeminiClient, LLMClient, GeminiClient]:
    """Build (once) and return the provider clients from settings."""
    global _provider_a, _provider_b, _synthesizer
    if _provider_a is None:
        _provider_a = GeminiClient(
            settings.GEMINI_API_KEY, settings.GEMINI_MODEL, settings.GEMINI_FALLBACK_MODEL
        )
    if _provider_b is None:
        _provider_b = GroqClient(settings.GROQ_API_KEY, settings.GROQ_MODEL)
        logger.info("Provider B: %s (model=%s)", _provider_b.name, _provider_b.model)
    if _synthesizer is None:
        _synthesizer = GeminiClient(
            settings.GEMINI_API_KEY,
            settings.GEMINI_SYNTHESIS_MODEL,
            settings.GEMINI_FALLBACK_MODEL,
        )
        _synthesizer.name = "gemini-synthesis"
        logger.info("Synthesizer: gemini (model=%s)", _synthesizer.model)
    return _provider_a, _provider_b, _synthesizer


async def startup_checks() -> None:
    """Build provider clients and verify the Groq model list at startup."""
    _, provider_b, _ = _build_clients()
    if isinstance(provider_b, GroqClient):
        await provider_b.verify_model()


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from an LLM response."""
    text = text.strip()
    if text.startswith("```"):
        text = _CODE_FENCE_OPEN_RE.sub("", text)
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _parse_json_object(raw: str) -> dict[str, Any]:
    """Parse an LLM response into a JSON object.

    Strips code fences first; if the whole string still fails to parse,
    retries on the outermost ``{...}`` span (models sometimes prepend prose
    despite instructions).

    Raises:
        json.JSONDecodeError: if no JSON object can be recovered.
    """
    text = _strip_code_fences(raw)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("expected a JSON object at the top level", text, 0)
    return parsed


async def _generate_json(client: LLMClient, prompt: str) -> dict[str, Any]:
    """Call an LLM and parse JSON, retrying the call once on a parse failure."""
    raw = await client.generate(prompt)
    try:
        return _parse_json_object(raw)
    except json.JSONDecodeError:
        logger.warning(
            "%s returned invalid JSON; retrying once with a stricter instruction",
            client.name,
        )
        raw = await client.generate(prompt + STRICT_JSON_SUFFIX)
        return _parse_json_object(raw)


async def _candidates_from(
    client: LLMClient, prompt: str, source_tag: str
) -> Optional[list[dict[str, Any]]]:
    """Fetch and tag one provider's candidate attractions.

    Returns None (and logs) on any failure so the pipeline can continue with
    the other provider.
    """
    try:
        payload = await _generate_json(client, prompt)
    except Exception as exc:
        logger.warning(
            "Provider %s failed (%s); continuing without it",
            client.name, type(exc).__name__,
        )
        return None
    items = payload.get("attractions")
    if not isinstance(items, list):
        logger.warning(
            "Provider %s returned no 'attractions' list; ignoring its output",
            client.name,
        )
        return None
    tagged: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict) and item.get("name"):
            item["sources"] = [source_tag]
            tagged.append(item)
    if not tagged:
        logger.warning("Provider %s returned zero usable attractions", client.name)
        return None
    return tagged


async def _run_searches(request: TravelRequest) -> list[dict[str, str]]:
    """Run the three Brave queries in parallel; [] when search is unavailable."""
    if not settings.BRAVE_API_KEY:
        return []
    year = datetime.date.today().year
    queries = (
        f"{request.destination} events festivals {request.travel_month} {year}",
        f"{request.destination} hidden gems local culture",
        f"{request.destination} heritage sites",
    )
    result_lists = await asyncio.gather(
        *(brave_search.search(settings.BRAVE_API_KEY, query) for query in queries)
    )
    snippets: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for results in result_lists:
        for result in results:
            if result["url"] and result["url"] not in seen_urls:
                seen_urls.add(result["url"])
                snippets.append(result)
    return snippets


def _format_snippets(snippets: list[dict[str, str]]) -> str:
    """Render search snippets as a compact bullet list for the prompt."""
    return "\n".join(
        f"- {item['title']}: {item['snippet']} (source: {item['url']})"
        for item in snippets[:15]
    )


def _merged_fallback(
    a_items: Optional[list[dict[str, Any]]],
    b_items: Optional[list[dict[str, Any]]],
) -> dict[str, Any]:
    """Merge raw provider outputs for the degraded (Claude-down) path.

    Deduplicates by normalized name, unions sources, and caps the list.
    """
    merged: dict[str, dict[str, Any]] = {}
    for item in (a_items or []) + (b_items or []):
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        key = _NAME_KEY_RE.sub("", name.lower())
        if key in merged:
            sources = merged[key].setdefault("sources", [])
            for source in item.get("sources", []):
                if source not in sources:
                    sources.append(source)
        else:
            merged[key] = item
    return {
        "attractions": list(merged.values())[:MAX_ATTRACTIONS],
        "stories": [],
        "local_events": [],
        "seasonal_alternatives": [],
        "nearby_recommendations": [],
    }


def _validate_items(model_cls: type, items: Any, label: str) -> list[Any]:
    """Validate list items individually, dropping (and logging) bad ones."""
    if not isinstance(items, list):
        return []
    valid: list[Any] = []
    for item in items:
        try:
            valid.append(model_cls.model_validate(item))
        except ValidationError as exc:
            logger.debug("Dropping invalid %s item (%s)", label, exc.error_count())
    return valid


async def _fetch_wikipedia_thumbnail(title: str) -> Optional[str]:
    """Fetch a Wikipedia page-summary thumbnail URL; None on any failure."""
    url = WIKIPEDIA_SUMMARY_URL + urllib.parse.quote(title.replace(" ", "_"), safe="")
    try:
        async with httpx.AsyncClient(
            timeout=WIKIPEDIA_TIMEOUT_S, follow_redirects=True
        ) as client:
            response = await client.get(
                url,
                headers={"User-Agent": "CultureCompass/1.0 (travel discovery app)"},
            )
        if response.status_code != 200:
            return None
        thumbnail = response.json().get("thumbnail") or {}
        source = thumbnail.get("source")
        return source if isinstance(source, str) else None
    except (httpx.HTTPError, ValueError):
        return None


async def _hydrate_photos(attractions: list[Attraction]) -> None:
    """Concurrently fill photo_url from Wikipedia thumbnails where possible."""
    targets = [a for a in attractions if a.wikipedia_title and not a.photo_url]
    if not targets:
        return
    thumbnails = await asyncio.gather(
        *(_fetch_wikipedia_thumbnail(a.wikipedia_title or "") for a in targets)
    )
    hydrated = 0
    for attraction, thumbnail in zip(targets, thumbnails):
        if thumbnail:
            attraction.photo_url = thumbnail
            hydrated += 1
    logger.info("Hydrated %d/%d Wikipedia thumbnails", hydrated, len(targets))


async def discover(request: TravelRequest) -> TravelResponse:
    """Run the full three-stage discovery pipeline for a request.

    Raises:
        UpstreamError: only when BOTH recommendation providers fail.
    """
    provider_a, provider_b, synthesizer = _build_clients()
    recommender_prompt = build_recommender_prompt(
        request.destination, request.travel_month, request.interests
    )

    # Stage 1 — parallel fan-out: search x3 + both recommendation providers.
    snippets, a_items, b_items = await asyncio.gather(
        _run_searches(request),
        _candidates_from(provider_a, recommender_prompt, "gemini"),
        _candidates_from(provider_b, recommender_prompt, "provider_b"),
    )
    if a_items is None and b_items is None:
        raise UpstreamError("both recommendation providers failed")
    search_used = bool(snippets)
    logger.info(
        "Stage 1 complete: gemini=%s provider_b=%s search_snippets=%d",
        len(a_items) if a_items else 0,
        len(b_items) if b_items else 0,
        len(snippets),
    )

    # Stage 2 — synthesis (deduplicate, rank, stories, extras).
    synthesis_prompt = build_synthesis_prompt(
        destination=request.destination,
        month=request.travel_month,
        radius_km=request.extra_radius_km,
        interests=request.interests,
        gemini_json=json.dumps(a_items or [], ensure_ascii=False),
        provider_b_json=json.dumps(b_items or [], ensure_ascii=False),
        search_snippets=_format_snippets(snippets),
    )
    degraded = False
    try:
        payload = await _generate_json(synthesizer, synthesis_prompt)
    except Exception as exc:
        logger.warning(
            "Synthesis failed (%s); returning merged provider output "
            "with degraded=true",
            type(exc).__name__,
        )
        payload = _merged_fallback(a_items, b_items)
        degraded = True

    # Stage 3 — validate leniently, hydrate photos, return.
    attractions = _validate_items(
        Attraction, payload.get("attractions"), "attraction"
    )[:MAX_ATTRACTIONS]
    response = TravelResponse(
        destination=request.destination,
        month=request.travel_month,
        search_used=search_used,
        degraded=degraded,
        attractions=attractions,
        stories=_validate_items(Story, payload.get("stories"), "story")[:MAX_STORIES],
        local_events=_validate_items(
            LocalEvent, payload.get("local_events"), "local_event"
        ),
        seasonal_alternatives=_validate_items(
            SeasonalAlternative,
            payload.get("seasonal_alternatives"),
            "seasonal_alternative",
        ),
        nearby_recommendations=_validate_items(
            NearbyRecommendation,
            payload.get("nearby_recommendations"),
            "nearby_recommendation",
        ),
    )
    await _hydrate_photos(response.attractions)
    return response
