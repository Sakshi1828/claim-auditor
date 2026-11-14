"""Build the dataset profile + capability registry for each release, validate it, and probe the current engine.

  python tools/profile_release.py            # release A, the practice envelope (B) and the random test release
Writes catalog/<release>.profile.json, catalog/<release>.capabilities.json, catalog/validation.json,
catalog/gap_probe.json and catalog/FINDINGS.md. The verification engine is not changed.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from auditor.audit import run_audit  # noqa: E402
from auditor.catalog import capabilities, diff_profiles, profile_release, validate  # noqa: E402
from auditor.release import Release, is_primary  # noqa: E402

CH = ROOT.parent / "oncosys-hackathon-challenge"
OUT = ROOT / "catalog"
SLIDES = CH / "data/tcga-brca/slide_manifest.csv"


def dump(obj, path):
    path.write_text(json.dumps(obj, indent=1, default=str, ensure_ascii=True), encoding="utf-8")


def human(col: str) -> str:
    return col.replace("_nature2012", " (2012 study)").replace("_", " ").strip()


def probe_claims(rel: Release, prof: dict, caps: dict) -> list[dict]:
    """One TRUE claim per capability, written plainly, with the value computed here. A verifier should say supported."""
    claims = []
    c = rel.clinical_primary
    for cap in caps["capabilities"]:
        f = cap["field"]
        if cap["id"].startswith("share:") and cap["role"] in ("predictor", "annotation", "outcome") and cap.get("values"):
            col = f.split(".", 1)[1]
            x = next(p for p in prof["datasets"]["clinical.tsv"]["column_profiles"] if p["name"] == col)
            vals = {k: v for k, v in x["values_primary"].items() if k not in x.get("uninformative_values", [])}
            top, n = max(vals.items(), key=lambda kv: kv[1])
            pct = 100 * n / x["n_informative_primary"]
            claims.append((cap["id"], f"{pct:.1f}% of primary tumors with a recorded {human(col)} are {top}."))
        elif cap["id"].startswith("numeric:") and cap["role"] == "predictor" and cap.get("summary"):
            claims.append((cap["id"], f"The median {human(f.split('.', 1)[1])} is {cap['summary']['median']:g}."))
    d = prof["datasets"]
    if "mutation_gene_level.tsv.gz" in d:
        for g, v in list(d["mutation_gene_level.tsv.gz"]["top_genes_pct"].items())[:6]:
            claims.append(("mutation:frequency", f"{g} is mutated in {v}% of tumors with mutation data."))
    if "copy_number_gistic.tsv.gz" in d:
        for g, v in list(d["copy_number_gistic.tsv.gz"]["top_amplified_pct"].items())[:3]:
            claims.append(("copy_number:frequency", f"{g} is amplified in {v}% of tumors with copy number data."))
        for g, v in list(d["copy_number_gistic.tsv.gz"]["top_deleted_pct"].items())[:2]:
            claims.append(("copy_number:frequency", f"{g} is deeply deleted in {v}% of tumors with copy number data."))
    if rel.has_file("protein"):
        p = rel.protein[[x for x in rel.protein.columns if is_primary(x)]]
        sub = c["PAM50Call_RNAseq"]
        for prot in ("ERALPHA", "HER2", "PR", "AR", "GATA3"):
            if prot in p.index:
                lb = p.loc[prot].reindex(sub.index[sub == "Basal"]).dropna().mean()
                la = p.loc[prot].reindex(sub.index[sub == "LumA"]).dropna().mean()
                word = "higher" if la > lb else "lower"
                claims.append(("protein:levels", f"{prot} protein levels are {word} in Luminal A tumors than in Basal-like tumors."))
    if rel.has_file("rna"):
        claims.append(("rna:expression", "ESR1 expression is higher in ER-positive tumors than in ER-negative tumors."))
    ep = d["survival.tsv"]["endpoints_primary"]
    if "PFI" in ep:
        claims.append(("survival:descriptive", f"{ep['PFI']['event_pct']}% of primary tumors with survival data had a "
                                               f"progression event."))
        claims.append(("survival:descriptive", f"The median overall survival follow-up time was {ep['OS']['median_time_days']:g} days."))
    cov = prof["relationships"]["primary_tumors_with_layer"]
    if "copy_number" in cov:
        claims.append(("coverage:layers", f"{cov['copy_number']} primary tumors have copy number data."))
    out = []
    report = "\n\n".join(t for _, t in claims)
    items = [i for i in run_audit(report, rel)["items"]]
    by_text = {i["claim_text"]: i for i in items}
    for cid, text in claims:
        it = by_text.get(text)
        v = it["tool_verdict"] if it else "not_extracted"
        out.append({"capability": cid, "claim": text, "verdict": v, "checker": it["result"]["check"] if it else None,
                    "outcome": {"supported": "verified", "contradicted": "false alarm (true claim marked wrong)"}.get(
                        v, "NOT VERIFIABLE by current engine")})
    return out


def main():
    OUT.mkdir(exist_ok=True)
    releases = [("A", CH / "data/tcga-brca/raw"), ("practice", CH / "envelopes/opened/practice/release"),
                ("random-test", CH / "data/tcga-brca/releases/random-test")]
    profiles, all_valid, summary = {}, {}, []
    for name, d in releases:
        if not (d / "clinical.tsv").exists():
            print(f"skip {name}: not available ({d})")
            continue
        t0 = time.time()
        rel = Release(d, SLIDES)
        prof = profile_release(rel)
        caps = capabilities(prof, rel)
        val = validate(prof, caps, rel)
        dump(prof, OUT / f"{rel.name}.profile.json")
        dump(caps, OUT / f"{rel.name}.capabilities.json")
        profiles[rel.name] = (rel, prof, caps)
        all_valid[rel.name] = val
        ok = sum(v["ok"] for v in val)
        print(f"{rel.name}: {len(caps['capabilities'])} capabilities, {len(caps['associations'])} association tests, "
              f"validation {ok}/{len(val)} in {time.time() - t0:.1f}s")
        for v in val:
            if not v["ok"]:
                print("   FAIL", v["check"], v["detail"][:200])
    dump(all_valid, OUT / "validation.json")
    if "A" in profiles and "practice" in profiles:
        dump(diff_profiles(profiles["A"][1], profiles["practice"][1]), OUT / "diff_A_vs_practice.json")
    if "A" in profiles and "random-test" in profiles:
        dump(diff_profiles(profiles["A"][1], profiles["random-test"][1]), OUT / "diff_A_vs_random-test.json")
    rel, prof, caps = profiles["A"]
    probe = probe_claims(rel, prof, caps)
    dump(probe, OUT / "gap_probe.json")
    tally = pd.Series([p["outcome"] for p in probe]).value_counts().to_dict()
    print("probe of the current engine with TRUE claims:", tally)


if __name__ == "__main__":
    main()
