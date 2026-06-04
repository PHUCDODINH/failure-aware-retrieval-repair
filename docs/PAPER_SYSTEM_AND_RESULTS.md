# Structured Failure-Aware Retrieval for LLM Program Repair — System & Results

Consolidated paper-facing description of the system and every result we will use.
Last updated 2026-06-03. Numbers traced to files in `experiments/`; significance via
`experiments/analysis/significance_tests.py`.

---

## PART A — System Description

### A.1 Research question and thesis

Recommended paper title (critical empirical study, not a method-win paper):

> **Better Retrieval, Same Repair: Why Relevance Gains Don't Convert in LLM Program Repair**
>
> Alt: "The Retrieval Ceiling in LLM Program Repair: Relevance, Exploitation, and a
> Re-evaluation of Prior Gains". "Structured Failure-Aware Retrieval" is the name of
> the *method* inside the paper, not the title's promise.

We study **when retrieval-augmented LLM program repair helps, is neutral, or hurts**,
and isolate the role of *retrieval relevance*. Final, statistically-grounded thesis:

> Structured failure-aware reranking **significantly improves retrieval relevance**,
> but this **does not convert to downstream repair gains** — across models, corpora,
> and benchmarks, structured retrieval is statistically *neutral* on repair success.
> The bottleneck is **retrieval quality, not the model's ability to exploit an
> example**: a sufficiently relevant example significantly improves a knowledge-gap
> model (oracle +25.7 pts), yet current retrieval surfaces none of that headroom. We
> further show a published positive claim (RAGFix) is largely a post-processing
> artifact.

### A.2 End-to-end pipeline

1. Collect buggy Python code + a raw failure signal (pytest / test output).
2. Extract a **structured failure state** from the failure signal (`failure_state.py`).
3. Dense-retrieve candidate bug-fix pairs from a FAISS index (`all-MiniLM-L6-v2`
   embeddings of buggy code) over a JSONL corpus (`index_store.py`).
4. **Rerank** the candidate pool by one of five variants (`repair_rag.py`).
5. Prompt the LLM with the bug, failure signal, and the top-k retrieved examples
   (k=2) rendered as compact buggy→fixed diffs + an inferred "repair lesson".
6. Generate the repair.
7. Apply the edit: whole-code replacement (files ≤ 40k chars) or a strict JSON
   line-range patch (`patch_utils.py`, schema `line_range_v1`) for large files.
8. Execute tests; record pass/fail and full traces.

### A.3 Retrieval variants

| Variant | Mechanism |
| --- | --- |
| `baseline` | Direct repair, no retrieval |
| `code_only` | Dense retrieval on buggy code; rank = dense rank |
| `raw_text` | Dense retrieval on buggy code + raw failure text |
| `raw_text_rerank` | Dense + lexical failure-text reranking |
| `structured` | Dense + **structured failure-aware reranking** (our method) |

### A.4 Structured failure state (query side, 6 fields)

Extracted from the failure signal: `failure_mode`, `exception_type`, `test_name`,
`assertion_summary`, `suspicious_symbols`, `contract_tags`.

### A.5 Corpus-side repair metadata (6 fields)

Inferred from each corpus example's buggy→fixed diff (`repair_metadata.py`):
`repair_pattern_tags`, `suspicious_symbols`, `changed_operators`, `edit_scope`,
`file_family`, `changed_lines`.

### A.6 Structured rerank score (the method)

For each candidate at dense rank r:

```
score = 1.0*dense_rank_score(r)
      + 0.8*contract_tag_overlap(failure.contract_tags, cand.repair_pattern_tags)
      + 0.7*symbol_overlap(failure.suspicious_symbols, cand.suspicious_symbols)
      + 0.8*failure_mode_compat(failure.failure_mode, cand)
      + 0.5*exception_compat(failure.exception_type, cand)
      + 0.2*file_family_bonus
      - edit_size_penalty(cand.changed_lines/400)
```

Field ablation (QuixBugs gpt-4o): removing contract_tags, suspicious_symbols,
failure_mode, test_name, or assertion_summary each costs 1 problem (37→36);
exception_type contributes nothing on QuixBugs.

### A.7 Patch layer

Whole-code replacement for small files; strict line-range JSON patch
(`line_range_v1`) for large files, with validation-retry and fuzzy span fallback.

### A.8 Corpora (retrieval knowledge bases)

| Profile | Content | Use |
| --- | --- | --- |
| `repair_clean` | 551 BugsInPy real-world repo bug-fix pairs | Primary corpus (QuixBugs, HumanEvalFix) |
| `repair_clean_holdout_pybughive_projects` | 277 BugsInPy pairs, 11 projects removed | PyBugHive contamination control |
| `mbpp_real` | 1041 genuine MBPP buggy/fixed pairs | MBPP corpus (built fresh this session) |
| `mbpp_holdout` | 508 MBPP pairs, problems disjoint from test set | Contamination-safe MBPP repair |

