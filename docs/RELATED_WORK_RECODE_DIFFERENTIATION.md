# Related-Work Differentiation: ReCode and Structured Retrieval APR

Purpose: position this project's **structured failure-aware retrieval** against the
closest concurrent and prior structured-retrieval program-repair systems, so the
novelty claim is explicit and defensible.

Primary comparison target: **ReCode** (CIKM 2025), the most conceptually adjacent
recent work. Secondary anchors: **InferFix** (FSE 2023), **RAP-Gen** (FSE 2023),
**RAGFix** (IEEE BigData 2024).

---

## 1. What ReCode actually does

Confirmed from the full paper (arXiv:2509.02330, CIKM 2025):

- **Structuring signal:** LLM-predicted **algorithm-type labels** (e.g. greedy,
  binary search, graph, dp), inferred *statically* from the buggy code plus the
  problem description.
- **Retrieval:** a dual-encoder design — `OASIS-code-1.3B` for the buggy code,
  `bge-m3` for the natural-language problem description — fused into one query
  vector, run in parallel against **algorithm-bucketed sub-knowledge bases** of
  Codeforces buggy<->fixed code pairs.
- **Knowledge base:** hierarchical — broad algorithm category -> problem ->
  curated buggy/fixed submission pairs. Built via a semi-automated pipeline using
  syntactic/semantic diffing, compiler diagnostics, and test-execution outcomes.
- **Failure information at query time:** **none.** Test cases, exceptions, and
  execution outcomes are used *only offline*, to annotate KB entries with coarse
  "error types" for partitioning. The inference-time repair prompt is
  `Concat((q*, x*, y*), (q, x))` = retrieved example + target. There is **no
  failure signal, no test output, and no reranking score in the prompt.**
- **Domain:** competitive programming (RACodeBench from Codeforces, plus six
  out-of-distribution judges: AtCoder, CodeChef, HackerRank, HackerEarth,
  GeeksforGeeks, Aizu).
- **Models:** Gemma-2-9B/27B, GPT-4o-mini, Gemini-1.5-Flash, DeepSeek-V2-Chat,
  DeepSeek-Coder-V2-Instruct.
- **Headline pitch:** accuracy gain *plus* large inference-cost reduction (reaches
  a target pass rate in ~4-6 LLM calls vs 11-27 for Best-of-N / Self-Repair).
- **Code:** no public repository found.

---

## 2. Core distinction: orthogonal structuring signals

> ReCode structures retrieval by **what the code is trying to do** (algorithm
> intent, inferred statically). This project structures retrieval by **how the
> code fails** (failure mode, exception, assertion, contract tags — extracted from
> the runtime test failure).

These are perpendicular axes, not competing versions of one idea:

- Two bugs in the *same* algorithm class ("dp") can fail completely differently —
  timeout vs wrong-answer vs `IndexError`. ReCode retrieves the **same bucket** for
  all three; our reranker **discriminates by failure mode**.
- Two bugs in *different* algorithm classes can share a failure signature
  (off-by-one boundary). ReCode separates them; our `contract_tags` / `edit_scope`
  matching **links them**.

Failure-state is therefore information ReCode explicitly leaves on the table: it
*has* the execution data offline but never uses it as a query-time matching signal.

---

## 3. Side-by-side comparison

| Axis | ReCode (CIKM'25) | InferFix (FSE'23) | This project |
|---|---|---|---|
| Structuring signal | Algorithm-type (static, from code) | Static-analyzer bug type (Infer) | **Test-failure state (dynamic)** |
| Signal granularity | 1 axis (algorithm class) | 1 axis (bug category) | **6 fields**: failure_mode, exception_type, test_name, assertion_summary, suspicious_symbols, contract_tags |
| Failure info at query time | No (offline only) | Partial (analyzer category) | **Yes — core** |
| Explicit reranking function | No (encoder fusion + "collaborative" aggregation) | Dense retrieval | **Yes — weighted, ablatable compatibility score** |
| Corpus-side repair metadata | Error-type tag | — | **Diff-derived**: repair_pattern_tags, changed_operators, edit_scope, file_family, changed_lines |
| Domain | Competitive programming | Java/C# security & perf bugs | **Python repair**: algorithmic (QuixBugs), functional (HumanEvalFix), repo-level (PyBugHive) |
| Research framing | Accuracy + inference cost | Accuracy | **When retrieval helps/hurts**: relevance + model-sensitivity + honest negatives |
| Public code | No | No | Yes (this repo) |

