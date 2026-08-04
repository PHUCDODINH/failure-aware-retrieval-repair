"""Paired significance tests (exact two-sided McNemar) across all result files.

For each pair of conditions evaluated on the SAME task set, counts discordant pairs
and computes the exact binomial p-value on them. Run: no API calls.

  .venv312/bin/python experiments/analysis/significance_tests.py
"""
import json, os
from math import comb

EXP = os.path.join(os.path.dirname(__file__), "..")


def load(name):
    p = os.path.join(EXP, name + ".json")
    if not os.path.exists(p):
        return None
    out = {}
    for r in json.load(open(p)):
        tid = r.get("task_id") or r.get("id") or r.get("problem")
        out[tid] = bool(r.get("pass"))
    return out


def mcnemar(a, b):
    ids = set(a) & set(b)
    bb = sum(1 for i in ids if a[i] and not b[i])
    cc = sum(1 for i in ids if not a[i] and b[i])
    n = bb + cc
    if n == 0:
        return bb, cc, 1.0, len(ids)
    k = min(bb, cc)
    p = min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / (2 ** n))
    return bb, cc, p, len(ids)


# (label, file_a, file_b)
COMPARISONS = [
    ("HEF gpt-4o      base vs structured", "humanevalfix_baseline_gpt4o_full_v1", "humanevalfix_structured_gpt4o_full_v1"),
    ("HEF gpt-4.1     base vs structured", "humanevalfix_baseline_gpt41_full_v1", "humanevalfix_structured_gpt41_full_v1"),
    ("HEF gpt-4o-mini base vs structured", "humanevalfix_baseline_gpt4omini_full_v1", "humanevalfix_structured_gpt4omini_full_v1"),
    ("HEF llama70b    base vs structured", "humanevalfix_baseline_llama3_70b_v1", "humanevalfix_structured_llama3_70b_v1"),
    ("HEF llama70b    base vs code_only", "humanevalfix_baseline_llama3_70b_v1", "humanevalfix_code_only_llama3_70b_v1"),
    ("HEF llama70b    code_only vs structured", "humanevalfix_code_only_llama3_70b_v1", "humanevalfix_structured_llama3_70b_v1"),
    ("Corpus gpt-4o   base vs struct/MBPP", "humanevalfix_baseline_gpt4o_full_v1", "humanevalfix_structured_mbpp_gpt4o_v1"),
    ("Corpus gpt-4o   struct/BugsInPy vs struct/MBPP", "humanevalfix_structured_gpt4o_full_v1", "humanevalfix_structured_mbpp_gpt4o_v1"),
    ("Corpus 70b      struct/BugsInPy vs struct/MBPP", "humanevalfix_structured_llama3_70b_v1", "humanevalfix_structured_mbpp_llama70b_v1"),
    ("MBPP gpt4omini  base vs structured", "mbpp_repair_baseline_gpt4omini_v1", "mbpp_repair_structured_gpt4omini_v1"),
    ("MBPP llama8b    base vs code_only", "mbpp_repair_baseline_llama8b_v1", "mbpp_repair_code_only_llama8b_v1"),
    ("MBPP llama8b    base vs structured", "mbpp_repair_baseline_llama8b_v1", "mbpp_repair_structured_llama8b_v1"),
    ("MBPP llama8b    base vs ORACLE_corpus", "mbpp_repair_baseline_llama8b_v1", "mbpp_repair_oracle_corpus_llama8b_v1"),
    ("MBPP llama8b    base vs ORACLE_self", "mbpp_repair_baseline_llama8b_v1", "mbpp_repair_oracle_self_llama8b_v1"),
]


def main():
    print(f"{'comparison':52}{'n':>5}{'b':>4}{'c':>4}{'p':>9}  sig")
    rows = []
    for label, fa, fb in COMPARISONS:
        a, b = load(fa), load(fb)
        if a is None or b is None:
            print(f"{label:52}  (missing file)")
            continue
        bb, cc, p, n = mcnemar(a, b)
        sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"
        print(f"{label:52}{n:>5}{bb:>4}{cc:>4}{p:>9.4f}  {sig}")
        rows.append({"comparison": label, "n": n, "b": bb, "c": cc, "p": p, "sig": sig})
    json.dump(rows, open(os.path.join(EXP, "significance_mcnemar.json"), "w"), indent=2)
    print("\nsaved -> experiments/significance_mcnemar.json")


if __name__ == "__main__":
    main()
