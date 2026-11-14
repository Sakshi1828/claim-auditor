"""Analytical execution engine: a structured claim -> validated, approved calculation -> traceable verdict.

    from auditor.engine import execute
    result = execute(spec, release)          # spec = one SemanticClaim (auditor/semantic.py); result = checks.Result

No model-generated code is ever run. A claim is mapped onto a fixed registry of operations (OPERATIONS), each a
small pandas function written here. Every run records a 10-step trace:
  1 variables exist  2 semantic compatibility  3 types and missingness  4 patient/sample level  5 population and
  denominator  6 operation chosen  7 calculation  8 evidence  9 comparison with the claim  10 verdict.
Any step that fails ends in "insufficient evidence" with the reason: the data cannot establish the claim.
"""
from __future__ import annotations

import re

import pandas as pd

from .catalog import MISSING, UNINFORMATIVE
from .checks import (FILES, Number, Result, SubCheck, fmt_pct, is_primary, matches, pct)
from .release import Release

MIN_DENOMINATOR = 10          # never judge a share or a mean on fewer tumors than this
LAYER_FILE = {"clinical": "clinical", "mutation": "mutation", "copy_number": "copy_number", "protein": "protein",
              "rna": "rna", "survival": "survival"}
CN_VALUES = {"amplified": (lambda x: x == 2, "== 2"), "deep_deletion": (lambda x: x == -2, "== -2"),
             "gain": (lambda x: x >= 1, ">= 1"), "loss": (lambda x: x <= -1, "<= -1")}
RECEPTORS = ["breast_carcinoma_estrogen_receptor_status", "breast_carcinoma_progesterone_receptor_status",
             "lab_proc_her2_neu_immunohistochemistry_receptor_status"]
HUMAN_CATEGORIES = {"causal": "a causal claim: observational data can't show cause and effect",
                    "treatment_response": "a treatment response or benefit claim: the release records whether a "
                                          "treatment was given, not whether it worked"}


class Stop(Exception):
    """A validation step failed: the data can't establish this claim (becomes insufficient evidence)."""

    def __init__(self, step: str, reason: str, needed: str = ""):
        super().__init__(reason)
        self.step, self.reason, self.needed = step, reason, needed


def _norm(v) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(v).lower())


# ------------------------------------------------------------------ data access (read-only, cached per release)
class Data:
    def __init__(self, rel: Release):
        self.rel = rel
        self._c = None
        self._cache = {}

    @property
    def clinical(self) -> pd.DataFrame:
        """Primary tumors, every column as the file's text (labels exactly as written)."""
        if self._c is None:
            c = pd.read_csv(self.rel.path("clinical"), sep="\t", dtype=str, keep_default_na=False)
            self._c = c[c.sampleID.map(is_primary)].set_index("sampleID")
        return self._c

    def matrix(self, layer: str) -> pd.DataFrame:
        if layer not in self._cache:
            df = pd.read_csv(self.rel.path(layer), sep="\t", index_col=0)
            self._cache[layer] = df[[x for x in df.columns if is_primary(x)]]
        return self._cache[layer]

    @property
    def survival(self) -> pd.DataFrame:
        if "survival" not in self._cache:
            sv = self.rel.survival
            self._cache["survival"] = sv[sv["sample"].map(is_primary)].set_index("sample")
        return self._cache["survival"]

    @property
    def membership(self) -> pd.DataFrame:
        m = self.rel.membership
        return m[m.type_code == "01"].set_index("sample_id")


_DATA: dict[str, Data] = {}


def data_for(rel: Release) -> Data:
    if str(rel.dir) not in _DATA:
        _DATA[str(rel.dir)] = Data(rel)
    return _DATA[str(rel.dir)]


# ------------------------------------------------------------------ resolving a field reference into a series
def _clean_text(s: pd.Series) -> pd.Series:
    t = s.astype(str).str.strip()
    return s.where(~t.str.lower().isin(MISSING) & ~t.str.match(UNINFORMATIVE) & (t != ""))


