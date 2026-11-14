"""Every analytical-engine operation against independently computed answers (tests/independent_answers.py).

  python tests/test_engine.py
Claims are written as structured specs by hand (no LLM), so this tests the engine alone: field resolution,
populations, denominators, operations, comparison, verdicts, insufficient-evidence paths and the rule/engine merge.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from auditor.checks import Result  # noqa: E402
from auditor.engine import OPERATIONS, combine, execute  # noqa: E402
from auditor.release import Release  # noqa: E402

CH = HERE.parent.parent / "oncosys-hackathon-challenge"
A = Release(CH / "data/tcga-brca/raw", CH / "data/tcga-brca/slide_manifest.csv")
B = Release(CH / "envelopes/opened/practice/release", CH / "data/tcga-brca/slide_manifest.csv")
SUB, ER = "clinical.PAM50Call_RNAseq", "clinical.breast_carcinoma_estrogen_receptor_status"
HER2 = "clinical.lab_proc_her2_neu_immunohistochemistry_receptor_status"
AGE = "clinical.age_at_initial_pathologic_diagnosis"


def R(field, value=None):
    return {"field": field, "value": value, "text": "x"}


def S(field, value=None, agg="percentage", num=None, unit="percent", cmp="eq", approx=False, filters=(), groups=(),
      direction="none", cat="descriptive", verif="checkable", factual=True, layers=(), low=None, high=None, written=None):
    return {"sentence_id": 1, "claim_text": "x", "is_factual": factual, "category": cat, "entity": "x", "metric": "x",
            "aggregation": agg, "target": R(field, value),
            "claimed_value": {"number": num, "unit": unit, "comparator": cmp, "low": low, "high": high,
                              "approximate": approx, "as_written": written},
            "population": {"base": "primary_tumors", "filters": [R(*f) for f in filters], "text": None},
            "grouping_variables": [], "comparison": {"is_comparison": bool(groups), "groups": [R(*g) for g in groups],
                                                     "direction": direction},
            "required_evidence": {"layers": list(layers), "description": "x"},
            "verifiability": {"status": verif, "reason": "x"}, "ambiguities": []}


bad, used_ops = 0, set()


def case(name, spec, verdict, observed=None, rel=A, step=None):
    """Run one claim; check the verdict, the computed evidence text, and (for refusals) the step that stopped it."""
    global bad
    r = execute(spec, rel)
    obs = " | ".join(s.observed for s in r.subchecks)
    ok = r.verdict == verdict and (observed is None or observed in obs) and (step is None or r.trace[-1]["step"].startswith(step))
    if r.check.startswith("engine:"):
        used_ops.add(r.check.split(":")[1])
    if r.verdict in ("supported", "contradicted") and r.check.startswith("engine:") and r.check not in (
            "engine:cohort", "engine:slides"):
        ok = ok and [t["step"][:2] for t in r.trace] == ["1 ", "2 ", "3 ", "4 ", "5 ", "6 ", "7 ", "8 ", "9 ", "10"]
    print(f"{'ok  ' if ok else 'FAIL'} {name}: {r.verdict}" + (f" | {obs}" if obs else f" | {r.trace[-1]['detail'][:90]}"))
    bad += 0 if ok else 1
    return r


print("-- shares (categorical, derived, stage groups, numeric thresholds)")
case("Luminal A about 50%", S(SUB, "LumA", num=50, approx=True), "supported", "49.9% (421 of 844)")
r = case("Luminal A 62%", S(SUB, "LumA", num=62), "contradicted", "49.9% (421 of 844)")
assert r.correct_value and "421 of 844" in r.correct_value
case("ER-positive 77%", S(ER, "Positive", num=77), "supported", "77.2% (808 of 1,046)")
case("triple-negative about 16%", S("derived.triple_negative", "Positive", num=16, approx=True), "supported", "16.1% (116 of 722)")
case("stage IIIA 14.5%", S("clinical.pathologic_stage", "Stage IIIA", num=14.5), "supported", "14.5% (156 of 1,075)")
case("stage III (IIIA-C) about 23%", S("clinical.pathologic_stage", "Stage III", num=23, approx=True), "supported",
     "23.3% (250 of 1,075)")
case("older than 65: 23% (wrong)", S(AGE, ">65", num=23), "contradicted", "29.3% (321 of 1,097)")
case("under 35: fewer than 5%", S(AGE, "<35", num=5, cmp="lt"), "supported", "2.6% (28 of 1,097)")

print("-- numeric summaries")
case("median age 58", S(AGE, agg="median", num=58, unit="years"), "supported", "58 (n = 1,097)")
case("mean age about 58", S(AGE, agg="mean", num=58, unit="years", approx=True), "supported", "58.46 (n = 1,097)")
case("median age 62 (wrong)", S(AGE, agg="median", num=62, unit="years"), "contradicted", "58")
case("median lymph nodes examined 9", S("clinical.lymph_node_examined_count", agg="median", num=9, unit="count"),
     "supported", "9 (n = 971)")
case("mean ER-alpha protein about 1.5", S("protein.ERALPHA", agg="mean", num=1.5, unit="relative_level", approx=True),
     "supported", "1.46 (n = 742)")
case("median OS follow-up 843 days", S("survival.OS.time", agg="median", num=843, unit="days"), "supported", "843")

print("-- mutations and copy number (incl. subgroups and counts)")
case("TP53 mutated 33.4%", S("mutation.TP53", "mutated", num=33.4), "supported", "33.4% (264 of 791)")
case("at least 250 TP53-mutated", S("mutation.TP53", "mutated", agg="count", num=250, unit="count", cmp="ge"),
     "supported", "264")
case("TP53 in basal-like ~80% (wrong)", S("mutation.TP53", "mutated", num=80, approx=True, filters=[(SUB, "Basal")]),
     "contradicted", "84.9% (90 of 106)")
case("PIK3CA in ER+ about 41%", S("mutation.PIK3CA", "mutated", num=41, approx=True, filters=[(ER, "Positive")]),
     "supported", "41.4% (235 of 567)")
case("ERBB2 amplified 12.3%", S("copy_number.ERBB2", "amplified", num=12.3), "supported", "12.3% (133 of 1,080)")
case("CDKN2A deep deletion 4.4%", S("copy_number.CDKN2A", "deep_deletion", num=4.4), "supported", "4.4% (47 of 1,080)")
case("MYC gain about 63%", S("copy_number.MYC", "gain", num=63, approx=True), "supported", "62.8% (678 of 1,080)")
case("ERBB2 amplified in HER2+ about half", S("copy_number.ERBB2", "amplified", num=50, approx=True, written="about half",
                                              filters=[(HER2, "Positive")]), "supported", "53.7% (87 of 162)")

print("-- comparisons, ranks")
case("ER-alpha higher in ER+ than ER-", S("protein.ERALPHA", agg="group_difference", cat="comparative",
     groups=[(ER, "Positive"), (ER, "Negative")], direction="higher"), "supported", "mean 2.18 vs -0.87")
case("ER-alpha lower in ER+ (wrong)", S("protein.ERALPHA", agg="group_difference", cat="comparative",
     groups=[(ER, "Positive"), (ER, "Negative")], direction="lower"), "contradicted", "mean 2.18 vs -0.87")
case("Luminal A patients older than basal-like", S(AGE, agg="group_difference", cat="comparative",
     groups=[(SUB, "LumA"), (SUB, "Basal")], direction="higher"), "supported", "mean 58.98 vs 55.89; median 61.00 vs 54.00")
case("GATA3 mutated more often than MAP3K1", S("mutation.GATA3", "mutated", agg="group_difference", cat="comparative",
     groups=[("mutation.GATA3", "mutated"), ("mutation.MAP3K1", "mutated")], direction="more_common"),
     "supported", "12.3% vs mutation.MAP3K1 8.3%")
case("Luminal A ranks 1st", S(SUB, "LumA", agg="rank", num=1, unit="count"), "supported", "rank 1")
case("Basal-like ranks 2nd (wrong: 3rd)", S(SUB, "Basal", agg="rank", num=2, unit="count"), "contradicted", "rank 3")

print("-- outcomes, coverage, cohort, slides")
case("deaths 13.8%", S("survival.OS", "event", num=13.8), "supported", "13.8% (151 of 1,097)")
case("recurrence 20% (wrong)", S("survival.DFI", "event", num=20), "contradicted", "8.8% (84 of 953)")
case("protein data: fewer than 800", S("coverage.protein", "present", agg="count", num=800, unit="count", cmp="lt"),
     "supported", "742")
case("RNA and protein: 612 (wrong)", S("coverage.all", "present", agg="count", num=612, unit="count",
     layers=["rna", "protein"]), "contradicted", "742")
case("all five layers: 535", S("coverage.all", "present", agg="count", num=535, unit="count"), "supported", "535")
case("1,101 patients", S("cohort.patients", agg="count", num=1101, unit="count"), "supported", "1,101")
case("139 normal samples", S("cohort.normal_samples", agg="count", num=139, unit="count"), "supported", "139")
case("3,111 slides", S("slides.count", agg="count", num=3111, unit="count"), "supported", "3,111")
case("1,133 diagnostic slides", S("slides.slide_kind", "diagnostic", agg="count", num=1133, unit="count"), "supported", "1,133")
case("median slide about 338 MB", S("slides.size_mb", agg="median", num=338, unit="megabytes", approx=True), "supported", "337.6")
case("83% scanned at 40x", S("slides.objective", "40", num=83), "supported", "83.0% (2,583 of 3,111)")
case("about 2.8 slides per patient", S("slides.per_patient", agg="average_per_entity", num=2.8, unit="count", approx=True),
     "supported", "2.83")

print("-- the data can't establish it: insufficient evidence, with the step that stopped")
case("causal claim", S("mutation.TP53", "mutated", cat="causal", verif="needs_human_judgement"), "insufficient_evidence", step="2")
case("treatment response", S(SUB, "LumA", cat="treatment_response", verif="needs_human_judgement"), "insufficient_evidence", step="2")
case("tumor grade (not in data)", S(None, verif="not_in_data", num=40), "insufficient_evidence", step="2")
case("unknown field", S("clinical.tumor_grade", "3", num=40), "insufficient_evidence", step="1")
case("category that doesn't exist", S(SUB, "Luminal C", num=10), "insufficient_evidence", step="1")
case("mean of a category (incompatible)", S(SUB, agg="mean", num=3), "insufficient_evidence", step="2")
case("population too small (male basal-like)", S("mutation.TP53", "mutated", num=50,
     filters=[("clinical.gender", "MALE"), (SUB, "Basal")]), "insufficient_evidence", step="5")
case("RNA claim on an envelope release (no RNA file)", S("rna.ESR1", agg="mean", num=10, unit="relative_level"),
     "insufficient_evidence", rel=B, step="1")
case("share with no number stated", S(SUB, "LumA"), "insufficient_evidence", step="6")
case("same MYC answer on the envelope release", S("copy_number.ERBB2", "amplified", num=12.3), "supported",
     "12.3% (133 of 1,080)", rel=B)
r = execute(S(SUB, "LumA", factual=False), A)
print(f"{'ok  ' if r.verdict == 'not_a_claim' else 'FAIL'} non-factual: {r.verdict}")
bad += r.verdict != "not_a_claim"

print("-- working alongside the rule-based checkers")
rule_ok = Result(verdict="supported", check="subtype_share", summary="rule")
eng_bad = Result(verdict="contradicted", check="engine:share", summary="engine")
m = combine(rule_ok, eng_bad)
ok1 = m.verdict == "supported" and m.confidence == "low" and "engine disagrees" in m.limitation
eng_ok = Result(verdict="supported", check="engine:share", summary="engine")
ok2 = combine(Result(verdict="insufficient_evidence", check="unrecognised", summary="rule"), eng_ok).check == "engine:share"
ok3 = combine(Result(verdict="insufficient_evidence", check="treatment_response", summary="r"), eng_ok).check == "treatment_response"
for name, ok in (("rule verdict stands; disagreement flagged for a person", ok1),
                 ("engine fills a gap the rules couldn't check", ok2),
                 ("rules' deliberate refusal (treatment) is kept", ok3)):
    print(f"{'ok  ' if ok else 'FAIL'} {name}")
    bad += not ok

missing = set(OPERATIONS) - used_ops
print(f"\noperations exercised: {sorted(used_ops)}" + (f"; NOT exercised: {sorted(missing)}" if missing else ""))
bad += bool(missing)
print("ALL PASSED" if not bad else f"{bad} FAILURE(S)")
sys.exit(1 if bad else 0)
