"""Regression tests: expected verdicts for the practice brief and the team's stress report.

  python tests/run_tests.py
Expected values were computed independently from release A (see the stress report's comments in README).
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import re  # noqa: E402

from auditor.audit import run_audit, to_shared_format  # noqa: E402
from auditor.release import Release  # noqa: E402

CH = ROOT.parent / "oncosys-hackathon-challenge"
REL = Release(CH / "data/tcga-brca/raw", CH / "data/tcga-brca/slide_manifest.csv")

EXPECT = {
    CH / "products/research-claim-auditor/practice_brief.md":
        ["not_a_claim", "supported", "contradicted", "not_a_claim", "insufficient_evidence", "not_a_claim"],
    HERE / "stress_report.md":
        ["supported", "supported", "contradicted", "supported", "contradicted", "supported", "supported", "supported",
         "supported", "supported", "contradicted", "contradicted", "insufficient_evidence", "insufficient_evidence", "supported"],
    HERE / "manifest_report.md":   # claims about slide_manifest.csv and sample_manifest.csv
        ["supported", "contradicted", "supported", "supported", "supported", "supported", "supported", "supported",
         "supported", "contradicted", "supported", "supported", "contradicted", "supported"],
    HERE / "next_steps_report.md":
        ["contradicted", "contradicted", "contradicted", "contradicted", "insufficient_evidence", "insufficient_evidence"],
}

# What should happen after each verdict (action, and the corrected sentence where the tool can write one)
ACTIONS = {
    HERE / "next_steps_report.md": [
        ("state_definition", None),   # 44% matches the 2012 Nature column: ask, don't change the number
        ("fix_number", "TP53 is mutated in 33.4% (264 of 791) of primary tumors with mutation data."),
        ("fix_number", "742 primary tumors have both RNA and protein data."),
        ("fix_number", "The median age at diagnosis was 58.0 years."),
        ("remove_or_reword", None),
        ("check_by_hand", None),
    ],
    CH / "products/research-claim-auditor/practice_brief.md": [
        (None, None), ("keep", None),
        ("fix_number", "Luminal A is the largest RNA subtype, accounting for 49.9% (421 of 844) of primary tumors with an RNA subtype call."),
        (None, None), ("remove_or_reword", None), (None, None)],
}

bad = 0
for path, want in EXPECT.items():
    audit = run_audit(path.read_text(encoding="utf-8"), REL)
    got = [i["tool_verdict"] for i in audit["items"]]
    for f in to_shared_format(audit)["findings"]:   # every contradicted claim must say what the data shows, with a number
        if f["claim_verdict"] == "contradicted" and not re.search(r"\d", f.get("correct_value") or ""):
            bad += 1
            print(f"FAIL {path.name} {f['id']}: contradicted without a numeric correct_value ({f.get('correct_value')!r})")
    for k, (it, (act, text)) in enumerate(zip(audit["items"], ACTIONS.get(path, [])), 1):
        imp = it["impact"]
        if act and imp["action"] != act:
            bad += 1
            print(f"FAIL {path.name} sentence {k}: next step {imp['action']!r}, expected {act!r}")
        if text and imp["suggested_text"] != text:
            bad += 1
            print(f"FAIL {path.name} sentence {k}: suggested text {imp['suggested_text']!r}")
        if act and act != "keep" and not (imp["why_it_matters"] and imp["next_step"] and imp["cant_tell"]):
            bad += 1
            print(f"FAIL {path.name} sentence {k}: missing why / next step / can't tell")
    for k, (g, w) in enumerate(zip(got, want), 1):
        if g != w:
            bad += 1
            print(f"FAIL {path.name} sentence {k}: got {g}, expected {w}")
    if len(got) != len(want):
        bad += 1
        print(f"FAIL {path.name}: {len(got)} sentences, expected {len(want)}")
    print(f"{'ok  ' if not bad else '    '} {path.name}: {len(got)} sentences")
print("ALL PASSED" if not bad else f"{bad} FAILURE(S)")
sys.exit(1 if bad else 0)
