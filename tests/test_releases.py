"""Robustness to releases whose schema differs from release A, plus the full envelope flow.

  python tests/test_releases.py
Builds a deliberately altered release in a temporary folder (renamed, added and removed columns; age stored as text;
recoded labels; fewer tumors with mutation data; missing protein and RNA files; an extra file), then checks that:
the adapter reports every change; claims are answered from the ACTIVE release (expected values computed with plain
pandas on the altered files); claims needing missing data become insufficient evidence with the reason; results
differ across releases where the data differ; rewriting a release in the same folder never reuses old results; and
the sealed-envelope flow (unseal, CLI, web app) still works.
"""
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from auditor.adapt import activate, compare_items, fingerprint  # noqa: E402
from auditor.audit import run_audit, to_shared_format  # noqa: E402
from auditor.engine import execute  # noqa: E402
from auditor.release import Release  # noqa: E402

CH = ROOT.parent / "oncosys-hackathon-challenge"
RAW = CH / "data/tcga-brca/raw"
SLIDES = CH / "data/tcga-brca/slide_manifest.csv"
bad = 0


def check(name, ok, detail=""):
    global bad
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if not ok and detail else ""))
    bad += 0 if ok else 1


def share(mask):
    return f"{100 * mask.sum() / len(mask):.1f}% ({int(mask.sum()):,} of {len(mask):,})"


# ------------------------------------------------------------------ build the altered release
tmp = pathlib.Path(tempfile.mkdtemp(prefix="altered_release_"))
V = tmp / "altered"
V.mkdir()
c = pd.read_csv(RAW / "clinical.tsv", sep="\t", dtype=str, keep_default_na=False)
c = c.rename(columns={"PAM50Call_RNAseq": "pam50_subtype_call",                       # renamed
                      "breast_carcinoma_estrogen_receptor_status": "er_status_ihc",
                      "age_at_initial_pathologic_diagnosis": "age_dx"})
c["pam50_subtype_call"] = c["pam50_subtype_call"].replace(                           # recoded labels
    {"LumA": "Luminal A", "LumB": "Luminal B", "Basal": "Basal-like", "Her2": "HER2-enriched", "Normal": "Normal-like"})
c["er_status_ihc"] = c["er_status_ihc"].replace({"Positive": "POS", "Negative": "NEG"})
c["age_dx"] = c["age_dx"].map(lambda v: f"{v} years" if v else v)                   # number stored as text
c = c.drop(columns=["histological_type"])                                             # removed
c["tumor_grade"] = ["G3" if i % 3 == 0 else "G2" for i in range(len(c))]              # added
c.to_csv(V / "clinical.tsv", sep="\t", index=False)
sv = pd.read_csv(RAW / "survival.tsv", sep="\t").rename(columns={"OS": "overall_survival"})   # renamed outcome
sv.to_csv(V / "survival.tsv", sep="\t", index=False)
mut = pd.read_csv(RAW / "mutation_gene_level.tsv.gz", sep="\t")
prim_cols = [x for x in mut.columns[1:] if x[13:15] == "01"]
mut = mut.drop(columns=prim_cols[:200])                                               # coverage changed
mut.to_csv(V / "mutation_gene_level.tsv.gz", sep="\t", index=False)
shutil.copy(RAW / "copy_number_gistic.tsv.gz", V / "copy_number_gistic.tsv.gz")
(V / "lab_notes.txt").write_text("extra file")                                        # extra file; no protein, no RNA

# expected answers straight from the altered files (no auditor code)
cp = c[c.sampleID.str[13:15] == "01"].set_index("sampleID")
sub = cp["pam50_subtype_call"][cp["pam50_subtype_call"] != ""]
er = cp["er_status_ihc"][cp["er_status_ihc"].isin(["POS", "NEG"])]
age = pd.to_numeric(cp["age_dx"].str.extract(r"(\d+)", expand=False), errors="coerce").dropna()
grade = cp["tumor_grade"]
mp = [x for x in mut.columns[1:] if x[13:15] == "01"]
tp53 = mut.set_index(mut.columns[0]).loc["TP53", mp] > 0
svp = sv[sv["sample"].str[13:15] == "01"]["overall_survival"].dropna()
EXP = {"luma": share(sub == "Luminal A"), "er": share(er == "POS"), "age": f"{age.median():g}",
       "grade3": share(grade == "G3"), "tp53": share(tp53), "n_mut": f"{len(mp):,}", "deaths": share(svp == 1)}
