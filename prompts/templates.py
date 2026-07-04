"""All LLM prompts for Side Quest live here as constants.

Templates use ``str.format`` placeholders. The literal JSON schemas are kept
as separate constants (injected via a ``{schema}`` placeholder) so the
templates themselves contain no raw braces that would break formatting.
"""

STRICT_JSON_SUFFIX = "\n\nReturn ONLY valid JSON, no prose"

RECOMMENDER_SCHEMA = """{
  "attractions": [
    {
      "name": "Exact place name",
      "type": "attraction|hidden_gem|heritage|experience",
      "lat": 22.7196,
      "lon": 75.8577,
      "why_this_month": "Month-specific reasoning: weather, festivals, seasonal food, crowd levels",
      "authenticity_tip": "One practical insider tip to experience it like a local",
      "wikipedia_title": "Exact English Wikipedia article title, or null if none plausibly exists"
    }
  ]
}"""

RECOMMENDER_PROMPT = """You are an expert local travel curator with deep, on-the-ground knowledge of {destination} and its surrounding region. You know the famous landmarks, but you also know the alleys, the family-run food stalls, the artisan workshops, and the festivals only locals attend.

Traveler details:
- Destination: {destination}
- Month of travel: {month}
- Interests: {interests}

Your task: recommend 15-20 items for this traveler, mixing:
- Famous attractions worth the crowds
- Hidden gems known mostly to locals
- Heritage sites (forts, temples, monuments, old quarters)
- Authentic experiences (food streets, artisan workshops, community events, markets)

Rules for every item:
1. Provide real, accurate latitude and longitude coordinates.
2. "why_this_month" must be specific to {month}: weather, festivals, seasonal food, harvest, migrations, crowd levels — never generic.
3. Include exactly one practical authenticity tip (best time of day, what to order, whom to ask, how locals do it).
4. Set "wikipedia_title" to the exact English Wikipedia article title when the place plausibly has one; otherwise null.
5. Weight the mix toward the traveler's stated interests when given, but keep variety.

Output ONLY valid JSON matching this exact schema — no prose, no markdown fences, no comments:
{schema}"""

SYNTHESIS_SCHEMA = """{
  "destination": "City name",
  "month": "Month name",
  "attractions": [
    {
      "name": "Exact place name",
      "type": "attraction|hidden_gem|heritage|experience",
      "lat": 22.7196,
      "lon": 75.8577,
      "why_this_month": "Month-specific reasoning",
      "authenticity_tip": "One insider tip",
      "wikipedia_title": "Exact English Wikipedia article title or null",
      "sources": ["gemini", "provider_b", "search"]
    }
  ],
  "stories": [
    {
      "place": "Name of one of the top 3 attractions",
      "narrative": "A 120-180 word immersive second-person story"
    }
  ],
  "local_events": [
    {
      "name": "Event or festival name",
      "dates": "Dates or date range as stated in the sources",
      "description": "One or two sentences on what happens and why it matters"
    }
  ],
  "seasonal_alternatives": [
    {
      "season": "Season or month range",
      "why": "What changes at this destination then and why it is worth visiting",
      "highlights": ["highlight 1", "highlight 2"]
    }
  ],
  "nearby_recommendations": [
    {
      "city": "Nearby city or town name",
      "distance_km": 55,
      "highlights": ["highlight 1", "highlight 2"],
      "lat": 23.1793,
      "lon": 75.7849
    }
  ]
}"""

SYNTHESIS_PROMPT = """You are a master travel editor and storyteller. Two independent AI travel curators have proposed candidate recommendations for a trip, and live web-search snippets are provided for corroboration. Produce the single, definitive travel plan.

Traveler details:
- Destination: {destination}
- Month of travel: {month}
- Willing to travel up to {radius_km} km beyond the destination for day trips
- Interests: {interests}

Candidate list A (from Gemini — every item carries sources ["gemini"]):
{gemini_json}

Candidate list B (from a second model — every item carries sources ["provider_b"]):
{provider_b_json}

Web search snippets (may be empty if search was unavailable):
{search_snippets}

Your tasks:
1. DEDUPLICATE: merge items that are the same place under different names or spellings. When merging, union their "sources" arrays.
2. RANK: select and rank the top 5-10 attractions for {month} specifically. Prefer items that appear in BOTH candidate lists or are corroborated by the search snippets; add "search" to an item's sources when a snippet corroborates it. Keep a healthy mix of types and respect the traveler's interests.
3. STORIES: for exactly the top 3 ranked attractions, write a vivid 120-180 word immersive story in the second person ("you"). Weave in sights, sounds, smells, taste, and a thread of history. No bullet points — flowing sensory prose.
4. LOCAL EVENTS: extract events and festivals happening in or around {month} from the search snippets. If no snippets are available, include only well-known events you are confident occur in {month}, and phrase dates approximately (e.g. "mid-{month}").
5. SEASONAL ALTERNATIVES: describe 3-4 other seasons or month-ranges at {destination} — what changes (weather, festivals, scenery, crowds) and why a traveler might choose that season instead.
6. NEARBY RECOMMENDATIONS: suggest 2-5 real cities or towns within {radius_km} km of {destination}, each with realistic road distance in km, real coordinates, and 2-3 concrete highlights. If the radius is 0, return an empty list.
7. Preserve accurate lat/lon coordinates and "wikipedia_title" values for every attraction; correct them if a candidate got them wrong.

Output ONLY valid JSON matching this exact schema — no prose, no markdown fences, no comments:
{schema}"""


def _format_interests(interests: list[str]) -> str:
    """Render the interests list for prompt injection."""
    return ", ".join(interests) if interests else "no specific interests — curate a balanced mix"


def build_recommender_prompt(destination: str, month: str, interests: list[str]) -> str:
    """Build the standardized recommendation prompt used by Providers A and B."""
    return RECOMMENDER_PROMPT.format(
        destination=destination,
        month=month,
        interests=_format_interests(interests),
        schema=RECOMMENDER_SCHEMA,
    )


def build_synthesis_prompt(
    destination: str,
    month: str,
    radius_km: int,
    interests: list[str],
    gemini_json: str,
    provider_b_json: str,
    search_snippets: str,
) -> str:
    """Build the Claude synthesis prompt from provider outputs and search snippets."""
    return SYNTHESIS_PROMPT.format(
        destination=destination,
        month=month,
        radius_km=radius_km,
        interests=_format_interests(interests),
        gemini_json=gemini_json,
        provider_b_json=provider_b_json,
        search_snippets=search_snippets or "(no search results available)",
        schema=SYNTHESIS_SCHEMA,
    )
