"""Google Gemini provider client (Provider A) — REST generateContent API."""

import logging

from services.llm_base import LLM_TIMEOUT_S, LLMClient, UpstreamError, request_with_retry

logger = logging.getLogger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


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

    async def generate(self, prompt: str) -> str:
        """Generate a completion, retrying once on the fallback model.

        A 404 (model retired) switches to the fallback model permanently;
        any other exhausted failure (overload 503, rate limit, timeout)
        tries the fallback model once for this request only.
        """
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
                "Gemini model %r unavailable (%s); trying fallback %r for this request",
                self.model, exc, self._fallback_model,
            )
            return await self._call(self._fallback_model, prompt)

    async def _call(self, model: str, prompt: str) -> str:
        url = f"{GEMINI_BASE_URL}/{model}:generateContent"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 8192,
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
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError, TypeError) as exc:
            raise UpstreamError("gemini returned an unexpected response shape") from exc
        if not text.strip():
            raise UpstreamError("gemini returned an empty completion")
        return text
