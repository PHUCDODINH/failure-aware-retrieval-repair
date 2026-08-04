"""Recompute pass@1 from RAGFix's released per-example CSVs.

A row counts as a pass iff its `exception_type` is empty (the code executed
against the HumanEvalFix tests without raising). Validation: recomputed baselines
match RAGFix's reported figures (70B 72.6% vs 72.5%; 8B 41.5% vs 41.4%).

Inputs: experiments/ragfix_released_outputs/*.csv (copied from RAGFix GitHub,
RAG Results/LLAMA3/{70B,8B}/).

Run: .venv312/bin/python experiments/analysis/ragfix_recompute.py
"""
import csv, os
from collections import Counter

csv.field_size_limit(10**8)
DIR = os.path.join(os.path.dirname(__file__), "..", "ragfix_released_outputs")

FILES = [
    ("70B baseline (no-db-7-15)", "70B_llama3-70b-no-db-7-15.csv"),
    ("70B RAG no-postproc (vdb-7-15)", "70B_llama3-70b-vdb-7-15.csv"),
    ("70B RAG +import-postproc (vdb-7-16, reported)", "70B_llama3-70b-vdb-7-16.csv"),
    ("8B baseline (no-db-7-11)", "8B_llama3-8b-no-db-7-11.csv"),
    ("8B RAG (vdb-7-12)", "8B_llama3-8b-vdb-7-12.csv"),
]


def analyze(path):
    rows = list(csv.DictReader(open(path, newline="")))
    def is_pass(r):
        ex = (r.get("exception_type") or "").strip()
        return ex == "" or ex.lower() in ("none", "nan")
    passed = sum(1 for r in rows if is_pass(r))
    exc = Counter((r.get("exception_type") or "").strip() for r in rows if not is_pass(r))
    retries = [int(float(r["num_retries"])) for r in rows if (r.get("num_retries") or "").strip().replace(".", "").isdigit()]
    return len(rows), passed, max(retries) if retries else 0, exc


if __name__ == "__main__":
    print(f"{'run':46} {'n':>4} {'pass':>5} {'rate':>7} {'maxretry':>8}  top_exc")
    for label, fn in FILES:
        p = os.path.join(DIR, fn)
        if not os.path.exists(p):
            print(f"{label:46} MISSING"); continue
        n, passed, mr, exc = analyze(p)
        top = "; ".join((k or "(blank)") + ":" + str(v) for k, v in exc.most_common(3))
        print(f"{label:46} {n:>4} {passed:>5} {100*passed/n:6.1f}% {mr:>8}  {top}")
