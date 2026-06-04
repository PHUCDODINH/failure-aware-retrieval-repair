# Structured Failure-Aware Retrieval for LLM Program Repair — System & Results

Consolidated paper-facing description of the system and every result we will use.
Last updated 2026-06-03. Numbers traced to files in `experiments/`; significance via
`experiments/analysis/significance_tests.py`.

---

## PART A — System Description

### A.1 Research question and thesis

Recommended paper title (critical empirical study, not a method-win paper):

> **Better Retrieval, Same Repair: Why Relevance Gains Don't Convert in Synthetic and Algorithmic LLM Program Repair**
>
> The scope qualifier ("Synthetic and Algorithmic") is required: every executable
> result is on synthetic/algorithmic benchmarks, so the title must not promise general
> repair. "Structured Failure-Aware Retrieval" is the *method* name inside the paper,
> not the title's promise. The positive contribution is the FINDING (coverage >
> ranking; relevance proxy doesn't convert), not the method.

We study **when retrieval-augmented LLM program repair helps, is neutral, or hurts**,
and isolate the role of *retrieval relevance*. Final, statistically-grounded thesis:

> Structured failure-aware reranking **significantly improves retrieval relevance**
> (independent metric, Wilcoxon p=0.0001), but this **does not convert to downstream
> repair gains**: across models and corpora on synthetic/algorithmic function-level
> benchmarks, structured retrieval is **neutral-to-slightly-negative** (point
> estimates -0.5 to -3.7 pp; the most capable model, gpt-4o, shows borderline small
> harm; equivalent to baseline within +-10 pp but NOT within +-5 pp; minimum
> detectable effect 4.8-9.1 pp). A planted-corpus experiment shows the binding
> constraint is **primarily corpus coverage; ranking headroom is small and
> heterogeneous**, replicated across two independent knowledge-gap models (table in
> B.7a): coverage headroom +14.4 pp (Llama-3-8B) / +13.4 pp (Qwen2.5-7B) from planting
> a perfect example (both significant), vs ranking headroom of +7.5 pp (Llama,
> p=0.065) but −1.6 pp (Qwen, ns) from forcing the best *real* example — i.e. ranking
> headroom is inconsistent (sometimes ~0/negative), which only strengthens "coverage
> dominates." Structured reranking adds nothing over plain dense retrieval
> downstream and selects the best example *less* often than dense retrieval (94.1% vs
> 100%). We further show a published positive claim (RAGFix) is **consistent with a
> post-processing artifact** (controlled ablation pending).

SCOPE: all executable evidence is on synthetic/algorithmic benchmarks (QuixBugs,
HumanEvalFix, MBPP). Claims are scoped accordingly; realistic natural-bug executable
repair is future work (see Part D).

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

Dataset/benchmark provenance (cite):
- HumanEvalFix — OctoPack (Muennighoff et al., 2023, arXiv:2308.07124).
- QuixBugs (Lin et al., SPLASH 2017); MBPP (Austin et al., 2021, arXiv:2108.07732);
  BugsInPy (Widyasari et al., ESEC/FSE 2020); PyBugHive (project source).

---

## PART B — Results (all paper-usable)

### B.1 Retrieval relevance — structured improves a proxy (SETUP, not a "win")

FRAMING: this is the *setup for the paper's puzzle*, not a standalone positive
contribution. Structured significantly improves a relevance *proxy*, yet B.7a shows
that improvement is downstream-hollow (no better best-example selection than plain
dense retrieval, no conversion). Present B.1 and B.7a together: "we can improve a
relevance proxy, and here is why that does not help."

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

### B.3 HumanEvalFix model-sensitivity — neutral-to-slightly-negative

| Model | baseline | structured | McNemar p |
| --- | ---: | ---: | ---: |
| gpt-4o | 80.5% | 76.8% | 0.109 (ns) |
| gpt-4.1 | 79.9% | 78.7% | 0.727 (ns) |
| gpt-4o-mini | 68.3% | 66.5% | 0.629 (ns) |
| Llama-3.3-70B | 69.5% | 67.7% | 0.648 (ns) |

The "drops" are not significant by exact McNemar (all ns), but every point estimate is
negative and the most capable model (gpt-4o, -3.7) shows **borderline small harm**
(see B.8 reconciliation). Honest reading: **neutral-to-slightly-negative**, not clean
neutrality; structured never beats baseline and trends slightly negative.
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

Interpretation (stated conservatively):
1. `oracle_self` (+25.7) is a **sanity check, not a headroom measurement** — it shows
   the model the exact fix pattern for its own problem, so it mainly confirms the
   model can use a near-identical example. It is NOT evidence of deployable headroom.
2. The honest, deployable ceiling is `oracle_corpus` (best *real* corpus example):
   +7.5 (90% CI [+1.3,+13.6], exact McNemar p=0.065) on 8B, negligible on gpt-4o-mini.
   Marginal and wide — a thin ceiling.