def resolve(ref_field: str, d: Data, layers_hint: list[str] | None = None) -> tuple[pd.Series, str, str, str]:
    """field id -> (series over primary tumors (NaN = no value), kind, file, pandas expression). Raises Stop."""
    layer, _, name = (ref_field or "").partition(".")
    rel = d.rel
    if layer == "clinical":
        if name not in d.clinical.columns:
            raise Stop("1 variables", f"there is no clinical field {name!r} in this release")
        s = _clean_text(d.clinical[name])
        num = pd.to_numeric(s, errors="coerce")
        kind = "numeric" if s.notna().sum() and num.notna().sum() >= 0.95 * s.notna().sum() and s.dropna().nunique() > 12 \
            else "categorical"
        return (num if kind == "numeric" else s), kind, FILES["clinical"], f"clinical['{name}']"
    if layer in ("mutation", "copy_number", "protein", "rna"):
        if not rel.has_file(LAYER_FILE[layer]):
            raise Stop("1 variables", f"this release has no {layer.replace('_', ' ')} file",
                       f"A release that includes {FILES[LAYER_FILE[layer]]}.")
        m = d.matrix(layer)
        if name not in m.index:
            raise Stop("1 variables", f"{name!r} is not in {FILES[layer]}")
        s = m.loc[name]
        if isinstance(s, pd.DataFrame):          # duplicated gene symbol: one row only
            s = s.iloc[0]
        s = s.reindex(d.clinical.index)          # tumors without this layer -> NaN (they are not in the denominator)
        kind = {"mutation": "binary01", "copy_number": "cn"}.get(layer, "numeric")
        return s.astype(float), kind, FILES[layer], f"{layer}.loc['{name}']"
    if layer == "survival":
        ep = name.replace(".time", "")
        if ep not in ("OS", "DSS", "DFI", "PFI") or name not in d.survival.columns:
            raise Stop("1 variables", f"unknown survival endpoint {name!r}")
        s = pd.to_numeric(d.survival[name], errors="coerce").reindex(d.clinical.index)
        return s, ("numeric" if name.endswith(".time") else "binary01"), FILES["survival"], f"survival['{name}']"
    if layer == "coverage":
        mem = d.membership.reindex(d.clinical.index)
        lay = [x for x in (layers_hint or []) if x in LAYER_FILE] if name == "all" else [name]
        if name == "all" and not lay:
            lay = [k for k in ("survival", "mutation", "copy_number", "rna", "protein") if rel.has_file(k)]
        missing = [x for x in lay if f"has_{x}" not in mem or not rel.has_file(LAYER_FILE.get(x, x))]
        if missing:
            raise Stop("1 variables", f"this release has no {', '.join(missing)} file",
                       "A release that includes those files.")
        s = mem[[f"has_{x}" for x in lay]].all(axis=1).astype(float)
        return s, "binary01", "sample_manifest.csv", " & ".join(f"membership.has_{x}" for x in lay)
    if layer == "derived" and name == "triple_negative":
        sub = d.clinical[RECEPTORS]
        definite = sub.isin(["Positive", "Negative"]).all(axis=1)
        s = (sub == "Negative").all(axis=1).astype(float).where(definite)
        return s, "binary01", FILES["clinical"], "(clinical[ER, PR, HER2] == 'Negative').all(axis=1)"
    raise Stop("1 variables", f"{ref_field!r} is not a field the engine can read")


