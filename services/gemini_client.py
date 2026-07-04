"""Google Gemini provider client — REST generateContent API."""

import logging
import time

from services.llm_base import LLM_TIMEOUT_S, LLMClient, UpstreamError, request_with_retry

logger = logging.getLogger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
# After the primary model exhausts its retries (overload/rate limit), route
# straight to the fallback model for this long instead of re-hammering it.
OVERLOAD_COOLDOWN_S = 300.0
# Generous budget: Gemini 2.5+/3.x "thinking" tokens count against
# maxOutputTokens, so a tight limit silently truncates large JSON outputs.
MAX_OUTPUT_TOKENS = 16384


class GeminiClient(LLMClient):
    """Client for Google's Gemini free-tier REST API.

    Falls back to the configured fallback model once if the primary model
    returns 404 (model not found / retired).
    """

    name = "gemini"

    def __init__(self, api_key: str, model: str, fallback_model: str) -> None:
        self._api_key = api_key
        self.model = model
        self._fallback_model = fallback_model
        self._prefer_fallback_until = 0.0

    async def generate(self, prompt: str) -> str:
        """Generate a completion with model-level failover.

        A 404 (model retired) switches to the fallback model permanently.
        Any other exhausted failure (overload 503, rate limit, timeout) uses
        the fallback model for this request and keeps preferring it for a
        cooldown window, so back-to-back calls don't re-pay the retry ladder
        against a model that is known to be overloaded.
        """
        if (
            self.model != self._fallback_model
            and time.monotonic() < self._prefer_fallback_until
        ):
            return await self._call(self._fallback_model, prompt)
        try:
            return await self._call(self.model, prompt)
        except UpstreamError as exc:
            if self.model == self._fallback_model:
                raise
            if exc.status_code == 404:
                logger.warning(
                    "Gemini model %r not found (404); switching to %r permanently",
                    self.model, self._fallback_model,
                )
                self.model = self._fallback_model
                return await self._call(self.model, prompt)
            logger.warning(
                "Gemini model %r unavailable (%s); using fallback %r for the "
                "next %.0f seconds",
                self.model, exc, self._fallback_model, OVERLOAD_COOLDOWN_S,
            )
            result = await self._call(self._fallback_model, prompt)
            self._prefer_fallback_until = time.monotonic() + OVERLOAD_COOLDOWN_S
            return result

    async def _call(self, model: str, prompt: str) -> str:
        url = f"{GEMINI_BASE_URL}/{model}:generateContent"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": MAX_OUTPUT_TOKENS,
                "responseMimeType": "application/json",
            },
        }
        response = await request_with_retry(
            self.name,
            "POST",
            url,
            headers={"content-type": "application/json"},
            params={"key": self._api_key},
            json_body=body,
            timeout_s=LLM_TIMEOUT_S,
        )
        data = response.json()
        try:
            candidate = data["candidates"][0]
            parts = candidate["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError, TypeError) as exc:
            raise UpstreamError("gemini returned an unexpected response shape") from exc
        if candidate.get("finishReason") == "MAX_TOKENS":
            logger.warning(
                "gemini response hit MAX_TOKENS (model=%s) — output may be truncated",
                model,
            )
        if not text.strip():
            raise UpstreamError("gemini returned an empty completion")
        return text
