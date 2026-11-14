"""Dataset intelligence: profile every file in a release and list only the analyses the data can actually support.

profile_release(release)   -> machine-readable profile of every file, column, identifier and relationship
capabilities(profile, rel) -> registry of verifiable analyses (each with field, population, n, limits)
validate(profile, caps, rel) -> independent re-checks of the profile against the raw files

Nothing here is used by the verification engine yet. Aggregates only: no sample or patient identifiers are stored.
"""
from __future__ import annotations

import math
import re

import pandas as pd

from .release import FILES, Release, is_primary

PROFILE_VERSION = "1.0"
MIN_N = 30            # a capability needs at least this many informative primary tumors
MIN_GROUP = 20        # a grouping variable needs >= 2 groups of at least this size
MISSING = {"", "nan", "none", "[discrepancy]", "[not available]", "[unknown]", "[not evaluated]", "[not applicable]"}
UNINFORMATIVE = re.compile(r"indeterminate|^unknown|not assessed|^stage x$|^[ntm]x$|discrepancy|not evaluated", re.I)

# ------------------------------------------------------------------ roles
ROLE_RULES = [   # first match wins; checked on the column name
    ("identifier", r"^sampleID$|^_PATIENT$|barcode|^patient_id$|uuid|^sample$|_GENOMIC_ID"),
    ("outcome", r"vital|death|days_to_last|last_contact|new_tumor_event|neoplasm_cancer_status|^OS|^DSS|^DFI|^PFI|"
                r"_event_|recurrence|lost_follow|Survival_Data_Form|followup_case_report"),
    ("metadata", r"form_completion|vial|portion|tissue_source|_INTEGRATION|system_version|method|oct_embedded|is_ffpe|"
                 r"prospective|retrospective|batch|center|^year_of|icd|days_to_collection|days_to_initial|consent|"
                 r"_cohort$|_primary_disease|_primary_site|disease_code|project|^sample_type$|^sample_type_id$|tumor_tissue_site|"
                 r"anatomic_neoplasm|^other_dx$|_mcrmtstss|cytokeratin|primary_lymph_node_presentation"),
    ("annotation", r"cluster|PAM50|_PANCAN|nature2012|Converted_Stage|methylation|miRNA|_CNA_"),
]
ROLE_NOTE = {
    "identifier": "Links records; never a quantity to analyse.",
    "outcome": "Something observed after diagnosis (vital status, events, follow-up). Descriptive rates only: the release "
               "has no pre-specified survival analysis, and follow-up differs by patient.",
    "metadata": "Describes how a sample or record was collected or coded, not the patient or tumor. Shares are computable "
                "but rarely scientific claims.",
    "annotation": "A derived research label (2012 publication, Pan-Cancer clusters, PAM50 calls). Only covers the samples "
                  "that study analysed.",
    "predictor": "A characteristic of the patient or tumor at diagnosis, or a treatment given (yes/no, not response).",
    "free_text": "Free text or near-unique values: not aggregable.",
}


def role_of(col: str, kind: str) -> str:
    if kind == "free_text":
        return "free_text"
    for role, pat in ROLE_RULES:
        if re.search(pat, col, re.I):
            return role
    return "predictor"


