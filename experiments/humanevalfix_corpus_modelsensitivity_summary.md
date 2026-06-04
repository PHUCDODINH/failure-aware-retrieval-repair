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

1. **Retrieval is statistically NEUTRAL on HumanEvalFix** for every capable model
   tested (Llama-3.3-70B, gpt-4o-mini, gpt-4.1, gpt-4o), across both corpora and
   both retrieval variants. The apparent -1 to -4 point "drops" are NOT significant
   (McNemar p=0.11-0.73, all ns; see section 10) — so structured RAG neither helps
   nor hurts here; it does not beat baseline and the negative deltas are within noise.
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
net-neutral and ties/loses to code_only (McNemar: all ns; see section 10).

NOTE (superseded by section 9): an earlier draft concluded the bottleneck was the
generator's ability to EXPLOIT an example. The oracle experiment (section 9) REFUTES
this — oracle_self reaches 90.4% (p<0.0001), proving the model exploits a relevant
example readily. The bottleneck is RETRIEVAL (surfacing fix-relevant examples), not
exploitation.

Paper implication: the supportable thesis is NOT "our method improves repair." It
is "structured failure-aware reranking improves retrieval relevance, but relevance
does not convert to repair success because it is not the binding constraint" —
demonstrated across models, corpora, and benchmarks, with a de-confounding
re-evaluation of RAGFix's published positive claim.

## 8. Independent relevance metric (2026-06-03) — defuses circularity

The tag-compat metric shares its vocabulary/inference with the structured reranker's
objective, so a structured win there is partly circular. Independent check
(`experiments/analysis/independent_relevance.py`): relevance = cosine(embed(candidate
fix-diff), embed(ground-truth fix-diff)). No variant optimizes for this.

QuixBugs (n=40), cosine of fix-diff to GT fix-diff:

| variant | top1 | top2 | top5 |
| --- | ---: | ---: | ---: |
| code_only | 0.251 | 0.230 | 0.207 |
| raw_text | 0.210 | 0.208 | 0.192 |
| raw_text_rerank | 0.248 | 0.227 | 0.198 |
| structured | 0.265 | 0.256 | 0.234 |

Structured wins on every cut on this independent metric -> the relevance gain is
REAL, not a tag-vocabulary artifact. BUT magnitude is smaller: +13% top-5 here vs
+81% on tag-compat. Honest takeaway: structured retrieval is genuinely more
fix-relevant, but the tag-compatibility metric overstates the effect size; report
both.

SIGNIFICANCE (top-5, structured vs code_only, paired over n=40 problems): mean diff
+0.0265, 95% bootstrap CI [+0.0156, +0.0374] (excludes 0); Wilcoxon p=0.0001;
structured higher on 31/40, tie 1, lower 8. The relevance gain is statistically
significant. (Caveat: single benchmark, n=40; PyBugHive independent metric not yet run.)

## 9. Oracle / ceiling experiment (2026-06-03) — KEY RESULT

Bounds what retrieval *could* achieve, decoupled from the reranker. Llama-3-8B,
MBPP-holdout (187, contamination-controlled). `experiments/analysis/oracle_ceiling_mbpp.py`.

| Condition | Pass/187 | Rate | Δ baseline |
| --- | ---: | ---: | ---: |
| baseline | 121 | 64.7% | — |
| code_only | 122 | 65.2% | +0.5 |
| structured | 120 | 64.2% | -0.5 |
| ORACLE corpus (best fix-similar from disjoint corpus) | 135 | 72.2% | +7.5 |
| ORACLE self (exact fix pattern shown) | 169 | 90.4% | +25.7 |

Interpretation (with McNemar significance, section 10):
1. The model CAN exploit a relevant example: oracle_self 90.4% (+25.7, p<0.0001).
   This is the load-bearing, statistically-solid ceiling result. It refutes "weak
   model can't use examples" and proves exploitation is NOT the bottleneck.
