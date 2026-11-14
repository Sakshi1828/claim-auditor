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
Needs **Python 3.10 or newer** and git. Only `pandas`, `jsonschema` and `cryptography`: no Streamlit, no API keys,
no internet after fetching. Every command below runs from **one folder that holds both repos**:
```
your-folder/
  oncosys-hackathon-challenge/   ← organizers' repo (data is fetched into it)
  claim-auditor/                 ← this repo
```

**1. Check your Python.** Mac/Linux: `python3 --version`. Windows: `py --version`.
If it says 3.9 or older (the built-in Python on many Macs), install Python 3.12 from python.org
(or `brew install python@3.12`) and use `python3.12` in step 3.

**2. Get both repos, side by side**
```bash
git clone https://github.com/disleveK/oncosys-hackathon-challenge.git
```
```bash
git clone https://github.com/Sakshi1828/claim-auditor.git
```

**3. Make a virtual environment and turn it on**

Mac/Linux:
```bash
python3 -m venv .venv
```
```bash
source .venv/bin/activate
```
Windows (PowerShell or Anaconda Prompt):
```bash
py -m venv .venv
```
```bash
.venv\Scripts\activate
```
After this, `python` and `pip` mean the venv's copies on every system.

**4. Install and fetch the data**
```bash
pip install -r claim-auditor/requirements.txt
```
```bash
python oncosys-hackathon-challenge/data/tcga-brca/fetch.py
```
`fetch.py` checks every file against the organizers' frozen checksums. The RNA file is 64 MB, so on a slow connection
this step can take a couple of minutes.

> **Windows with Smart App Control:** if importing pandas fails with "An Application Control policy has blocked this
> file", install `pip install "pandas==2.3.3"`. Newer pandas wheels are not yet allowed by that policy on some machines.

## Run it
All commands run from the folder that holds both repos, with the venv turned on.