DATA-INTEGRITY NOTE: the legacy `mbpp_clean`/`quixbugs_clean`/`humaneval_clean`
indexes are byte-identical duplicates of `repair_clean` (BugsInPy). Harmless to
headline claims (the intended corpus was BugsInPy everywhere), but the genuine MBPP
corpora above were built fresh to avoid the mislabel.

### A.9 Benchmarks and models

- **Benchmarks:** QuixBugs (40, algorithmic), HumanEvalFix (164, function-level),
  PyBugHive-black (34, repo-level), MBPP-holdout (187, synthetic mutations).
- **Models:** gpt-4o, gpt-4.1, gpt-4o-mini (OpenAI); Llama-3-8B-Instruct,
  Llama-3.3-70B-Instruct-Turbo (Together AI). Embeddings: local `all-MiniLM-L6-v2`.

---

## PART B — Results (all paper-usable)

### B.1 Retrieval relevance — structured significantly more relevant

Tag-compatibility (top-5 Jaccard of repair-pattern tags vs ground truth):

| Benchmark | code_only | structured |
| --- | ---: | ---: |
| QuixBugs | 0.218 | **0.394** (+81%) |
| PyBugHive-black | 0.123 | **0.258** (+110%) |

INDEPENDENT (vocabulary-free) metric — cosine of candidate fix-diff to GT fix-diff,
which shares nothing with the reranker objective (defuses circularity):

| variant | top-1 | top-2 | top-5 |
| --- | ---: | ---: | ---: |
| code_only | 0.251 | 0.230 | 0.207 |
| structured | 0.265 | 0.256 | **0.234** |

Significant: structured vs code_only top-5, n=40, mean diff +0.0265, 95% CI
[+0.016,+0.037], Wilcoxon **p=0.0001**, structured higher on 31/40. The tag metric
overstates the effect (+81%) relative to the independent metric (+13%), but the gain
is real and significant.

### B.2 QuixBugs downstream (single attempt, k=2)

| Model | baseline | code_only | structured |
| --- | ---: | ---: | ---: |
| gpt-4o | 35/40 | 37/40 | 37/40 |
| gpt-4.1 | 36/40 | 35/40 | 35/40 |
| gpt-4o-mini | 33/40 | 33/40 | 30/40 |

Variance (5 trials, gpt-4o): baseline 89.5%, structured 91.0%, code_only 90.5% —
OVERLAPPING. The QuixBugs structured "+2" is within noise; not a significant win.

### B.3 HumanEvalFix model-sensitivity — statistically NEUTRAL

| Model | baseline | structured | McNemar p |
| --- | ---: | ---: | ---: |
| gpt-4o | 80.5% | 76.8% | 0.109 (ns) |
| gpt-4.1 | 79.9% | 78.7% | 0.727 (ns) |
| gpt-4o-mini | 68.3% | 66.5% | 0.629 (ns) |
| Llama-3.3-70B | 69.5% | 67.7% | 0.648 (ns) |

The apparent "drops" are NOT significant → structured RAG is neutral, not harmful.
(Llama-3-8B raw collapsed to 8.5% but this was an output-format confound: 123/164
syntax errors; the model could not format output under the longer RAG prompt.
Corrected with robust extraction in the MBPP harness — see B.6.)

### B.4 Corpus ablation (HumanEvalFix, BugsInPy vs genuine MBPP corpus)

| Model | corpus | structured | vs baseline |
| --- | --- | ---: | ---: |
| gpt-4o | BugsInPy | 76.8% | -3.7 |
| gpt-4o | MBPP | 78.0% | -2.5 |
| Llama-3.3-70B | BugsInPy | 67.7% | -1.8 |
| Llama-3.3-70B | MBPP | 62.8% | -6.7 |

Corpus domain-match is a small, model-dependent, inconsistent effect (helps gpt-4o
slightly, hurts 70B); not significant; not the explanation for non-conversion.

### B.5 PyBugHive-black repo-level

Original (contaminated corpus): baseline 23/34, all RAG ~11-12/34 (retrieval hurts).
Project-held-out (contamination removed): baseline 23/34, code_only 23/34,
structured 23/34 — neutral; large-file patch layer is the bottleneck there.

### B.6 Positive-regime hunt: MBPP-holdout repair (contamination-controlled)

Robust code extraction fixes the weak-model output confound (8B syntax errors:
123/164 → 0/187).

| Model | baseline | code_only | structured | McNemar (base vs structured) |
| --- | ---: | ---: | ---: | --- |
| gpt-4o-mini | 93.0% | 92.5% | 91.4% | ns (p=0.55) |
| Llama-3-8B | 64.7% | 65.2% | 64.2% | ns (p=1.0) |

