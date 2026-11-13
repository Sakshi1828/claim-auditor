# Research Claim Auditor · Team Cache us if u can

**Track:** Evidence Navigator · **Product:** Research Claim Auditor (with Evidence Copilot-style real queries)
**User:** a data-use reviewer handed a report and asked *"can we trust this?"*

Upload a report. The tool splits it into sentences, recognises each factual claim, **runs a real calculation on the frozen
TCGA-BRCA release**, and sorts claims into **supported**, **contradicted** (with the correct value) or **insufficient evidence**
(with the data that would be needed). A person confirms or overrides every verdict; both are kept. The reviewer then records a
decision (Proceed / Fix a problem / Narrow the question / Stop) and exports `audit.json` in the organizers' shared format.

> **Research use only.** No diagnosis, treatment advice or risk scores. Verdicts are about whether a report matches the data,
> not about patients. Every verdict is flagged for human review until a person confirms it.

## Setup (about 5 minutes)
The tool sits **next to** the challenge repo:
```
your-folder/
  oncosys-hackathon-challenge/   ← organizers' repo (data is fetched into it)
  claim-auditor/                 ← this repo
```
```bash
git clone https://github.com/disleveK/oncosys-hackathon-challenge.git
```
```bash
pip install -r claim-auditor/requirements.txt
```
```bash
python oncosys-hackathon-challenge/data/tcga-brca/fetch.py
```
Needs Python 3.10+. Only `pandas`, `jsonschema` and `cryptography`: no Streamlit, no API keys, no internet after fetching.
On Windows use `py` instead of `python` if `python` isn't found.

## Run it
**Review app** (opens http://localhost:8501):
```bash
python claim-auditor/app.py
```
1. *Use the practice report* (or upload / paste a report, or open a sealed envelope).
2. *Check claims*. Click any sentence to see the claim, the numbers, the files and fields, and where the evidence stops.
   Switch *Program lead / Reviewer / Researcher* for less or more detail. The same facts are shown in every view.
3. *Confirm* or *Override…* each verdict (an override needs a reason).
4. Pick a decision, write why, and *Export*. Files go to `claim-auditor/outputs/`.

**Command line** (fast, for the live test):
```bash
python claim-auditor/audit_report.py
```
```bash
python claim-auditor/audit_report.py path/to/report.md
```
```bash
python claim-auditor/audit_report.py --envelope 07 amber falcon river quartz
```
The envelope command unseals, audits `claim_auditor_report.md` against release A and against the envelope's own release,
prints any verdict that changes between the two, and writes `outputs/audit.json`. The whole run takes a few seconds.

Validate the output:
```bash
python oncosys-hackathon-challenge/format/validate.py claim-auditor/outputs/audit.json
```
Regression tests:
```bash
python claim-auditor/tests/run_tests.py
```

## Required outputs
| Output | Where |
|---|---|
| `audit.json` (shared format v0.2, one `claim_check` finding per claim) | `outputs/audit.json` |
| Full audit with tool verdicts, reviewer decisions and calculations | `outputs/audit_full.json` |
| Human-readable decision record | `outputs/decision_summary.md` |

## How a verdict is reached
Each sentence goes through checkers in order. The first that recognises it runs the calculation:

| Checker | Recognises | Data used |
|---|---|---|
| `treatment_response` | response / benefit / "works best" / guide-treatment claims | clinical therapy fields (context only) → **insufficient evidence**: there are no response outcomes |
| `not_a_claim` | recommendations, opinions, background with nothing to measure | not scored |
| `slide_counts` | slide totals, frozen vs diagnostic | `slide_manifest.csv` |
| `survival` | death counts, follow-up; comparisons → insufficient (need time-to-event analysis) | `survival.tsv` |
| `protein_comparison` | "ER-alpha protein is higher in ER-positive tumors" | `protein_rppa.tsv.gz` + clinical status |
| `subtype_share` | PAM50 subtype % / counts / "largest" | `PAM50Call_RNAseq` (or `PAM50_mRNA_nature2012` if the claim says 2012/Nature) |
| `receptor_share` | ER / PR / HER2 positive or negative, triple-negative | clinical receptor status columns |
| `mutation_frequency` | "TP53 is mutated in X%", "most frequently mutated" | `mutation_gene_level.tsv.gz` |
| `age` | median / mean age, share over/under an age | `age_at_initial_pathologic_diagnosis` |
| `cohort_coverage` | counts of tumors / samples / patients and which data layers they have | barcodes present in each release file |
| `unrecognised` | anything else with a number | **insufficient evidence, flagged for manual check** |

**Tolerance:** counts must match exactly. Percentages must match within ±0.5 points (±0.15 if the claim gives a decimal),
or within ±1.5 points or 5% if the claim says *about / approximately / roughly*. Results close to the line are marked
*borderline* for the reviewer. Every claim card also shows **the same question under other reasonable definitions**
(other subtype column, other denominator), so a reviewer can see when a conclusion depends on a choice.

## Known limitations
- Claim recognition is rule-based (deterministic and reproducible, with no LLM and no key). Unusual phrasing falls through to
  *unrecognised*, which is reported honestly as needing manual review rather than guessed.
- It checks a report against **one release at a time** (release A by default). For envelopes it also checks the envelope
  release and shows the differences.
- For release A, which samples exist and which data layers they have comes from `sample_manifest.csv`, the organizers'
  official list. The tool cross-checks it against the files and reports any disagreement. For any other release (for example an
  envelope), the manifest doesn't apply, so membership is read from that release's own files. Missing values inside a file are not counted.
- Survival rows marked `Redaction = Redacted` (5 primary tumors in release A) are kept, as the organizers advise, and flagged
  on every survival-related claim for a person to review.
- Survival comparisons and treatment effects are never judged as supported: that needs a pre-specified statistical analysis.

## Data and credit
TCGA-BRCA via the UCSC Xena TCGA hub and NCI Imaging Data Commons (see the challenge repo's `DATA_LICENSES.md`).
Raw data is fetched by the organizers' `fetch.py` and is **not** committed here. De-identified, patient-derived, research use only.

**Windows note:** `envelopes/unseal.py` fails its fingerprint check on Windows because pandas writes `\r\n` line endings.
Our tool runs it unchanged with `os.linesep = "\n"` (see `auditor/envelope.py`).
