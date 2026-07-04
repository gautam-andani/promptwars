"""Smoke-test every configured provider key with a minimal (1-token) call.

Run from the repository root before starting the server:

    python scripts/check_providers.py

Prints PASS / FAIL / SKIP per provider. Exits non-zero if any *required*
provider (Gemini recommender, Gemini synthesizer, Groq) fails.
"""

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import apply_hardcoded_fallbacks, settings  # noqa: E402

TIMEOUT_S = 20.0


def _report(provider: str, ok: bool, detail: str = "") -> None:
    """Print a single PASS/FAIL line for a provider."""
    status = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"[{status}] {provider}{suffix}")


def _skip(provider: str, reason: str) -> None:
    """Print a SKIP line for an unconfigured optional provider."""
    print(f"[SKIP] {provider} — {reason}")


async def check_gemini_model(
    client: httpx.AsyncClient, label: str, model: str, fallback: str
) -> bool:
    """1-token generateContent call; tries the fallback model on 404."""
    if not settings.GEMINI_API_KEY:
        _report(label, False, "GEMINI_API_KEY not set")
        return False
    for candidate in dict.fromkeys((model, fallback)):
        try:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{candidate}:generateContent",
                params={"key": settings.GEMINI_API_KEY},
                json={
                    "contents": [{"parts": [{"text": "Hi"}]}],
                    "generationConfig": {"maxOutputTokens": 1},
                },
            )
        except httpx.HTTPError as exc:
            _report(label, False, f"network error ({type(exc).__name__})")
            return False
        if response.status_code == 200:
            _report(label, True, f"model={candidate}")
            return True
        if response.status_code == 404:
            continue
        _report(label, False, f"HTTP {response.status_code} on model={candidate}")
        return False
    _report(label, False, "both primary and fallback models returned 404")
    return False


async def check_groq(client: httpx.AsyncClient) -> bool:
    """1-token chat completion against Groq."""
    if not settings.GROQ_API_KEY:
        _report("groq", False, "GROQ_API_KEY not set")
        return False
    try:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
            json={
                "model": settings.GROQ_MODEL,
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 1,
            },
        )
    except httpx.HTTPError as exc:
        _report("groq", False, f"network error ({type(exc).__name__})")
        return False
    ok = response.status_code == 200
    _report(
        "groq",
        ok,
        f"model={settings.GROQ_MODEL}" if ok else f"HTTP {response.status_code}",
    )
    return ok


async def check_brave(client: httpx.AsyncClient) -> bool:
    """Minimal 1-result Brave search (optional provider)."""
    if not settings.BRAVE_API_KEY:
        _skip("brave", "BRAVE_API_KEY not set (search will degrade gracefully)")
        return True
    try:
        response = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "X-Subscription-Token": settings.BRAVE_API_KEY,
                "Accept": "application/json",
            },
            params={"q": "test", "count": 1},
        )
    except httpx.HTTPError as exc:
        _report("brave", False, f"network error ({type(exc).__name__})")
        return False
    ok = response.status_code == 200
    _report("brave", ok, "" if ok else f"HTTP {response.status_code}")
    return ok


async def main() -> int:
    """Run all provider checks and return the process exit code."""
    apply_hardcoded_fallbacks()
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        recommender_ok = await check_gemini_model(
            client, "gemini-recommender", settings.GEMINI_MODEL, settings.GEMINI_FALLBACK_MODEL
        )
        synthesizer_ok = await check_gemini_model(
            client,
            "gemini-synthesizer",
            settings.GEMINI_SYNTHESIS_MODEL,
            settings.GEMINI_FALLBACK_MODEL,
        )
        groq_ok = await check_groq(client)
        brave_ok = await check_brave(client)

    print()
    if recommender_ok and synthesizer_ok and groq_ok:
        print("All required providers are healthy. You are good to go!")
        if not brave_ok:
            print("Note: Brave search failed — the app will run without web search.")
        return 0
    print("One or more required providers failed — fix the keys above before starting.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