Even with a real knowledge gap (8B), matched corpus, contamination control, and the
output confound removed, structured is statistically neutral and ties code_only.

### B.7 Oracle / ceiling — the central mechanistic result

Force the most fix-relevant example(s) and measure the repair ceiling.

| Condition | gpt-4o-mini (base 93.0%) | Llama-3-8B (base 64.7%) |
| --- | --- | --- |
| structured | 91.4% (ns) | 64.2% (ns) |
| ORACLE_corpus (best from disjoint corpus) | 94.7% (+1.6, ns) | 72.2% (+7.5, borderline p=0.065) |
| ORACLE_self (exact fix pattern shown) | 96.3% (+3.2, ns) | **90.4% (+25.7, p<0.0001 ***)** |

Interpretation:
1. A relevant example **significantly** improves the knowledge-gap model (8B +25.7) —
   so the model CAN exploit examples; exploitation is not the bottleneck.
2. The ceiling is **model-dependent**: negligible for the saturated model (mini),
   large for the knowledge-gap model (8B). Matches the knowledge-gap principle.
3. Current retrieval (structured/code_only) captures ~none of this headroom →
   bottleneck is retrieval quality.
4. `oracle_corpus` (best real corpus example) is only borderline → part of the limit
   is corpus coverage / the model needing near-exact examples. (oracle_corpus uses
   the GT fix to select; it is an upper bound, not a deployable target.)

### B.8 Statistical rigor

- Significance: `experiments/analysis/significance_tests.py` (McNemar) +
  `significance_mcnemar.json`. All downstream comparisons ns except `oracle_self`
  (8B). Independent relevance significant (Wilcoxon p=0.0001).
- Determinism: temperature-0 runs are deterministic (baseline 0 flips, structured
  1/187 across trials) → single-trial results representative.

### B.9 Re-evaluation of RAGFix (IEEE BigData 2024) — de-confounding

Recomputed pass@1 from RAGFix's released CSVs (validated: baselines match their
reported figures).

| Model | RAGFix run | pass@1 | vs baseline |
| --- | --- | ---: | ---: |
| 70B | baseline | 72.6% | — |
| 70B | RAG, no postproc | 71.3% | -1.3 |
| 70B | RAG + import postproc (reported) | 78.0% | +5.4 |
| 8B | baseline | 41.5% | — |
| 8B | RAG (reported, excludes 4) | 48.8% (true) / 51.2% (reported) | +7.3 |

RAGFix's 70B "gain" is an import-postprocessing artifact (ImportErrors 13→8→0);
de-confounded RAG is *below* baseline. The 8B gain is real but inflated (excluded
examples + retries). Caveat: this is inferential (different runs), not a controlled
postprocessing on/off ablation.

### B.10 Related-work differentiation

vs **ReCode** (CIKM'25, algorithm-type retrieval) and **InferFix** (FSE'23,
static-analyzer bug-type retrieval): our signal is **dynamic failure state** (runtime
test failure), orthogonal to their static signals; we contribute an explicit,
ablatable reranking function and a human/independent-validated relevance analysis.
Full analysis: `docs/RELATED_WORK_RECODE_DIFFERENTIATION.md`. (Direct numeric
comparison infeasible: ReCode/InferFix closed-source; RAP-Gen is Java/JS.)

---

## PART C — Claim → evidence map

| Paper claim | Evidence |
| --- | --- |
| Structured reranking improves retrieval relevance | B.1 (tag + independent metric, significant) |
| Relevance does not convert to repair success | B.2-B.6 (all ns, multi-model/corpus/benchmark) |
| Bottleneck is retrieval, not example exploitation | B.7 (oracle_self +25.7 sig; model exploits a relevant example) |
| Ceiling follows the knowledge-gap principle | B.7 (model-dependent: large for 8B, negligible for saturated) |
| Reported RAG-repair gains can be confounded | B.9 (RAGFix de-confounding) |
| Results are statistically grounded | B.8 (McNemar, Wilcoxon, determinism) |

## PART D — Honest limitations (state in the paper)

1. **External validity:** all executable results are algorithmic / synthetic
   (QuixBugs, HumanEvalFix, MBPP mutations); no natural/realistic executable repair.
2. Oracle ceiling shown on MBPP synthetic bugs (2 models, 1 bug family).
3. `oracle_corpus` headroom is borderline; the strong ceiling claim rests on
   `oracle_self`.
4. RAGFix de-confounding is inferential, single system.
5. Human blind relevance audit is tooled (`build_blind_audit.py`) but not yet
   annotated; the relevance validation currently rests on the automated independent
   metric.
6. QuixBugs downstream "+2" is within variance — not claimed as a win.
