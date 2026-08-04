"""Oracle / ceiling experiment for retrieval-augmented MBPP repair.

Bounds what retrieval *could* achieve, decoupled from the reranker:

  oracle_corpus : force the top-k corpus examples whose fix-diff is most similar
                  (cosine) to the target's ground-truth fix-diff. Best a retriever
                  could do from the (disjoint) held-out corpus.
  oracle_self   : force the target's OWN buggy->fixed pair as the example. Absolute
                  upper bound: the model is shown the exact fix pattern it needs.

Interpretation:
  - oracle_corpus ~= baseline  -> retrieval fundamentally can't help here (the
                                  non-conversion is intrinsic, not a reranker miss).
  - oracle_corpus >> baseline  -> a ceiling exists; the reranker is the bottleneck.
  - oracle_self gauges the model's raw ability to exploit a perfect example.

Run (Llama-3-8B via Together):
  env OPENAI_API_KEY=$TOGETHER_API_KEY OPENAI_BASE_URL=https://api.together.xyz/v1 \\
      .venv312/bin/python experiments/analysis/oracle_ceiling_mbpp.py \\
      --mode oracle_corpus --model meta-llama/Meta-Llama-3-8B-Instruct-Lite --tag llama8b
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.models.repair_rag import build_repair_prompt_with_strategy, safe_chat_completion, _strip_code_fences, DEFAULT_MODEL, _estimate_completion_tokens
from src.eval.evaluate_mbpp_repair import extract_code, run_candidate, build_failure_signal, load_existing_results, save_results
from src.retrieval.repair_metadata import changed_regions
from src.retrieval.index_store import embed_text

TEST = "data/mbpp/mbpp_holdout_test.jsonl"
CORPUS = "data/corpora/mbpp_holdout_corpus.jsonl"
K = 2


def fix_diff(buggy, fixed):
    b, f = changed_regions(buggy or "", fixed or "")
    return (b + "\n=>\n" + f).strip() or (fixed or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["oracle_corpus", "oracle_self"], required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    tests = [json.loads(l) for l in open(TEST)]
    corpus = [json.loads(l) for l in open(CORPUS)]
    if args.limit:
        tests = tests[: args.limit]

    corpus_emb = None
    if args.mode == "oracle_corpus":
        print(f"embedding {len(corpus)} corpus fix-diffs...")
        corpus_emb = np.array([embed_text(fix_diff(c.get("buggy_code", ""), c.get("fixed_code", ""))) for c in corpus])
        corpus_emb /= (np.linalg.norm(corpus_emb, axis=1, keepdims=True) + 1e-9)

    out_path = f"experiments/mbpp_repair_{args.mode}_{args.tag}_v1.json"
    results = load_existing_results(out_path)
    done = {r["id"] for r in results}

    for task in tests:
        if task["id"] in done:
            continue
        buggy, fixed = task["buggy_code"], task["fixed_code"]
        if args.mode == "oracle_self":
            examples = [{"buggy_code": buggy, "fixed_code": fixed}]
        else:
            q = embed_text(fix_diff(buggy, fixed)); q /= (np.linalg.norm(q) + 1e-9)
            sims = corpus_emb @ q
            top = np.argsort(-sims)[:K]
            examples = [corpus[i] for i in top]
        desc = build_failure_signal(task)
        prompt = build_repair_prompt_with_strategy(
            buggy_code=buggy,
            description=f"Description (optional): {desc}\n\n",
            examples=examples, strategy_note="",
        )
        resp = safe_chat_completion(model=args.model or DEFAULT_MODEL,
                                    messages=[{"role": "user", "content": prompt}],
                                    temperature=0, max_completion_tokens=_estimate_completion_tokens(buggy))
        code = extract_code(_strip_code_fences(resp.choices[0].message.content))
        passed, _ = run_candidate(code, task["tests"])
        results.append({"id": task["id"], "mode": args.mode, "pass": passed, "bug_type": task.get("bug_type")})
        done.add(task["id"])
        save_results(out_path, results)
        print(f"{task['id']}: {'PASS' if passed else 'FAIL'}")

    pa = sum(1 for r in results if r.get("pass"))
    print(json.dumps({"out": out_path, "passed": pa, "total": len(results)}, indent=2))


if __name__ == "__main__":
    main()