def predicate(series: pd.Series, kind: str, value, field: str) -> tuple[pd.Series, str]:
    """Turn a field + value into a True/False/NaN series. Raises Stop when the value doesn't exist."""
    if value is None:
        if kind in ("binary01", "cn"):
            return (series > 0).where(series.notna()) if kind == "binary01" else series.notna().where(series.notna()), "has a value"
        return series.notna().where(series.notna()), "has a value"
    v = str(value).strip()
    if kind == "binary01":
        neg = _norm(v) in ("wildtype", "absent", "no", "notmutated", "0", "negative", "noevent")
        return ((series == 0) if neg else (series > 0)).where(series.notna()), ("== 0" if neg else "> 0")
    if kind == "cn":
        if v not in CN_VALUES:
            raise Stop("2 compatibility", f"copy-number value {v!r} is not one of {sorted(CN_VALUES)}")
        fn, txt = CN_VALUES[v]
        return series.map(lambda x: fn(x) if pd.notna(x) else None).astype("object").where(series.notna()), txt
    if kind == "numeric":
        m = re.match(r"^\s*(>=|<=|>|<|=)?\s*(-?\d+(?:\.\d+)?)\s*(\+)?\s*$", v)
        if not m:
            raise Stop("2 compatibility", f"{field} is numeric; {v!r} is not a threshold")
        op = m.group(1) or (">=" if m.group(3) else "==")
        thr = float(m.group(2))
        f = {">": series.gt, ">=": series.ge, "<": series.lt, "<=": series.le, "==": series.eq, "=": series.eq}[op]
        return f(thr).where(series.notna()), f"{op} {thr:g}"
    # categorical: exact label (case and punctuation insensitive); "Stage II" also covers IIA / IIB
    cats = series.dropna().unique()
    if re.fullmatch(r"(?i)stage\s+(iv|iii|ii|i)", v):
        # "stage III" in a claim means the whole group: III, IIIA, IIIB, IIIC (not only tumors coded plain "Stage III")
        grp = v.split()[-1].upper()
        hit = [c for c in cats if re.fullmatch(rf"(?i)stage\s+{grp}[abc]?", str(c))]
    else:
        hit = [c for c in cats if _norm(c) == _norm(v)]
    if not hit:
        raise Stop("1 variables", f"{field} has no value {v!r} (values: {', '.join(map(str, sorted(cats)[:8]))})")
    return series.isin(hit).where(series.notna()), f"in {hit}"


# ------------------------------------------------------------------ claimed value -> Number (reuse the margin rules)
CMP = {"gt": ">", "ge": ">=", "lt": "<", "le": "<=", "eq": None, "none": None, "range": None}


def claimed_number(cv: dict) -> Number | None:
    if cv["comparator"] == "range" and cv["low"] is not None and cv["high"] is not None:
        lo, hi = sorted([cv["low"], cv["high"]])
        return Number((lo + hi) / 2, cv["unit"] == "percent", cv["approximate"], 0, 0, cv.get("as_written") or f"{lo}-{hi}",
                      lo=lo, hi=hi)
    if cv["number"] is None:
        return None
    written = cv.get("as_written") or ""
    word = bool(re.search(r"(?i)\b(half|third|quarter|fifth|in \d+|one in|two in|most|majority|nearly all)\b", written))
    return Number(float(cv["number"]), cv["unit"] == "percent", cv["approximate"] or word, 0, 0,
                  written or f"{cv['number']:g}{'%' if cv['unit'] == 'percent' else ''}",
                  cmp=CMP.get(cv["comparator"]), word=word)


# ------------------------------------------------------------------ the operation registry
class Ctx:
    """Everything an operation needs, already validated."""

    def __init__(self, spec, d, pop_mask, pop_desc, target, kind, tfile, texpr, pred, pred_txt, files, fields, code):
        self.spec, self.d, self.pop_mask, self.pop_desc = spec, d, pop_mask, pop_desc
        self.target, self.kind, self.tfile, self.texpr, self.pred, self.pred_txt = target, kind, tfile, texpr, pred, pred_txt
        self.files, self.fields, self.code = files, fields, code


def op_share(x: Ctx) -> dict:
    """Share of the population (with a value for the target) where the target condition holds."""
    p = x.pred[x.pop_mask]
    known = p.dropna()
    k, n = int(known.astype(bool).sum()), len(known)
    if n < MIN_DENOMINATOR:
        raise Stop("5 population", f"only {n} tumors have a value for this in the population")
    all_n = int(x.pop_mask.sum())
    return {"value": pct(k, n), "observed": fmt_pct(k, n), "k": k, "n": n, "is_pct": True,
            "ids": sorted(known.index[known.astype(bool)]),
            "alt": [{"definition": f"denominator = all {all_n:,} tumors in the population (including those with no value)",
                     "value": fmt_pct(k, all_n)}] if all_n != n else [],
            "label": f"share where {x.texpr} {x.pred_txt}"}


