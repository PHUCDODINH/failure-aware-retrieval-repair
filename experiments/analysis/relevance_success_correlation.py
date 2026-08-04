"""Instance-level relevance<->success analysis.

For structured-RAG traces, compute each task's best-selected-example failure
relevance (sum of the failure-aware rerank components) and bucket tasks by the
baseline-vs-structured outcome (rag_win / rag_loss / both_pass / both_fail).

Tests whether higher retrieval relevance predicts whether retrieval flips a task
to success. Finding: it does not (win-relevance ~= loss-relevance), i.e. relevance
is not the binding constraint for repair success.

Run: .venv312/bin/python experiments/analysis/relevance_success_correlation.py
"""
import glob, json, os
from statistics import mean

ROOT = os.path.join(os.path.dirname(__file__), "..")
REL_COMPONENTS = ["contract_tag_overlap", "symbol_overlap", "exception_compat", "failure_mode_compat"]


def best_relevance(trace):
    rd = trace.get("retrieval_debug") or {}
    pool = {c["id"]: c for c in (rd.get("candidate_pool") or [])}
    sel = [s for s in (rd.get("selected_example_ids") or []) if s in pool]
    if not sel:
        return None
    return max(sum(float((pool[s].get("components") or {}).get(k, 0) or 0) for k in REL_COMPONENTS) for s in sel)


def analyze(name, structured_trace_glob, baseline_results_json=None, baseline_trace_glob=None):
    S = {}
    for f in glob.glob(os.path.join(ROOT, structured_trace_glob)):
        t = json.load(open(f)); S[t.get("task_id") or t.get("id")] = t
    if baseline_results_json:
        base = {r.get("task_id") or r.get("id"): r["pass"] for r in json.load(open(os.path.join(ROOT, baseline_results_json)))}
    else:
        base = {}
        for f in glob.glob(os.path.join(ROOT, baseline_trace_glob)):
            t = json.load(open(f)); base[t.get("task_id") or t.get("id")] = t["pass"]
    buckets = {"rag_win": [], "rag_loss": [], "both_pass": [], "both_fail": []}
    for tid, t in S.items():
        if tid not in base:
            continue
        rel = best_relevance(t)
        if rel is None:
            continue
        sp, bp = bool(t["pass"]), bool(base[tid])
        k = "both_pass" if bp and sp else "rag_win" if sp and not bp else "rag_loss" if bp and not sp else "both_fail"
        buckets[k].append(rel)
    print(f"=== {name} (n={sum(len(v) for v in buckets.values())}) ===")
    for k in ["rag_win", "rag_loss", "both_pass", "both_fail"]:
        v = buckets[k]
        print(f"  {k:9}: n={len(v):3}" + (f"  mean_rel={mean(v):.3f}" if v else ""))


if __name__ == "__main__":
    # HumanEvalFix (BugsInPy corpus)
    for m in ["gpt4o", "gpt41", "gpt4omini"]:
        analyze(f"HumanEvalFix {m}",
                f"traces/humanevalfix_structured_{m}_full_v1/*.json",
                baseline_trace_glob=f"traces/humanevalfix_baseline_{m}_full_v1/*.json")
    # MBPP repair (holdout corpus); baselines have no traces -> use results json
    for m in ["llama8b", "gpt4omini"]:
        analyze(f"MBPP-repair {m}",
                f"traces/mbpp_repair_structured_{m}_v1/*.json",
                baseline_results_json=f"mbpp_repair_baseline_{m}_v1.json")
