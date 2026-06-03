# HumanEvalFix: Model-Sensitivity and Corpus Ablation

Generated: 2026-06-03. Metric: test-pass rate (pass@1) on 164 HumanEvalFix tasks,
`prompt-mode tests`. Open models served via Together AI.

## 1. Model-sensitivity sweep (retrieval corpus = BugsInPy `repair_clean`)

| Model | baseline | code_only | structured | structured Δ |
| --- | ---: | ---: | ---: | ---: |
| Llama-3-8B (Instruct-Lite) | 37.2% | 11.6% | 8.5% | -28.7 (confounded) |
| Llama-3.3-70B-Turbo | 69.5% | 67.7% | 67.7% | -1.8 |
| gpt-4o-mini | 68.3% | — | 66.5% | -1.8 |
| gpt-4.1 | 79.9% | — | 78.7% | -1.2 |
| gpt-4o | 80.5% | — | 76.8% | -3.7 |

**8B is a confound, not a result.** Baseline 8B emits 0 syntax errors; under any
retrieval prompt the 8B model emits syntactically invalid output on 123-124/164
tasks. The collapse measures the weak model's inability to format output under a
longer prompt, not retrieval quality. The 70B and GPT rows are clean (0 syntax
errors) and are the usable evidence.

## 2. Corpus ablation (HumanEvalFix; BugsInPy vs MBPP corpus)

| Model | Variant | Corpus | Rate | Δ vs baseline |
| --- | --- | --- | ---: | ---: |
| gpt-4o | baseline | — | 80.5% | — |
| gpt-4o | code_only | MBPP | 78.0% | -2.5 |
| gpt-4o | structured | MBPP | 78.0% | -2.5 |
| gpt-4o | structured | BugsInPy | 76.8% | -3.7 |
| Llama-3.3-70B | baseline | — | 69.5% | — |
| Llama-3.3-70B | code_only | BugsInPy | 67.7% | -1.8 |
| Llama-3.3-70B | structured | BugsInPy | 67.7% | -1.8 |
| Llama-3.3-70B | code_only | MBPP | 64.6% | -4.9 |
| Llama-3.3-70B | structured | MBPP | 62.8% | -6.7 |

## 3. Conclusions

1. **Retrieval is net-neutral-to-harmful on HumanEvalFix** for every capable model
   tested (Llama-3.3-70B, gpt-4o-mini, gpt-4.1, gpt-4o), across both corpora and
   both retrieval variants. No configuration beats the no-retrieval baseline.
2. **Corpus domain-match is a small, model-dependent, inconsistent effect.** An
   algorithmic corpus (MBPP) helps gpt-4o slightly over real-world repo bugs
   (BugsInPy) but hurts the 70B model. Corpus mismatch was a minor factor, not the
   explanation for retrieval underperformance.
3. **Structured reranking does not convert to downstream pass-rate on this
   benchmark.** structured ~= code_only in every clean cell.
4. Consistent with prior project results: structured failure-aware retrieval helps
   retrieval *relevance* and controlled QuixBugs repair, but does not help
   function-level HumanEvalFix repair.

## 4. Relation to RAGFix (IEEE BigData 2024)

RAGFix reports that Stack-Overflow RAG *raises* Llama-3-8B (41.4% -> 51.2%) and
Llama-3-70B (72.5% -> 78.0%) on HumanEvalFix. Our results point the other way.
Important caveats before treating this as a direct contradiction:

- **Metric mismatch (unverified).** RAGFix's text describes "detection and
  localization accuracy," which may not be the standard test-pass (pass@1) metric
  used here. Confirm before any head-to-head numeric claim.
- **Method/prompt differ.** RAGFix uses algorithm-summary queries, dynamic Google
  search, and a chain-of-thought repair prompt; ours uses BugsInPy/MBPP dense
  retrieval + structured reranking and a terse code-only prompt.
- **Corpus differs.** RAGFix retrieves Stack Overflow Q&A; we retrieve curated
  buggy->fixed pairs. (Our structured reranking cannot run on SO posts because they
  lack buggy->fixed diffs.)
- **Models differ.** RAGFix uses Llama-3.0; our open-model 70B is Llama-3.3.

Defensible framing: *across a controlled corpus ablation and the full model
capability range, retrieval-augmented repair does not improve HumanEvalFix pass-
rate; reported gains elsewhere are sensitive to method, corpus, prompt, and metric
definition.*

### 4a. Re-evaluation of RAGFix's released outputs (2026-06-03)

We downloaded RAGFix's released per-example CSVs and recomputed pass rate as
"row passes iff `exception_type` is empty" (code executed against the tests). This
method is validated: recomputed baselines match RAGFix's reported figures
(70B 72.6% vs reported 72.5%; 8B 41.5% vs reported 41.4%).

| Model | Run | Pass/164 | Rate | vs baseline |
| --- | --- | ---: | ---: | ---: |
| 70B | baseline (no-db-7-15) | 119 | 72.6% | — |
| 70B | RAG, no postproc (vdb-7-15) | 117 | 71.3% | -1.3 |
| 70B | RAG, +import postproc (vdb-7-16, reported) | 128 | 78.0% | +5.4 |
| 8B | baseline (no-db-7-11) | 68 | 41.5% | — |
| 8B | RAG (vdb-7-12) | 80 | 48.8% | +7.3 |

Findings:
1. **RAGFix's 70B gain is an import-postprocessing artifact.** De-confounded RAG
   (71.3%) is BELOW baseline (72.6%). The reported 78% is driven by import fixing:
   ImportError fails go 13 (baseline) -> 8 (RAG no-postproc) -> 0 (RAG +postproc).
   This agrees with our 70B result (retrieval hurts capable models).
