"""Load one TCGA-BRCA release folder and answer simple, traceable questions about it.

Everything here reads the frozen files directly. Nothing comes from memory or an LLM.
"""
from __future__ import annotations

import hashlib
import pathlib
from functools import cached_property

import pandas as pd

FILES = {
    "clinical": "clinical.tsv",
    "survival": "survival.tsv",
    "mutation": "mutation_gene_level.tsv.gz",
    "copy_number": "copy_number_gistic.tsv.gz",
    "rna": "rna_hiseq.tsv.gz",
    "protein": "protein_rppa.tsv.gz",
}

LAYER_LABELS = {
    "clinical": "clinical",
    "survival": "survival",
    "mutation": "mutation",
    "copy_number": "copy number",
    "rna": "RNA",
    "protein": "protein",
}


def is_primary(sample_id: str) -> bool:
    return str(sample_id)[13:15] == "01"


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Release:
    """A folder holding the release files, plus the challenge repo's slide manifest."""

    def __init__(self, release_dir: str | pathlib.Path, slide_manifest: str | pathlib.Path | None = None,
                 name: str | None = None):
        self.dir = pathlib.Path(release_dir).resolve()
        if not (self.dir / FILES["clinical"]).exists():
            raise FileNotFoundError(f"No clinical.tsv in {self.dir}. Run fetch.py first, or point at a release folder.")
        # release A lives in raw/; an envelope's in opened/<name>/release/; a generated one in releases/<name>/
        self.name = name or ("A" if self.dir.name == "raw" else
                             self.dir.parent.name if self.dir.name == "release" else self.dir.name)
        self.is_release_a = self.dir.name == "raw"
        # A release folder that ships its own manifests (e.g. an envelope) uses them; otherwise the challenge repo's.
        own_sl, own_sm = self.dir / "slide_manifest.csv", self.dir / "sample_manifest.csv"
        self.slide_manifest_path = own_sl if own_sl.exists() else (pathlib.Path(slide_manifest) if slide_manifest else None)
        # Organizers: sample_manifest.csv is the official list of samples and which data each has (for release A).
        sm = self.slide_manifest_path.parent / "sample_manifest.csv" if self.slide_manifest_path else None
        if own_sm.exists():
            self.sample_manifest_path, self.own_sample_manifest = own_sm, True
        else:
            self.sample_manifest_path, self.own_sample_manifest = (sm if sm and sm.exists() else None), False
        self.membership_note = ""

    # ---------- files ----------
    def path(self, layer: str) -> pathlib.Path:
        return self.dir / FILES[layer]

    def has_file(self, layer: str) -> bool:
        return self.path(layer).exists()

    @cached_property
    def checksums(self) -> list[dict]:
        return [{"file": FILES[k], "sha256": sha256(self.path(k))} for k in FILES if self.has_file(k)]

    # ---------- tables (loaded lazily, cached) ----------
    @cached_property
    def clinical(self) -> pd.DataFrame:
        return pd.read_csv(self.path("clinical"), sep="\t", low_memory=False)

    @cached_property
    def clinical_primary(self) -> pd.DataFrame:
        c = self.clinical
        return c[c.sampleID.map(is_primary)].set_index("sampleID", drop=False)

    @cached_property
    def survival(self) -> pd.DataFrame:
        return pd.read_csv(self.path("survival"), sep="\t")

    @cached_property
    def mutation(self) -> pd.DataFrame:
        return pd.read_csv(self.path("mutation"), sep="\t", index_col=0)

    @cached_property
    def protein(self) -> pd.DataFrame:
        return pd.read_csv(self.path("protein"), sep="\t", index_col=0)

    @cached_property
    def slides(self) -> pd.DataFrame | None:
        if self.slide_manifest_path and self.slide_manifest_path.exists():
            return pd.read_csv(self.slide_manifest_path)
        return None

    def _columns_of(self, layer: str) -> set[str]:
        """Sample ids present in a matrix file (reads only the header)."""
        if not self.has_file(layer):
            return set()
        if layer == "survival":
            return set(self.survival["sample"])
        if layer == "clinical":
            return set(self.clinical["sampleID"])
        header = pd.read_csv(self.path(layer), sep="\t", nrows=0)
        return set(header.columns[1:])

    @cached_property
    def file_membership(self) -> pd.DataFrame:
        """One row per sample: which release files its barcode appears in."""
        layers = {k: self._columns_of(k) for k in FILES}
        ids = sorted(set().union(*layers.values()))
        df = pd.DataFrame({"sample_id": ids})
        df["patient_id"] = df.sample_id.str[:12]
        df["type_code"] = df.sample_id.str[13:15]
        for k, s in layers.items():
            df[f"has_{k}"] = df.sample_id.isin(s)
        return df

    @cached_property
    def membership(self) -> pd.DataFrame:
        """Official sample list. Release A: sample_manifest.csv (organizers' rule). Other releases: built from their files,
        because the manifest describes release A only."""
        files = self.file_membership
        if self.sample_manifest_path and (self.is_release_a or self.own_sample_manifest):
            sm = self.sample_manifest
            df = pd.DataFrame({"sample_id": sm.sample_id, "patient_id": sm.patient_id, "type_code": sm.sample_id.str[13:15],
                               "has_clinical": sm.in_clinical.astype(bool)})
            for k in ("survival", "mutation", "copy_number", "rna", "protein"):
                df[f"has_{k}"] = sm[f"has_{k}"].astype(bool)
            # cross-check against the files so a reviewer sees any disagreement
            merged = df.merge(files, on="sample_id", how="outer", suffixes=("", "_file"), indicator=True)
            diffs = [k for k in FILES if (merged[f"has_{k}"].fillna(False) != merged[f"has_{k}_file"].fillna(False)).any()]
            only_files = int((merged._merge == "right_only").sum())
            self.membership_note = ("Sample list and data layers from sample_manifest.csv (the organizers' official list). "
                                    + ("It agrees with the release files." if not diffs and not only_files else
                                       f"It disagrees with the release files on: {', '.join(diffs) or 'none'}; "
                                       f"{only_files} barcode(s) appear only in the files."))
        else:
            df = files.copy()
            self.membership_note = ("Sample list built from this release's own files (sample_manifest.csv describes "
                                    "release A, not this release).")
        if self.slides is not None:
            counts = self.slides.groupby("sample_id").size()
            dx = self.slides[self.slides.slide_kind.str.startswith("diagnostic")].groupby("sample_id").size()
            df["n_slides"] = df.sample_id.map(counts).fillna(0).astype(int)
            df["n_diagnostic_slides"] = df.sample_id.map(dx).fillna(0).astype(int)
            df["n_frozen_slides"] = df.n_slides - df.n_diagnostic_slides
        return df

    @cached_property
    def sample_manifest(self) -> pd.DataFrame | None:
        if self.sample_manifest_path and self.sample_manifest_path.exists():
            return pd.read_csv(self.sample_manifest_path)
        return None

    @cached_property
    def manifest_note(self) -> str:
        """Do the two manifests agree with each other? Reported on every slide claim so a reviewer sees any gap."""
        sl, sm = self.slides, self.sample_manifest
        if sl is None or sm is None:
            return ""
        outside = sl[~sl.sample_id.isin(sm.sample_id)]
        parts = []
        if len(outside):
            kinds = outside.sample_id.str[13:15].map({"01": "primary", "11": "normal", "06": "metastatic"}).fillna("other")
            parts.append(f"slide_manifest.csv has {len(outside):,} slide(s) from {outside.sample_id.nunique():,} sample(s) "
                         f"that are not in sample_manifest.csv ({', '.join(f'{v} {k}' for k, v in kinds.value_counts().items())} "
                         f"by barcode), so sample_manifest's slides_for_sample adds up to {int(sm.slides_for_sample.sum()):,}, "
                         f"not {len(sl):,}")
        per = sl.groupby("sample_id").size()
        mism = sm[sm.slides_for_sample != sm.sample_id.map(per).fillna(0).astype(int)]
        if len(mism):
            parts.append(f"{len(mism):,} sample(s) have a slides_for_sample count that differs from the slide manifest")
        return ("Manifest cross-check: " + "; ".join(parts) + ".") if parts else "The two manifests agree with each other."


    @cached_property
    def primary_ids(self) -> list[str]:
        m = self.membership
        return m[(m.type_code == "01") & m.has_clinical].sample_id.tolist()