def op_count(x: Ctx) -> dict:
    p = x.pred[x.pop_mask].dropna()
    k = int(p.astype(bool).sum())
    return {"value": float(k), "observed": f"{k:,}", "k": k, "n": len(p), "is_pct": False,
            "ids": sorted(p.index[p.astype(bool)]), "alt": [], "label": f"tumors where {x.texpr} {x.pred_txt}"}


def _numeric(x: Ctx) -> pd.Series:
    if x.kind not in ("numeric",):
        raise Stop("2 compatibility", f"a mean or median needs a numeric field; {x.texpr} is {x.kind}")
    v = x.target[x.pop_mask].dropna()
    if len(v) < MIN_DENOMINATOR:
        raise Stop("5 population", f"only {len(v)} tumors have a value")
    return v


def op_mean(x: Ctx) -> dict:
    v = _numeric(x)
    return {"value": float(v.mean()), "observed": f"{v.mean():.2f} (n = {len(v):,})", "n": len(v), "is_pct": False,
            "ids": sorted(v.index), "alt": [{"definition": "median instead of mean", "value": f"{v.median():g}"}],
            "label": f"mean of {x.texpr}"}


def op_median(x: Ctx) -> dict:
    v = _numeric(x)
    return {"value": float(v.median()), "observed": f"{v.median():g} (n = {len(v):,})", "n": len(v), "is_pct": False,
            "ids": sorted(v.index), "alt": [{"definition": "mean instead of median", "value": f"{v.mean():.2f}"}],
            "label": f"median of {x.texpr}"}


def op_rank(x: Ctx) -> dict:
    """Where the target value ranks among the field's categories by count (1 = most common)."""
    if x.kind != "categorical" or x.spec["target"]["value"] is None:
        raise Stop("2 compatibility", "a rank needs a categorical field and a category")
    vc = x.target[x.pop_mask].dropna().value_counts()
    hit = [c for c in vc.index if _norm(c) == _norm(x.spec["target"]["value"])]
    if not hit:
        raise Stop("1 variables", f"no category {x.spec['target']['value']!r}")
    rank = list(vc.index).index(hit[0]) + 1
    return {"value": float(rank), "observed": f"rank {rank} ({', '.join(f'{k} {v}' for k, v in vc.head(5).items())})",
            "n": int(vc.sum()), "is_pct": False, "ids": [], "alt": [], "label": f"rank of {hit[0]} in {x.texpr}"}


def _group_mask(ref: dict, d: Data, hint) -> tuple[pd.Series, str]:
    s, kind, _, expr = resolve(ref["field"], d, hint)
    p, txt = predicate(s, kind, ref.get("value"), ref["field"])
    return pd.Series(p.to_numpy(dtype=object) == True, index=p.index), f"{expr} {txt}"  # noqa: E712  NaN -> False