**Review app** (opens http://localhost:8501):
```bash
python claim-auditor/app.py
```
If port 8501 is busy (another app, or a second copy of this one), pick another port:
```bash
python claim-auditor/app.py --port 8502
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

To try it now, use the public practice envelope:
```bash
python claim-auditor/audit_report.py --envelope practice orange meadow pilot lantern
```
**That's expected to stop after unsealing**: the practice envelope holds only a new release, with no report inside, so
there is nothing to audit. It says so, prints the command for auditing a report against that release, and exits with code 0.
Saturday's envelopes contain `claim_auditor_report.md`.

Exit codes: `0` audit written (or practice envelope with no report), `1` unsealing failed (wrong number or words, or
release A not fetched), `2` report not found.

Validate the output:
```bash
python oncosys-hackathon-challenge/format/validate.py claim-auditor/outputs/audit.json
```
Regression tests: 6 reports, 81 sentences (including 20 real-world phrasings and 20 held-out claims written before the tool saw them), plus a random release rebuilt from `tests/random_release.json` with the organizers' `make_release.py` to check that numbers come from the release you point at:
```bash
python claim-auditor/tests/run_tests.py
```

## Required outputs
| Output | Where |
|---|---|
| `audit.json` (shared format v0.2, one `claim_check` finding per claim) | `outputs/audit.json` |
| Full audit with tool verdicts, reviewer decisions and calculations | `outputs/audit_full.json` |
| Human-readable decision record, next steps and what the audit can't tell you | `outputs/decision_summary.md` |
| Suggested corrected report for the author | `outputs/corrected_report.md` |
| **In plain words**: a bottom line, one jargon-free sentence per claim and a short glossary, for readers with no data or biology background | top of the app and of `decision_summary.md`; `plain_summary` in `audit.json` |

## What happens after a verdict
Finding a wrong number is the start. For every claim the tool also says:

| | Contradicted | Insufficient evidence | Supported |
|---|---|---|---|
| **Why it matters** | How far off it is in the data's own units ("12.1 points too high, about 102 of 844 tumors") and what that breaks downstream (group sizes, power, cohort joins) | It will be read as a finding even though this release can't show it | It can stay, but only if the definition is stated |
| **What to do next** | Fix the number (with suggested wording), **or**, if the number matches another reasonable definition (e.g. the 2012 Nature subtype column), ask the author which one they used and name it, without changing the number | Remove or reword it as an open question; or rerun on a release with the missing file; or check by hand if the tool couldn't read it | Keep it and cite the release and definition; decide on rounding if borderline |
| **What the tool can't tell you** | Why the author's number differs | Whether the effect is real | Whether the author's method was right |

The plan for the whole report (in order: fix, ask, remove, check by hand) and the list of **what this audit can't tell you** are
shown in section 3 of the app, printed by the command line, written to `audit.json` (`next_steps`, and `why_it_matters` /
`next_step` / `suggested_text` / `cannot_tell` on each finding) and `decision_summary.md`. A **suggested corrected report**
(`outputs/corrected_report.md`) applies the fixes and marks what must come out. Everything updates when a reviewer overrides a
verdict.

## How a verdict is reached
Each sentence goes through checkers in order. The first that recognises it runs the calculation:

| Checker | Recognises | Data used |
|---|---|---|
| `treatment_response` | response / benefit / "works best" / guide-treatment claims | clinical therapy fields (context only) → **insufficient evidence**: there are no response outcomes |
| `not_a_claim` | recommendations, opinions, background with nothing to measure | not scored |
| `manifest` | slide totals and kinds (diagnostic, frozen, top/bottom/middle section), slide size (median/mean/total, MB/GB/TB), scan magnification (40x/20x), licence, viewer links, slides per patient/sample, the sample manifest's own slide total, and patients/samples **with** or **without** slides ("1,098 of the 1,101 primary tumors") | `slide_manifest.csv` + `sample_manifest.csv`, cross-checked against each other |
| `survival` | death counts, follow-up; comparisons → insufficient (need time-to-event analysis) | `survival.tsv` |
| `protein_comparison` | "ER-alpha protein is higher in ER-positive tumors" | `protein_rppa.tsv.gz` + clinical status |
| `subtype_share` | PAM50 subtype % / counts / "largest" | `PAM50Call_RNAseq` (or `PAM50_mRNA_nature2012` if the claim says 2012/Nature) |
| `receptor_share` | ER / PR / HER2 positive or negative, triple-negative | clinical receptor status columns |
| `mutation_frequency` | "TP53 is mutated in X%", "most frequently mutated" | `mutation_gene_level.tsv.gz` |
| `age` | median / mean age, share over/under an age | `age_at_initial_pathologic_diagnosis` |
| `cohort_coverage` | counts of tumors / samples / patients and which data layers they have, including "N of the M" | `sample_manifest.csv` for release A (or a release's own manifest), else barcodes present in each release file |
| `unrecognised` | anything else with a number | **insufficient evidence, flagged for manual check** |

**Contradicted claims always carry `correct_value`** with the number the data gives (for example `49.9% (421 of 844)`). If a reviewer overrides a verdict to *contradicted*, the app requires them to type the correct value.

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
- **The two manifests don't fully agree:** `slide_manifest.csv` has 50 slides from 24 normal-tissue samples that are not in `sample_manifest.csv`, so `slides_for_sample` adds up to 3,061, not 3,111. Every slide claim shows this note, and a claim that uses one total where the other was meant is caught.
- If a release folder ships its own `sample_manifest.csv` / `slide_manifest.csv` (for example an envelope), those are used.
- Survival rows marked `Redaction = Redacted` (5 primary tumors in release A) are kept, as the organizers advise, and flagged
  on every survival-related claim for a person to review.
- Survival comparisons and treatment effects are never judged as supported: that needs a pre-specified statistical analysis.

## Data and credit
TCGA-BRCA via the UCSC Xena TCGA hub and NCI Imaging Data Commons (see the challenge repo's `DATA_LICENSES.md`).
Raw data is fetched by the organizers' `fetch.py` and is **not** committed here. De-identified, patient-derived, research use only.

## Optional LLM layer (in development, not used by the auditor yet)
`auditor/llm.py` connects Gemini 2.5 Flash (primary) and Groq `openai/gpt-oss-120b` (fallback) behind one interface
that returns schema-validated JSON (`auditor/claim_schema.py`), with timeouts, retries, rate-limit handling, caching
and graceful failure. **Keys are user-supplied**: copy `.env.example` to `.env` (git-ignored) and add your own. Keys
are sent only in request headers and are redacted from every message, cache file and export.
```bash
python tests/test_llm.py           # offline: fakes the APIs, no key needed
python tools/llm_smoke_test.py --both   # live: sends 7 sample claims to each provider
```
Without a key the tool behaves exactly as before.

`auditor/semantic.py` asks the model to *describe* each claim (field, value, population, aggregation, comparison,
verifiability) using the release catalog; code grounds every field it names. `auditor/engine.py` then runs only
**approved operations** (share, count, mean, median, rank, two-group comparison, cohort and slide facts) through a
10-step validated pipeline with a trace, ending in insufficient evidence whenever a step fails. The model never runs
code or decides verdicts. `python tests/test_engine.py` checks every operation against answers computed independently
in `tests/independent_answers.py`.

## Third-party code and licenses
| Package | Used for | License |
|---|---|---|
| [pandas](https://pandas.pydata.org) (with numpy) | Counting and joining the release files | BSD-3-Clause (numpy: BSD-3-Clause) |
| [jsonschema](https://github.com/python-jsonschema/jsonschema) | The organizers' `format/validate.py` | MIT |
| [cryptography](https://cryptography.io) | The organizers' `envelopes/unseal.py` | Apache-2.0 or BSD-3-Clause |
| Organizers' challenge repo (`fetch.py`, `unseal.py`, `make_release.py`, `validate.py`) | Run unchanged, not copied | See the challenge repo |

Everything else (the checkers, the app and the tests) is our own code. No AI model, API key or network service is used:
every verdict is computed locally from the release files.

**Windows note:** `envelopes/unseal.py` fails its fingerprint check on Windows because pandas writes `\r\n` line endings.
Our tool runs it unchanged with `os.linesep = "\n"` (see `auditor/envelope.py`).
