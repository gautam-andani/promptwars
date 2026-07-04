"""Brave Search API client with graceful degradation.

Search is best-effort: any failure returns an empty result list and logs a
warning, so a Brave outage or missing key never blocks the pipeline.
"""

import logging

from services.llm_base import UpstreamError, request_with_retry

logger = logging.getLogger(__name__)

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


async def search(api_key: str, query: str, count: int = 5) -> list[dict[str, str]]:
    """Run one Brave web search.

    Args:
        api_key: Brave Search subscription token.
        query: Search query string.
        count: Maximum number of results to return.

    Returns:
        Simplified results ``[{"title", "url", "snippet"}, ...]`` — empty on
        any failure.
    """
    headers = {"X-Subscription-Token": api_key, "Accept": "application/json"}
    params = {"q": query, "count": count}
    try:
        response = await request_with_retry(
            "brave", "GET", BRAVE_SEARCH_URL, headers=headers, params=params
        )
    except UpstreamError as exc:
        logger.warning(
            "Brave search failed for query %r (%s); continuing without it",
            query, type(exc).__name__,
        )
        return []

    try:
        results = response.json().get("web", {}).get("results", []) or []
    except ValueError:
        logger.warning("Brave search returned non-JSON for query %r", query)
        return []

    return [
        {
            "title": str(item.get("title", "")),
            "url": str(item.get("url", "")),
            "snippet": str(item.get("description", "")),
        }
        for item in results[:count]
        if isinstance(item, dict)
    ]
