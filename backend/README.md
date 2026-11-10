# BerthIQ — Backend

Multi-agent congestion advisory pipeline: **Monitoring → Classification → Precedent retrieval → Decision-support → Advisory-drafting**, orchestrated with LangGraph and reasoned over by the Claude API.

## Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # ANTHROPIC_API_KEY (required), AISSTREAM_API_KEY (optional, for live data)
```

## Run the pipeline from the CLI

```bash
python cli.py low       # or medium | high | critical
```

Runs a synthetic Jebel Ali scenario (see `app/scenarios.py`) through the full pipeline and prints the tier, recommendations and advisories.

## Run the API server

```bash
uvicorn app.main:app --reload --port 8000
```

The live AIS collector starts and stops with the server (FastAPI `lifespan`).

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness check |
| `GET /scenarios` | Synthetic snapshot presets, one per tier |
| `POST /advisory` | Run the full pipeline on a `PortSnapshot` JSON body |
| `GET /live/ports?lang=` | Tracked ports and whether each has live AIS coverage |
| `GET /live/vessel-queue?port=&positions=&lang=` | Live reading for one port; `positions=true` adds each ship's lat/lon for the map |
| `GET /live/vessel-queue/all?lang=` | Live readings for every port (board view) |
| `GET /live/advisory?port=&lang=` | Build a snapshot from live AIS data and run the full pipeline on it |
| `GET /live/history?port=&hours=` | Readings the monitor recorded for a port (up to 24 h) |
| `GET /alerts?status=&port=` | Alerts raised by the monitor, newest first |
| `POST /alerts/{id}/acknowledge` · `/approve` · `/reject` · `/resolve` | Human-in-the-loop workflow (optional `{"note": "..."}` body) |
| `POST /alerts/{id}/advisory` | Ask the agents to draft (or re-draft) advice for an alert |
| `POST /demo/replay?port=` | Raise a clearly-labelled demo escalation, so the full flow can be shown when every port is calm |

Live board responses also include the port's current `tier`, per-metric `metric_tiers`, a 24 h `trend` and an `idle_cost_usd` estimate (`tier` is `null` while a port has no coverage or is still warming up).

Every advisory response includes `evidence` (the metrics, thresholds and precedents behind the tier) and `impact` (estimates — see below).

`port` is one of `rotterdam`, `antwerp`, `felixstowe`, `le_havre`, `valencia`, `singapore`, `hong_kong`, `los_angeles`, `new_york_nj`, `jebel_ali`. `lang` is `en` or `ar`.

**`PortSnapshot` body:**

```json
{
  "port_name": "Jebel Ali",
  "berth_occupancy_rate": 0.95,
  "vessel_queue_length": 22,
  "avg_waiting_time_hours": 30,
  "language": "en"
}
```

`berth_occupancy_rate` is a fraction (0–1), not a percentage. Invalid snapshots (out-of-range values, blank port name, unsupported language) return **422** with a readable message.

## Autonomous monitoring and alerts

A background monitor (`app/monitoring/monitor.py`) runs every `MONITOR_INTERVAL_SECONDS` (default 120). For each port with live coverage it classifies the current snapshot (rule-based, no LLM cost), records it in a rolling 24 h history, and runs three detectors (`app/monitoring/detectors.py`):

| Detector | Fires when | Notes |
|---|---|---|
| Congestion escalation | The tier rises to Medium or above and holds for `MONITOR_CONFIRM_TICKS` (2) consecutive checks | Only once the port's usual queue is known (≈1 h of history); confirmation stops one noisy reading from raising an alert |
| Anchor drag | A ship reporting "at anchor" is more than `ANCHOR_DRAG_METERS` (800 m) from where it first anchored, at no more than `ANCHOR_DRAG_MAX_KNOTS` (3 kn), and keeps moving further away for `ANCHOR_DRAG_CONFIRM_TICKS` (2) checks in a row | A big ship swinging on its chain can sit 600 m+ from its first fix. Ships faster than 3 kn have left and not updated their AIS status: 20 of the first 24 live alerts were this, and all 24 were false by these rules. Such ships are also left out of the queue count |
| Weather risk | The Open-Meteo forecast for the next 12 h shows gusts ≥ 34 kn (gale) or visibility ≤ 1,000 m | Severity is higher when a queue already exists |

**How the live tier is decided.** Only the two measured metrics count: ships waiting and observed waiting time. The berth-occupancy figure from AIS (moored ships ÷ a hand-sourced container-berth count) is shown but not used, because it saturates at 100% at large multi-purpose ports. The queue is judged against **the port's own usual level** (the median of up to 7 days of history): below 1.2× usual is Low, under 1.5× Medium, under 2× High, and 2× or more Critical (`RELATIVE_QUEUE_THRESHOLDS` in `app/thresholds.py`; a floor of 3 ships stops near-empty ports looking dramatic). Until a port has about an hour of history (`MIN_BASELINE_SAMPLES`, 30), the global thresholds apply. Waiting time always uses the global hour thresholds, since hours mean the same at every port.

Each alert type has a cooldown so the same event isn't raised repeatedly. For congestion and weather alerts, the agents draft an advisory automatically (capped at `AUTO_ADVISORY_MAX_PER_HOUR`, default 6; disable with `AUTO_ADVISORY=0`). The draft is marked `pending_approval`: **nothing AI-written counts as shared until a person approves it**, and an alert can't be resolved while advice is awaiting review. Every action is recorded in the alert's activity log.

Alerts and history are saved to `app/live/.alerts.json` and `app/live/.history.json` (gitignored), so they survive restarts.

## Impact estimates

`app/impact.py` attaches two order-of-magnitude estimates to every advisory:

- **Idle ship time:** ships waiting × average wait × a typical daily operating cost.
- **Just-in-time arrival:** for one inbound ship 24 h out, the speed that would absorb the current wait instead of anchoring, and the fuel, CO₂ and cost saved. Main-engine fuel per day scales with roughly the cube of speed; the saving also counts auxiliary fuel not burned at anchor.

Every assumption (service speed, fuel burn, fuel price, the IMO CO₂ factor of 3.114, daily ship cost) is returned with the numbers and can be overridden with `IMPACT_*` environment variables. These are estimates, not measurements, and the UI labels them that way.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required for advisories |
| `AISSTREAM_API_KEY` | — | Live AIS data (without it, the board and monitor stay idle) |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated CORS origins — set to your frontend URL in production |
| `LLM_RATE_LIMIT_PER_MINUTE` | `6` | Per-IP limit on endpoints that call Claude (429 when exceeded) |
| `MONITOR_INTERVAL_SECONDS` | `120` | How often the monitor checks every port |
| `AUTO_ADVISORY` / `AUTO_ADVISORY_MAX_PER_HOUR` | `1` / `6` | Automatic advice drafting for alerts, and its hourly cap |
| `DEMO_MODE` | `1` | Enables `POST /demo/replay` |
| `CLAUDE_MODEL` | `claude-opus-4-5` | Model used by the decision-support and drafting agents |
| `CLAUDE_TIMEOUT_SECONDS` / `CLAUDE_MAX_RETRIES` | `30` / `2` | Per-call timeout and SDK retries (timeouts, connection errors, 429, 5xx) |
| `CLAUDE_PRICE_INPUT_PER_MTOK` / `CLAUDE_PRICE_OUTPUT_PER_MTOK` | `5` / `25` | USD per million tokens, used for the cost reported with each advisory |

## Reliability and cost

- **Timeouts and retries.** Each Claude call times out after 30 s (the SDK default is 10 minutes) and is retried up to twice for timeouts, connection errors, rate limits and server errors.
- **Fallback.** If Claude is still unavailable, or its reply fails validation after our own retry, the advisory is not lost: the congestion level, evidence, precedents and impact estimate are rule-based and unaffected, and the three recommendations fall back to standard guidance for that level (English or Arabic). The response carries `"ai_status": "fallback"` and the interface says so. Invalid input is still rejected with 422, and unexpected errors still return 502.
- **Cost per advisory.** Every advisory returns a `usage` block (Claude calls, input/output tokens, cost in USD, latency) and logs one line with the same numbers. The evaluator reports median and total cost alongside quality.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

103 tests cover input validation, tier classification, JSON parsing and retry, Claude timeouts and the rule-based fallback, token and cost tracking, all three detectors, the impact model, the alert workflow, the monitor loop (with a fake AIS feed and forecast), rate limiting, CORS and the API. Claude is mocked throughout, so the suite is free and runs in about a second.

## Evaluation

`eval/exam_set.json` holds 20 hand-labelled cases: every tier, threshold boundaries, port-relative queues (Singapore vs Felixstowe, a usually-empty port, a port still warming up), Arabic output, alert situations (gale, dragging anchor), a prompt injection and an impossible input. Expected tiers were worked out by hand from the policy in `app/thresholds.py`, and each case lists the past episodes a human would accept as relevant.

```bash
python -m eval.run_eval            # offline: tiers, driving metrics, validation, retrieval (free)
python -m eval.run_eval --llm      # full pipeline with Claude (~76 API calls) plus grounding checks
python -m eval.run_eval --rescore  # re-check the saved Claude run without calling the API
```

Grounding checks on Claude's output: all three personas present, every recommendation cites a real number from the snapshot, no code-style field names, advisories of at most 4 sentences, no past episode cited that retrieval didn't supply, no quoting of the unreliable live occupancy estimate, Arabic when asked, the alert situation addressed, and the injected instruction ignored.

| Run | Result |
|---|---|
| Offline (tier, driving metric, retrieval hit@2, validation) | 43/43 checks pass |
| Claude, first run | Quoted the excluded occupancy estimate ("99% capacity") as fact in 4 of 7 live-data cases, despite being told not to rely on it |
| Claude, after removing that number from the prompt | 19/19 cases pass every check; median 17 s per full advisory |
| Claude, Day 4 re-run with cost tracking, timeouts and fallback | 19/19 cases pass every check, no fallbacks; median 16.8 s and $0.030 per full advisory (4 Claude calls, ~1,460 input + ~900 output tokens); whole exam $0.59. Output tokens are ~76% of the cost. |

Results are saved in `eval/results/` (`llm_run1_before_fix.json` keeps the first run, `llm_run2_day3_after_fix.json` the Day 3 run). The automated checks are heuristics, so read a sample of the saved advice too. Retrieval labels are generous with a six-episode corpus, so retrieval hit@2 will mean more once the corpus grows.

## Live data

DP World and most port authorities don't publish berth occupancy or queue data, so BerthIQ derives what it can from public AIS ship broadcasts via the free [aisstream.io](https://aisstream.io) WebSocket feed, geofenced around each port (`app/live/aisstream_client.py`):

- **Vessel queue length** — ships whose AIS navigational status is "at anchor" (falls back to speed < threshold when status is missing).
- **Average waiting time** — each anchored ship's elapsed time since it was first seen waiting. Ships already anchored when the server started are undercounted, so treat it as a floor.
- **Berth occupancy (estimated)** — ships reporting "moored" ÷ the port's published container-berth count. Flagged in `estimated_fields` because the berth count is hand-sourced and a moored ship may be at a non-container berth inside the same box.

The collector runs in the background and caches to `app/live/.vessel_cache.json`, because anchored vessels only broadcast every ~2–3 minutes — a per-request fetch would almost always see nothing. `warming_up` is true until the cache has been listening long enough to be reliable.

**Known limitation:** aisstream.io is a volunteer-receiver network, not satellite AIS. The nine live ports were each confirmed with a 4-minute capture before being added; **Jebel Ali has little to none** and will usually show 0 vessels (Busan and Port Klang returned 0 ships in testing and were left out).

**Adding a port:** add an entry to `PORTS` with a bounding box covering both the container terminals and the anchorages where ships wait, its container-berth count (cite the source), and English/Arabic names. Check coverage first by capturing the box for a few minutes — a box with ships but no anchored ones usually means the waiting area is outside it. `tests/test_monitoring.py` checks boxes are valid and don't overlap. Real Gulf coverage needs a paid satellite-AIS provider (e.g. MarineTraffic, Datalastic).

## Agents

| Agent | File | Job |
|---|---|---|
| Monitoring | `app/agents/monitoring.py` | Validates the snapshot: required fields, occupancy 0–1, non-negative whole-number queue, non-negative wait, supported language |
| Classification | `app/agents/classification.py` | Tiers each metric with `app/thresholds.py`; overall tier = worst metric, with a plain-language explanation (EN/AR) |
| Precedent retrieval | `app/agents/precedent_retrieval.py` | RAG over `app/rag/corpus.py` — top-2 similar past episodes, using term-overlap similarity plus a same-tier boost (`app/rag/retriever.py`) |
| Decision-support | `app/agents/decision_support.py` | Claude reasoning node — one recommendation per persona, citing metrics and relevant precedent. The JSON reply is validated (all three personas, non-empty fields); an invalid reply gets one retry with the error fed back |
| Advisory-drafting | `app/agents/advisory_drafting.py` | Turns each recommendation into a 2–4 sentence persona message; the three drafts run in parallel |

Personas: `carrier`, `trucking_company`, `terminal_operator`.

The pipeline is wrapped by `app/advisory_service.py`, which adds the evidence and impact blocks and is shared by the API and the monitor.

## Still to do

- Grow the exam set with cases scored by a port-operations expert rather than derived from the threshold policy.
- `app/thresholds.py` holds UNCTAD-style placeholder thresholds — replace with the dissertation's validated values.
- The precedent corpus is six hand-written episodes; swap in an embeddings index over the dissertation's case studies when available (the `retrieve()` interface stays the same).