3. The ceiling is larger for the knowledge-gap model than the saturated one — this is
   **consistent with** the knowledge-gap idea, but rests on two models, so we do NOT
   call it a "principle".
4. `oracle_corpus` being only marginal raised a confound: corpus-coverage vs
   retrieval-ranking. Resolved by the planted-corpus experiment (B.7a).

### B.7a Planted-corpus experiment — resolves the coverage-vs-ranking confound

Plant each test problem's EXACT (buggy→fixed) pair into the corpus (`mbpp_planted`,
695 entries), so a perfect example is GUARANTEED present. Llama-3-8B, with traces.

| condition | rate | vs baseline | planted-pair top-k hit-rate |
| --- | ---: | --- | ---: |
| baseline | 64.7% | — | — |
| code_only / holdout | 65.2% | ns | — |
| structured / holdout | 64.2% | ns | — |
| code_only / PLANTED | 86.6% | +21.9, p<0.0001 | 100% |
| structured / PLANTED | 86.6% | +21.9, p<0.0001 | 94.1% (demotes 11) |

DECOMPOSITION (the strongest internal logic): baseline → oracle_corpus (best REAL
example) → planted (perfect example). Ranking headroom = oracle_corpus − baseline;
coverage headroom = planted − oracle_corpus. Replicated across two independent
knowledge-gap models (Llama-3-8B, Qwen2.5-7B) plus a saturated control (gpt-4o-mini):

| Model (base) | oracle_corpus | planted | ranking headroom | coverage headroom |
| --- | ---: | ---: | ---: | ---: |
| Llama-3-8B (64.7%) | 72.2% | 86.6% | **+7.5** (p=0.065) | **+14.4** (p<0.0001) |
| Qwen2.5-7B (78.6%) | 77.0% | 90.4% | **−1.6** (ns) | **+13.4** (p=0.0001) |
| gpt-4o-mini (93.0%, saturated) | 94.7% | 94.1% | +1.6 (ns) | −0.5 (ns) |

(n=187 each; McNemar vs baseline. Qwen2.5-7B-Instruct-Turbo via Together.)

- **Coverage headroom is large and significant on BOTH gap models (+14.4, +13.4)** and
  ~0 on the saturated model. This is the robust, replicated result: corpus coverage
  is the dominant binding constraint.
- **Ranking headroom is HETEROGENEOUS and not robustly positive**: +7.5 (Llama,
  marginal p=0.065) vs −1.6 (Qwen, ns — forcing the best real example slightly HURT).
  So we do NOT claim a consistent "marginal ranking gap"; we claim ranking headroom is
  small and inconsistent (sometimes ~0/negative), which only strengthens "coverage
  dominates." We avoid averaging +7.5 and −1.6 into a single positive effect.
- Honest claim: "**primarily corpus coverage; ranking headroom is small and
  heterogeneous (+7.5 to −1.6 across models)**" — NOT "coverage, not ranking" (the
  absolute version), and NOT "a consistent small ranking gap" (the +7.5-only version).

ROBUST CLAIM (lead with this): structured reranking does NOT improve best-example
selection over plain dense retrieval — when a perfect example is present, dense
retrieval selects it 100% of the time (top-k) while structured selects it only 94.1%,
and conversion is identical (both 86.6%). So structured's proxy-relevance gain (B.1)
does not translate into better top-example selection or better repair; it slightly
degrades selection. (The 100% dense hit-rate rules out "the example is hard to
retrieve" — the reranking is what moves it. We do not over-specify the internal cause
of the 6% degradation.)

### B.8 Statistical rigor

- Significance (McNemar, `significance_tests.py`): all downstream comparisons ns
  except `oracle_self` (8B). Independent relevance significant (Wilcoxon p=0.0001).
- **Equivalence (TOST) + minimum detectable effect** (`equivalence_power.py`,
  `equivalence_power.json`). d = structured − baseline (pp), 90% CI, TOST verdict at
  ±5pp / ±10pp, MDE at 80% power:

  | comparison | n | d (pp) | 90% CI (pp) | eq ±5 | eq ±10 | MDE (pp) |
  | --- | --- | ---: | --- | --- | --- | ---: |
  | HEF gpt-4o | 164 | -3.7 | [-6.8,-0.5] | no | YES | 5.4 |
  | HEF gpt-4.1 | 164 | -1.2 | [-4.1,+1.6] | YES | YES | 4.8 |
  | HEF gpt-4o-mini | 164 | -1.8 | [-6.0,+2.3] | no | YES | 7.0 |
  | HEF llama70b | 164 | -1.8 | [-6.2,+2.5] | no | YES | 7.4 |
  | MBPP llama8b | 187 | -0.5 | [-5.9,+4.8] | no | YES | 9.1 |
  | MBPP gpt4omini | 187 | -1.6 | [-4.5,+1.3] | YES | YES | 5.0 |

  Honest reading: equivalent within **±10pp** but NOT within **±5pp**; MDE 4.8-9.1pp.
  ±10pp is a WIDE margin — "equivalent within ±10pp" only means "we cannot rule out
  effects smaller than ~10pp" (weak equivalence). Point estimates are
  neutral-to-slightly-negative (-0.5 to -3.7pp).
  RECONCILIATION (gpt-4o): the Wald 90% CI [-6.8,-0.5] excludes 0, but exact McNemar
  p=0.109 (ns). These disagree because the discordant count is small (b=8, c=2, m=10),
  where the normal approximation is unreliable; we defer to the EXACT test. Honest
  presentation: gpt-4o shows **borderline small harm** (point estimate -3.7pp), i.e.
  the "slightly-negative" end of neutral-to-slightly-negative — NOT clean neutrality.