2. oracle_corpus (+7.5) is only BORDERLINE vs baseline (McNemar p=0.065, NOT
   significant at n=187), though it IS significantly above structured (p=0.024). So
   "a fix-aware retriever could extract gains from this corpus" is SUGGESTIVE, not
   conclusive; do not overstate it.
3. The bottleneck is RETRIEVAL, inferred from: (a) the model exploits a perfect
   example (oracle_self, solid) yet (b) current retrieval is net-neutral
   (structured ~= code_only ~= baseline, all ns). Current retrieval is not surfacing
   examples good enough to help.
4. oracle_corpus uses the GROUND-TRUTH fix to rank candidates -> it is an UPPER BOUND
   that a deployable retriever (which lacks the fix) may not reach; frame as ceiling,
   not achievable target.

REVISED THESIS: a relevant-enough example demonstrably and significantly improves
weak-model repair (oracle_self), yet current retrieval — incl. structured reranking —
does not help (all ns). So the bottleneck is retrieval quality, not example
exploitation. The corpus-achievable headroom (oracle_corpus) is suggestive but
borderline. Open problem: fix-aware retrieval. (Plus RAGFix de-confounding.)

## 10. Statistical significance (2026-06-03) — McNemar paired tests

Llama-3-8B / MBPP-holdout (n=187), exact two-sided McNemar on paired pass/fail:

| Comparison | discordant b/c | p | verdict |
| --- | --- | ---: | --- |
| baseline vs code_only | 23/24 | 1.000 | ns |
| baseline vs structured | 19/18 | 1.000 | ns |
| code_only vs structured | 11/9 | 0.824 | ns |
| baseline vs ORACLE_corpus | 18/32 | 0.065 | ns (borderline) |
| baseline vs ORACLE_self | 8/56 | <0.0001 | *** |
| structured vs ORACLE_corpus | 12/27 | 0.024 | * |

Takeaways:
- The downstream neutrality (structured ~= code_only ~= baseline) is statistically
  confirmed (all ns) — solid. NOTE: the HumanEvalFix "drops" are ALSO ns (gpt-4o
  base vs structured p=0.109), so structured is NEUTRAL, not harmful, on HumanEvalFix.
- oracle_self gain is highly significant (model can exploit a perfect example).
- oracle_corpus vs baseline is NOT significant (p=0.065); only significant vs the
  structured method (p=0.024). Report honestly.
- Independent relevance (structured vs code_only top-5, n=40): Wilcoxon p=0.0001,
  bootstrap CI [+0.016,+0.037] — relevance gain IS significant.

Full McNemar table across all paired comparisons: experiments/significance_mcnemar.json
(script: experiments/analysis/significance_tests.py). All HumanEvalFix and corpus-
ablation downstream comparisons are ns; only oracle_self is significant (***).

GAPS this exposes / still open:
- Significance only computed for MBPP-llama8b; not for HumanEvalFix/corpus-ablation
  or the independent-relevance metric (n=40, no test).
- All new runs are SINGLE-TRIAL (temperature 0 but APIs not fully deterministic);
  only QuixBugs has a 5-trial variance study.
- Oracle ceiling is a SINGLE (model, benchmark) cell, on SYNTHETIC MBPP mutations;
  needs replication (e.g., gpt-4o-mini, QuixBugs/HumanEvalFix) and natural bugs.
- RAGFix de-confounding is INFERENTIAL (vdb-7-15 vs vdb-7-16 are different runs, not
  a controlled postprocessing on/off ablation); attribution rests on their note +
  ImportError counts (13->8->0), not a clean experiment.
- Realistic executable repair still untested; human blind audit (section tooling)
  not yet annotated.

## 11. Determinism / trial variance (2026-06-03)

Temperature-0 re-run (trial2) vs trial1, Llama-3-8B MBPP-holdout:

| condition | trial1 | trial2 | flips |
| --- | ---: | ---: | ---: |
| baseline | 121/187 | 121/187 | 0 (0.0%) |
| structured | 120/187 | 121/187 | 1 (0.5%) |

