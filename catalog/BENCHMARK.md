# Benchmark: rules-only vs hybrid (Gemini 2.5 Flash reading + analytical engine)

Run with `python tools/benchmark.py` on 14 Nov, release A unless stated. Gold verdicts: tests/run_tests.py (10 reports,
116 sentences, each answered independently in pandas). Semantic labels: tests/semantic_gold.py (114 sentences).

| Metric | Rules only | Hybrid |
|---|---|---|
| Verdict accuracy vs gold labels | 116/116 (100%) | 113/116 (97.4%)* |
| Claim recognition (claim vs not a claim) | 100% | 100% |
| Judged claims answered / correct | 97/97, 97/97 | 97/97, 97/97 |
| False "supported" vs gold labels | 0 of 46 | 3 of 46* |
| Insufficient evidence: precision / recall | 1.00 / 1.00 | 1.00 / 0.81* |
| Decided by | rules 116 | rules 41, rules+engine agree 72, engine fills a gap 3 |
| Disagreements flagged for a person | n/a | 9 (the rules' verdict kept each time; all 9 rules verdicts match gold) |

\* The 3 differences are the routing report's deliberately hard sentences, which the rules refuse on purpose
(RPPA cluster share, "no distant metastasis", 2012 AJCC stage). The hybrid answers them from the exact columns
(`RPPA_Clusters_nature2012` Basal 21.6% (87 of 403), `distant_metastasis_present_ind2` NO 96.9%,
`AJCC_Stage_nature2012` IIA 32.4%), and those claims are true (their values were taken from the data), so these are
correct answers that differ from the conservative label, not false "supported" verdicts.

**False "supported" found and fixed during benchmarking:** on the practice envelope (no RNA file), the hybrid first
marked "535 tumors have survival, mutation, copy number, RNA and protein data" supported: the model read only the
"1,101" in the sentence and the engine's answer replaced the rules' deliberate "can't check: no RNA". Two guards
now prevent this: the engine only fills gaps where the rules have no check at all (a deliberate refusal is never
overridden), and a partial reading (numbers in the sentence the reading doesn't cover) is never used.

## Semantic extraction (Gemini 2.5 Flash, 114 sentences)
89 answered (one batch of 25 failed on the provider side and fell back to rules; the Groq fallback is too small for
these requests on the free tier). On the answered sentences: target field 75/75, number 57/57, aggregation 70/70,
value 15/15, comparator 12/12, filter 5/5, direction 6/6, category 83/84, verifiability 82/84; every field and value it
named exists in the data (89/89 grounded); 86/89 fully correct. An earlier complete run scored 90% fully correct with
all 8 paraphrase groups identical.

## Other
- **Dataset mapping** (25 columns renamed at random, half also recoded): 19 mapped correctly, 0 wrongly, 6 refused as
  ambiguous and reported missing (no silent wrong mapping).
- **Calculation accuracy:** 54/54 engine checks match values computed independently in tests/independent_answers.py.
- **Envelope compatibility:** release A, the practice envelope and the random release all audit and validate in both
  modes, with identical verdicts in both modes.
- **API:** 0 failures in the final run (earlier: Gemini 503s, Groq 413/429 on the free tier, all handled by fallback
  to rules). Latency per report: median 3.8 s cached, 25-60 s uncached; rules-only about 2 s.