- Near-determinism: temperature-0 re-run flips 0/187 (baseline) and 1/187 (structured)
  → effectively but not strictly deterministic; single-trial results representative.
  (Note: retrieval *pool ordering* can vary in near-duplicate tie-clusters — see
  B.7a caveat — a separate, embedding-level effect from the pass/fail determinism.)

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

RAGFix's reported 70B gain is **consistent with an import-postprocessing artifact**:
the only RAG run *without* import postprocessing (vdb-7-15) is 71.3%, *below* baseline
(72.6%), and the reported 78% run adds import fixing (ImportErrors 13→8→0). The 8B
gain is real but the reported 51.2% is computed over 160 (4 API-failed examples
excluded); on the full 164 it is 48.8% (+7.3).

IMPORTANT CAVEATS (state in paper; do NOT overclaim):
- This is **inferential, not controlled**: vdb-7-15 and vdb-7-16 are *different runs*,
  not a postprocessing on/off ablation on identical outputs. We cannot prove the gain
  IS postprocessing, only that the data is *consistent with* it.
- We do NOT allege intent in the example exclusion; we report the denominator
  difference factually (160 vs 164) as a comparability issue.
- A clean controlled ablation (their pipeline, postprocessing on/off) is needed to
  make this a strong claim. Recommended framing: "the reported gain is consistent
  with a post-processing artifact; a controlled ablation is required to confirm."

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
| Structured improves a relevance PROXY (setup, not a standalone win) | B.1 (independent metric, Wilcoxon p=0.0001) — see B.7a for why it is downstream-hollow |
| Relevance does not convert to repair success (neutral-to-slightly-negative) | B.2-B.6 + equivalence/MDE (B.8): no effect > ~10pp (weak equiv.), point estimates -0.5 to -3.7pp; gpt-4o borderline-negative |
| Binding constraint is PRIMARILY corpus coverage; ranking headroom small + heterogeneous | B.7a (table): replicated on 2 gap models — coverage headroom +14.4 (Llama-8B) / +13.4 (Qwen-7B), both significant; ranking headroom +7.5 (Llama) / −1.6 (Qwen), inconsistent; structured selects the best example less often than dense retrieval (94.1% vs 100%) |
| Knowledge-gap ceiling is model-dependent (consistent with, not a "principle") | B.7 (2 models) |
| Reported RAG-repair gains can be confounded | B.9 (RAGFix; inferential, "consistent with" postprocessing) |
| Results are statistically grounded | B.8 (McNemar, Wilcoxon, TOST+MDE, near-determinism) |

## PART D — Honest limitations (state in the paper)

1. **External validity:** all executable results are algorithmic / synthetic
   (QuixBugs, HumanEvalFix, MBPP mutations); no natural/realistic executable repair.
2. The coverage decomposition is shown on MBPP synthetic bugs, **2 knowledge-gap
   models** (Llama-3-8B, Qwen2.5-7B) + 1 saturated control, **1 bug family** (synthetic
   mutations). The coverage effect replicates across the two gap models; the bug-family
   and benchmark scope is still narrow.
3. We do NOT rest any claim on `oracle_self` (it is a sanity check; see B.7 pt 1). The
   deployable retrieval signal is `oracle_corpus`, whose ranking headroom is small and
   heterogeneous (+7.5 / −1.6). The robust, replicated claim is the COVERAGE headroom
   (+14.4 / +13.4), not a ranking ceiling.
4. RAGFix de-confounding is inferential (different runs, not a controlled
   postprocessing on/off ablation), single system.
5. Human blind relevance audit is tooled (`build_blind_audit.py`) but not yet
   annotated; the B.1 relevance gain currently rests on an automated proxy. The
   PyBugHive relevance number (+110%) is tag-metric-only (no independent-metric
   corroboration) and we note the tag metric overstates.
6. QuixBugs downstream "+2" is within variance — not claimed as a win.