Runs are essentially deterministic at temperature 0. Single-trial results are
representative; the small downstream deltas are stable, not undersampling noise.
(The QuixBugs +-2 variance arose from its temperature-varied candidate strategies,
which are not used here.) Resolves the multi-trial concern.

## 12. Oracle ceiling REPLICATION on gpt-4o-mini (2026-06-03)

Same oracle ladder on the saturated model, vs the knowledge-gap model. McNemar vs baseline.

| Condition | gpt-4o-mini (base 93.0%) | Llama-8B (base 64.7%) |
| --- | --- | --- |
| code_only | 92.5% (ns) | 65.2% (ns) |
| structured | 91.4% (ns) | 64.2% (ns) |
| ORACLE_corpus | 94.7% (+1.6, ns p=0.45) | 72.2% (+7.5, borderline p=0.065) |
| ORACLE_self | 96.3% (+3.2, ns p=0.07) | 90.4% (+25.7, *** p<0.0001) |

The ceiling is MODEL-DEPENDENT and concentrated in the knowledge-gap regime: a
perfect example helps significantly only for the weak model (8B +25.7 ***); for the
saturated model the same perfect example yields only +3.2 (ns). This is exactly the
knowledge-gap prediction and strengthens (does not contradict) the mechanism: examples
help when the model lacks the knowledge, and current retrieval fails to surface
sufficiently relevant ones. oracle_corpus headroom remains weak/borderline in both.

## 13. Equivalence (TOST) + power / MDE (2026-06-03) — addresses "neutral != ns"

Non-significance is not equivalence. For each null comparison: paired diff (treatment
- baseline, pp), 90% CI, TOST equivalence verdict at +-5pp and +-10pp margins, and
the minimum detectable effect at 80% power. Script: analysis/equivalence_power.py.

| comparison | n | d (pp) | 90% CI (pp) | eq +-5 | eq +-10 | MDE (pp) |
| --- | --- | ---: | --- | --- | --- | ---: |
| HEF gpt-4o base->structured | 164 | -3.7 | [-6.8, -0.5] | no | YES | 5.4 |
| HEF gpt-4.1 base->structured | 164 | -1.2 | [-4.1, +1.6] | YES | YES | 4.8 |
| HEF gpt-4o-mini base->structured | 164 | -1.8 | [-6.0, +2.3] | no | YES | 7.0 |
| HEF llama70b base->structured | 164 | -1.8 | [-6.2, +2.5] | no | YES | 7.4 |
| MBPP llama8b base->structured | 187 | -0.5 | [-5.9, +4.8] | no | YES | 9.1 |
| MBPP gpt4omini base->structured | 187 | -1.6 | [-4.5, +1.3] | YES | YES | 5.0 |
| MBPP llama8b base->ORACLE_corpus | 187 | +7.5 | [+1.3, +13.6] | no | no | 10.6 |

HONEST CLAIMS (replace "neutral" language):
- We are NOT powered to claim equivalence at +-5pp (MDE 4.8-9.1pp); we CAN claim it
  at +-10pp for structured-vs-baseline. So: "structured produces no conversion larger
  than ~10pp; point estimates are neutral-to-slightly-negative (-0.5 to -3.7pp)."
- gpt-4o leans slightly NEGATIVE (90% CI excludes 0 on Wald approx; exact McNemar
  p=0.109). Do not call it "neutral"; call it "neutral-to-slightly-negative".
- oracle_corpus 90% CI [+1.3,+13.6] excludes 0 (marginally positive) but is wide and
  not equivalent at +-10pp; exact McNemar p=0.065. Report as marginal, wide.

## 14. Full index audit (2026-06-03) — answers "what else is mislabeled?"

Every `data/indexes/*` meta.jsonl audited (content signature + source field):

