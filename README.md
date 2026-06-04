# Structured Failure-Aware Retrieval for Program Repair

This repository contains an experimental LLM program-repair system for studying
when retrieval-augmented repair helps, when it is neutral, and when it hurts.

The current research direction is:

> Structured failure-aware reranking **significantly improves retrieval relevance**,
> but this **does not convert to downstream repair gains** — across models, corpora,
> and benchmarks, structured retrieval is statistically *neutral* on repair success
> (no significant difference from baseline). The bottleneck is **retrieval quality,
> not the model's ability to exploit an example**: a sufficiently relevant example
> significantly improves a knowledge-gap model (oracle ceiling +25.7 pts, p<0.0001),
> yet current retrieval surfaces none of that headroom.

The intended paper framing is not "RAG always beats the baseline." The core claim is
a critical, statistically-grounded characterization: explicit failure structure
significantly improves the *relevance* of retrieved repair examples, but relevance is
not the binding constraint for repair success. We additionally show that a published
positive claim (RAGFix) is largely a post-processing artifact.

See `docs/PAPER_SYSTEM_AND_RESULTS.md` for the consolidated system description and
every paper-usable result with significance tests.

## System Overview

The system compares direct LLM repair against several retrieval-augmented
variants.

Pipeline:

1. Collect buggy Python code and a raw failure signal from tests.
2. Extract a structured failure state from the raw failure signal.
3. Retrieve repair examples from a FAISS-backed bug-fix corpus.
4. Rerank examples with structured failure metadata.
5. Prompt an LLM with the bug, tests/failure signal, and optional retrieved examples.
6. Generate a repair.
7. Apply whole-code or strict line-range patches.
8. Run tests and write traces.

Retrieval variants:

| Variant | Description |
|---|---|
| `baseline` | Direct repair, no retrieval |
| `code_only` | Dense retrieval using buggy code only |
| `raw_text` | Dense retrieval using buggy code plus raw failure text |
| `raw_text_rerank` | Dense retrieval plus lexical failure-text reranking |
| `structured` | Dense retrieval plus structured failure-aware reranking |

Structured failure state fields include:

- `failure_mode`
- `exception_type`
- `test_name`
- `assertion_summary`
- `suspicious_symbols`
- `contract_tags`

Corpus-side repair metadata includes:

- `repair_pattern_tags`
- `suspicious_symbols`
- `changed_operators`
- `edit_scope`
- `file_family`
- `changed_lines`

## Main Components

| Path | Purpose |
|---|---|
| `src/models/repair_baseline.py` | Direct LLM repair baseline |
| `src/models/repair_rag.py` | RAG repair, retrieval variants, structured reranking |
| `src/models/patch_utils.py` | Strict line-range JSON patch parser/applier |
| `src/retrieval/failure_state.py` | Failure-state extraction |
| `src/retrieval/repair_metadata.py` | Automatic repair metadata inference |
| `src/retrieval/index_store.py` | FAISS index loading and retrieval profile resolution |
| `src/retrieval/build_index.py` | Builds FAISS indexes from JSONL corpora |
| `src/eval/evaluate_quixbugs.py` | QuixBugs repair evaluation |
| `src/eval/evaluate_pybughive.py` | PyBugHive repository-level repair evaluation |
| `src/eval/evaluate_humanevalfix.py` | HumanEvalFix repair evaluation |
| `src/eval/eval_retrieval_relevance.py` | Retrieval-only relevance analysis |
| `src/eval/ablate_fields.py` | Structured-field ablations |
| `src/eval/run_variance_trials.py` | Repeated-trial variance runs |
| `src/datasets/import_humanevalfix.py` | Imports BigCode/OctoPack HumanEvalFix data |
| `src/datasets/build_heldout_repair_corpus.py` | Builds project-held-out retrieval corpora |

## Benchmarks

The current experiments use:

- **QuixBugs**: controlled algorithmic Python repair.
- **PyBugHive-black**: realistic repository-level repair stress test.
- **PyBugHive project-held-out**: contamination-controlled PyBugHive runs.
- **HumanEvalFix**: synthetic function-level repair benchmark from BigCode/OctoPack.

Large external repositories, generated indexes, and cloned benchmark workspaces
are intentionally ignored by Git. Rebuild or import them locally with the scripts
in `src/datasets/` and `src/retrieval/`.

## Key Paper Results

Detailed paper-facing results are consolidated in:

- `docs/PAPER_SYSTEM_AND_RESULTS.md` (current, with significance tests) — primary
- `experiments/humanevalfix_corpus_modelsensitivity_summary.md` (full 2026-06-03 run)
- `experiments/paper_detailed_results_pack_20260525.md` (prior pack)

Headline results (significance via `experiments/analysis/significance_tests.py`):

| Benchmark / Setting | Main Observation |
|---|---|
| Retrieval relevance (QuixBugs) | Structured improves top-5 tag compatibility `0.218`→`0.394`; on an **independent** fix-diff metric (no shared vocabulary) +13%, **significant** (Wilcoxon `p=0.0001`, 31/40) |
| QuixBugs `gpt-4o` downstream | Baseline `35/40`, structured `37/40` — **within variance** (5-trial: baseline 89.5% vs structured 91.0%, overlapping); not a significant win |
| HumanEvalFix (gpt-4o/4.1/4o-mini/Llama-70B) | Structured is **statistically neutral** vs baseline (e.g. gpt-4o `132`→`126`, McNemar `p=0.11`, ns) — neither helps nor hurts |
| Corpus ablation (HumanEvalFix) | BugsInPy vs genuine MBPP corpus: small, model-dependent, non-significant; corpus match is not the lever |
| PyBugHive-black held-out | Baseline `23/34`, code_only `23/34`, structured `23/34` — neutral; patch layer is the bottleneck |
| **Oracle ceiling (MBPP-holdout, Llama-3-8B)** | A perfect example lifts repair `64.7%`→`90.4%` (**+25.7, p<0.0001**); current retrieval captures ~none → **bottleneck is retrieval, not example exploitation**. Model-dependent: negligible for saturated gpt-4o-mini |
| RAGFix de-confounding | Their reported Llama-70B gain (`72.5`→`78.0`) is an import-postprocessing artifact; de-confounded RAG (`71.3%`) is *below* baseline (recomputed from their released CSVs) |
| Determinism | Temperature-0 runs are deterministic (≤0.5% trial-to-trial flips); single-trial results representative |

