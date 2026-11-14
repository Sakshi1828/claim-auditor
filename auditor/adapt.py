"""Release adaptation: make every release (release A, an envelope, a generated one) speak the reference schema, or say
exactly where it can't.

    from auditor.adapt import activate
    ctx = activate(release)          # profile, map and validate; the release's tables are translated in place
    ctx.report()                     # renamed / missing / added variables, type and value changes, files, coverage

How a renamed or recoded column is recognised (code, never a guess by a model):
- same name -> same variable;
- otherwise a candidate must match on EVIDENCE: categorical columns by value overlap (after normalising case and
  common synonyms such as POS/Positive), numeric columns by distribution (median and range) and missingness; the
  column name is only a tie-breaker. A mapping is accepted only when one candidate clearly wins.
- values are mapped label by label; anything that doesn't map is reported, never forced.
Every cache that holds data or results is keyed by the release's file FINGERPRINT (names, sizes, contents' timestamps),
so results from one release are never reused for another, even in the same folder.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import pathlib
import re

import pandas as pd

from .release import FILES, Release, is_primary

ROOT = pathlib.Path(__file__).resolve().parents[1]
REFERENCE_PROFILE = ROOT / "catalog" / "A.profile.json"
MISSING_TOKENS = {"", "nan", "none", "na", "n/a", "[discrepancy]", "[not available]", "[unknown]", "[not evaluated]",
                  "[not applicable]"}
SYNONYMS = {"pos": "positive", "+": "positive", "neg": "negative", "-": "negative", "y": "yes", "n": "no", "true": "yes",
            "false": "no", "f": "female", "m": "male", "luminala": "luma", "luminalb": "lumb", "basallike": "basal",
            "her2enriched": "her2", "normallike": "normal", "alive": "living", "dead": "deceased"}
SURVIVAL_REF = ["OS", "OS.time", "DSS", "DSS.time", "DFI", "DFI.time", "PFI", "PFI.time", "Redaction", "_PATIENT"]


def norm(v) -> str:
    raw = str(v).strip().lower()
    if raw in ("+", "-"):
        return SYNONYMS[raw]
    k = re.sub(r"[^a-z0-9]+", "", raw)            # "Basal-like" -> "basallike" -> synonym "basal"
    return SYNONYMS.get(k, k)


def fingerprint(directory: str | pathlib.Path) -> str:
    """Identity of a release's contents: file names, sizes and modification times (cheap, changes on any rewrite)."""
    d = pathlib.Path(directory)
    parts = [f"{p.name}:{p.stat().st_size}:{p.stat().st_mtime_ns}" for p in sorted(d.glob("*")) if p.is_file()]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def _num(s: pd.Series) -> pd.Series:
    """Numbers in text: '58', '58.0', '58 years', '~58' -> 58.0 (anything else NaN)."""
    return pd.to_numeric(s.astype(str).str.extract(r"(-?\d+(?:\.\d+)?)", expand=False), errors="coerce")


def _present(s: pd.Series) -> pd.Series:
    return s[~s.astype(str).str.strip().str.lower().isin(MISSING_TOKENS)]


# ------------------------------------------------------------------ the reference schema (release A)
def reference() -> dict:
    """{column: {kind, values, median, min, max, missing_pct}} from the committed release-A profile."""
    if not REFERENCE_PROFILE.exists():
        return {}
    prof = json.loads(REFERENCE_PROFILE.read_text(encoding="utf-8"))
    out = {}
    for c in prof["datasets"]["clinical.tsv"]["column_profiles"]:
        out[c["name"]] = {"kind": c["kind"], "role": c["role"], "values": list(c.get("values_primary", {})),
                          "summary": c.get("summary_primary"), "missing_pct": c["missing_pct_primary"]}
    return out


# ------------------------------------------------------------------ matching
def value_map(ref_values: list[str], act_values) -> tuple[dict, list]:
    """Map each active label to a reference label (exact, then normalised/synonym). Returns ({act: ref}, unmapped)."""
    by_norm = {}
    for r in ref_values:
        by_norm.setdefault(norm(r), r)
    m, unmapped = {}, []
    for a in act_values:
        if a in ref_values:
            continue
        hit = by_norm.get(norm(a))
        if hit is not None:
            m[a] = hit
        else:
            unmapped.append(a)
    return m, unmapped


def _cat_score(ref: dict, act: pd.Series) -> float:
    vals = _present(act).astype(str)
    if vals.empty or not ref["values"]:
        return 0.0
    rn = {norm(v) for v in ref["values"]}
    an = {norm(v) for v in vals.unique()}
    if len(an) > 3 * max(len(rn), 1) + 5:
        return 0.0
    return len(rn & an) / len(rn | an)


