"""Pydantic request/response schemas for CultureCompass.

All user-supplied strings are sanitized (HTML tags stripped) before
validation. LLM-produced payloads are validated leniently: unknown
attraction types are coerced to ``"attraction"`` rather than rejected, so
one malformed field never sinks an otherwise good response.
"""

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

MONTH_NAMES: tuple[str, ...] = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

_HTML_TAG_RE = re.compile(r"<[^>]*>")


def sanitize_text(value: str) -> str:
    """Strip HTML tags and surrounding whitespace from user-supplied text."""
    return _HTML_TAG_RE.sub("", value).strip()


class TravelRequest(BaseModel):
    """Incoming discovery request from the frontend."""

    destination: str = Field(min_length=2, max_length=80)
    travel_month: str
    extra_radius_km: int = Field(default=100, ge=0, le=500)
    interests: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("destination", mode="before")
    @classmethod
    def _sanitize_destination(cls, value: object) -> object:
        if isinstance(value, str):
            return sanitize_text(value)
        return value

    @field_validator("travel_month", mode="before")
    @classmethod
    def _validate_month(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        month = sanitize_text(value).capitalize()
        if month not in MONTH_NAMES:
            raise ValueError(
                "travel_month must be a month name: " + ", ".join(MONTH_NAMES)
            )
        return month

    @field_validator("interests", mode="before")
    @classmethod
    def _sanitize_interests(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        cleaned = [sanitize_text(item) for item in value if isinstance(item, str)]
        cleaned = [item for item in cleaned if item]
        for item in cleaned:
            if len(item) > 40:
                raise ValueError("each interest must be at most 40 characters")
        return cleaned


AttractionType = Literal["attraction", "hidden_gem", "heritage", "experience"]
_VALID_ATTRACTION_TYPES = {"attraction", "hidden_gem", "heritage", "experience"}


class Attraction(BaseModel):
    """A single recommended place or experience."""

    name: str = Field(min_length=1)
    type: AttractionType = "attraction"
    lat: float
    lon: float
    why_this_month: str = ""
    authenticity_tip: str = ""
    wikipedia_title: Optional[str] = None
    photo_url: Optional[str] = None
    sources: list[str] = Field(default_factory=list)

    @field_validator("type", mode="before")
    @classmethod
    def _coerce_type(cls, value: object) -> str:
        if isinstance(value, str):
            normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
            if normalized in _VALID_ATTRACTION_TYPES:
                return normalized
        return "attraction"

    @field_validator("sources", mode="before")
    @classmethod
    def _coerce_sources(cls, value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if item]
        return []


class Story(BaseModel):
    """An immersive second-person narrative for a top pick."""

    place: str
    narrative: str


class LocalEvent(BaseModel):
    """A local event or festival happening during the travel month."""

    name: str
    dates: str = ""
    description: str = ""


class SeasonalAlternative(BaseModel):
    """What the same destination offers in a different season."""

    season: str
    why: str = ""
    highlights: list[str] = Field(default_factory=list)

    @field_validator("highlights", mode="before")
    @classmethod
    def _coerce_highlights(cls, value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if item]
        return []


class NearbyRecommendation(BaseModel):
    """A nearby city worth the extra kilometers."""

    city: str
    distance_km: int = 0
    highlights: list[str] = Field(default_factory=list)
    lat: float
    lon: float

    @field_validator("distance_km", mode="before")
    @classmethod
    def _coerce_distance(cls, value: object) -> int:
        try:
            return int(round(float(value)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0

    @field_validator("highlights", mode="before")
    @classmethod
    def _coerce_highlights(cls, value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if item]
        return []


class TravelResponse(BaseModel):
    """Full discovery response returned to the frontend."""

    destination: str
    month: str
    search_used: bool = False
    degraded: bool = False
    attractions: list[Attraction] = Field(default_factory=list)
    stories: list[Story] = Field(default_factory=list)
    local_events: list[LocalEvent] = Field(default_factory=list)
    seasonal_alternatives: list[SeasonalAlternative] = Field(default_factory=list)
    nearby_recommendations: list[NearbyRecommendation] = Field(default_factory=list)
