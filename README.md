# 🧭 Side Quest

Side Quest is a GenAI travel & culture discovery platform. Enter a destination city, your
travel month, and how far you'll roam — it fans out to **two
independent LLM curators** (plus optional live web search), then a fast
synthesis model merges everything into a single, month-specific plan: ranked
attractions, hidden gems, local festivals, immersive stories, seasonal
alternatives, and nearby cities — all pinned on an interactive map.

## How it works

```
                      ┌──────────────────────────────────┐
   Stage 1 (parallel) │ Brave Search × 3 queries (opt.)  │
                      │ Gemini (gemini-3.5-flash)        │  same prompt,
                      │ Groq (llama-3.3-70b-versatile)   │  same JSON schema
                      └──────────────┬───────────────────┘
                                     ▼
   Stage 2            Gemini synthesis (gemini-2.5-flash-lite, high RPM):
                      dedupe · rank for the month · 3 stories ·
                      events · seasonal alternatives · nearby cities
                                     ▼
   Stage 3            Wikipedia thumbnails (concurrent) · Pydantic validation
```

Two Gemini models are used deliberately: the main recommender model has a
low free-tier RPM (2–5/min), so the synthesis stage runs on
`gemini-2.5-flash-lite` (~10 requests/min free) to spread quota across the
pipeline.

**Resilience:** every external call has retries with exponential backoff
(1s, 3s) on 429/5xx/timeouts — 30s timeout for search/metadata, 90s for LLM
generation. If one recommendation provider dies, the other carries the
request; only if *both* fail does the API return 502. If the synthesis stage
fails, you still get the merged provider output with `degraded: true` (the
UI shows a subtle banner). No Brave key? Search is skipped and `search_used`
is `false`.

## Design priorities

The codebase is organized and invested in this order:

1. **Problem statement (high)** — the full multi-LLM pipeline: two independent
   curators → synthesis (dedupe, rank-for-month, stories, events, seasons,
   nearby cities) → map + photos. See `services/orchestrator.py` and
   `prompts/templates.py`.
2. **Code quality (high)** — typed, docstring-covered modules; providers
   behind one abstract `LLMClient`; all prompts in one place; Pydantic
   validation at every boundary; structured logging (no prints).
3. **Efficiency (medium)** — Stage 1 fans out in parallel (`asyncio.gather`);
   photo hydration is concurrent; quota is split across two Gemini models so
   the low-RPM recommender is called exactly once per request.
4. **Security (medium)** — input sanitization, per-IP rate limiting, CORS
   allowlist, generic client errors with server-side-only causes, `.env`
   key hygiene.
5. **Accessibility (low)** — semantic HTML, labeled controls,
   `aria-live` loading state, `aria-pressed` interest chips, focus-visible
   outlines, and `prefers-reduced-motion` support.
6. **Fallbacks (low)** — provider failover, Gemini model fallback on
   404/overload, JSON-repair retry, degraded mode when synthesis fails,
   graceful no-search operation.

## Project layout

```
main.py                      FastAPI app, rate limiting, CORS, static serving
config.py                    pydantic-settings config + fail-fast validation
models/schemas.py            Request/response Pydantic models
prompts/templates.py         All LLM prompts (recommender + synthesis)
services/
  llm_base.py                Abstract LLMClient + shared retry/timeout plumbing
  gemini_client.py           Gemini REST client (404 → fallback model)
  groq_client.py             Groq client (startup model verification)
  brave_search.py            Brave Search with graceful degradation
  orchestrator.py            The 3-stage pipeline
static/
  index.html                 Frontend markup (Tailwind CDN + Leaflet)
  styles.css                 Custom styles: aurora, glass, loader, animations
  app.js                     Frontend logic: form, fetch, map, rendering
scripts/check_providers.py   Per-provider key smoke test (run before serving)
```

## Local setup

Requires **Python 3.11+**.

```bash
# 1. Create a virtualenv and install dependencies
python3 -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Configure keys
cp .env.example .env
# edit .env — set GEMINI_API_KEY and GROQ_API_KEY (both free),
# and optionally BRAVE_API_KEY

# 3. Verify every key with a 1-token call per provider
python scripts/check_providers.py

# 4. Run
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000> — the frontend is served by FastAPI itself.
API docs live at `/docs`; health check at `/api/health`.

### Free-tier notes

- **Gemini** free-tier RPM varies by model; each discovery makes 1 call on
  the main model and 1 on the synthesis model (plus at most 1 JSON-repair
  retry each). The endpoint is rate-limited to 5 requests/min per IP.
- **Groq** models rotate; at startup the app fetches Groq's live model list,
  logs it, and auto-selects a llama/qwen chat model if the configured one is
  gone (with a warning).

### API

`POST /api/discover` (rate-limited to 5/min per IP):

```json
{
  "destination": "Indore",
  "travel_month": "September",
  "extra_radius_km": 200,
  "interests": ["heritage", "food"]
}
```

Response: `TravelResponse` — see `models/schemas.py` for the full schema
(`attractions`, `stories`, `local_events`, `seasonal_alternatives`,
`nearby_recommendations`, plus `search_used` / `degraded` flags).

## Deploy on Render

1. Push this repository to GitHub (`.env` is git-ignored — verify with
   `git status` before pushing).
2. In Render: **New → Web Service**, connect the repo.
3. Configure:
   - **Runtime:** Python 3.11+
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add environment variables in the Render dashboard: `GEMINI_API_KEY`,
   `GROQ_API_KEY`, optionally `BRAVE_API_KEY`, and set `ALLOWED_ORIGINS` to
   your Render URL (e.g. `https://your-app.onrender.com`).
5. Deploy. The app fails fast with a clear message naming any missing key.

## Security

- Input sanitization (HTML stripped) + strict Pydantic length limits
- 5 req/min/IP rate limit on `/api/discover` (slowapi)
- CORS restricted via `ALLOWED_ORIGINS`
- Generic error messages to clients (502 "Upstream AI service unavailable",
  500 "Something went wrong"); real causes logged server-side only
- Keys via `.env` / environment; `.gitignore` blocks `.env`; a loud warning
  is logged if the local-dev `HARDCODED_KEYS` escape hatch is ever used
