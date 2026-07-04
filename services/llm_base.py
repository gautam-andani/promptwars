"""Abstract LLM client base class and shared HTTP retry plumbing.

Every outbound call in the app funnels through :func:`request_with_retry`,
which enforces the resilience contract: 30s timeout, two retries with
exponential backoff (1s, 3s) on 429/5xx/timeouts, and structured logging of
provider name, latency, and error class for every attempt.
"""

import abc
import asyncio
import logging
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 30.0
# LLM generation calls produce thousands of tokens and routinely exceed 30s
# on free tiers; they get a longer per-attempt budget than search/metadata.
LLM_TIMEOUT_S = 90.0
RETRY_DELAYS_S: tuple[float, ...] = (1.0, 3.0)
MAX_ATTEMPTS = 1 + len(RETRY_DELAYS_S)


class UpstreamError(Exception):
    """An upstream AI/search service call ultimately failed."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _is_retryable(status_code: int) -> bool:
    """Return True for statuses worth retrying: rate limits and server errors."""
    return status_code == 429 or status_code >= 500


async def request_with_retry(
    provider: str,
    method: str,
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    params: Optional[dict[str, Any]] = None,
    json_body: Optional[dict[str, Any]] = None,
    timeout_s: float = REQUEST_TIMEOUT_S,
) -> httpx.Response:
    """Issue an HTTP request with retries and per-attempt logging.

    Args:
        provider: Short provider name used in log lines (never the URL, which
            may carry an API key in its query string).
        method: HTTP method.
        url: Full request URL.
        headers: Optional request headers.
        params: Optional query parameters.
        json_body: Optional JSON request body.
        timeout_s: Per-attempt timeout in seconds.

    Returns:
        The successful ``httpx.Response`` (status < 400).

    Raises:
        UpstreamError: after all attempts fail, or immediately on a
            non-retryable 4xx response (with ``status_code`` set).
    """
    last_error: Optional[Exception] = None
    for attempt, delay_s in enumerate((0.0, *RETRY_DELAYS_S), start=1):
        if delay_s:
            await asyncio.sleep(delay_s)
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.request(
                    method, url, headers=headers, params=params, json=json_body
                )
        except httpx.TimeoutException as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.warning(
                "%s call timed out (latency=%dms attempt=%d/%d error=%s)",
                provider, latency_ms, attempt, MAX_ATTEMPTS, type(exc).__name__,
            )
            last_error = exc
            continue
        except httpx.HTTPError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.warning(
                "%s call failed (latency=%dms attempt=%d/%d error=%s)",
                provider, latency_ms, attempt, MAX_ATTEMPTS, type(exc).__name__,
            )
            last_error = exc
            continue

        latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code < 400:
            logger.info(
                "%s call succeeded (status=%d latency=%dms attempt=%d/%d)",
                provider, response.status_code, latency_ms, attempt, MAX_ATTEMPTS,
            )
            return response
        if _is_retryable(response.status_code):
            logger.warning(
                "%s call failed (status=%d latency=%dms attempt=%d/%d)",
                provider, response.status_code, latency_ms, attempt, MAX_ATTEMPTS,
            )
            last_error = UpstreamError(
                f"{provider} returned HTTP {response.status_code}",
                status_code=response.status_code,
            )
            continue
        logger.error(
            "%s call failed with non-retryable status (status=%d latency=%dms)",
            provider, response.status_code, latency_ms,
        )
        raise UpstreamError(
            f"{provider} returned HTTP {response.status_code}",
            status_code=response.status_code,
        )

    error_class = type(last_error).__name__ if last_error else "UnknownError"
    status = last_error.status_code if isinstance(last_error, UpstreamError) else None
    raise UpstreamError(
        f"{provider} unavailable after {MAX_ATTEMPTS} attempts ({error_class})",
        status_code=status,
    ) from last_error


class LLMClient(abc.ABC):
    """Abstract base class making LLM providers interchangeable."""

    name: str = "llm"

    @abc.abstractmethod
    async def generate(self, prompt: str) -> str:
        """Generate a completion for ``prompt`` and return its raw text."""