def op_group_difference(x: Ctx) -> dict:
    """Two groups compared on one measure: numeric target -> mean and median; yes/no target -> share. Or two yes/no
    targets (e.g. two genes) compared within the same population."""
    spec, d = x.spec, x.d
    groups = spec["comparison"]["groups"]
    direction = spec["comparison"]["direction"]
    hint = spec["required_evidence"]["layers"]
    # "GATA3 is mutated more often than MAP3K1": the two "groups" are two genes measured in the same tumors
    two_genes = len(groups) == 2 and all((g.get("field") or "").split(".")[0] in ("mutation", "copy_number")
                                         for g in groups)
    if two_genes:
        vals = []
        for g in groups:
            s, kind, _, expr = resolve(g["field"], d, hint)
            p, _ = predicate(s, kind, g.get("value") or spec["target"]["value"], g["field"])
            p = p[x.pop_mask].dropna().astype(bool)
            vals.append((g["field"], p.mean() * 100, len(p)))
        a, b = vals
        diff = a[1] - b[1]
        return {"value": diff, "observed": f"{a[0]} {a[1]:.1f}% vs {b[0]} {b[1]:.1f}% (n = {a[2]:,})", "n": a[2],
                "is_pct": False, "ids": [], "alt": [], "label": f"{a[0]} vs {b[0]}", "direction_ok": _dir_ok(diff, diff, direction)}
    if len(groups) < 2:
        if len(groups) == 1:            # "higher in HER2-positive tumors": the other group is the rest with a value
            m1, t1 = _group_mask(groups[0], d, hint)
            g_field = groups[0]["field"]
            gs, gk, _, gexpr = resolve(g_field, d, hint)
            m2, t2 = (gs.notna() & ~m1), f"{gexpr} not {groups[0].get('value')}"
        else:
            raise Stop("2 compatibility", "a comparison needs two groups, and the claim names fewer")
    else:
        (m1, t1), (m2, t2) = _group_mask(groups[0], d, hint), _group_mask(groups[1], d, hint)
    if x.kind == "numeric":
        a, b = x.target[x.pop_mask & m1].dropna(), x.target[x.pop_mask & m2].dropna()
        if min(len(a), len(b)) < MIN_DENOMINATOR:
            raise Stop("5 population", f"groups too small ({len(a)} and {len(b)})")
        dm, dmed = a.mean() - b.mean(), a.median() - b.median()
        return {"value": dm, "observed": f"mean {a.mean():.2f} vs {b.mean():.2f}; median {a.median():.2f} vs "
                                         f"{b.median():.2f} (n = {len(a):,} vs {len(b):,})",
                "n": len(a) + len(b), "is_pct": False, "ids": sorted(a.index.union(b.index)), "alt": [],
                "label": f"{x.texpr}: [{t1}] vs [{t2}]", "direction_ok": _dir_ok(dm, dmed, direction)}
    p = x.pred
    a, b = p[x.pop_mask & m1].dropna().astype(bool), p[x.pop_mask & m2].dropna().astype(bool)
    if min(len(a), len(b)) < MIN_DENOMINATOR:
        raise Stop("5 population", f"groups too small ({len(a)} and {len(b)})")
    diff = 100 * (a.mean() - b.mean())
    return {"value": diff, "observed": f"{fmt_pct(int(a.sum()), len(a))} vs {fmt_pct(int(b.sum()), len(b))}",
            "n": len(a) + len(b), "is_pct": False, "ids": sorted(a.index.union(b.index)), "alt": [],
            "label": f"share {x.pred_txt}: [{t1}] vs [{t2}]", "direction_ok": _dir_ok(diff, diff, direction)}


def _dir_ok(d_mean: float, d_median: float, direction: str):
    if direction in ("higher", "more_common", "worse_is_higher"):
        return bool(d_mean > 0 and d_median >= 0)
    if direction in ("lower", "less_common"):
        return bool(d_mean < 0 and d_median <= 0)
    if direction == "equal":
        return None
    return None


OPERATIONS = {   # name -> (function, needs a claimed number, description)
    "share": (op_share, True, "percentage of a population meeting a condition"),
    "count": (op_count, True, "number of tumors meeting a condition"),
    "mean": (op_mean, True, "mean of a numeric field"),
    "median": (op_median, True, "median of a numeric field"),
    "rank": (op_rank, False, "rank of a category by frequency"),
    "group_difference": (op_group_difference, False, "two groups compared on a measure (direction only)"),
}
AGG_TO_OP = {"percentage": "share", "count": "count", "total": "count", "mean": "mean", "median": "median",
             "rank": "rank", "group_difference": "group_difference", "existence": "count"}


