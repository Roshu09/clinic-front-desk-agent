#!/usr/bin/env python3
"""Run conversation scripts in-process and compare against each script's `expected` block.

    python scripts/check.py [dir ...]      (default: ../starter/conversations and ../adversarial)
"""
import json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent import FrontDeskAgent  # noqa: E402
from app.service import build_extractor  # noqa: E402


def grade(script, result):
    exp, problems = script["expected"], []
    names = [c["name"] for c in result["tool_calls"]]
    if result["terminal_state"] != exp["terminal_state"]:
        problems.append(f"state {result['terminal_state']} != {exp['terminal_state']}")
    if result["escalation_reason"] != exp["escalation_reason"]:
        problems.append(f"reason {result['escalation_reason']} != {exp['escalation_reason']}")
    problems += [f"missing call {n}" for n in exp.get("must_call", []) if n not in names]
    problems += [f"forbidden call {n}" for n in exp.get("must_not_call", []) if n in names]
    return problems


def main(dirs):
    agent = FrontDeskAgent(extractor=build_extractor())
    failures = total = 0
    for directory in dirs:
        for path in sorted(pathlib.Path(directory).glob("*.json")):
            script = json.load(open(path, encoding="utf-8"))
            result = agent.run(script["id"], script.get("today", "2026-10-01"), script["turns"]).to_response()
            problems = grade(script, result)
            total += 1
            failures += bool(problems)
            print(f"{'FAIL' if problems else 'ok  '} {script['id']:<10} {result['terminal_state']}/{result['escalation_reason']} "
                  f"pt={result['patient_id']} ap={result['appointment_id']} calls={[c['name'] for c in result['tool_calls']]}"
                  + (f"\n       -> {problems}\n       reply: {result['reply']}" if problems else ""))
    print(f"\n{total - failures}/{total} match expectations")
    return 1 if failures else 0


if __name__ == "__main__":
    base = ROOT.parent
    sys.exit(main(sys.argv[1:] or [base / "starter" / "conversations", base / "adversarial"]))