print("expected (pandas on the altered files):", EXP)

# ------------------------------------------------------------------ 1-7: the adapter sees every change
rel = Release(V, SLIDES)
ctx = activate(rel)
r = ctx.report()
check("renamed columns found by their values",
      r["renamed_fields"].get("PAM50Call_RNAseq") == "pam50_subtype_call"
      and r["renamed_fields"].get("breast_carcinoma_estrogen_receptor_status") == "er_status_ihc"
      and r["renamed_fields"].get("age_at_initial_pathologic_diagnosis") == "age_dx", r["renamed_fields"])
check("recoded labels mapped (Luminal A -> LumA, POS -> Positive)",
      r["recoded_values"].get("PAM50Call_RNAseq", {}).get("Luminal A") == "LumA"
      and r["recoded_values"].get("breast_carcinoma_estrogen_receptor_status", {}).get("POS") == "Positive",
      r["recoded_values"])
check("changed type: age as text is detected and convertible",
      r["type_changes"].get("age_at_initial_pathologic_diagnosis", {}).get("coercible") is True, r["type_changes"])
check("removed column reported", "histological_type" in r["missing_fields"], r["missing_fields"][:5])
check("added column reported", "tumor_grade" in r["added_fields"], r["added_fields"])
check("renamed survival endpoint mapped", r["survival_renamed"].get("OS") == "overall_survival", r["survival_renamed"])
check("missing files and extra file reported", set(r["files_missing"]) == {"protein_rppa.tsv.gz", "rna_hiseq.tsv.gz"}
      and r["files_extra"] == ["lab_notes.txt"], (r["files_missing"], r["files_extra"]))
check("changed coverage measured from the files", r["coverage_primary"].get("mutation") == len(mp),
      r["coverage_primary"])

# ------------------------------------------------------------------ 8-9: rule checkers answer from the ACTIVE release
REPORT = """# Altered release test
Luminal A accounts for 49.9% of primary tumors with an RNA subtype call.
About 77% of primary tumors with a definite result were ER-positive.
The median age at diagnosis was 58 years.
TP53 is mutated in 33.4% of primary tumors with mutation data.
Mutation data is available for 791 primary tumors.
About 14% of primary tumors with survival data had a recorded death.
Infiltrating ductal carcinoma accounts for about 72% of tumors.
ER-alpha protein is lower in ER-negative tumors than in ER-positive tumors.
"""
a_audit = run_audit(REPORT, Release(RAW, SLIDES))
v_audit = run_audit(REPORT, rel)
class ByPrefix(dict):
    def __getitem__(self, k):
        return next(v for kk, v in self.items() if kk.startswith(k))


items = ByPrefix({i["claim_text"]: i for i in v_audit["items"]})
obs = lambda k: " | ".join(s["observed"] for s in items[k]["result"]["subchecks"])  # noqa: E731
check("renamed + recoded subtype: same answer as pandas", items["Luminal A accounts for 49.9% o"]["tool_verdict"] == "supported"
      and EXP["luma"] in obs("Luminal A accounts for 49.9% o"), obs("Luminal A accounts for 49.9% o"))
check("renamed + recoded ER (POS/NEG)", EXP["er"] in obs("About 77% of primary tumors wi"), obs("About 77% of primary tumors wi"))
check("age stored as text still gives the median", items["The median age at diagnosis w"]["tool_verdict"] == "supported"
      and EXP["age"] in obs("The median age at diagnosis w"), obs("The median age at diagnosis w"))
check("TP53 recomputed on the smaller mutation set (now differs from 33.4%)", EXP["tp53"] in obs("TP53 is mutated in 33.4% of pr"),
      obs("TP53 is mutated in 33.4% of pr"))