def _num_score(ref: dict, act: pd.Series) -> float:
    s = ref.get("summary")
    x = _num(_present(act)).dropna()
    if not s or len(x) < 10:
        return 0.0
    span = max(s["max"] - s["min"], 1e-9)
    d_med = abs(x.median() - s["median"]) / span
    d_rng = (abs(x.min() - s["min"]) + abs(x.max() - s["max"])) / (2 * span)
    return max(0.0, 1 - 4 * d_med - d_rng)


def _name_score(a: str, b: str) -> float:
    na, nb = re.sub(r"[^a-z0-9]+", " ", a.lower()), re.sub(r"[^a-z0-9]+", " ", b.lower())
    return difflib.SequenceMatcher(None, na, nb).ratio()


def map_columns(ref: dict, act: pd.DataFrame) -> dict:
    """Same-name, renamed (evidence-matched), missing and added columns, type changes and value maps."""
    act_cols = [c for c in act.columns if c != "sampleID"]
    same = [c for c in act_cols if c in ref]
    new = [c for c in act_cols if c not in ref]
    gone = [c for c in ref if c not in act.columns]
    renamed, ambiguous = {}, {}
    taken = set()
    analysable = [c for c in gone if ref[c]["role"] not in ("identifier", "free_text") and ref[c]["kind"] in ("categorical", "numeric")]
    for rc in analysable:
        scored = []
        for ac in new:
            if ac in taken:
                continue
            ev = _cat_score(ref[rc], act[ac]) if ref[rc]["kind"] == "categorical" else _num_score(ref[rc], act[ac])
            if ev < 0.6:
                continue
            scored.append((ev + 0.15 * _name_score(rc, ac), ev, ac))
        scored.sort(reverse=True)
        if not scored:
            continue
        if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.1:
            ambiguous[rc] = [s[2] for s in scored[:3]]
            continue
        renamed[rc] = {"to": scored[0][2], "evidence": round(scored[0][1], 2),
                       "how": "value overlap" if ref[rc]["kind"] == "categorical" else "distribution"}
        taken.add(scored[0][2])
    missing = [c for c in gone if c not in renamed]
    added = [c for c in new if c not in taken]
    # types and values for every reference column we can now see
    types, values, unmapped_values = {}, {}, {}
    for rc in same + list(renamed):
        ac = renamed[rc]["to"] if rc in renamed else rc
        col = _present(act[ac])
        if col.empty:
            continue
        if ref[rc]["kind"] == "numeric":
            direct = pd.to_numeric(col, errors="coerce").notna().mean()
            if direct < 0.95:
                parsed = _num(col).notna().mean()
                types[rc] = {"was": "numeric", "now": "text", "coercible": bool(parsed >= 0.95),
                             "parsed_share": round(float(parsed), 3)}
        elif ref[rc]["kind"] == "categorical" and ref[rc]["values"] and len(ref[rc]["values"]) < 25:
            present = set(col.astype(str).unique())
            vm, um = value_map(ref[rc]["values"], present)
            vm = {a: r for a, r in vm.items() if r not in present}   # both spellings in the data = a quirk, not a recode
            um = [u for u in um if norm(u) not in {norm(r) for r in ref[rc]["values"]}]
            if len(um) > 0.5 * max(len(present), 1):
                um = []                                               # mostly new labels: reported as a changed column
                values.pop(rc, None)
            if vm:
                values[rc] = vm
            if um and len(um) <= 20:
                unmapped_values[rc] = sorted(map(str, um))[:10]
    return {"same": same, "renamed": renamed, "ambiguous": ambiguous, "missing": missing, "added": added,
            "type_changes": types, "value_maps": values, "unmapped_values": unmapped_values}


def map_survival(act: pd.DataFrame) -> dict:
    """Survival columns: OS / OS.time ... by name (case, separators), else missing."""
    cols = {re.sub(r"[^a-z0-9]+", "", c.lower()): c for c in act.columns}
    out, missing = {}, []
    for rc in SURVIVAL_REF:
        if rc in act.columns:
            continue
        key = re.sub(r"[^a-z0-9]+", "", rc.lower())
        alias = {"os": ["overallsurvival", "osstatus", "osevent"], "ostime": ["overallsurvivaltime", "osdays", "osmonths"]}
        hit = cols.get(key) or next((cols[a] for a in alias.get(key, []) if a in cols), None)
        if hit:
            out[rc] = hit
        else:
            missing.append(rc)
    return {"renamed": out, "missing": [m for m in missing if m not in ("Redaction",)]}


# ------------------------------------------------------------------ applying the mapping
def translate_clinical(df: pd.DataFrame, plan: dict, as_text: bool = False) -> pd.DataFrame:
    """Rename mapped columns back to reference names, recode mapped values, and coerce '58 years' -> 58."""
    if not plan:
        return df
    df = df.rename(columns={v["to"]: k for k, v in plan["renamed"].items()})
    for col, vm in plan["value_maps"].items():
        if col in df:
            df[col] = df[col].map(lambda v: vm.get(v, v) if isinstance(v, str) else v)
    for col, t in plan["type_changes"].items():
        if col in df and t["coercible"]:
            x = _num(df[col].where(~df[col].astype(str).str.strip().str.lower().isin(MISSING_TOKENS)))
            df[col] = x.map(lambda v: "" if pd.isna(v) else f"{v:g}") if as_text else x
    return df


