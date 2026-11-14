"""Expected values for the analytical engine, computed with plain pandas straight from release A's files.

  python tests/independent_answers.py
Uses none of the auditor's code, so the engine is checked against an independent calculation. The numbers it prints
are pasted into tests/test_engine.py.
"""
import pathlib

import pandas as pd

CH = pathlib.Path(__file__).resolve().parents[2] / "oncosys-hackathon-challenge"
R = CH / "data/tcga-brca/raw"
c = pd.read_csv(R / "clinical.tsv", sep="\t", dtype=str, keep_default_na=False)
c = c[c.sampleID.str[13:15] == "01"].set_index("sampleID")
BAD = {"", "[Discrepancy]", "[Not Available]", "[Unknown]", "Indeterminate"}


def share(mask, base):
    return f"{100 * mask.sum() / len(base):.1f}% ({int(mask.sum())} of {len(base)})"


def rec(col, extra=()):
    v = c[col]
    return v[~v.isin(BAD | set(extra))]


out = {}
s = rec("PAM50Call_RNAseq")
out["share LumA"] = share(s == "LumA", s)
out["rank PAM50 counts"] = s.value_counts().to_dict()
out["share LumA+LumB"] = share(s.isin(["LumA", "LumB"]), s)
er = rec("breast_carcinoma_estrogen_receptor_status")
out["share ER+"] = share(er == "Positive", er)
h = c["lab_proc_her2_neu_immunohistochemistry_receptor_status"]
h = h[h.isin(["Positive", "Negative"])]
out["share HER2+ definite"] = share(h == "Positive", h)
cols = ["breast_carcinoma_estrogen_receptor_status", "breast_carcinoma_progesterone_receptor_status",
        "lab_proc_her2_neu_immunohistochemistry_receptor_status"]
d = c[cols][c[cols].isin(["Positive", "Negative"]).all(axis=1)]
out["share triple-negative"] = share((d == "Negative").all(axis=1), d)
st = rec("pathologic_stage", ["Stage X"])
out["share stage IIIA"] = share(st == "Stage IIIA", st)
age = pd.to_numeric(c["age_at_initial_pathologic_diagnosis"], errors="coerce").dropna()
out["age median/mean"] = (float(age.median()), round(float(age.mean()), 2), len(age))
out["share age > 65"] = share(age > 65, age)
out["share age < 35"] = share(age < 35, age)
ln = pd.to_numeric(c["lymph_node_examined_count"], errors="coerce").dropna()
out["lymph nodes examined median"] = (float(ln.median()), len(ln))
age_luma = age.reindex(s.index[s == "LumA"]).dropna()
age_basal = age.reindex(s.index[s == "Basal"]).dropna()
out["age LumA vs Basal (mean, median)"] = (round(age_luma.mean(), 2), age_luma.median(), round(age_basal.mean(), 2),
                                           age_basal.median(), len(age_luma), len(age_basal))

mut = pd.read_csv(R / "mutation_gene_level.tsv.gz", sep="\t", index_col=0)
mp = [x for x in mut.columns if x[13:15] == "01"]
out["share TP53 mutated"] = share(mut.loc["TP53", mp] > 0, mp)
out["count TP53 mutated"] = int((mut.loc["TP53", mp] > 0).sum())
basal_m = [x for x in mp if s.get(x) == "Basal"]
out["share TP53 in Basal"] = share(mut.loc["TP53", basal_m] > 0, basal_m)
erp = [x for x in mp if er.get(x) == "Positive"]
out["share PIK3CA in ER+"] = share(mut.loc["PIK3CA", erp] > 0, erp)
both = ((mut.loc["TP53", mp] > 0) & (mut.loc["PIK3CA", mp] > 0))
out["share TP53 and PIK3CA co-mutated"] = share(both, mp)
out["GATA3 vs MAP3K1"] = (round(100 * (mut.loc["GATA3", mp] > 0).mean(), 1), round(100 * (mut.loc["MAP3K1", mp] > 0).mean(), 1))
freq = (mut[mp] > 0).mean(1).sort_values(ascending=False)
out["top 3 mutated genes"] = list(freq.index[:3])

cn = pd.read_csv(R / "copy_number_gistic.tsv.gz", sep="\t", index_col=0)
cp = [x for x in cn.columns if x[13:15] == "01"]
out["share ERBB2 amplified"] = share(cn.loc["ERBB2", cp] == 2, cp)
out["share CDKN2A deep deletion"] = share(cn.loc["CDKN2A", cp] == -2, cp)
out["share MYC gain (>=1)"] = share(cn.loc["MYC", cp] >= 1, cp)
her2pos_cn = [x for x in cp if h.get(x) == "Positive"]
out["share ERBB2 amplified in HER2+"] = share(cn.loc["ERBB2", her2pos_cn] == 2, her2pos_cn)

p = pd.read_csv(R / "protein_rppa.tsv.gz", sep="\t", index_col=0)
pp = [x for x in p.columns if x[13:15] == "01"]
pv = p.loc["ERALPHA", pp]
a, b = pv.reindex(er.index[er == "Positive"]).dropna(), pv.reindex(er.index[er == "Negative"]).dropna()
out["ERALPHA ER+ vs ER- (mean, median, n)"] = (round(a.mean(), 2), round(a.median(), 2), round(b.mean(), 2),
                                               round(b.median(), 2), len(a), len(b))
out["ERALPHA mean all"] = (round(pv.mean(), 3), len(pv))

sv = pd.read_csv(R / "survival.tsv", sep="\t")
sv = sv[sv["sample"].str[13:15] == "01"]
for ep in ("OS", "PFI", "DFI"):
    e = sv[ep].dropna()
    out[f"{ep} events"] = share(e == 1, e)
out["OS.time median days"] = float(sv["OS.time"].dropna().median())

sm = pd.read_csv(CH / "data/tcga-brca/sample_manifest.csv")
prim = sm[sm.sample_id.str[13:15] == "01"]
out["coverage protein"] = int(prim.has_protein.sum())
out["coverage rna&protein"] = int((prim.has_rna & prim.has_protein).sum())
out["coverage all 5 layers"] = int(prim[["has_survival", "has_mutation", "has_copy_number", "has_rna", "has_protein"]].all(axis=1).sum())
out["patients / samples / normal"] = (int(sm.patient_id.nunique()), len(sm), int((sm.sample_id.str[13:15] == "11").sum()))

sl = pd.read_csv(CH / "data/tcga-brca/slide_manifest.csv")
out["slides total / diagnostic"] = (len(sl), int(sl.slide_kind.str.startswith("diagnostic").sum()))
out["slide size median MB"] = float(sl.size_mb.median())
out["share slides 40x"] = share(sl.objective == 40, sl)
out["slides per patient"] = round(len(sl) / sl.patient_id.nunique(), 2)
for k, v in out.items():
    print(f"{k}: {v}")
