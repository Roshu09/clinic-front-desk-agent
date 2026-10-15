#!/usr/bin/env python3
"""Tokens + latency per conversation, for the README table.

    LLM_API_KEY=... LLM_BASE_URL=... LLM_MODEL=... LLM_CACHE=0 python scripts/benchmark.py

Run it with your real key; it prints a markdown table (and writes ../BENCHMARK.md) you can paste into README.md.
LLM_CACHE=0 forces cold calls so the numbers are real, not replayed.
"""
import glob, json, os, pathlib, statistics, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LLM_CACHE", "0")
from app.agent import FrontDeskAgent  # noqa: E402
from app.service import build_extractor  # noqa: E402

extractor = build_extractor()
agent = FrontDeskAgent(extractor=extractor)
model = os.environ.get("LLM_MODEL", "rules-only (no LLM_API_KEY set)") if extractor else "rules-only (no LLM_API_KEY set)"
rows = []
for path in sorted(glob.glob(str(ROOT.parent / "starter/conversations/*.json")) + glob.glob(str(ROOT.parent / "adversarial/*.json"))):
    script = json.load(open(path, encoding="utf-8"))
    r = agent.run(script["id"], script["today"], script["turns"])
    rows.append((script["id"], len(script["turns"]), r.terminal_state, r.metrics["tokens"], r.metrics["latency_ms"], r.nlu))
lines = [f"Model: `{model}`", "", "| conversation | turns | terminal_state | tokens | latency (ms) |", "|---|---|---|---|---|"]
lines += [f"| {c} | {t} | {s} | {tok} | {ms} |" for c, t, s, tok, ms, _ in rows]
lines += ["", f"**Mean:** {statistics.mean(r[3] for r in rows):.0f} tokens, {statistics.mean(r[4] for r in rows):.0f} ms per conversation "
          f"(median {statistics.median(r[4] for r in rows):.0f} ms, max {max(r[4] for r in rows)} ms) over {len(rows)} conversations."]
notes = sorted({r[5] for r in rows})
lines += ["", "NLU mode seen: " + "; ".join(notes)]
if any("unavailable" in n for n in notes):
    try:  # show the real reason the LLM call failed
        import datetime as dt
        extractor.enhance(["hello"], dt.date.today(), [{"id": "d", "name": "x", "speciality": "y"}], [])
    except Exception as error:  # noqa: BLE001
        body = getattr(getattr(error, "response", None), "text", "")
        lines += ["", f"LLM ERROR: {type(error).__name__}: {error} {body[:300]}"]
text = "\n".join(lines)
print(text)
(ROOT.parent / "BENCHMARK.md").write_text(text + "\n", encoding="utf-8")