# ------------------------------------------------------------------ the 10-step pipeline
def execute(spec: dict, rel: Release) -> Result:
    trace = []

    def ok(step, detail):
        trace.append({"step": step, "ok": True, "detail": detail})

    def stopped(e: Stop, fields=(), files=()):
        trace.append({"step": e.step, "ok": False, "detail": e.reason})
        return Result(verdict="insufficient_evidence", check="engine", confidence="medium",
                      summary=f"The data can't establish this claim: {e.reason}.",
                      needed=e.needed or "A reviewer should check the claim by hand, or restate it in terms of fields "
                                         "the release contains.",
                      limitation="Stopped at step " + e.step + ". No calculation was run, so this is not evidence "
                                 "against the claim.", fields=list(fields), files=list(files), trace=trace)

    if not spec["is_factual"]:
        return Result(verdict="not_a_claim", check="engine", summary="Not a factual claim; not scored.",
                      trace=[{"step": "0 claim type", "ok": True, "detail": "not factual"}])
    status = spec["verifiability"]["status"]
    if spec["category"] in HUMAN_CATEGORIES or status in ("needs_human_judgement", "not_in_data"):
        why = HUMAN_CATEGORIES.get(spec["category"]) or spec["verifiability"]["reason"] or status
        return stopped(Stop("2 compatibility", why,
                            "A pre-specified study design and analysis reviewed by a statistician."
                            if status != "not_in_data" else f"Data the release doesn't contain: {why}"))
    d = data_for(rel)
    hint = spec["required_evidence"]["layers"]
    tgt = spec["target"]
    try:
        # 1. variables exist
        if not tgt["field"]:
            raise Stop("1 variables", "the claim's target couldn't be matched to any field in this release")
        if tgt["field"].split(".")[0] in ("cohort", "slides"):
            return _execute_structural(spec, rel, d, trace)
        series, kind, tfile, texpr = resolve(tgt["field"], d, hint)
        files, fields = {tfile}, [tgt["field"]]
        ok("1 variables", f"target {tgt['field']} found in {tfile}")
        # 2. semantic compatibility: the aggregation must fit the field type
        agg = spec["aggregation"]
        op_name = AGG_TO_OP.get(agg)
        if op_name is None:
            raise Stop("2 compatibility", f"no approved operation for aggregation {agg!r}")
        if op_name in ("mean", "median") and kind != "numeric":
            raise Stop("2 compatibility", f"a {op_name} needs a numeric field; {tgt['field']} is {kind}")
        if op_name in ("share", "count") and kind == "numeric" and tgt["value"] is None:
            raise Stop("2 compatibility", f"a share of a numeric field needs a threshold (e.g. '> 65')")
        pred, pred_txt = predicate(series, kind, tgt["value"], tgt["field"])
        ok("2 compatibility", f"{agg} on a {kind} field ({texpr} {pred_txt})")
        # 3. types and missingness
        n_val, n_all = int(series.notna().sum()), len(series)
        ok("3 types & missingness", f"{kind}; {n_val:,} of {n_all:,} primary tumors have a value "
                                    f"({100 * (1 - n_val / n_all):.0f}% missing)")
        # 4. unit of analysis
        pts = pd.Series(series.index.str[:12])
        dup = int(pts.duplicated().sum())
        ok("4 unit", "one primary tumor per patient: patients and primary tumors are the same unit"
           if not dup else f"{dup} patients have more than one primary tumor; counted per tumor")
        # 5. population and denominator
        mask = pd.Series(True, index=series.index)
        pop_txt = ["primary tumors"]
        for f in spec["population"]["filters"]:
            if not f.get("field"):
                continue
            fm, ftxt = _group_mask(f, d, hint)
            mask &= fm
            pop_txt.append(ftxt)
            fields.append(f["field"])
            files.add(FILES.get(f["field"].split(".")[0], "sample_manifest.csv"))
        if int(mask.sum()) < MIN_DENOMINATOR:
            raise Stop("5 population", f"the population ({'; '.join(pop_txt)}) has only {int(mask.sum())} tumors")
        ok("5 population", f"{'; '.join(pop_txt)}: {int(mask.sum()):,} tumors; denominator = those with a value for "
                           f"the target")
        # 6. approved operation
        fn, needs_number, desc = OPERATIONS[op_name]
        claimed = claimed_number(spec["claimed_value"])
        if needs_number and claimed is None:
            raise Stop("6 operation", f"{op_name} needs a number in the claim, and none was stated")
        ok("6 operation", f"{op_name}: {desc}")
        # 7. calculate
        x = Ctx(spec, d, mask, pop_txt, series, kind, tfile, texpr, pred, pred_txt, files, fields, "")
        for g in spec["comparison"]["groups"]:
            if g.get("field"):
                fields.append(g["field"])
                files.add(FILES.get(g["field"].split(".")[0], "sample_manifest.csv"))
        r = fn(x)
        ok("7 calculation", f"{r['label']} = {r['observed']}")
        # 8. evidence
        ok("8 evidence", f"n = {r['n']:,}; files: {', '.join(sorted(files))}")
        # 9. compare
        if op_name == "group_difference":
            good = r.get("direction_ok")
            if good is None:
                raise Stop("9 comparison", f"the claim gives no direction to check ({spec['comparison']['direction']})")
            sub = SubCheck(r["label"], spec["comparison"]["direction"], r["observed"], good,
                           "both mean and median (or the shares) differ in the stated direction")
        elif op_name == "rank":
            want = claimed.value if claimed else 1.0
            good = r["value"] == want
            sub = SubCheck(r["label"], f"rank {want:g}", r["observed"], good, "same rank")
        else:
            good, rule = matches(claimed, r["value"], r["is_pct"])
            sub = SubCheck(r["label"], claimed.text, r["observed"], good, rule)
        ok("9 comparison", f"claim {sub.claimed} vs data {sub.observed}: {'matches' if good else 'does not match'}")
        verdict = "supported" if good else "contradicted"
        ok("10 verdict", verdict)
        code = (f"# primary tumors (barcode chars 14-15 == '01'), {'; '.join(pop_txt[1:]) or 'no filter'}\n"
                f"x = {texpr}  # {pred_txt}\n# operation: {op_name}")
        return Result(verdict=verdict, check=f"engine:{op_name}", confidence="medium",
                      summary=f"{r['label']}: {r['observed']}.", subchecks=[sub],
                      correct_value=None if good else r["observed"] if op_name != "group_difference" else
                      f"{r['observed']}", files=sorted(files), fields=fields, n=r["n"],
                      population="; ".join(pop_txt), alternatives=r["alt"], code=code,
                      sample_ids=r["ids"][:2000], trace=trace,
                      limitation="Computed by the analytical engine from a structured reading of the claim; the "
                                 "reading itself should be checked (see the trace). Descriptive only: no significance "
                                 "testing.")
    except Stop as e:
        return stopped(e, fields=[tgt.get("field") or ""], files=[])


