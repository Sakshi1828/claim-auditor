"""Regression tests: expected verdicts for the practice brief and the team's stress report.

  python tests/run_tests.py
Expected values were computed independently from release A (see the stress report's comments in README).
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from auditor.audit import run_audit  # noqa: E402
from auditor.release import Release  # noqa: E402

CH = ROOT.parent / "oncosys-hackathon-challenge"
REL = Release(CH / "data/tcga-brca/raw", CH / "data/tcga-brca/slide_manifest.csv")

EXPECT = {
    CH / "products/research-claim-auditor/practice_brief.md":
        ["not_a_claim", "supported", "contradicted", "not_a_claim", "insufficient_evidence", "not_a_claim"],
    HERE / "stress_report.md":
        ["supported", "supported", "contradicted", "supported", "contradicted", "supported", "supported", "supported",
         "supported", "supported", "contradicted", "contradicted", "insufficient_evidence", "insufficient_evidence", "supported"],
}

bad = 0
for path, want in EXPECT.items():
    got = [i["tool_verdict"] for i in run_audit(path.read_text(encoding="utf-8"), REL)["items"]]
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
