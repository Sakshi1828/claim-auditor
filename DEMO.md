# Demo script: 3 minutes + 2 minutes Q&A

**Team Cache us if u can · Research Claim Auditor**

The judges said every working tool finds the same errors. So spend about 30 seconds on *finding* and the rest on
**what happens after**: why it matters, what to do next, and what the tool can't tell you.

## Before you go on (5 minutes before)
- `python claim-auditor/app.py`. Then type your name and set the role to "Data-use reviewer".
- Have the envelope number and the four words ready, on paper.
- Have a second terminal open in `oncosys-hackathon` for the command-line fallback:
  `python claim-auditor/audit_report.py --envelope <num> <w1> <w2> <w3> <w4>`

## 0:00–0:20 · The user and the problem
> "Our user is a data-use reviewer. Someone hands them a report on TCGA-BRCA and asks: *can we trust this, and what do I do
> about it?* Finding wrong numbers is the easy part. What they need is a decision."

## 0:20–0:50 · Open the envelope live
- Section 1 → *Open a sealed envelope* → number + four words → **Unseal and load**. The tool checks every claim in a few seconds.
- Point at the chips: *N supported, N contradicted, N insufficient.*
> "Every verdict comes from a real calculation on the frozen release, with no AI guessing. Every one waits for a person to confirm it."

## 0:50–1:50 · What happens after: one contradicted claim
Click the red claim.
- **Why it matters:** read the gap aloud: *"12.1 points too high, about 102 of 844 tumors. Subtype shares set group sizes and power."*
- **What to do next:** the suggested wording, and *Ask the author* (which file, column, denominator).
- If a claim says *"ask the author which definition"*, show it. It's the strongest moment:
  > "This number isn't simply wrong. It matches the 2012 Nature subtype column. So the tool doesn't tell you to change it. It tells you to
  > find out which definition the author used, and name it."
- **What the tool can't tell you:** *why* the author's number differs. Only the author knows.
- Switch to **Program lead** view for a second: the same facts, as one decision.

## 1:50–2:20 · The insufficient-evidence claim
> "This one isn't wrong. It can't be answered from this release: there are no treatment-response outcomes. So the next step is to
> remove it or reword it as a question, and here's the data that *would* answer it."

## 2:20–2:50 · Section 3: the decision
- **Do this, in order** (fix → ask → remove → check by hand).
- **What this audit can't tell you**: read two lines: *methods, and anything clinical*.
- Open **Suggested corrected report**: struck-through old sentence, the fixed one in green, unsupported claims flagged.
- Confirm one verdict, override one (show that it **demands a reason**, and a correct value if you choose contradicted), pick the
  decision, **Export** → *validator: valid*.

## 2:50–3:00 · Close
> "It finds what everyone finds. Then it tells the reviewer why it matters, what to do next, and where it stops. And a person
> signs off on every verdict."

## Likely questions (keep answers to about 20 seconds)
| Question | Answer |
|---|---|
| Is it an LLM? | No. Rule-based and deterministic. The same report gives the same audit, and every number has the pandas code behind it (Researcher view). |
| What if it can't read a sentence? | It says *insufficient evidence: check by hand*, low confidence. It never guesses a verdict. Those sentences are listed first under "can't tell you". |
| Release A or the envelope release? | The command line checks both and prints any verdict that changes. The app uses whichever release folder you point it at. |
| Manifests? | Both manifests are checked and cross-checked. They disagree: 50 slides from 24 normal samples are missing from `sample_manifest.csv` (3,061 vs 3,111). The tool flags this on every slide claim. |
| Redacted survival rows? | Kept, as the organizers advised, and flagged on every survival claim. |
| How do you know it's right? | Four regression reports (41 sentences) with hand-checked answers: `python claim-auditor/tests/run_tests.py`. |
| Clinical use? | No. It only checks whether a report matches research data. No diagnosis, treatment or risk statements. |

## If something breaks
- App won't start → use the command line. It prints the same verdicts, next steps and "can't tell you" list, and writes `audit.json`.
- Unseal fails on Windows → the tool already works around the CRLF problem. Check the four words and the number (`07`, not `7`).