2. **RAGFix's 8B gain is real but inflated.** Full-164 recompute is +7.3pp (48.8%),
   not the reported +9.8pp (51.2%); the report excludes 4 Groq-API-failed examples.
3. **RAG pipeline uses retries** (num_retries up to 2; baselines have 0), an
   additional asymmetry favoring the RAG condition.

Convergent conclusion: retrieval is neutral-to-harmful for capable models on
HumanEvalFix (our data + RAGFix's own de-confounded data agree). For the weakest
model, retrieval can help, but only with output postprocessing (import fixing) and
retries; without that scaffolding our 8B runs collapsed to syntax errors
(123/164). The "RAG helps weak models" claim is real only under heavy output
repair, not from retrieved knowledge alone.

Result CSVs analyzed (from RAGFix GitHub):
RAG Results/LLAMA3/{70B,8B}/{no-db,vdb}*.csv

## 5. Data integrity note (separate issue, found during this work)

All four `data/corpora/*_external_bugfix.jsonl` files (and the derived indexes
`repair_clean`, `mbpp_clean`, `quixbugs_clean`, `humaneval_clean`) are byte-identical
BugsInPy (551 rows). The named "clean" profiles are NOT benchmark-specific corpora.
The genuine MBPP corpus used here was built fresh from `data/mbpp/mbpp_bugfix.jsonl`
(1041 rows, source `mbpp_synthetic`) into profile `mbpp_real`. Any past result that
assumed `mbpp_clean`/`quixbugs_clean`/`humaneval_clean` retrieved benchmark-matched
examples should be re-audited.

### 5a. Audit conclusion (2026-06-03): mislabel is HARMLESS to headline claims

Because the mislabeled profiles are byte-identical duplicates of `repair_clean`
(BugsInPy), any run using any of those names retrieved the SAME BugsInPy corpus,
which is exactly the corpus the paper intends everywhere (QuixBugs, HumanEvalFix,
PyBugHive). The bug mislabels profiles but does not change retrieval results, so all
headline numbers are unaffected. PyBugHive held-out used the genuine distinct corpus
`repair_clean_holdout_pybughive_projects` (277 rows). The mislabel would only matter
for the OLD exploratory MBPP/HumanEval code-generation runs (`mbpp_rag_*`,
`humaneval_rag_*`), which are not paper-headline experiments.

Prior headline numbers re-verified against files this session: QuixBugs gpt-4o
(35/37/37), relevance (quixbugs code_only top5 0.218 / structured 0.394; pybughive
0.123 / 0.258), PyBugHive held-out (23/23/23), variance (baseline 89.5%, structured
91.0%, code_only 90.5%). All match `paper_detailed_results_pack_20260525.md`.

Residual (reproducibility, not correctness): result rows do not store
`retrieval_profile`; record it explicitly for the paper's repro appendix, and
delete/rename the duplicate `*_clean` indexes so no future run trusts the name.

## 6. Result files

- `experiments/humanevalfix_{baseline,code_only,structured}_llama3_8b_v1.json`
- `experiments/humanevalfix_{baseline,code_only,structured}_llama3_70b_v1.json`
- `experiments/humanevalfix_{code_only,structured}_mbpp_{gpt4o,llama70b}_v1.json`

## 7. Positive-regime hunt on MBPP repair (2026-06-03) — NEGATIVE

Goal: find a regime where structured retrieval converts to downstream repair
gains. Design: contamination-controlled held-out MBPP split (187 test problems
disjoint from 187 corpus problems / 508 pairs, profile `mbpp_holdout`), repair
harness `src/eval/evaluate_mbpp_repair.py` with robust code extraction (fixes the
weak-model syntax-collapse confound). Models: gpt-4o-mini, Llama-3-8B.

| Model | baseline | code_only | structured | str-base | str-codeonly |
| --- | ---: | ---: | ---: | ---: | ---: |
| gpt-4o-mini | 93.0% | 92.5% | 91.4% | -1.6 | -1.1 |
| Llama-3-8B | 64.7% | 65.2% | 64.2% | -0.5 | -1.1 |

Output-confound removed: Llama-3-8B syntax errors went 123/164 (HumanEvalFix raw)
-> 2/187 baseline, 0/187 RAG here, confirming `extract_code` works. So the 8B RAG
result is now a clean logic measurement.

Instance-level relevance<->success (structured traces vs baseline outcomes):
- Llama-3-8B: retrieval is ACTIVE (flips 37/187: 18 wins, 19 losses) but
  win-relevance (2.645) ~= loss-relevance (2.621): relevance does NOT predict
  whether a flip helps or hurts. both_fail lowest (2.572).
- gpt-4o-mini: saturated, 4 wins / 7 losses, little action.

Conclusion: the positive regime does NOT exist in executable Python benchmarks for
these models. Even with a genuine knowledge gap (8B 64.7% baseline), matched corpus,
contamination control, and the output confound removed, structured retrieval is
net-neutral and ties/loses to code_only. Mechanism: relevance is not the binding
constraint; at 8B retrieval is active but a coin-flip, limited by the generator's
ability to EXPLOIT an example, not by which example is retrieved. Structured
reranking's proven relevance gains (QuixBugs 0.218->0.394) therefore do not convert
downstream.

Paper implication: the supportable thesis is NOT "our method improves repair." It
is "structured failure-aware reranking improves retrieval relevance, but relevance
does not convert to repair success because it is not the binding constraint" —
demonstrated across models, corpora, and benchmarks, with a de-confounding
re-evaluation of RAGFix's published positive claim.