---

## 4. Threats to novelty, and how to neutralize each

1. **High-level pitch collision.** Both are "fine-grained / structured
   retrieval-augmented repair over buggy<->fixed pairs."
   - *Neutralize:* lead every framing with **dynamic failure vs static intent**,
     never just "structured retrieval."

2. **ReCode's KB error-type annotation.** They tag KB entries with error types and
   claim this enables "error-specific examples," so a reviewer could call our idea
   a subset.
   - *Neutralize:* (a) theirs is **offline partitioning**, ours is a **query-time
     matching signal**; (b) theirs is a coarse error *type*, ours is a
     **multi-field failure state** (assertion summary, suspicious symbols, contract
     tags) consumed by an **explicit reranking function we ablate field-by-field**.
     ReCode reports **no ablation isolating its algorithm-type component**.

3. **Generality.** ReCode works *because* every Codeforces problem has a clean
   algorithm tag.
   - *Neutralize:* our PyBugHive / HumanEvalFix evidence — real repair targets (a
     CLI flag, a formatter, a config parser) often have **no clean algorithm type**
     but always have a **failure signature**. Failure-state generalizes where
     algorithm-type degenerates.

4. **"Structured retrieval helps" is partly claimed already.** ReCode shows a
   structured retriever beating naive retrieval on weaker models.
   - *Neutralize:* our differentiated claims are the ones they do not make —
     **retrieval-relevance measurement**, **model-sensitivity** (helps weak
     models, neutral/hurts strong ones), and **honest negative results**.

---

## 5. Verdict

The novelty gap is **real and defensible**:

- The structuring signal is orthogonal (dynamic failure vs static intent).
- The mechanism is an **explicit, ablatable reranker**, not encoder fusion.
- The domain and framing (when retrieval helps in *realistic* Python repair) are
  distinct from ReCode's competitive-programming accuracy+cost story.

ReCode is best used as the **strongest related-work anchor**, not a blocker:
"concurrent structured-retrieval work that structures on algorithm intent; we show
dynamic failure structure is a complementary and more general signal."

**Caveat for the paper:** ReCode is competitive-programming-only and closed-source,
so a direct numerical head-to-head is not feasible. Contrast on **mechanism and
signal**, not head-to-head pass rates.

---

## 6. One-paragraph related-work draft

> Recent work has begun to structure retrieval for program repair rather than
> relying on raw code similarity. ReCode [CIKM'25] predicts algorithm-type labels
> from the buggy code and retrieves algorithm-bucketed buggy/fixed pairs through a
> dual-encoder, while InferFix [FSE'23] conditions retrieval on static-analyzer bug
> categories, and RAP-Gen [FSE'23] uses a hybrid lexical/semantic patch retriever.
> These approaches structure retrieval by *static* properties of the code or the
> problem. In contrast, we structure retrieval by the *dynamic* failure behavior of
> the program: we extract a multi-field failure state (failure mode, exception
> type, assertion summary, suspicious symbols, and contract tags) from the runtime
> test failure and use it in an explicit, ablatable reranking function over
> diff-derived corpus metadata. This signal is orthogonal to algorithm intent — two
> bugs sharing an algorithm class may fail in entirely different ways, and bugs in
> different algorithm classes may share a failure pattern — and, unlike algorithm
> typing, it remains well defined for realistic repair targets that have no clean
> algorithmic label.