# ------------------------------------------------------------------ small statistics (no scipy available)
def _gammq(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x) (Numerical Recipes): chi-square p-value = Q(df/2, stat/2)."""
    if x <= 0:
        return 1.0
    gln = math.lgamma(a)
    if x < a + 1:                                    # series
        ap, s, d = a, 1.0 / a, 1.0 / a
        for _ in range(500):
            ap += 1
            d *= x / ap
            s += d
            if abs(d) < abs(s) * 1e-12:
                break
        return 1.0 - s * math.exp(-x + a * math.log(x) - gln)
    b, c, d = x + 1 - a, 1e300, 1.0 / (x + 1 - a)   # continued fraction
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1.0 / d
        h *= d * c
        if abs(d * c - 1) < 1e-12:
            break
    return math.exp(-x + a * math.log(x) - gln) * h


def chi_square(table: pd.DataFrame) -> dict:
    obs = table.values.astype(float)
    n = obs.sum()
    exp = obs.sum(1, keepdims=True) * obs.sum(0, keepdims=True) / n
    stat = float(((obs - exp) ** 2 / exp).sum())
    df = (obs.shape[0] - 1) * (obs.shape[1] - 1)
    return {"test": "chi-square", "statistic": round(stat, 3), "df": df, "p": _gammq(df / 2, stat / 2), "n": int(n),
            "min_expected": round(float(exp.min()), 2), "valid": bool(df > 0 and (exp >= 5).mean() >= 0.8 and exp.min() >= 1)}


def mann_whitney(a: pd.Series, b: pd.Series) -> dict:
    """Two-sided Mann-Whitney U, normal approximation with tie correction."""
    a, b = a.dropna(), b.dropna()
    n1, n2 = len(a), len(b)
    ranks = pd.concat([a, b]).rank()
    u = float(ranks.iloc[:n1].sum() - n1 * (n1 + 1) / 2)
    ties = pd.concat([a, b]).value_counts()
    tie = float(((ties ** 3 - ties).sum()) / ((n1 + n2) * (n1 + n2 - 1))) if n1 + n2 > 1 else 0
    sd = math.sqrt(n1 * n2 / 12 * ((n1 + n2 + 1) - tie)) or 1e-9
    z = (u - n1 * n2 / 2) / sd
    return {"test": "Mann-Whitney U", "statistic": round(u, 1), "z": round(z, 3), "p": math.erfc(abs(z) / math.sqrt(2)),
            "n": n1 + n2, "valid": bool(n1 >= MIN_GROUP and n2 >= MIN_GROUP)}


# ------------------------------------------------------------------ column profiling
def _clean(s: pd.Series) -> pd.Series:
    t = s.astype(str).str.strip()
    return s.where(~t.str.lower().isin(MISSING) & s.notna())


def profile_column(name: str, raw: pd.Series, primary_mask: pd.Series, patient: pd.Series) -> dict:
    s = _clean(raw)
    n = len(s)
    present = s.dropna()
    num = pd.to_numeric(present, errors="coerce")
    numeric_share = float(num.notna().mean()) if len(present) else 0.0
    n_unique = int(present.astype(str).nunique())
    if len(present) and numeric_share >= 0.95 and n_unique > 12:
        kind = "numeric"
    elif n_unique <= 40 or (len(present) and n_unique / len(present) < 0.05):
        kind = "categorical"
    else:
        kind = "free_text"
    if n_unique <= 1:
        kind = "constant" if n_unique == 1 else "empty"
    prim = s[primary_mask]
    informative = prim.dropna().astype(str)
    informative = informative[~informative.str.match(UNINFORMATIVE)]
    # granularity: does the value ever differ between samples of the same patient?
    per_patient = s.groupby(patient).nunique(dropna=True)
    multi = patient.value_counts()
    multi = multi[multi > 1].index
    varies = int((per_patient.reindex(multi).fillna(0) > 1).sum())
    out = {
        "name": name, "kind": kind, "role": None,
        "pandas_dtype": str(raw.dtype),
        "missing_pct": round(100 * (1 - len(present) / n), 1) if n else 100.0,
        "missing_pct_primary": round(100 * (1 - prim.notna().sum() / len(prim)), 1) if len(prim) else 100.0,
        "n_unique": n_unique,
        "n_informative_primary": int(len(informative)),
        "granularity": "sample" if varies else "patient",
        "patients_with_differing_values": varies,
    }
    if kind == "categorical":
        vc = prim.dropna().astype(str).value_counts()
        out["values_primary"] = {k: int(v) for k, v in vc.head(25).items()}
        out["uninformative_values"] = sorted(v for v in vc.index if UNINFORMATIVE.search(v))
        if len(vc) > 25:
            out["values_truncated"] = int(len(vc) - 25)
    elif kind == "numeric":
        x = pd.to_numeric(prim, errors="coerce").dropna()
        if len(x):
            out["summary_primary"] = {"n": int(len(x)), "min": float(x.min()), "q1": float(x.quantile(.25)),
                                      "median": float(x.median()), "mean": round(float(x.mean()), 3),
                                      "q3": float(x.quantile(.75)), "max": float(x.max())}
    out["role"] = role_of(name, kind)
    out["role_note"] = ROLE_NOTE[out["role"]]
    return out


def _matrix_profile(df: pd.DataFrame, layer: str) -> dict:
    cols = [c for c in df.columns if is_primary(c)]
    vals = pd.Series(df[cols].values.ravel())
    out = {"features": int(df.shape[0]), "samples": int(df.shape[1]), "primary_samples": len(cols),
           "missing_pct": round(100 * float(vals.isna().mean()), 2), "granularity": "sample",
           "orientation": "features x samples (first column = feature name)"}
    if layer == "mutation":
        freq = (df[cols] > 0).mean(1).sort_values(ascending=False)
        out.update(values={"0": "no non-silent mutation called", "1": "at least one non-silent mutation"},
                   genes_mutated_in_any_primary=int((freq > 0).sum()),
                   genes_mutated_ge_1pct=int((freq >= .01).sum()),
                   top_genes_pct={g: round(100 * float(v), 1) for g, v in freq.head(25).items()})
    elif layer == "copy_number":
        amp = (df[cols] == 2).mean(1).sort_values(ascending=False)
        dele = (df[cols] == -2).mean(1).sort_values(ascending=False)
        out.update(values={"-2": "deep (likely homozygous) deletion", "-1": "shallow loss", "0": "diploid",
                           "1": "low-level gain", "2": "high-level amplification"},
                   value_share_pct={str(k): round(100 * float(v), 2) for k, v in vals.value_counts(normalize=True).sort_index().items()},
                   top_amplified_pct={g: round(100 * float(v), 1) for g, v in amp.head(15).items()},
                   top_deleted_pct={g: round(100 * float(v), 1) for g, v in dele.head(15).items()})
    else:
        x = vals.dropna()
        out.update(value_range=[round(float(x.min()), 3), round(float(x.max()), 3)],
                   value_median=round(float(x.median()), 3))
        if layer == "protein":
            out["units"] = "RPPA, normalized relative levels (median-centred per protein): compare groups, not absolute amounts"
            out["features_list"] = list(map(str, df.index))
        if layer == "rna":
            out["units"] = "log2(normalized count + 1) per gene: compare groups, not absolute amounts"
    return out


# ------------------------------------------------------------------ release profile
def profile_release(rel: Release) -> dict:
    # read as text so category labels are exactly what the file says ("2", not "2.0")
    c = pd.read_csv(rel.path("clinical"), sep="\t", dtype=str, keep_default_na=False)
    sid = c.sampleID.astype(str)
    patient = sid.str[:12]
    primary = sid.map(is_primary)
    cols = [profile_column(col, c[col], primary, patient) for col in c.columns if col != "sampleID"]
    files = {k: rel.has_file(k) for k in FILES}
    prof = {
        "profile_version": PROFILE_VERSION,
        "release": rel.name,
        "files_present": {FILES[k]: v for k, v in files.items()},
        "identifiers": {
            "barcode": "TCGA-XX-XXXX = patient; TCGA-XX-XXXX-NN = sample; NN = 01 primary tumor, 11 solid normal, 06 metastatic",
            "join_key": "sample barcode (first 15 characters); patient = first 12",
            "id_columns": {"clinical.tsv": "sampleID", "survival.tsv": "sample (+ _PATIENT)",
                           "matrices": "column headers are sample barcodes", "sample_manifest.csv": "sample_id, patient_id",
                           "slide_manifest.csv": "slide_barcode -> sample_id -> patient_id"},
        },
        "datasets": {},
    }
    prof["datasets"]["clinical.tsv"] = {
        "purpose": "One row per sample: demographics, diagnosis, pathology, receptor tests, treatment given (yes/no), "
                   "follow-up, and 2012 / Pan-Cancer research annotations.",
        "rows": int(len(c)), "columns": int(c.shape[1]),
        "sample_types": {k: int(v) for k, v in sid.str[13:15].value_counts().items()},
        "patients": int(patient.nunique()), "primary_tumors": int(primary.sum()),
        "granularity": "sample rows; most variables are patient-level and repeat across a patient's samples",
        "column_profiles": cols,
        "roles": pd.Series([x["role"] for x in cols]).value_counts().to_dict(),
        "kinds": pd.Series([x["kind"] for x in cols]).value_counts().to_dict(),
    }
    sv = rel.survival
    sv_prim = sv[sv["sample"].map(is_primary)]
    endpoints = {}
    for ep in ("OS", "DSS", "DFI", "PFI"):
        if ep in sv:
            e = pd.to_numeric(sv_prim[ep], errors="coerce")
            t = pd.to_numeric(sv_prim.get(f"{ep}.time"), errors="coerce")
            endpoints[ep] = {"n_with_status": int(e.notna().sum()), "events": int(e.sum()),
                             "event_pct": round(100 * float(e.mean()), 1),
                             "median_time_days": float(t.median()) if t.notna().any() else None}
    prof["datasets"]["survival.tsv"] = {
        "purpose": "Curated outcome endpoints per sample: overall (OS), disease-specific (DSS), disease-free (DFI) and "
                   "progression-free (PFI) status (1 = event) and time in days.",
        "rows": int(len(sv)), "patients": int(sv["_PATIENT"].nunique()) if "_PATIENT" in sv else None,
        "primary_rows": int(len(sv_prim)), "granularity": "sample rows, patient-level values",
        "endpoints_primary": endpoints,
        "redacted_rows": int((sv.get("Redaction") == "Redacted").sum()) if "Redaction" in sv else 0,
        "role": "outcome",
    }
    if files["mutation"]:
        prof["datasets"][FILES["mutation"]] = {"purpose": "Gene-level somatic mutation calls (non-silent).",
                                               **_matrix_profile(rel.mutation, "mutation")}
    if files["copy_number"]:
        cn = pd.read_csv(rel.path("copy_number"), sep="\t", index_col=0)
        prof["datasets"][FILES["copy_number"]] = {"purpose": "GISTIC2 thresholded gene-level copy number.",
                                                  **_matrix_profile(cn, "copy_number")}
    if files["protein"]:
        prof["datasets"][FILES["protein"]] = {"purpose": "Reverse-phase protein array (RPPA) levels, including "
                                              "phospho-proteins.", **_matrix_profile(rel.protein, "protein")}
    if files["rna"]:
        rna = pd.read_csv(rel.path("rna"), sep="\t", index_col=0)
        prof["datasets"][FILES["rna"]] = {"purpose": "Gene expression (RNA-seq, normalized).", **_matrix_profile(rna, "rna")}
    for name, df in (("sample_manifest.csv", rel.sample_manifest), ("slide_manifest.csv", rel.slides)):
        if df is not None:
            prof["datasets"][name] = {
                "purpose": "Organizers' list of samples and which data layers each has (describes release A)."
                if name == "sample_manifest.csv" else "One row per pathology slide: kind, size, scan magnification, licence.",
                "rows": int(len(df)), "columns": {k: str(v) for k, v in df.dtypes.items()},
                "missing_pct": {k: round(100 * float(v), 1) for k, v in df.isna().mean().items() if v > 0},
            }
    # relationships: which primary tumors have which layers, and pairwise overlaps
    m = rel.membership
    prim = m[m.type_code == "01"]
    layers = [k for k in FILES if f"has_{k}" in prim]
    prof["relationships"] = {
        "membership_source": rel.membership_note or "built from this release's files",
        "primary_tumors_with_layer": {k: int(prim[f"has_{k}"].sum()) for k in layers},
        "pairwise_overlap_primary": {f"{a}&{b}": int((prim[f"has_{a}"] & prim[f"has_{b}"]).sum())
                                     for i, a in enumerate(layers) for b in layers[i + 1:]},
        "all_layers_primary": int(prim[[f"has_{k}" for k in layers]].all(axis=1).sum()),
        "patients_with_multiple_primary_samples": int(prim.patient_id.duplicated().sum()),
    }
    return prof


# ------------------------------------------------------------------ capability registry
def _col(prof: dict, name: str) -> dict | None:
    return next((x for x in prof["datasets"]["clinical.tsv"]["column_profiles"] if x["name"] == name), None)


def groupings(prof: dict) -> list[dict]:
    """Categorical variables usable to split tumors into comparable groups (>= 2 groups of >= MIN_GROUP)."""
    out = []
    for x in prof["datasets"]["clinical.tsv"]["column_profiles"]:
        if x["kind"] != "categorical" or x["role"] in ("identifier", "free_text"):
            continue
        groups = {k: v for k, v in x.get("values_primary", {}).items()
                  if v >= MIN_GROUP and k not in x.get("uninformative_values", [])}
        if len(groups) >= 2:
            out.append({"field": f"clinical.{x['name']}", "role": x["role"], "groups": groups})
    return out


KEY_VARS = ["PAM50Call_RNAseq", "breast_carcinoma_estrogen_receptor_status", "breast_carcinoma_progesterone_receptor_status",
            "lab_proc_her2_neu_immunohistochemistry_receptor_status", "histological_type", "pathologic_stage",
            "pathologic_N", "menopause_status", "margin_status", "radiation_therapy"]


def _grouped(series: pd.Series, field: str) -> pd.Series:
    s = series.astype(str)
    if field == "pathologic_stage":
        return s.str.extract(r"Stage (IV|III|II|I)", expand=False)
    if field == "pathologic_N":
        return s.str[:2].where(s.str[:2].isin(["N0", "N1", "N2", "N3"]))
    return series.where(~s.str.match(UNINFORMATIVE) & series.notna())


def associations(rel: Release, prof: dict, top_genes: int = 8) -> list[dict]:
    """Pre-registered, exploratory association tests between key variables (descriptive; Bonferroni-corrected)."""
    c = rel.clinical_primary
    vars_ = {k: _grouped(c[k], k) for k in KEY_VARS if k in c}
    if rel.has_file("mutation"):
        mut = rel.mutation
        mcols = [x for x in mut.columns if is_primary(x)]
        top = (mut[mcols] > 0).mean(1).sort_values(ascending=False).head(top_genes).index
        for g in top:
            vars_[f"{g}_mutated"] = (mut.loc[g, mcols] > 0).map({True: "mutated", False: "wild-type"}).reindex(c.index)
    age = pd.to_numeric(c.get("age_at_initial_pathologic_diagnosis"), errors="coerce")
    tests = []
    names = list(vars_)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            t = pd.crosstab(vars_[a], vars_[b])
            t = t.loc[t.sum(1) >= 10, t.sum(0) >= 10]
            if t.shape[0] < 2 or t.shape[1] < 2:
                continue
            tests.append({"a": a, "b": b, **chi_square(t)})
        g = vars_[a].dropna()
        lv = g.value_counts()
        if age is not None and len(lv) >= 2:
            x, y = lv.index[0], lv.index[1]
            tests.append({"a": a, "b": "age_at_initial_pathologic_diagnosis", "groups": [str(x), str(y)],
                          **mann_whitney(age[g[g == x].index], age[g[g == y].index])})
    k = len(tests) or 1
    for t in tests:
        t["p"] = float(f"{t['p']:.3g}")
        t["bonferroni_p"] = float(f"{min(1.0, t['p'] * k):.3g}")
        t["significant_after_correction"] = bool(t["valid"] and t["bonferroni_p"] < 0.05)
    return tests


def capabilities(prof: dict, rel: Release) -> dict:
    caps = []
    cp = prof["datasets"]["clinical.tsv"]["column_profiles"]
    grp = [g["field"] for g in groupings(prof)]
    sci_groups = [g for g in grp if (_col(prof, g.split(".", 1)[1]) or {}).get("role") in ("predictor", "annotation")]
    for x in cp:
        if x["role"] in ("identifier", "free_text") or x["kind"] in ("constant", "empty", "free_text"):
            continue
        if x["n_informative_primary"] < MIN_N:
            continue
        base = {"field": f"clinical.{x['name']}", "role": x["role"], "n": x["n_informative_primary"],
                "population": "primary tumors with an informative value", "granularity": x["granularity"]}
        lim = [x["role_note"]]
        if x["missing_pct_primary"] > 30:
            lim.append(f"{x['missing_pct_primary']}% of primary tumors have no value: shares depend on the denominator.")
        if x["kind"] == "categorical":
            vals = [k for k, v in x.get("values_primary", {}).items() if k not in x.get("uninformative_values", [])]
            caps.append({**base, "id": f"share:{x['name']}", "analysis": ["count", "percentage", "distribution", "rank"],
                         "values": vals, "alt_denominator": "all primary tumors", "limitations": lim})
            if x["role"] in ("predictor", "annotation") and f"clinical.{x['name']}" in grp:
                caps.append({**base, "id": f"subgroup:{x['name']}", "analysis": ["subgroup filter", "group comparison"],
                             "values": vals, "limitations": lim + ["Comparisons are descriptive; significance needs a "
                                                                   "pre-specified test (see associations)."]})
        elif x["kind"] == "numeric":
            caps.append({**base, "id": f"numeric:{x['name']}", "analysis": ["mean", "median", "range", "quartiles",
                         "share above/below a threshold", "compare by group"], "summary": x.get("summary_primary"),
                         "limitations": lim})
    d = prof["datasets"]
    if FILES["mutation"] in d:
        m = d[FILES["mutation"]]
        caps.append({"id": "mutation:frequency", "field": "mutation.<gene>", "role": "predictor",
                     "n": m["primary_samples"], "population": "primary tumors with mutation calls",
                     "analysis": ["percentage mutated", "count", "rank genes", "within a subgroup", "co-occurrence of two genes"],
                     "genes_available": m["features"], "examples": list(m["top_genes_pct"])[:10],
                     "valid_subgroups": sci_groups,
                     "limitations": ["Gene-level calls only (no variant, position or allele frequency).",
                                     "A gene absent from the file cannot be checked; 0% means no call among sequenced tumors."]})
    if FILES["copy_number"] in d:
        m = d[FILES["copy_number"]]
        caps.append({"id": "copy_number:frequency", "field": "copy_number.<gene>", "role": "predictor",
                     "n": m["primary_samples"], "population": "primary tumors with copy-number calls",
                     "analysis": ["percentage amplified (2)", "percentage deeply deleted (-2)", "gain/loss (+1/-1)",
                                  "within a subgroup", "rank genes"],
                     "examples_amplified": list(m["top_amplified_pct"])[:8], "valid_subgroups": sci_groups,
                     "limitations": ["GISTIC thresholds are estimates; +1/-1 are low-level and noisy.",
                                     "Copy number is not expression: amplification does not prove the gene is overexpressed."]})
    if FILES["protein"] in d:
        m = d[FILES["protein"]]
        caps.append({"id": "protein:levels", "field": "protein.<name>", "role": "predictor", "n": m["primary_samples"],
                     "population": "primary tumors with RPPA data",
                     "analysis": ["mean/median by group", "compare two groups (higher/lower)", "correlate with another protein"],
                     "proteins_available": m["features"], "valid_subgroups": sci_groups,
                     "limitations": ["Relative, normalized levels: 'higher in group A than B' is checkable; absolute "
                                     "amounts are not.", "Only 131 antibodies; many proteins are not measured."]})
    if FILES["rna"] in d:
        m = d[FILES["rna"]]
        caps.append({"id": "rna:expression", "field": "rna.<gene>", "role": "predictor", "n": m["primary_samples"],
                     "population": "primary tumors with RNA-seq",
                     "analysis": ["mean/median by group", "compare two groups", "correlate with protein or copy number"],
                     "genes_available": m["features"], "valid_subgroups": sci_groups,
                     "limitations": ["Not present in envelope releases.", "Relative expression only."]})
    sv = d["survival.tsv"]
    caps.append({"id": "survival:descriptive", "field": "survival.{OS,DSS,DFI,PFI}", "role": "outcome",
                 "n": sv["primary_rows"], "population": "primary tumors with survival rows",
                 "analysis": ["event count and percentage", "median follow-up time", "events by group (descriptive)"],
                 "endpoints": sv["endpoints_primary"],
                 "limitations": ["Follow-up length varies: raw event percentages are not survival probabilities.",
                                 "No hazard ratios, Kaplan-Meier comparisons or significance without a pre-specified "
                                 "analysis; treatment effects cannot be inferred.",
                                 f"{sv['redacted_rows']} rows are marked Redacted."]})
    caps.append({"id": "coverage:layers", "field": "membership", "role": "metadata",
                 "n": prof["datasets"]["clinical.tsv"]["primary_tumors"],
                 "population": "primary tumors", "analysis": ["count with each layer", "overlap of layers", "count with all layers"],
                 "values": prof["relationships"]["primary_tumors_with_layer"], "limitations": [
                     "Release A uses sample_manifest.csv; other releases use their own files."]})
    if "slide_manifest.csv" in d:
        caps.append({"id": "slides:manifest", "field": "slide_manifest.*", "role": "metadata", "n": d["slide_manifest.csv"]["rows"],
                     "population": "slides", "analysis": ["count by kind", "slides per sample/patient", "size", "magnification"],
                     "limitations": ["Slides are images only: no image-derived measurements are in the release."]})
    assoc = associations(rel, prof)
    return {"profile_version": PROFILE_VERSION, "release": prof["release"], "min_n": MIN_N, "min_group": MIN_GROUP,
            "capabilities": caps, "groupings": groupings(prof), "associations": assoc,
            "never_verifiable": [
                "Treatment response or benefit (only whether a treatment was given is recorded)",
                "Causal claims (observational data)", "Tumor grade (not in the release)",
                "Individual-patient predictions, diagnosis or risk scores (out of scope)",
                "Anything about patients outside this release, or other cancers"]}


# ------------------------------------------------------------------ validation (independent of the code above)
def validate(prof: dict, caps: dict, rel: Release) -> list[dict]:
    """Re-derive facts straight from the files with separate code, and check the profile's internal consistency."""
    res = []

    def check(name, ok, detail=""):
        res.append({"check": name, "ok": bool(ok), "detail": detail})

    raw = pd.read_csv(rel.path("clinical"), sep="\t", dtype=str, keep_default_na=False)
    prim = raw[raw.sampleID.str[13:15] == "01"]
    cl = prof["datasets"]["clinical.tsv"]
    check("clinical row count", cl["rows"] == len(raw), f"{cl['rows']} vs {len(raw)}")
    check("primary tumor count", cl["primary_tumors"] == len(prim), f"{cl['primary_tumors']} vs {len(prim)}")
    check("every clinical column profiled", len(cl["column_profiles"]) == raw.shape[1] - 1,
          f"{len(cl['column_profiles'])} of {raw.shape[1] - 1}")
    bad = []
    for x in cl["column_profiles"]:
        col = raw[x["name"]].str.strip()
        miss = col.str.lower().isin(MISSING)
        if abs(round(100 * miss.mean(), 1) - x["missing_pct"]) > 0.11:
            bad.append(f"{x['name']} missing {x['missing_pct']} vs {round(100 * miss.mean(), 1)}")
        if not 0 <= x["missing_pct"] <= 100:
            bad.append(f"{x['name']} missing out of range")
        if x["kind"] == "categorical":
            pv = prim[x["name"]].str.strip()
            vc = pv[~pv.str.lower().isin(MISSING)].value_counts()
            for k, v in list(x.get("values_primary", {}).items())[:5]:
                if int(vc.get(k, -1)) != v:
                    bad.append(f"{x['name']}={k}: {v} vs {vc.get(k)}")
            if sum(x.get("values_primary", {}).values()) > len(prim):
                bad.append(f"{x['name']} counts exceed primary rows")
        if x["role"] == "identifier" and ("values_primary" in x):
            bad.append(f"{x['name']}: identifier values stored")
    check("column missingness and category counts re-derived independently", not bad, "; ".join(bad[:8]))
    names = set(raw.columns)
    unknown = [c["field"] for c in caps["capabilities"] if c["field"].startswith("clinical.")
               and c["field"].split(".", 1)[1] not in names]
    check("every capability points at a real column", not unknown, ", ".join(unknown))
    small = [c["id"] for c in caps["capabilities"] if c.get("n", MIN_N) < MIN_N]
    check(f"every capability has n >= {MIN_N}", not small, ", ".join(small))
    for layer, key in (("mutation", "mutation_gene_level.tsv.gz"), ("copy_number", "copy_number_gistic.tsv.gz"),
                       ("protein", "protein_rppa.tsv.gz")):
        if rel.has_file(layer):
            hdr = pd.read_csv(rel.path(layer), sep="\t", nrows=0).columns[1:]
            n_prim = sum(1 for h in hdr if h[13:15] == "01")
            check(f"{layer}: primary sample count", prof["datasets"][key]["primary_samples"] == n_prim,
                  f"{prof['datasets'][key]['primary_samples']} vs {n_prim}")
    if rel.has_file("mutation"):
        mut = pd.read_csv(rel.path("mutation"), sep="\t", index_col=0)
        pc = [h for h in mut.columns if h[13:15] == "01"]
        for g, pctv in list(prof["datasets"]["mutation_gene_level.tsv.gz"]["top_genes_pct"].items())[:3]:
            v = round(100 * (mut.loc[g, pc] > 0).mean(), 1)
            check(f"mutation frequency {g} re-derived", abs(v - pctv) < 0.05, f"{pctv} vs {v}")
    sv = pd.read_csv(rel.path("survival"), sep="\t")
    sp = sv[sv["sample"].str[13:15] == "01"]
    ev = prof["datasets"]["survival.tsv"]["endpoints_primary"].get("OS", {})
    check("OS events re-derived", ev.get("events") == int(pd.to_numeric(sp.OS, errors="coerce").sum()),
          f"{ev.get('events')} vs {int(pd.to_numeric(sp.OS, errors='coerce').sum())}")
    rel_ = prof["relationships"]
    over = [k for k, v in rel_["pairwise_overlap_primary"].items()
            if v > min(rel_["primary_tumors_with_layer"][a] for a in k.split("&"))]
    check("layer overlaps never exceed either layer", not over, ", ".join(over))
    check("no sample or patient identifiers in the profile",
          not re.search(r"TCGA-(?!XX-XXXX)[A-Z0-9]{2}-[A-Z0-9]{4}", str(prof) + str(caps)))
    inv = [f"{t['a']}~{t['b']}" for t in caps["associations"] if not 0 <= t["p"] <= 1]
    check("association p-values within [0, 1]", not inv, ", ".join(inv))
    # the chi-square implementation against a textbook value: stat 3.841 with df 1 -> p 0.05
    check("chi-square p-value implementation (3.841, df 1 -> 0.050)", abs(_gammq(0.5, 3.841 / 2) - 0.05) < 0.001,
          f"{_gammq(0.5, 3.841 / 2):.4f}")
    return res


