# BerthIQ — Congestion Advisory System

A multi-agent system that turns port congestion signals into stakeholder-specific decisions — not just a prediction, but a recommendation with the reasoning shown and grounded in past episodes.

Built on top of the domain research and congestion tiers from a port-congestion-prediction dissertation, kept clearly separate: the dissertation is rigorous predictive modeling, this is the agentic decision layer.

## Pipeline

**Monitoring → Classification → Precedent retrieval → Decision-support → Advisory-drafting**

1. **Monitoring agent** — validates an incoming port snapshot (berth occupancy, vessel queue, average waiting time) and rejects out-of-range values before anything reaches the model
2. **Classification agent** — maps each metric to a Low/Medium/High/Critical tier; the overall tier is the worst of the three, with a plain-language explanation of which metric drove it
3. **Precedent-retrieval agent (RAG)** — finds the most similar past congestion episodes (e.g. LA/Long Beach 2021, Yantian 2021, Suez 2021) from a curated corpus
4. **Decision-support agent** — Claude reasoning node producing recommendations for three personas, citing the numbers and any relevant precedent; replies are schema-validated with one self-correcting retry
5. **Advisory-drafting agent** — turns each recommendation into a short message for a carrier, trucking company and terminal operator (drafted in parallel)

Every step can output **English or Modern Standard Arabic** (`language: "ar"`); the UI is RTL-aware.

## Watch → Detect → Decide → Prove

- **Watch:** a background monitor checks every live port every 2 minutes and keeps a 7-day history; port cards show the live congestion tier, a 24 h sparkline and the port's usual queue. Each port is judged against **its own normal** (Singapore's anchorage is always busy), using only the live-measured queue and waiting time.
- **Detect:** alerts fire on their own for congestion escalation (confirmed over consecutive checks), possible anchor drag (confirmed over consecutive checks, ignoring ships that just never switched off their "at anchor" status), and gale or fog forecasts (Open-Meteo).
- **Decide:** for congestion and weather alerts, the agents draft advice automatically. It waits in the **Alerts Center** until a person approves or rejects it.
- **Prove:** every advisory shows its evidence (metrics, thresholds, past episodes) and an impact estimate: idle ship time, and the fuel, CO₂ and cost a just-in-time arrival would save.

A **Run demo alert** button raises a clearly-labelled demo escalation, so the full flow can be shown even when every real port is calm.

## Data: what's live and what isn't

| Signal | Source |
|---|---|
| Vessel queue length | **Live** — ships reporting "at anchor" inside each port's geofence, via the free [aisstream.io](https://aisstream.io) AIS feed |
| Average waiting time | **Live-observed** — measured from when each anchored ship was first seen (a floor, since ships already waiting before the server started are undercounted) |
| Berth occupancy | **Estimated** — ships reporting "moored" ÷ the port's published container-berth count |

Live tracking covers **nine ports on three continents**: Rotterdam, Antwerp, Felixstowe, Le Havre and Valencia (Europe), Singapore and Hong Kong (Asia), Los Angeles / Long Beach and New York / New Jersey (Americas). Every port's map area covers both its container terminals and the anchorages where ships wait, and each was checked against a live AIS capture before being added (sources are cited next to each entry in `backend/app/live/aisstream_client.py`). **Jebel Ali** is listed but has no free AIS receiver coverage, so it shows 0 vessels — use the synthetic scenarios for Gulf demos. Busan and Port Klang were tested and also have no free coverage. Real coverage there would need a paid satellite-AIS provider.

The backend has a 103-test suite (`cd backend && python -m pytest`), with Claude mocked so it's free to run, plus a 20-case **exam set** (`backend/eval/`) that scores tier accuracy, retrieval and the grounding of Claude's advice. See [Evaluation](backend/README.md#evaluation).

The precedent corpus is a small hand-written set of well-known episodes, matched with lightweight term-overlap scoring rather than a vector database. Tier thresholds in [`backend/app/thresholds.py`](backend/app/thresholds.py) are currently UNCTAD-style placeholders.

## Structure

- [`backend/`](backend) — FastAPI + LangGraph agent pipeline, Claude API, live AIS collector
- [`frontend/`](frontend) — Next.js (App Router, TypeScript, Tailwind) dashboard: multi-port live board, ship map, per-port advisory view

## Quickstart

```bash
# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add ANTHROPIC_API_KEY (required) and AISSTREAM_API_KEY (for live data)
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
cp .env.local.example .env.local   # points at http://localhost:8000 by default
npm run dev
```

Open http://localhost:3000. To try the pipeline without the UI: `cd backend && python cli.py critical`.

## Stack

FastAPI · LangGraph · Claude API · aisstream.io (AIS WebSocket) · Open-Meteo · Next.js · TypeScript · Tailwind · Leaflet · pytest
