"""Run the BerthIQ exam set and score it.

    python -m eval.run_eval            # offline: tiers, validation, retrieval (free, instant)
    python -m eval.run_eval --llm      # also runs the full pipeline with Claude and checks grounding
    python -m eval.run_eval --llm --ids E04 E17

Results are written to eval/results/<mode>_latest.json and a summary is printed.
"""

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from app.agents.classification import classify_snapshot  # noqa: E402
from app.agents.monitoring import SnapshotValidationError, monitoring_node  # noqa: E402
from app.agents.precedent_retrieval import precedent_retrieval_node  # noqa: E402
from app.rag.corpus import PRECEDENTS  # noqa: E402

EXAM_SET = HERE / "exam_set.json"
RESULTS = HERE / "results"

FIELD_NAMES = re.compile(r"berth_occupancy_rate|vessel_queue_length|avg_waiting_time_hours|queue_baseline|tier_metrics")
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
SENTENCE_END = re.compile(r"[.!?؟](?=\s|$)")
# Precedent port names as they would appear in English text.
PRECEDENT_PLACES = {
    "la-long-beach-2021": ["los angeles", "long beach", "west coast"],
    "yantian-2021": ["yantian"],
    "suez-2021": ["suez"],
    "rotterdam-2022": ["rotterdam"],
    "shanghai-2022": ["shanghai"],
    "felixstowe-2022": ["felixstowe"],
}


def load_cases(ids=None):
    cases = json.loads(EXAM_SET.read_text())["cases"]
    return [c for c in cases if not ids or c["id"] in ids]


# ------------------------------------------------------------------ offline checks
def offline_case(case):
    exp = case["expected"]
    out = {"id": case["id"], "category": case["category"], "checks": {}}
    try:
        state = monitoring_node({"snapshot": dict(case["snapshot"])})
    except SnapshotValidationError as exc:
        out["rejected"] = str(exc)
        out["checks"]["validation"] = bool(exp.get("rejected"))
        return out
    if exp.get("rejected"):
        out["checks"]["validation"] = False
        return out

    snap, lang = state["snapshot"], state["language"]
    cls = classify_snapshot(snap, lang)
    out["tier"] = cls["tier"]
    out["checks"]["tier"] = cls["tier"] == exp["tier"]
    if "driving_metrics" in exp:
        out["driving_metrics"] = cls["driving_metrics"]
        out["checks"]["driving_metrics"] = sorted(cls["driving_metrics"]) == sorted(exp["driving_metrics"])

    retrieved = precedent_retrieval_node({
        "snapshot": snap, "tier": cls["tier"], "tier_reasoning": cls["tier_reasoning"],
        "driving_metrics": cls["driving_metrics"],
    })["precedents"]
    out["retrieved"] = [p["id"] for p in retrieved]
    if case["relevant_precedents"]:
        out["checks"]["retrieval_hit@2"] = bool(set(out["retrieved"]) & set(case["relevant_precedents"]))
    return out


# ------------------------------------------------------------------ LLM checks
def _numbers_in(snap):
    nums = {str(snap["vessel_queue_length"]), f"{snap['avg_waiting_time_hours']:g}"}
    if "berth_occupancy_rate" in (snap.get("tier_metrics") or ["berth_occupancy_rate"]):
        nums.add(f"{round(snap['berth_occupancy_rate'] * 100)}%")
    if snap.get("queue_baseline") is not None:
        nums.add(str(round(snap["queue_baseline"])))
    return nums


# Models often write a count of one as a word ("one ship", "سفينة واحدة").
NUMBER_WORDS = {"1": ("one", "a single", "واحد", "واحدة")}


