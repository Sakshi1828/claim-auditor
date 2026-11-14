"""Evaluate semantic claim understanding against hand-written labels.

  python tools/eval_semantic.py                 # provider from .env (Gemini, falling back to Groq)
  python tools/eval_semantic.py --provider groq
  python tools/eval_semantic.py --both          # Gemini and Groq separately
Scores the 81 sentences of the six release-A test reports plus paraphrase groups, per field, and lists every failure.
The LLM only describes claims; no verdicts are produced here. Writes outputs/semantic_eval_<provider>.json/.md.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from auditor.claims import split_sentences  # noqa: E402
from auditor.llm import LLMClient, load_env  # noqa: E402
from auditor.release import Release  # noqa: E402
from auditor.semantic import understand  # noqa: E402
from semantic_gold import GOLD_81, PARAPHRASES  # noqa: E402

CH = ROOT.parent / "oncosys-hackathon-challenge"
REPORTS = [CH / "products/research-claim-auditor/practice_brief.md"] + [
    ROOT / "tests" / f for f in ("stress_report.md", "manifest_report.md", "next_steps_report.md", "real_world_report.md",
                                 "holdout_report.md")]
FIELDS = ["factual", "category", "aggregation", "field", "value", "number", "comparator", "range", "filter",
          "direction", "verifiability"]


def norm(v) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(v).lower())


def score_one(spec: dict, gold: dict) -> dict:
    """Per-field True/False for the fields the label specifies (None = not labelled)."""
    r = dict.fromkeys(FIELDS)
    r["factual"] = spec["is_factual"] == gold["factual"]
    if not gold["factual"]:
        return r
    cv = spec["claimed_value"]
    r["category"] = spec["category"] in gold["cat"]
    r["verifiability"] = spec["verifiability"]["status"] in gold["verif"]
    if "agg" in gold:
        r["aggregation"] = spec["aggregation"] in gold["agg"]
    if "field" in gold:
        r["field"] = spec["target"]["field"] in gold["field"]
    if "value" in gold:
        r["value"] = norm(spec["target"]["value"]) in {norm(v) for v in gold["value"]}
    if "num" in gold:
        n = cv["number"]
        r["number"] = n is not None and abs(n - gold["num"]) <= max(0.6, 0.01 * abs(gold["num"]))
    if "cmp" in gold:
        r["comparator"] = cv["comparator"] in gold["cmp"]
    if "low" in gold:
        r["range"] = cv["low"] is not None and cv["high"] is not None and abs(cv["low"] - gold["low"]) < .6 \
            and abs(cv["high"] - gold["high"]) < .6
    if "filt" in gold:
        got = {f["field"] for f in spec["population"]["filters"]} | set(spec["grouping_variables"])
        r["filter"] = bool(got & set(gold["filt"]))
    if "dir" in gold:
        r["direction"] = spec["comparison"]["direction"] in gold["dir"]
    return r


def best(specs: list[dict], gold: dict):
    """A sentence can yield several claims; grade the one that matches the label best."""
    if not specs:
        return None, {k: (False if k == "factual" else None) for k in FIELDS}
    scored = [(s, score_one(s, gold)) for s in specs]
    return max(scored, key=lambda x: sum(1 for v in x[1].values() if v))


def signature(spec: dict) -> tuple:
    cv = spec["claimed_value"]
    num = None if cv["number"] is None else round(cv["number"])
    return (spec["is_factual"], spec["category"], spec["aggregation"], spec["target"]["field"],
            norm(spec["target"]["value"]), num, cv["comparator"])


def evaluate(client: LLMClient, rel: Release) -> dict:
    sents = [s.text for p in REPORTS for s in split_sentences(p.read_text(encoding="utf-8"))]
    mismatch = [(i + 1, a, b["text"]) for i, (a, b) in enumerate(zip(sents, GOLD_81)) if a != b["text"]]
    para = [(g, label, s) for g, label, ss in PARAPHRASES for s in ss]
    allsents = sents + [s for _, _, s in para]
    out = understand(allsents, rel, client)
    by_id = {}
    for c in out["claims"]:
        by_id.setdefault(c["sentence_id"], []).append(c)
    rows = []
    for i, gold in enumerate(GOLD_81 + [label for _, label, _ in para], 1):
        spec, sc = best(by_id.get(i, []), gold)
        rows.append({"id": i, "set": "81" if i <= len(GOLD_81) else "paraphrase", "text": allsents[i - 1],
                     "scores": sc, "grounding": spec["grounding"] if spec else None,
                     "n_specs": len(by_id.get(i, [])), "spec": spec})
    totals = {}
    for subset in ("81", "paraphrase", "all"):
        rs = [r for r in rows if subset == "all" or r["set"] == subset]
        acc = {}
        for f in FIELDS:
            vals = [r["scores"][f] for r in rs if r["scores"][f] is not None]
            acc[f] = [sum(vals), len(vals)]
        full = sum(1 for r in rs if all(v is not False for v in r["scores"].values()))
        grounded = [r for r in rs if r["grounding"] is not None]
        totals[subset] = {"fields": acc, "fully_correct": [full, len(rs)],
                          "grounded": [sum(r["grounding"]["ok"] for r in grounded), len(grounded)],
                          "missing": sum(1 for r in rs if r["n_specs"] == 0)}
    groups, k = [], len(GOLD_81)
    for g, label, ss in PARAPHRASES:
        ids = list(range(k + 1, k + len(ss) + 1))
        k += len(ss)
        sigs = [signature(rows[i - 1]["spec"]) if rows[i - 1]["spec"] else None for i in ids]
        is_para = not g.startswith(("causal", "associative", "not in the data", "not factual"))
        groups.append({"group": g, "paraphrase": is_para,
                       "consistent": (len(set(sigs)) == 1 and sigs[0] is not None) if is_para else None,
                       "all_match_label": all(all(v is not False for v in rows[i - 1]["scores"].values()) for i in ids),
                       "signatures": [list(s) if s else None for s in sigs], "sentences": ss})
    return {"provider": out.get("provider"), "model": out.get("model"), "seconds": out["seconds"], "errors": out["errors"],
            "gold_text_mismatches": mismatch, "totals": totals, "paraphrase_groups": groups, "rows": rows}


def pct(a):
    return f"{a[0]}/{a[1]} ({100 * a[0] / a[1]:.0f}%)" if a[1] else "n/a"


def report(ev: dict) -> str:
    L = [f"# Semantic understanding: {ev['provider']} ({ev['model']})", "",
         f"{len(ev['rows'])} sentences, {ev['seconds']} s total. The model only describes claims; no verdicts.", ""]
    if ev["errors"]:
        L += ["**Errors:** " + "; ".join(f"sentences {e['sentences']}: {e['error']}" for e in ev["errors"]), ""]
    if ev["gold_text_mismatches"]:
        L += [f"**Label/sentence mismatches:** {ev['gold_text_mismatches'][:3]}", ""]
    L += ["| Field | 81 report sentences | Paraphrases | All |", "|---|---|---|---|"]
    for f in FIELDS:
        L.append(f"| {f} | " + " | ".join(pct(ev["totals"][s]["fields"][f]) for s in ("81", "paraphrase", "all")) + " |")
    for k, name in (("fully_correct", "**every labelled field right**"), ("grounded", "fields/values exist in data")):
        L.append(f"| {name} | " + " | ".join(pct(ev["totals"][s][k]) for s in ("81", "paraphrase", "all")) + " |")
    L += ["", "## Paraphrase groups (same meaning, different words; '-' = a group of different claims of one kind)", "",
          "| Group | Same structure | Matches label |",
          "|---|---|---|"]
    L += [f"| {g['group']} | {'-' if g['consistent'] is None else 'yes' if g['consistent'] else 'NO'} | "
          f"{'yes' if g['all_match_label'] else 'NO'} |"
          for g in ev["paraphrase_groups"]]
    L += ["", "## Failure cases", ""]
    for r in ev["rows"]:
        bad = [f for f, v in r["scores"].items() if v is False]
        gissues = (r["grounding"] or {}).get("issues", [])
        if not bad and not gissues:
            continue
        s = r["spec"] or {}
        cv = s.get("claimed_value", {})
        got = (f"factual={s.get('is_factual')} cat={s.get('category')} agg={s.get('aggregation')} "
               f"field={s.get('target', {}).get('field')}={s.get('target', {}).get('value')!r} "
               f"num={cv.get('comparator')} {cv.get('number')} [{cv.get('low')}-{cv.get('high')}] "
               f"filters={[f['field'] for f in s.get('population', {}).get('filters', [])]} "
               f"verif={s.get('verifiability', {}).get('status')}") if s else "NO ENTRY RETURNED"
        L.append(f"- **{r['id']}** ({r['set']}) {r['text']}\n  - wrong: {', '.join(bad) or '-'}"
                 + (f"; grounding: {'; '.join(gissues)}" if gissues else "") + f"\n  - model said: {got}")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["gemini", "groq"])
    ap.add_argument("--both", action="store_true")
    a = ap.parse_args()
    load_env()
    rel = Release(CH / "data/tcga-brca/raw", CH / "data/tcga-brca/slide_manifest.csv")
    for prov in (["gemini", "groq"] if a.both else [a.provider]):
        if prov:
            os.environ["LLM_PROVIDER"], os.environ["LLM_FALLBACK"] = prov, "none"
        client = LLMClient.from_env()
        print("Configured:", client.status())
        ev = evaluate(client, rel)
        if not ev["provider"]:
            print("No provider answered:", ev["errors"][:2])
            continue
        md = report(ev)
        (ROOT / "outputs").mkdir(exist_ok=True)
        (ROOT / "outputs" / f"semantic_eval_{ev['provider']}.md").write_text(md, encoding="utf-8")
        (ROOT / "outputs" / f"semantic_eval_{ev['provider']}.json").write_text(json.dumps(ev, indent=1), encoding="utf-8")
        print(md.split("## Failure cases")[0])
        print(f"Full report with every failure: outputs/semantic_eval_{ev['provider']}.md")


if __name__ == "__main__":
    main()
