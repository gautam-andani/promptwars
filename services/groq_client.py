"""Groq provider client (Provider B default) — OpenAI-compatible API."""

import logging

from services.llm_base import LLM_TIMEOUT_S, LLMClient, UpstreamError, request_with_retry

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"

# Model-id substrings that mark non-chat models we must never auto-select.
_EXCLUDED_MODEL_HINTS = ("whisper", "guard", "tts", "embed", "moderation")


class GroqClient(LLMClient):
    """Client for Groq's free-tier OpenAI-compatible chat completions API."""

    name = "groq"

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self.model = model

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "content-type": "application/json",
        }

    async def verify_model(self) -> None:
        """Check the configured model against Groq's live model list.

        Called once at startup. Logs the available models; if the configured
        model is absent, auto-selects the first llama/qwen chat model and
        logs a warning. Never raises — a failed check keeps the configured
        model so a transient outage cannot block startup.
        """
        try:
            response = await request_with_retry(
                self.name, "GET", GROQ_MODELS_URL, headers=self._headers()
            )
            model_ids = sorted(
                item["id"]
                for item in response.json().get("data", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            )
            logger.info("Groq models available: %s", ", ".join(model_ids))
            if self.model in model_ids:
                return
            candidates = [
                model_id
                for model_id in model_ids
                if ("llama" in model_id.lower() or "qwen" in model_id.lower())
                and not any(hint in model_id.lower() for hint in _EXCLUDED_MODEL_HINTS)
            ]
            if candidates:
                logger.warning(
                    "Configured Groq model %r is not available; auto-selected %r",
                    self.model, candidates[0],
                )
                self.model = candidates[0]
            else:
                logger.warning(
                    "Configured Groq model %r is not in Groq's model list and no "
                    "llama/qwen chat model was found; keeping the configured model",
                    self.model,
                )
        except Exception as exc:
            logger.warning(
                "Groq model verification failed (%s); keeping configured model %r",
                type(exc).__name__, self.model,
            )

    async def generate(self, prompt: str) -> str:
        """Generate a chat completion and return the assistant message text."""
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 6000,
        }
        response = await request_with_retry(
            self.name,
            "POST",
            GROQ_CHAT_URL,
            headers=self._headers(),
            json_body=body,
            timeout_s=LLM_TIMEOUT_S,
        )
        try:
            text = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise UpstreamError("groq returned an unexpected response shape") from exc
        if not isinstance(text, str) or not text.strip():
            raise UpstreamError("groq returned an empty completion")
        return text