check("coverage claim checked against the new coverage", items["Mutation data is available for"]["tool_verdict"] == "contradicted"
      and EXP["n_mut"] in obs("Mutation data is available for"), obs("Mutation data is available for"))
check("renamed survival endpoint gives the same death share", EXP["deaths"] in obs("About 14% of primary tumors wi"),
      obs("About 14% of primary tumors wi"))
hist, prot = items["Infiltrating ductal carcinoma "], items["ER-alpha protein is lower in ER"]
check("claim on a removed column: insufficient evidence, says what's missing",
      hist["tool_verdict"] == "insufficient_evidence" and "histological_type" in hist["result"]["limitation"],
      hist["result"]["limitation"][-160:])
check("claim needing a missing file: insufficient evidence, says what's missing",
      prot["tool_verdict"] == "insufficient_evidence" and "protein_rppa" in prot["result"]["limitation"],
      prot["result"]["limitation"][-160:])
check("renamed field disclosed on the claim", "stored as `pam50_subtype_call`" in items["Luminal A accounts for 49.9% o"]["result"]["limitation"])
check("audit records the release fingerprint and its adaptation",
      v_audit["release"]["fingerprint"] == fingerprint(V) and v_audit["release"]["adaptation"]["renamed_fields"])
check("release A audit has no adaptation", a_audit["release"]["adaptation"] is None)
out = tmp / "audit.json"
out.write_text(json.dumps(to_shared_format(v_audit)))
val = subprocess.run([sys.executable, str(CH / "format/validate.py"), str(out)], capture_output=True, text=True)
check("audit.json on the altered release passes the organizers' validator", "valid" in val.stdout and "invalid" not in val.stdout,
      val.stdout + val.stderr)

# ------------------------------------------------------------------ engine on the altered release
def S(field, value, num, agg="percentage", filters=()):
    return {"sentence_id": 1, "claim_text": "x", "is_factual": True, "category": "descriptive", "entity": "x",
            "metric": "x", "aggregation": agg, "target": {"field": field, "value": value, "text": "x"},
            "claimed_value": {"number": num, "unit": "percent" if agg == "percentage" else "years", "comparator": "eq",
                              "low": None, "high": None, "approximate": True, "as_written": None},
            "population": {"base": "primary_tumors", "filters": [{"field": f, "value": v, "text": "x"} for f, v in filters],
                           "text": None}, "grouping_variables": [],
            "comparison": {"is_comparison": False, "groups": [], "direction": "none"},
            "required_evidence": {"layers": [], "description": "x"},
            "verifiability": {"status": "checkable", "reason": "x"}, "ambiguities": []}


e = execute(S("clinical.PAM50Call_RNAseq", "LumA", 50), rel)
check("engine: reference field name resolves to the renamed column", e.verdict == "supported" and EXP["luma"] in e.subchecks[0].observed,
      e.subchecks[0].observed if e.subchecks else e.summary)
e = execute(S("clinical.age_at_initial_pathologic_diagnosis", None, 58, agg="median"), rel)
check("engine: age text converted, median from active data", e.verdict == "supported", e.summary)
e = execute(S("clinical.tumor_grade", "G3", 33.3), rel)
check("engine: an ADDED variable can be analysed in the release that has it",
      e.verdict == "supported" and EXP["grade3"] in e.subchecks[0].observed, e.summary)
e = execute(S("clinical.histological_type", "Infiltrating Ductal Carcinoma", 72), rel)
check("engine: removed variable -> insufficient at step 1", e.verdict == "insufficient_evidence" and e.trace[-1]["step"].startswith("1"),
      e.summary)
e = execute(S("protein.ERALPHA", None, 1.5, agg="mean"), rel)
check("engine: missing file -> insufficient, names the file", e.verdict == "insufficient_evidence" and "protein" in e.summary, e.summary)
e = execute(S("clinical.tumor_grade", "G3", 33.3), Release(RAW, SLIDES))
check("engine: same claim on release A (no grade field) -> insufficient", e.verdict == "insufficient_evidence", e.summary)

