"""Application configuration for CultureCompass.

Settings are read from environment variables / a local ``.env`` file via
pydantic-settings. A clearly-marked local-dev escape hatch below allows
pasting keys directly; environment variables always take precedence.
"""

import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# ── LOCAL DEV ONLY: paste keys here if not using .env — NEVER COMMIT ──
HARDCODED_KEYS = {
    "GEMINI_API_KEY": "",
    "GROQ_API_KEY": "",
    "BRAVE_API_KEY": "",
}


class Settings(BaseSettings):
    """Runtime configuration, sourced from the environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    BRAVE_API_KEY: str = ""

    ALLOWED_ORIGINS: str = "*"
    LOG_LEVEL: str = "INFO"

    # Provider A — main recommender (low free-tier RPM, strongest quality).
    GEMINI_MODEL: str = "gemini-3.5-flash"
    GEMINI_FALLBACK_MODEL: str = "gemini-3.1-flash-lite"
    # Synthesis model — higher free-tier RPM (~10/min), used for the
    # dedupe/rank/storytelling stage so the main model's quota is spared.
    GEMINI_SYNTHESIS_MODEL: str = "gemini-2.5-flash-lite"
    # Provider B — second independent recommender.
    GROQ_MODEL: str = "llama-3.3-70b-versatile"


settings = Settings()


def apply_hardcoded_fallbacks() -> None:
    """Fill missing keys from HARDCODED_KEYS, warning loudly when one is used."""
    for key, value in HARDCODED_KEYS.items():
        if value and not getattr(settings, key):
            setattr(settings, key, value)
            logger.warning(
                "SECURITY WARNING: %s is being read from HARDCODED_KEYS in "
                "config.py. Move it to a .env file and NEVER commit real keys.",
                key,
            )


def validate_settings() -> None:
    """Fail fast at startup if a required API key is missing.

    Raises:
        RuntimeError: naming each missing key so the operator can fix .env.
    """
    apply_hardcoded_fallbacks()

    missing: list[str] = []
    if not settings.GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if not settings.GROQ_API_KEY:
        missing.append("GROQ_API_KEY")

    if missing:
        raise RuntimeError(
            "Missing required configuration: "
            + ", ".join(missing)
            + ". Set the key(s) in your environment or .env file and restart."
        )

    if not settings.BRAVE_API_KEY:
        logger.warning(
            "BRAVE_API_KEY is not set — web search is disabled; the pipeline "
            "will degrade gracefully to LLM knowledge only."
        )
