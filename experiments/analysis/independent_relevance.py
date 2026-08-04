"""Independent (vocabulary-free) retrieval-relevance metric.

The tag-compat metric in eval_retrieval_relevance.py shares its tag vocabulary and
inference function with the structured reranker's objective, so a structured win
there is partly circular. This script provides an INDEPENDENT relevance measure:

  relevance(candidate, target) = cosine( embed(candidate fix-diff),
                                          embed(ground-truth fix-diff) )

where a "fix-diff" is the changed-region text (buggy -> fixed) from difflib. No
variant optimizes for fix-diff embedding similarity, so this is independent of all
reranker objectives. If structured still beats code_only here, the relevance gain
is not a metric artifact.

Retrieval only (no LLM calls). QuixBugs by default.

Run: .venv312/bin/python experiments/analysis/independent_relevance.py --retrieval-profile repair_clean
"""
from __future__ import annotations
import argparse, os, sys
from pathlib import Path
from statistics import mean
import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.eval.evaluate_quixbugs import autodetect_problems, find_test_file, select_buggy_source
from src.eval.eval_retrieval_relevance import load_counterpart_code
from src.models.repair_rag import retrieve_examples
from src.retrieval.repair_metadata import changed_regions
from src.retrieval.index_store import embed_text

VARIANTS = ["code_only", "raw_text", "raw_text_rerank", "structured"]
TOP_KS = [1, 2, 5]


def fix_diff_text(buggy: str, fixed: str) -> str:
    b, f = changed_regions(buggy or "", fixed or "")
    return (b + "\n=>\n" + f).strip() or (fixed or "")


def cos(a, b) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrieval-profile", default="repair_clean")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default="experiments/independent_relevance_quixbugs.json")
    args = ap.parse_args()

    problems = autodetect_problems()
    if args.limit:
        problems = problems[: args.limit]

    # per-variant: list of top-k mean cosine sims (one per problem)
    agg = {v: {k: [] for k in TOP_KS} for v in VARIANTS}
    per_problem = []
    n = 0
    for problem in problems:
        tf = find_test_file(problem)
        if tf is None:
            continue
        try:
            src = select_buggy_source(problem, tf)
        except Exception:
            continue
        correct = load_counterpart_code(problem, src["label"])
        if correct is None:
            continue
        buggy = src["code"]
        gt_emb = embed_text(fix_diff_text(buggy, correct))
        n += 1
        prow = {"problem": problem}
        for v in VARIANTS:
            exs = retrieve_examples(buggy, failure_signal=src["failure_signal"], k=max(TOP_KS),
                                    retrieval_profile=args.retrieval_profile, retrieval_variant=v)
            sims = []
            for ex in exs:
                ce = embed_text(fix_diff_text(ex.get("buggy_code", ""),
                                              ex.get("fixed_code", ex.get("correct_code", ""))))
                sims.append(cos(ce, gt_emb))
            for k in TOP_KS:
                val = mean(sims[:k]) if sims[:k] else 0.0
                agg[v][k].append(val)
                prow[f"{v}_top{k}"] = val
        per_problem.append(prow)
        print(f"  {problem} done")

    print(f"\n=== Independent fix-diff relevance (cosine to GT fix-diff), QuixBugs n={n} ===")
    print(f"{'variant':<18}{'top1':>8}{'top2':>8}{'top5':>8}")
    summary = {"benchmark": "quixbugs", "n": n, "metric": "cosine_fixdiff_to_gt", "variants": {}}
    for v in VARIANTS:
        row = {f"top{k}": (mean(agg[v][k]) if agg[v][k] else 0.0) for k in TOP_KS}
        summary["variants"][v] = row
        print(f"{v:<18}{row['top1']:>8.3f}{row['top2']:>8.3f}{row['top5']:>8.3f}")

    summary["per_problem"] = per_problem
    import json
    with open(args.out, "w") as fh:
        json.dump(summary, fh, indent=2)
    print(f"\nSaved to {args.out}")


if __name__ == "__main__":
    main()