# ------------------------------------------------------------------ 10: across releases
diff = compare_items(a_audit["items"], v_audit["items"])
changed = {d["claim"] for d in diff}
check("cross-release comparison lists exactly the claims whose data changed",
      all(any(c.startswith(k) for c in changed) for k in ("TP53 is mutated", "Mutation data is available",
                                                            "Infiltrating ductal", "ER-alpha protein"))
      and not any(c.startswith("Luminal A accounts") for c in changed), sorted(changed))

# ------------------------------------------------------------------ never reuse results after a release is rewritten
fp1 = fingerprint(V)
time.sleep(0.05)
c2 = c.copy()
c2.loc[c2.sampleID.str[13:15] == "01", "er_status_ihc"] = "NEG"          # every primary tumor now ER-negative
c2.to_csv(V / "clinical.tsv", sep="\t", index=False)
os.utime(V / "clinical.tsv", None)
rel2 = Release(V, SLIDES)
again = ByPrefix({i["claim_text"]: i for i in run_audit(REPORT, rel2)["items"]})
check("rewritten release: new fingerprint", fingerprint(V) != fp1)
check("rewritten release: results recomputed, not reused", again["About 77% of primary tumors wi"]["tool_verdict"] == "contradicted"
      and "0.0%" in " ".join(s["observed"] for s in again["About 77% of primary tumors wi"]["result"]["subchecks"]))
e = execute(S("clinical.breast_carcinoma_estrogen_receptor_status", "Positive", 77), rel2)
check("rewritten release: engine reads the new contents", e.verdict == "contradicted", e.summary)

# ------------------------------------------------------------------ envelope flow still works end to end
env = CH / "envelopes/opened/practice/release"
res = subprocess.run([sys.executable, str(ROOT / "audit_report.py"), "--envelope", "practice", "orange", "meadow", "pilot",
                      "lantern"], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
                     env={**os.environ, "PYTHONIOENCODING": "utf-8"})
check("CLI: practice envelope unseals", "opened" in res.stdout and env.joinpath("clinical.tsv").exists(), res.stdout[-300:])
pa = run_audit((CH / "products/research-claim-auditor/practice_brief.md").read_text(encoding="utf-8"), Release(env, SLIDES))
check("practice envelope release: adaptation = only the RNA file missing",
      pa["release"]["adaptation"]["files_missing"] == ["rna_hiseq.tsv.gz"] and not pa["release"]["adaptation"]["renamed_fields"])
check("practice brief on the envelope release: the 5-layer claim (needs RNA) becomes insufficient, the rest match A",
      [i["tool_verdict"] for i in pa["items"]] == ["not_a_claim", "insufficient_evidence", "contradicted", "not_a_claim",
                                                    "insufficient_evidence", "not_a_claim"]
      and "RNA" in pa["items"][1]["result"]["needed"] + pa["items"][1]["result"]["summary"]
      + " ".join(s_["observed"] for s_ in pa["items"][1]["result"]["subchecks"]),
      [i["tool_verdict"] for i in pa["items"]])

# the web app: unseal + audit over HTTP, on a spare port, then stop it
with socket.socket() as s_:
    s_.bind(("127.0.0.1", 0))
    port = s_.getsockname()[1]
srv = subprocess.Popen([sys.executable, str(ROOT / "app.py"), "--port", str(port), "--no-browser"], cwd=ROOT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            break
        except OSError:
            time.sleep(0.5)

    def post(path, body):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=120).read())

    u = post("/api/unseal", {"number": "practice", "words": "orange meadow pilot lantern"})
    check("app: /api/unseal opens the practice envelope", "opened" in u["log"], u["log"][-200:])
    au = post("/api/audit", {"report_text": REPORT, "release_dir": str(V)})
    luma = next(i for i in au["items"] if i["claim_text"].startswith("Luminal A"))
    check("app: /api/audit on the altered release uses the active data",
          au["release"]["adaptation"]["renamed_fields"] and EXP["luma"] in luma["result"]["subchecks"][0]["observed"])
finally:
    srv.terminate()
    srv.wait(timeout=10)

shutil.rmtree(tmp, ignore_errors=True)
print("ALL PASSED" if not bad else f"{bad} FAILURE(S)")
sys.exit(1 if bad else 0)
