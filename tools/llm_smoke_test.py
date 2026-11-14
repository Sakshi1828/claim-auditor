"""Live check that the LLM providers return valid structured JSON for research claims. Independent of the auditor.

  python tools/llm_smoke_test.py                    # LLM_PROVIDER from .env (default gemini), with fallback
  python tools/llm_smoke_test.py --provider groq    # force one provider, no fallback
  python tools/llm_smoke_test.py --both             # test Gemini and Groq separately, side by side
  python tools/llm_smoke_test.py --no-cache         # always call the API

Keys come from .env (copy .env.example). Keys are never printed; errors are redacted.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from auditor.claim_schema import EXTRACTION, SYSTEM_PROMPT, user_prompt  # noqa: E402
from auditor.llm import LLMClient, load_env  # noqa: E402

SAMPLES = [
    "Luminal A is the largest RNA subtype, accounting for about 62% of primary tumors with an RNA subtype call.",
    "TP53 is mutated in roughly a third of tumors with mutation data.",
    "MYC is amplified in more than 20% of basal-like tumors.",
    "HER2 protein levels are higher in HER2-enriched tumors than in Luminal A tumors.",
    "Patients whose tumors had the highest ER-alpha protein responded best to hormone therapy.",
    "We recommend that future work combine all available data layers.",
    "Between 15% and 20% of tumors are HER2-positive.",
]
# What a correct reading must contain (checked loosely: the model describes, it doesn't judge)
EXPECT = [
    {"metric": "share", "number": 62, "unit": "percent", "approximate": True, "factual": True},
    {"metric": "share", "number": 33.3, "unit": "percent", "approximate": True, "factual": True},
    {"metric": "share", "number": 20, "comparator": "gt", "layer": "copy_number", "factual": True},
    {"metric": "comparison", "layer": "protein", "factual": True},
    {"human": True, "factual": True},
    {"factual": False},
    {"comparator": "range", "low": 15, "high": 20, "factual": True},
]


def grade(spec: dict, exp: dict) -> list[str]:
    cv, problems = spec["claimed_value"], []
    if "factual" in exp and spec["is_factual_claim"] != exp["factual"]:
        problems.append(f"is_factual_claim={spec['is_factual_claim']}")
    if "metric" in exp and spec["metric"] != exp["metric"]:
        problems.append(f"metric={spec['metric']}")
    if "layer" in exp and spec["data_layer"] != exp["layer"]:
        problems.append(f"data_layer={spec['data_layer']}")
    if "number" in exp and (cv["number"] is None or abs(cv["number"] - exp["number"]) > 0.6):
        problems.append(f"number={cv['number']}")
    for k in ("unit", "comparator", "approximate", "low", "high"):
        if k in exp and cv[k] != exp[k]:
            problems.append(f"{k}={cv[k]}")
    if exp.get("human") and not spec["needs_human_judgement"]:
        problems.append("needs_human_judgement=False")
    return problems


def run(provider: str | None, use_cache: bool) -> bool:
    if provider:
        os.environ["LLM_PROVIDER"], os.environ["LLM_FALLBACK"] = provider, "none"
    if not use_cache:
        os.environ["LLM_CACHE"] = "0"
    client = LLMClient.from_env()
    print("\nConfigured:", ", ".join(f"{s['provider']} ({s['model']}, key {'set' if s['key_configured'] else 'MISSING'})"
                                     for s in client.status()))
    res = client.complete_json(SYSTEM_PROMPT, user_prompt(SAMPLES), EXTRACTION, "claims")
    for a in res.attempts:
        print(f"  attempt: {a.get('provider')} try {a.get('try', '-')}: {a.get('error')} {a.get('message', '')[:160]}")
    if not res.ok:
        print("  RESULT: failed gracefully ->", res.error)
        return False
    print(f"  RESULT: valid JSON from {res.provider} ({res.model}) in {res.seconds}s{' [cache]' if res.cached else ''}")
    claims = res.data["claims"]
    if len(claims) != len(SAMPLES):
        print(f"  WARNING: {len(claims)} claims for {len(SAMPLES)} sentences")
    good = 0
    for i, (spec, exp) in enumerate(zip(claims, EXPECT), 1):
        p = grade(spec, exp)
        good += not p
        cv = spec["claimed_value"]
        print(f"  {i}. [{'ok' if not p else 'CHECK'}] {spec['metric']:<18} layer={spec['data_layer']:<11} "
              f"target={spec['target']['concept']!r}={spec['target']['value']!r} "
              f"value={cv['as_written']!r} ({cv['comparator']} {cv['number']} {cv['unit']}) "
              f"human={spec['needs_human_judgement']}" + (f"  <- {', '.join(p)}" if p else ""))
    print(f"  Reading quality: {good}/{len(EXPECT)} sentences described as expected")
    out = ROOT / "outputs" / f"llm_smoke_{res.provider}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"result": {k: v for k, v in res.to_dict().items() if k != "data"}, "claims": claims},
                              indent=2), encoding="utf-8")
    print(f"  Saved (no keys) -> {out.relative_to(ROOT)}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["gemini", "groq"])
    ap.add_argument("--both", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()
    load_env()
    ok = [run(p, not a.no_cache) for p in ("gemini", "groq")] if a.both else [run(a.provider, not a.no_cache)]
    sys.exit(0 if all(ok) else 1)


if __name__ == "__main__":
    main()