class ReleaseContext:
    def __init__(self, rel: Release, fp: str, plan: dict, surv: dict, files: dict, coverage: dict):
        self.rel, self.fingerprint, self.plan, self.survival_plan = rel, fp, plan, surv
        self.files, self.coverage = files, coverage

    @property
    def changed(self) -> bool:
        p = self.plan
        return bool(p["renamed"] or p["missing"] or p["added"] or p["type_changes"] or p["value_maps"]
                    or self.files["missing"] or self.files["extra"] or self.survival_plan["renamed"])

    def report(self) -> dict:
        p = self.plan
        return {"release": self.rel.name, "fingerprint": self.fingerprint,
                "files_missing": self.files["missing"], "files_extra": self.files["extra"],
                "renamed_fields": {k: v["to"] for k, v in p["renamed"].items()},
                "rename_evidence": p["renamed"], "ambiguous_fields": p["ambiguous"],
                "missing_fields": [c for c in p["missing"] if c in _ANALYSABLE_REF()],
                "added_fields": p["added"], "type_changes": p["type_changes"],
                "recoded_values": p["value_maps"], "unmapped_values": p["unmapped_values"],
                "survival_renamed": self.survival_plan["renamed"], "survival_missing": self.survival_plan["missing"],
                "coverage_primary": self.coverage}

    def missing_note(self) -> str:
        r = self.report()
        bits = []
        if r["files_missing"]:
            bits.append("no " + ", ".join(r["files_missing"]))
        if r["missing_fields"]:
            bits.append("no field " + ", ".join(r["missing_fields"][:8]) + ("…" if len(r["missing_fields"]) > 8 else ""))
        return ("This release has " + "; ".join(bits) + ". Claims that need them can't be checked here.") if bits else ""


_REF = {}


def _ANALYSABLE_REF():
    if "a" not in _REF:
        _REF["a"] = {k for k, v in reference().items() if v["role"] not in ("identifier", "free_text", "metadata")}
    return _REF["a"]


_CONTEXTS: dict[tuple, ReleaseContext] = {}


def activate(rel: Release) -> ReleaseContext:
    """Profile and map the release (once per fingerprint) and attach the translation to it."""
    fp = fingerprint(rel.dir)
    key = (str(rel.dir), fp)
    if key not in _CONTEXTS:
        ref = reference()
        raw = pd.read_csv(rel.path("clinical"), sep="\t", dtype=str, keep_default_na=False)
        plan = map_columns(ref, raw) if ref else {"same": list(raw.columns), "renamed": {}, "ambiguous": {}, "missing": [],
                                                  "added": [], "type_changes": {}, "value_maps": {}, "unmapped_values": {}}
        sv = pd.read_csv(rel.path("survival"), sep="\t", nrows=5) if rel.has_file("survival") else pd.DataFrame()
        surv = map_survival(sv) if len(sv.columns) else {"renamed": {}, "missing": SURVIVAL_REF}
        known = set(FILES.values())
        present = {p.name for p in pathlib.Path(rel.dir).iterdir() if p.is_file()}
        expected_extras = {"README.txt", "sample_manifest.csv", "slide_manifest.csv", "CHANGES.json"}
        files = {"missing": sorted(f for f in known if f not in present),
                 "extra": sorted(present - known - expected_extras)}
        cov = {}
        for k in FILES:
            if rel.has_file(k):
                cols = rel._columns_of(k)
                cov[k] = sum(1 for s in cols if is_primary(s))
        _CONTEXTS[key] = ReleaseContext(rel, fp, plan, surv, files, cov)
    ctx = _CONTEXTS[key]
    if getattr(rel, "adaptation", None) is not ctx:
        rel.adaptation = ctx        # Release reads its tables through this translation from now on
        for attr in ("clinical", "clinical_primary", "survival", "membership", "file_membership", "primary_ids"):
            rel.__dict__.pop(attr, None)        # drop anything read before the translation was attached
    return ctx


def compare_items(a: list[dict], b: list[dict]) -> list[dict]:
    """Claim-by-claim differences between two audits of the same report on two releases."""
    out = []
    for x, y in zip(a, b):
        if x["tool_verdict"] != y["tool_verdict"] or [s["observed"] for s in x["result"]["subchecks"]] != \
                [s["observed"] for s in y["result"]["subchecks"]]:
            out.append({"id": x["id"], "claim": x["claim_text"], "first": x["tool_verdict"], "second": y["tool_verdict"],
                        "first_value": "; ".join(s["observed"] for s in x["result"]["subchecks"])[:160],
                        "second_value": "; ".join(s["observed"] for s in y["result"]["subchecks"])[:160]})
    return out