## Setup

Python 3.12 is recommended.

```bash
python -m venv .venv312
.venv312/bin/pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set:

```bash
OPENAI_API_KEY=...
```

The embedding model defaults to:

```bash
all-MiniLM-L6-v2
```

If it is not already cached locally, `sentence-transformers` may download it on
first use.

## Rebuilding Retrieval Indexes

Build an index from a JSONL repair corpus:

```bash
.venv312/bin/python src/retrieval/build_index.py \
  --input-path data/corpora/repair_external_bugfix.jsonl \
  --profile repair_clean
```

Build a PyBugHive project-held-out corpus:

```bash
.venv312/bin/python src/datasets/build_heldout_repair_corpus.py \
  --input-path data/indexes/repair_clean/meta.jsonl \
  --output-path data/corpora/repair_clean_holdout_pybughive_projects.jsonl \
  --summary-path data/corpora/repair_clean_holdout_pybughive_projects.summary.json \
  --exclude-projects black pandas jax freqtrade spacy poetry salt cookiecutter scrapy discord.py numpy
```

Then build the held-out retrieval index:

```bash
env TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=1 \
  .venv312/bin/python src/retrieval/build_index.py \
  --input-path data/corpora/repair_clean_holdout_pybughive_projects.jsonl \
  --profile repair_clean_holdout_pybughive_projects
```

## Running Evaluations

QuixBugs primary run:

```bash
env TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=1 \
  .venv312/bin/python src/eval/evaluate_quixbugs.py \
  --mode rag \
  --retrieval-variant structured \
  --retrieval-profile repair_clean \
  --model gpt-4o \
  --limit 40 \
  --rag-max-attempts 1 \
  --rag-candidates 1 \
  --results-path experiments/quixbugs_structured_gpt4o.json
```

Retrieval-only relevance:

```bash
env TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=1 \
  .venv312/bin/python src/eval/eval_retrieval_relevance.py \
  --retrieval-profile repair_clean \
  --out experiments/retrieval_relevance.json
```

HumanEvalFix import:

```bash
.venv312/bin/python src/datasets/import_humanevalfix.py \
  --out data/humanevalfix/HumanEvalFix.jsonl
```

HumanEvalFix evaluation:

```bash
env TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=1 \
  .venv312/bin/python src/eval/evaluate_humanevalfix.py \
  --input-path data/humanevalfix/HumanEvalFix.jsonl \
  --mode rag \
  --retrieval-variant structured \
  --retrieval-profile repair_clean \
  --model gpt-4o \
  --prompt-mode tests \
  --results-path experiments/humanevalfix_structured_gpt4o.json
```

PyBugHive evaluation requires cloned project repositories, `pipenv`, and
project-specific dependency setup. See:

```text
docs/PYBUGHIVE_EVAL_WORKFLOW.md
```

## Tests

Run the lightweight unit tests:

```bash
.venv312/bin/python -m pytest -q \
  test_patch_utils.py \
  test_heldout_repair_corpus.py \
  test_humanevalfix_eval.py
```

Some older integration tests call the OpenAI API or expect local benchmark
indexes, so they are not suitable as default CI tests without environment setup.

## Repository Hygiene

Do not commit:

- `.env`
- virtual environments
- FAISS indexes
- cloned benchmark repositories
- PyBugHive temp worktrees
- raw traces with full prompts/generated code
- large JSONL corpora unless intentionally versioned

The `.gitignore` is configured to keep source code, docs, and markdown result
summaries while excluding heavy or sensitive generated artifacts.

If files are already tracked in Git, `.gitignore` will not remove them. Use
`git rm --cached <path>` after reviewing what should remain public.

## Paper Positioning

Recommended title:

> Better Retrieval, Same Repair: Why Relevance Gains Don't Convert in LLM Program Repair

(Alternative, if foregrounding the oracle ceiling + RAGFix correction:
"The Retrieval Ceiling in LLM Program Repair: Relevance, Exploitation, and a
Re-evaluation of Prior Gains".) "Structured Failure-Aware Retrieval" remains the
name of the *method* inside the paper, not the title's promise.

Recommended framing (a critical empirical study, not a "method wins" paper):

> Structured failure-aware reranking significantly improves retrieval relevance, but
> relevance does not convert to repair success — structured retrieval is statistically
> neutral downstream across models, corpora, and benchmarks. An oracle analysis shows
> a relevant example *can* significantly help a knowledge-gap model, so the open
> problem is fix-aware retrieval, not example exploitation. We also de-confound a
> published positive claim (RAGFix).

Honest scope: all executable results are on algorithmic / synthetic-mutation
benchmarks (QuixBugs, HumanEvalFix, MBPP); realistic natural-bug executable repair and
a blind human relevance audit remain future work.

This repository is research code. It is designed for traceable experiments,
not as a production repair service.