def _execute_structural(spec: dict, rel: Release, d: Data, trace: list) -> Result:
    """Cohort totals and slide-manifest facts (not tumor-level fields)."""
    tgt, cv = spec["target"], spec["claimed_value"]
    layer, _, name = tgt["field"].partition(".")
    claimed = claimed_number(cv)
    m = rel.membership
    if layer == "cohort":
        totals = {"patients": m.patient_id.nunique(), "samples": len(m), "primary_tumors": int((m.type_code == "01").sum()),
                  "normal_samples": int((m.type_code == "11").sum()), "metastatic_samples": int((m.type_code == "06").sum())}
        if name not in totals:
            raise Stop("1 variables", f"unknown cohort total {name!r}")
        value, observed, label, unit_pct = float(totals[name]), f"{totals[name]:,}", f"number of {name.replace('_', ' ')}", False
        files = ["sample_manifest.csv"]
    else:
        sl = rel.slides
        if sl is None:
            raise Stop("1 variables", "no slide manifest for this release")
        files = ["slide_manifest.csv"]
        if name == "count":
            value, observed, label, unit_pct = float(len(sl)), f"{len(sl):,}", "number of slides", False
        elif name == "slide_kind":
            k = str(tgt["value"] or "").lower()
            hit = sl.slide_kind.str.lower().str.startswith(k) if k else pd.Series(True, index=sl.index)
            if k and not hit.any():
                raise Stop("1 variables", f"no slide kind {tgt['value']!r}")
            n = int(hit.sum())
            unit_pct = cv["unit"] == "percent"
            value = pct(n, len(sl)) if unit_pct else float(n)
            observed, label = (fmt_pct(n, len(sl)) if unit_pct else f"{n:,}"), f"{tgt['value']} slides"
        elif name == "objective":
            k = float(re.sub(r"[^\d.]", "", str(tgt["value"] or "")) or 0)
            hit = sl.objective == k
            unit_pct = True
            value, observed, label = pct(int(hit.sum()), len(sl)), fmt_pct(int(hit.sum()), len(sl)), f"slides scanned at {k:g}x"
        elif name == "size_mb":
            if spec["aggregation"] == "total":
                tb = sl.size_mb.sum() / 1e6
                value, observed, label = tb if cv["unit"] == "terabytes" else float(sl.size_mb.sum()), \
                    f"{tb:.2f} TB ({sl.size_mb.sum():,.0f} MB)", "total slide size"
            else:
                value, observed, label = float(sl.size_mb.median()), f"{sl.size_mb.median():g} MB", "median slide size"
            unit_pct = False
        elif name == "per_patient":
            v = len(sl) / sl.patient_id.nunique()
            value, observed, label, unit_pct = v, f"{v:.2f}", "slides per patient", False
        else:
            raise Stop("6 operation", f"no approved operation for slides.{name}")
    ok_ = {"step": "1 variables", "ok": True, "detail": f"{tgt['field']} from {files[0]}"}
    trace.append(ok_)
    if claimed is None:
        raise Stop("6 operation", "the claim states no number to compare")
    good, rule = matches(claimed, value, unit_pct)
    trace += [{"step": "7 calculation", "ok": True, "detail": f"{label} = {observed}"},
              {"step": "9 comparison", "ok": True, "detail": f"claim {claimed.text} vs data {observed}"},
              {"step": "10 verdict", "ok": True, "detail": "supported" if good else "contradicted"}]
    return Result(verdict="supported" if good else "contradicted", check=f"engine:{layer}", confidence="medium",
                  summary=f"{label}: {observed}.", subchecks=[SubCheck(label, claimed.text, observed, good, rule)],
                  correct_value=None if good else observed, files=files, fields=[tgt["field"]],
                  population="slides" if layer == "slides" else "samples in the release", trace=trace,
                  code=f"# {label}\n" + ("slides = slide_manifest" if layer == "slides" else "membership"))


# ------------------------------------------------------------------ working alongside the rule-based checkers
def combine(rule: Result, engine: Result | None) -> Result:
    """Rule verdicts stand when they judged the claim; the engine fills gaps and flags disagreements for a person."""
    if engine is None or engine.verdict == "not_a_claim":
        return rule
    judged = ("supported", "contradicted")
    if rule.verdict in judged:
        if engine.verdict in judged and engine.verdict != rule.verdict:
            rule.confidence = "low"
            rule.limitation = (f"The analytical engine disagrees ({engine.verdict}: {engine.summary}) A person must check "
                               "which reading of the claim is right. " + rule.limitation)
        return rule
    # the rules couldn't judge it: the engine's computed verdict fills the gap, except where the rules deliberately
    # refuse (treatment response, survival comparisons: those need a pre-specified analysis, not a count)
    deliberate = rule.check in ("treatment_response", "survival", "protein_comparison") and rule.verdict == "insufficient_evidence"
    if engine.verdict in judged and rule.verdict in ("insufficient_evidence", "not_a_claim") and not deliberate:
        engine.limitation = ("The rule-based checkers had no check for this wording; computed by the analytical engine. "
                             + engine.limitation)
        return engine
    return rule
