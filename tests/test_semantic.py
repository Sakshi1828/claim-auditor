"""Offline test of the semantic layer and its evaluation harness (no key, no network: a fake model answers).

  python tests/test_semantic.py
1. Labels line up with the 81 real sentences. 2. A model that answers exactly like the labels scores 100% and is
grounded. 3. Injected mistakes (invented field, wrong number, made-up gene, wrong category) are caught.
"""
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE))

import jsonschema  # noqa: E402

from auditor.llm import LLMResult  # noqa: E402
from auditor.release import Release  # noqa: E402
from auditor.semantic import SEMANTIC_OUTPUT  # noqa: E402
import eval_semantic as ev  # noqa: E402
from semantic_gold import GOLD_81, PARAPHRASES  # noqa: E402

CH = HERE.parent.parent / "oncosys-hackathon-challenge"
REL = Release(CH / "data/tcga-brca/raw", CH / "data/tcga-brca/slide_manifest.csv")
LABELS = GOLD_81 + [label for _, label, ss in PARAPHRASES for _ in ss]
bad = 0


def check(name, ok, detail=""):
    global bad
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if not ok and detail else ""))
    bad += 0 if ok else 1


def spec_from(i: int, g: dict) -> dict:
    """The structure a perfect model would return for label g."""
    first = lambda k, d=None: (g.get(k) or [d])[0]  # noqa: E731
    value = first("value")
    field = first("field")
    if field and field.startswith("copy_number") and value is None:
        value = "amplified"
    num = g.get("num")
    return {
        "sentence_id": i, "claim_text": g["text"], "is_factual": g["factual"],
        "category": first("cat", "not_factual") if g["factual"] else "not_factual",
        "entity": "x", "metric": "x", "aggregation": first("agg", "none"),
        "target": {"field": field, "value": value, "text": "x"},
        "claimed_value": {"number": num if num is not None else (g.get("low") and (g["low"] + g["high"]) / 2),
                          "unit": "percent", "comparator": first("cmp", "eq"), "low": g.get("low"), "high": g.get("high"),
                          "approximate": False, "as_written": None},
        "population": {"base": "primary_tumors", "text": None,
                       "filters": [{"field": f, "value": None, "text": "x"} for f in (g.get("filt") or [])[:1]]},
        "grouping_variables": [], "comparison": {"is_comparison": False, "groups": [], "direction": first("dir", "none")},
        "required_evidence": {"layers": [], "description": "x"},
        "verifiability": {"status": first("verif", "not_a_claim") if g["factual"] else "not_a_claim", "reason": "x"},
        "ambiguities": []}


class FakeClient:
    def __init__(self, mutate=None):
        self.mutate = mutate or (lambda i, s: s)

    def complete_json(self, system, user, schema, schema_name):
        ids = [int(m) for m in re.findall(r"^(\d+)\. ", user, re.M)]
        claims = [self.mutate(i, spec_from(i, LABELS[i - 1])) for i in ids]
        data = {"claims": claims}
        jsonschema.validate(data, SEMANTIC_OUTPUT)     # the fake must obey the same schema as a real model
        return LLMResult(ok=True, data=data, provider="fake", model="perfect")


# 1. labels line up with the real sentences
sents = [s.text for p in ev.REPORTS for s in ev.split_sentences(p.read_text(encoding="utf-8"))]
check("81 sentences in the six release-A reports", len(sents) == 81 == len(GOLD_81), f"{len(sents)} / {len(GOLD_81)}")
mism = [i + 1 for i, (a, b) in enumerate(zip(sents, GOLD_81)) if a != b["text"]]
check("every label's text matches its sentence exactly", not mism, f"sentences {mism}")

# 2. a perfect model scores 100% and every field it names exists in the data
r = ev.evaluate(FakeClient(), REL)
t = r["totals"]["all"]
check("perfect answers: every labelled field right", t["fully_correct"][0] == t["fully_correct"][1], t["fully_correct"])
ungrounded = [(x["id"], x["grounding"]["issues"]) for x in r["rows"] if x["grounding"] and not x["grounding"]["ok"]]
check("perfect answers: every field, value and gene exists in release A (labels are grounded)", not ungrounded,
      str(ungrounded[:4]))
check("perfect answers: every paraphrase group consistent",
      all(g["consistent"] for g in r["paraphrase_groups"]), [g["group"] for g in r["paraphrase_groups"] if not g["consistent"]])


# 3. mistakes are caught
def mutate(i, s):
    if i == 14:                          # invented field
        s["target"]["field"] = "clinical.tumor_grade"
    if i == 8:                           # wrong number
        s["claimed_value"]["number"] = 87
    if i == 12:                          # gene that doesn't exist
        s["target"]["field"] = "mutation.PIK3CX"
    if i == 19:                          # wrong category
        s["category"] = "descriptive"
    return s


r = ev.evaluate(FakeClient(mutate), REL)
row = {x["id"]: x for x in r["rows"]}
check("invented field is caught by grounding and scoring",
      row[14]["scores"]["field"] is False and any("tumor_grade" in i for i in row[14]["grounding"]["issues"]))
check("wrong number is caught", row[8]["scores"]["number"] is False)
check("made-up gene is caught by grounding", any("PIK3CX" in i for i in row[12]["grounding"]["issues"]))
check("wrong category is caught", row[19]["scores"]["category"] is False)
check("failure report lists the mistakes", all(f"**{i}**" in ev.report(r) for i in (8, 12, 14, 19)))

print("ALL PASSED" if not bad else f"{bad} FAILURE(S)")
sys.exit(1 if bad else 0)