def diff_profiles(a: dict, b: dict) -> dict:
    """What changes between two releases' profiles (e.g. release A vs an envelope)."""
    fa, fb = a["files_present"], b["files_present"]
    ca = {x["name"]: x for x in a["datasets"]["clinical.tsv"]["column_profiles"]}
    cb = {x["name"]: x for x in b["datasets"]["clinical.tsv"]["column_profiles"]}
    changed = []
    for k in sorted(set(ca) & set(cb)):
        va, vb = ca[k].get("values_primary"), cb[k].get("values_primary")
        if va and vb and va != vb:
            delta = {v: vb.get(v, 0) - va.get(v, 0) for v in set(va) | set(vb) if vb.get(v, 0) != va.get(v, 0)}
            changed.append({"column": k, "changes": dict(sorted(delta.items(), key=lambda kv: -abs(kv[1]))[:4])})
        elif ca[k].get("missing_pct") != cb[k].get("missing_pct"):
            changed.append({"column": k, "missing_pct": [ca[k]["missing_pct"], cb[k]["missing_pct"]]})
    other = {}
    for f in sorted(set(a["datasets"]) & set(b["datasets"]) - {"clinical.tsv"}):
        da, db = a["datasets"][f], b["datasets"][f]
        for key in ("primary_samples", "endpoints_primary", "top_genes_pct", "top_amplified_pct", "top_deleted_pct",
                    "redacted_rows", "rows", "value_median"):
            if key in da and da.get(key) != db.get(key):
                other.setdefault(f, {})[key] = {"first": da.get(key), "second": db.get(key)}
    return {"other_files_changed": other,
            "files_only_in_first": [f for f in fa if fa[f] and not fb.get(f)],
            "files_only_in_second": [f for f in fb if fb[f] and not fa.get(f)],
            "primary_tumors": [a["datasets"]["clinical.tsv"]["primary_tumors"], b["datasets"]["clinical.tsv"]["primary_tumors"]],
            "columns_with_changed_values": changed}
