"""Benchmark the upgraded auditor: rules-only vs hybrid (LLM reading + analytical engine).

  python tools/benchmark.py            # needs a key in .env for the hybrid and semantic parts
Writes outputs/benchmark.md and outputs/benchmark.json. Gold verdicts come from tests/run_tests.py (each written and
answered independently in pandas); semantic labels from tests/semantic_gold.py.
"""
from __future__ import annotations

import ast
import json
import pathlib
import random
import re
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import pandas as pd  # noqa: E402

from auditor.adapt import activate  # noqa: E402
from auditor.audit import run_audit, to_shared_format  # noqa: E402
from auditor.llm import LLMClient, load_env  # noqa: E402
from auditor.release import Release  # noqa: E402

CH = ROOT.parent / "oncosys-hackathon-challenge"
RAW = CH / "data/tcga-brca/raw"
SLIDES = CH / "data/tcga-brca/slide_manifest.csv"
JUDGED = ("supported", "contradicted")


def gold_sets() -> dict:
    """EXPECT from tests/run_tests.py, read without running the tests."""
    src = (ROOT / "tests/run_tests.py").read_text(encoding="utf-8")
    node = next(n for n in ast.parse(src).body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "EXPECT")
    ns = {"HERE": ROOT / "tests", "CH": CH}
    return eval(compile(ast.Expression(node.value), "EXPECT", "eval"), ns)


def score(pairs):
    """pairs: (gold, predicted) verdicts over all sentences."""
    n = len(pairs)
    acc = sum(g == p for g, p in pairs) / n
    claims = [(g, p) for g, p in pairs if g != "not_a_claim"]
    recog = sum((g != "not_a_claim") == (p != "not_a_claim") for g, p in pairs) / n
    not_sup = [(g, p) for g, p in pairs if g in ("contradicted", "insufficient_evidence")]
    false_sup = sum(p == "supported" for _, p in not_sup)
    pred_ins = [(g, p) for g, p in pairs if p == "insufficient_evidence"]
    gold_ins = [(g, p) for g, p in pairs if g == "insufficient_evidence"]
    gold_jud = [(g, p) for g, p in claims if g in JUDGED]
    return {"sentences": n, "verdict_accuracy": round(acc, 3), "claim_recognition": round(recog, 3),
            "false_supported": f"{false_sup} of {len(not_sup)}",
            "false_supported_rate": round(false_sup / max(len(not_sup), 1), 3),
            "insufficient_precision": round(sum(g == p for g, p in pred_ins) / max(len(pred_ins), 1), 3),
            "insufficient_recall": round(sum(g == p for g, p in gold_ins) / max(len(gold_ins), 1), 3),
            "judged_claims_answered": f"{sum(p in JUDGED for _, p in gold_jud)} of {len(gold_jud)}",
            "judged_correct": f"{sum(g == p for g, p in gold_jud)} of {len(gold_jud)}"}


def mapping_benchmark(n_cols: int = 25, seed: int = 7) -> dict:
    """Rename (and partly recode) random analysable columns; how many does the adapter map back correctly?"""
    from auditor.adapt import reference
    ref = reference()
    cand = [k for k, v in ref.items() if v["role"] in ("predictor", "annotation", "outcome") and v["kind"] in
            ("categorical", "numeric") and v["missing_pct"] < 80]
    rnd = random.Random(seed)
    cols = rnd.sample(cand, min(n_cols, len(cand)))
    c = pd.read_csv(RAW / "clinical.tsv", sep="\t", dtype=str, keep_default_na=False)
    truth = {}
    for i, col in enumerate(cols):
        new = f"field_{i:02d}"
        if ref[col]["kind"] == "categorical" and i % 2 == 0:           # half the categorical ones also recoded
            c[col] = c[col].map(lambda v: v.upper() if v else v)
        c = c.rename(columns={col: new})
        truth[col] = new
    d = pathlib.Path(tempfile.mkdtemp(prefix="map_bench_"))
    c.to_csv(d / "clinical.tsv", sep="\t", index=False)
    for f in ("survival.tsv",):
        (d / f).write_bytes((RAW / f).read_bytes())
    ctx = activate(Release(d, SLIDES))
    got = {k: v["to"] for k, v in ctx.plan["renamed"].items()}
    correct = sum(got.get(k) == v for k, v in truth.items())
    wrong = sum(k in got and got[k] != v for k, v in truth.items())
    spurious = sum(1 for k in got if k not in truth)
    return {"renamed_columns": len(truth), "mapped_correctly": correct, "mapped_wrongly": wrong,
            "left_unmapped (reported as missing)": len(truth) - correct - wrong, "spurious_mappings": spurious,
            "ambiguous_refused": len(ctx.plan["ambiguous"])}