def _cites_number(text, nums):
    text = text.translate(ARABIC_DIGITS).replace("٪", "%")
    if any(re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", text) for n in nums):
        return True
    low = text.lower()
    return any(w in low for n in nums for w in NUMBER_WORDS.get(n, ()))


PAST_CUE = re.compile(r"\b(20\d\d|during|episode|experience|crisis|blockage|showed|proved)\b")


def invented_precedents(text, port_name, retrieved):
    """Past episodes cited that retrieval never supplied.

    A sentence counts only if it names a precedent's place *and* talks about the past
    (a year, "during", "episode"...). Naming a port as a diversion option is not a precedent.
    """
    current = port_name.lower()
    invented = set()
    for sentence in re.split(r"(?<=[.!?])\s+", text.lower()):
        if not PAST_CUE.search(sentence):
            continue
        # If the sentence is about a retrieved episode, other place names in it are context.
        if any(p in sentence for pid in retrieved for p in PRECEDENT_PLACES.get(pid, [])):
            continue
        for pid, places in PRECEDENT_PLACES.items():
            if pid not in retrieved and any(p in sentence and p not in current for p in places):
                invented.add(pid)
    return sorted(invented)


def _arabic_share(text):
    letters = [ch for ch in text if ch.isalpha()]
    return sum("؀" <= ch <= "ۿ" for ch in letters) / max(1, len(letters))


def llm_case(case):
    from app.advisory_service import run_advisory

    exp = case["expected"]
    if exp.get("rejected"):
        return {"id": case["id"], "skipped": "validation case (offline only)"}

    start = time.perf_counter()
    try:
        result = run_advisory(dict(case["snapshot"]))
    except Exception as exc:  # report, don't abort the whole run
        return {"id": case["id"], "error": f"{type(exc).__name__}: {exc}", "checks": {"pipeline_ok": False}}
    latency = round(time.perf_counter() - start, 1)
    row = {
        "id": case["id"], "category": case["category"], "latency_s": latency, "tier": result["tier"],
        "precedents": sorted(p["id"] for p in result["precedents"]),
        "recommendations": result["recommendations"], "advisories": result["advisories"],
        "ai_status": result.get("ai_status", "ok"), "usage": result.get("usage"),
    }
    row["checks"] = score(case, row)
    # Standard fallback advice is not what we are grading: count it as a pipeline failure.
    row["checks"]["pipeline_ok"] = row["ai_status"] == "ok"
    return row


def score(case, row):
    """Grounding checks on one saved pipeline output."""
    exp = case["expected"]
    snap = case["snapshot"]
    result = row
    recs = result["recommendations"]
    advisories = result["advisories"]
    rec_texts = [f"{r['action']} {r['reasoning']}" for r in recs]
    all_text = " ".join(rec_texts + list(advisories.values()))
    low = all_text.lower()
    nums = _numbers_in(snap)

    checks = {
        "pipeline_ok": True,
        "tier": result["tier"] == exp["tier"],
        "all_personas": len(recs) == 3 and len(advisories) == 3,
        "cites_data": all(_cites_number(t, nums) for t in rec_texts),
        "plain_language": not FIELD_NAMES.search(all_text),
        "advisory_length": all(len(SENTENCE_END.findall(m.strip())) <= 4 for m in advisories.values()),
    }
    retrieved = set(result["precedents"])
    if snap.get("language", "en") == "en":
        checks["no_invented_precedent"] = not invented_precedents(all_text, snap["port_name"], retrieved)
    if "berth_occupancy_rate" not in (snap.get("tier_metrics") or ["berth_occupancy_rate"]):
        # The live occupancy estimate is excluded from tiering; the advice must not quote it as fact.
        pct = round(snap["berth_occupancy_rate"] * 100)
        checks["no_unreliable_estimate"] = not re.search(rf"\b{pct}\s?(%|percent)", low.translate(ARABIC_DIGITS))
    if exp.get("language") == "ar":
        checks["language"] = all(_arabic_share(t) > 0.6 for t in rec_texts + list(advisories.values()))
    if "must_mention_any" in exp:
        checks["addresses_situation"] = any(w in low for w in exp["must_mention_any"])
    if "must_not_mention" in exp:
        checks["avoids_forbidden"] = not any(w.lower() in low for w in exp["must_not_mention"])

    return checks


# ------------------------------------------------------------------ reporting
def summarise(rows):
    totals = {}
    for row in rows:
        for name, ok in row.get("checks", {}).items():
            t = totals.setdefault(name, [0, 0])
            t[0] += bool(ok)
            t[1] += 1
    return {name: {"passed": p, "total": n, "rate": round(p / n, 3)} for name, (p, n) in totals.items()}


def print_report(mode, rows, summary):
    print(f"\nBerthIQ exam set — {mode} — {len(rows)} cases\n")
    print(f"{'check':<24}{'passed':>10}")
    for name, s in summary.items():
        print(f"{name:<24}{s['passed']:>5}/{s['total']:<4} {s['rate'] * 100:5.0f}%")
    fails = [(r["id"], k) for r in rows for k, ok in r.get("checks", {}).items() if not ok]
    if fails:
        print("\nFailures:")
        for cid, check in fails:
            row = next(r for r in rows if r["id"] == cid)
            detail = row.get("error") or row.get("tier") or row.get("rejected") or ""
            print(f"  {cid}  {check}  ({detail}; retrieved={row.get('retrieved') or row.get('precedents')})")
    lat = [r["latency_s"] for r in rows if "latency_s" in r]
    if lat:
        lat.sort()
        print(f"\nLatency per full advisory: median {lat[len(lat) // 2]} s, max {lat[-1]} s")
    costs = sorted(r["usage"]["cost_usd"] for r in rows if r.get("usage"))
    if costs:
        tokens = sorted(r["usage"]["input_tokens"] + r["usage"]["output_tokens"] for r in rows if r.get("usage"))
        print(f"Cost per full advisory: median ${costs[len(costs) // 2]:.4f}, max ${costs[-1]:.4f}, "
              f"total ${sum(costs):.4f} (median {tokens[len(tokens) // 2]} tokens)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--llm", action="store_true", help="also run Claude and check grounding (costs API calls)")
    parser.add_argument("--ids", nargs="*", help="only these case ids")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--rescore", action="store_true", help="re-check saved llm_latest.json without calling Claude")
    args = parser.parse_args()

    cases = load_cases(args.ids)
    if args.rescore:
        saved = json.loads((RESULTS / "llm_latest.json").read_text())
        by_id = {c["id"]: c for c in cases}
        rows = [r for r in saved["cases"] if r["id"] in by_id and "recommendations" in r]
        for r in rows:
            r["checks"] = score(by_id[r["id"]], r)
        mode = "llm"
    elif args.llm:
        from dotenv import load_dotenv

        load_dotenv(HERE.parent / ".env")
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            rows = list(pool.map(llm_case, cases))
        rows = [r for r in rows if "skipped" not in r]
        mode = "llm"
    else:
        rows = [offline_case(c) for c in cases]
        mode = "offline"

    summary = summarise(rows)
    print_report(mode, rows, summary)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{mode}_latest.json"
    out.write_text(json.dumps({
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode, "summary": summary, "cases": rows,
    }, indent=2, ensure_ascii=False))
    print(f"\nSaved {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
