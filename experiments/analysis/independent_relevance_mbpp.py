"""Independent (vocabulary-free) relevance metric on MBPP-holdout.

Second-benchmark corroboration of B.1 (which was QuixBugs n=40 only). Same metric as
independent_relevance.py: relevance = cosine(embed(candidate fix-diff), embed(GT
fix-diff)). Retrieval only (no LLM). Test = mbpp_holdout_test (187), corpus =
mbpp_holdout.

Run: .venv312/bin/python experiments/analysis/independent_relevance_mbpp.py
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
from statistics import mean
import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.models.repair_rag import retrieve_examples
from src.eval.evaluate_mbpp_repair import build_failure_signal
from src.retrieval.repair_metadata import changed_regions
from src.retrieval.index_store import embed_text

VARIANTS = ["code_only", "raw_text", "raw_text_rerank", "structured"]
TOP_KS = [1, 2, 5]


def fix_diff(buggy, fixed):
    b, f = changed_regions(buggy or "", fixed or "")
    return (b + "\n=>\n" + f).strip() or (fixed or "")


def cos(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(np.dot(a, b) / (na * nb)) if na and nb else 0.0


def main():
    tests = [json.loads(l) for l in open("data/mbpp/mbpp_holdout_test.jsonl")]
    agg = {v: {k: [] for k in TOP_KS} for v in VARIANTS}
    per = []
    for t in tests:
        gt = embed_text(fix_diff(t["buggy_code"], t["fixed_code"]))
        sig = build_failure_signal(t)
        row = {"id": t["id"]}
        for v in VARIANTS:
            exs = retrieve_examples(t["buggy_code"], failure_signal=sig, k=max(TOP_KS),
                                    retrieval_profile="mbpp_holdout", retrieval_variant=v)
            sims = [cos(embed_text(fix_diff(e.get("buggy_code", ""), e.get("fixed_code", ""))), gt) for e in exs]
            for k in TOP_KS:
                val = mean(sims[:k]) if sims[:k] else 0.0
                agg[v][k].append(val); row[f"{v}_top{k}"] = val
        per.append(row)

    print(f"=== Independent fix-diff relevance, MBPP-holdout n={len(tests)} ===")
    print(f"{'variant':18}{'top1':>8}{'top2':>8}{'top5':>8}")
    out = {"benchmark": "mbpp_holdout", "n": len(tests), "variants": {}, "per_problem": per}
    for v in VARIANTS:
        r = {f"top{k}": mean(agg[v][k]) for k in TOP_KS}
        out["variants"][v] = r
        print(f"{v:18}{r['top1']:>8.3f}{r['top2']:>8.3f}{r['top5']:>8.3f}")

    # paired significance structured vs code_only top5
    import random
    diff = [r["structured_top5"] - r["code_only_top5"] for r in per]
    n = len(diff); md = sum(diff) / n
    rng = random.Random(0); boot = sorted(sum(diff[rng.randrange(n)] for _ in range(n)) / n for _ in range(10000))
    lo, hi = boot[250], boot[9750]
    wins = sum(1 for x in diff if x > 0); losses = sum(1 for x in diff if x < 0)
    try:
        from scipy.stats import wilcoxon
        s = [r["structured_top5"] for r in per]; c = [r["code_only_top5"] for r in per]
        _, p = wilcoxon(s, c); wil = f"Wilcoxon p={p:.4g}"
    except Exception as e:
        wil = f"(scipy: {e})"
    print(f"\nstructured vs code_only top5: mean diff {md:+.4f}, 95% CI [{lo:+.4f},{hi:+.4f}], "
          f"higher {wins}/{n}, lower {losses}; {wil}")
    json.dump(out, open("experiments/independent_relevance_mbpp.json", "w"), indent=2)
    print("saved -> experiments/independent_relevance_mbpp.json")


if __name__ == "__main__":
    main()