def envelope_benchmark(hybrid: bool) -> list[dict]:
    out = []
    rels = {"A": RAW, "practice envelope": CH / "envelopes/opened/practice/release",
            "random-test": CH / "data/tcga-brca/releases/random-test"}
    rep = (CH / "products/research-claim-auditor/practice_brief.md").read_text(encoding="utf-8")
    for name, d in rels.items():
        if not (d / "clinical.tsv").exists():
            out.append({"release": name, "ok": False, "note": "not available"})
            continue
        t0 = time.time()
        a = run_audit(rep, Release(d, SLIDES), semantic=hybrid)
        p = pathlib.Path(tempfile.mkdtemp()) / "audit.json"
        p.write_text(json.dumps(to_shared_format(a)))
        v = subprocess.run([sys.executable, str(CH / "format/validate.py"), str(p)], capture_output=True, text=True)
        out.append({"release": name, "ok": "valid" in v.stdout and "invalid" not in v.stdout, "seconds": round(time.time() - t0, 1),
                    "verdicts": [i["tool_verdict"] for i in a["items"]],
                    "adaptation": bool(a["release"]["adaptation"])})
    return out


def main():
    load_env()
    has_key = any(s["key_configured"] for s in LLMClient.from_env().status())
    rel = Release(RAW, SLIDES)
    sets = gold_sets()
    res = {"rules": [], "hybrid": []}
    latency, failures, decided = [], [], {}
    disagreements, false_sup_cases = [], []
    for path, want in sets.items():
        text = path.read_text(encoding="utf-8")
        ra = run_audit(text, rel, semantic=False)
        res["rules"] += list(zip(want, [i["tool_verdict"] for i in ra["items"]]))
        if has_key:
            ha = run_audit(text, rel, semantic=True)
            s = ha.get("semantic") or {}
            if s.get("enabled") and s.get("provider"):
                latency.append(s["seconds"])
            if s.get("errors"):
                failures += [f"{path.name}: {e['error'][:120]}" for e in s["errors"]]
            res["hybrid"] += list(zip(want, [i["tool_verdict"] for i in ha["items"]]))
            for g, it in zip(want, ha["items"]):
                decided[it["decided_by"].split(" (")[0]] = decided.get(it["decided_by"].split(" (")[0], 0) + 1
                if "DISAGREES" in it["decided_by"]:
                    disagreements.append(f"{path.name}: {it['claim_text'][:90]} (rules {it['tool_verdict']}, engine "
                                         f"{(it.get('engine') or {}).get('verdict')}, gold {g})")
                if it["tool_verdict"] == "supported" and g != "supported":
                    false_sup_cases.append(f"{path.name}: {it['claim_text'][:100]} (gold {g}; {it['decided_by']})")
    for g, p_ in res["rules"]:
        pass
    rules_fs = [f"{p.name}" for p in []]
    out = {"rules": score(res["rules"]), "hybrid": score(res["hybrid"]) if res["hybrid"] else None,
           "decided_by": decided, "disagreements_flagged": disagreements, "false_supported_cases_hybrid": false_sup_cases,
           "llm_latency_s_per_report": {"n": len(latency), "median": round(sorted(latency)[len(latency) // 2], 1) if latency else None,
                                        "max": max(latency) if latency else None, "total": round(sum(latency), 1)},
           "llm_failures": failures, "mapping": mapping_benchmark()}
    if has_key:
        from eval_semantic import evaluate
        ev = evaluate(LLMClient.from_env(), rel)
        out["semantic"] = {"provider": ev["provider"], "model": ev["model"], "seconds": ev["seconds"],
                           "fields": {k: v for k, v in ev["totals"]["all"]["fields"].items()},
                           "fully_correct": ev["totals"]["all"]["fully_correct"], "grounded": ev["totals"]["all"]["grounded"],
                           "paraphrase_groups_consistent": sum(1 for g in ev["paraphrase_groups"] if g["consistent"]),
                           "paraphrase_groups": sum(1 for g in ev["paraphrase_groups"] if g["consistent"] is not None),
                           "errors": [e["error"][:120] for e in ev["errors"]]}
    out["envelopes_rules"] = envelope_benchmark(False)
    out["envelopes_hybrid"] = envelope_benchmark(True) if has_key else None
    eng = subprocess.run([sys.executable, str(ROOT / "tests/test_engine.py")], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    lines = [l for l in eng.stdout.splitlines() if l.startswith(("ok  ", "FAIL"))]
    out["calculation"] = {"engine_checks": len(lines), "passed": sum(l.startswith("ok") for l in lines)}
    (ROOT / "outputs").mkdir(exist_ok=True)
    (ROOT / "outputs/benchmark.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