| index | n | source | status |
| --- | --- | --- | --- |
| repair_clean, humaneval_clean, mbpp_clean, quixbugs_clean | 551 | bugsinpy | IDENTICAL (one duplicate group) |
| repair_clean_holdout_pybughive_projects | 277 | bugsinpy | genuine (held-out) |
| mbpp_real | 1041 | mbpp_synthetic | genuine |
| mbpp_holdout | 508 | mbpp_synthetic | genuine |
| mbpp_planted | 695 | mbpp_synthetic + planted_exact | genuine (diagnostic) |

Verification: exactly ONE duplicate group (the 4 legacy `*_clean`, all BugsInPy). All
other indexes carry a verified `source` field matching their intended content. No
other mislabels. The paper used `repair_clean`/`repair_clean_holdout` (BugsInPy, the
intended corpus) and the freshly-built genuine `mbpp_*` corpora.

## 15. Planted-corpus experiment (2026-06-03) — resolves coverage-vs-ranking confound

To separate corpus-coverage from retrieval-ranking, we planted each test problem's
EXACT (buggy→fixed) pair into the corpus (`mbpp_planted`, 695 entries), guaranteeing a
perfect example is present, then ran retrieval+repair on Llama-3-8B with traces.

| condition | pass/187 | rate | vs baseline | planted-pair hit-rate (top-k) |
| --- | ---: | ---: | --- | ---: |
| baseline | 121 | 64.7% | — | — |
| code_only / holdout | 122 | 65.2% | ns | — |
| structured / holdout | 120 | 64.2% | ns | — |
| code_only / PLANTED | 162 | 86.6% | +21.9, p<0.0001 | 100.0% |
| structured / PLANTED | 162 | 86.6% | +21.9, p<0.0001 | 94.1% (demotes 11/187) |

CONCLUSION (corrects the earlier "bottleneck is retrieval ranking" claim):
1. The binding constraint is CORPUS COVERAGE, not retrieval ranking. When a
   sufficiently-relevant example is present, both variants retrieve it and convert
   (+21.9pp, highly significant). The realistic holdout corpus simply lacks such an
   example (oracle_corpus best-available = +7.5 only).
2. Structured reranking is downstream-INERT and slightly harmful to ranking:
   structured = code_only on planted (86.6%), and structured DEMOTES the perfect
   example in 11/187 cases (94.1% hit-rate vs code_only 100%). It adds nothing
   because (a) realistic corpora rarely contain a good example, and (b) when they do,
   plain dense retrieval already surfaces it.

REVISED THESIS (honest, reviewer-aligned): structured failure-aware reranking
significantly improves a relevance proxy but does not convert to repair, because the
binding constraint is corpus coverage — the availability of a sufficiently-relevant
example — not retrieval ranking. When no relevant example exists (the common case on
realistic corpora) no reranker can help; when one exists, simple dense retrieval
already finds it (and structured reranking can even demote it).

## 16. Planted-corpus on a SECOND model (gpt-4o-mini) + decomposition (2026-06-03)

| | Llama-3-8B (gap, base 64.7%) | gpt-4o-mini (saturated, base 93.0%) |
| --- | --- | --- |
| oracle_corpus (ranking headroom) | 72.2% (+7.5pp, p=0.065) | 94.7% (+1.6pp, ns) |
| planted (total headroom) | 86.6% (+21.9pp, p<0.0001) | 94.1% (+1.1pp, ns) |
| coverage headroom (planted - oracle_corpus) | +14.4pp | -0.5pp |

Confirms the pattern is KNOWLEDGE-GAP-DEPENDENT: large coverage+ranking headroom for
the gap model, ~0 for the saturated model (no gap -> nothing to gain from coverage OR
ranking). HONEST LIMIT: gpt-4o-mini ceilings, so the large-magnitude decomposition
(+21.9 total, +14.4 coverage) still rests on a SINGLE knowledge-gap model (Llama-8B,
n=187). A second genuinely-knowledge-gapped model (another small model, or 8B on a
harder benchmark) is still needed to show the magnitude is not 8B-specific. The
reviewer's single-run concern is PARTIALLY addressed (mechanism direction confirmed;
magnitude not yet replicated).
