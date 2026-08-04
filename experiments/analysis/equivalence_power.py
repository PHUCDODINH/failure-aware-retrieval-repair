"""Equivalence (TOST) and power / minimum-detectable-effect for the null comparisons.

Non-significance != no effect. For each paired comparison we report:
  - paired difference of pass-rates d = (c - b)/n  (structured - baseline), in pp
  - 90% CI (TOST uses the 90% CI for two one-sided tests at alpha=0.05)
  - equivalence verdict at margins delta = 5pp and 10pp (CI inside [-delta, +delta]?)
  - MDE: minimum detectable difference at 80% power, alpha=0.05, given the observed
    discordant count m=b+c (normal approx: |c-b| detectable > 2.80*sqrt(m)).

b = first-pass & second-fail, c = first-fail & second-pass (second = the 'treatment').

Run: .venv312/bin/python experiments/analysis/equivalence_power.py
"""
import json, os
from math import sqrt

EXP = os.path.join(os.path.dirname(__file__), "..")
Z_A = 1.96   # alpha/2 = 0.025
Z_B = 0.84   # power 0.80
TOST_Z = 1.645  # 90% CI


def load(name):
    p = os.path.join(EXP, name + ".json")
    if not os.path.exists(p):
        return None
    return {(r.get("task_id") or r.get("id") or r.get("problem")): bool(r.get("pass"))
            for r in json.load(open(p))}


def analyze(a, b):
    ids = set(a) & set(b)
    n = len(ids)
    bb = sum(1 for i in ids if a[i] and not b[i])   # base pass, treat fail
    cc = sum(1 for i in ids if not a[i] and b[i])    # base fail, treat pass
    d = (cc - bb) / n                                  # treat - base, in proportion
    m = bb + cc
    # Wald variance for paired difference of proportions
    var = (m - (cc - bb) ** 2 / n) / n ** 2 if n else 0
    se = sqrt(max(var, 0))
    ci90 = (d - TOST_Z * se, d + TOST_Z * se)
    # MDE (proportion) at 80% power given observed discordant count m
    mde = (Z_A + Z_B) * sqrt(m) / n if n else float("nan")
    return n, bb, cc, d, ci90, mde


COMPARISONS = [  # (label, baseline_file, treatment_file)
    ("HEF gpt-4o      base->structured", "humanevalfix_baseline_gpt4o_full_v1", "humanevalfix_structured_gpt4o_full_v1"),
    ("HEF gpt-4.1     base->structured", "humanevalfix_baseline_gpt41_full_v1", "humanevalfix_structured_gpt41_full_v1"),
    ("HEF gpt-4o-mini base->structured", "humanevalfix_baseline_gpt4omini_full_v1", "humanevalfix_structured_gpt4omini_full_v1"),
    ("HEF llama70b    base->structured", "humanevalfix_baseline_llama3_70b_v1", "humanevalfix_structured_llama3_70b_v1"),
    ("MBPP llama8b    base->structured", "mbpp_repair_baseline_llama8b_v1", "mbpp_repair_structured_llama8b_v1"),
    ("MBPP llama8b    base->code_only", "mbpp_repair_baseline_llama8b_v1", "mbpp_repair_code_only_llama8b_v1"),
    ("MBPP gpt4omini  base->structured", "mbpp_repair_baseline_gpt4omini_v1", "mbpp_repair_structured_gpt4omini_v1"),
    ("MBPP llama8b    base->ORACLE_corpus", "mbpp_repair_baseline_llama8b_v1", "mbpp_repair_oracle_corpus_llama8b_v1"),
]


def main():
    print(f"{'comparison':38}{'n':>4}{'d(pp)':>7}{'90% CI (pp)':>18}{'eq5':>5}{'eq10':>6}{'MDE(pp)':>9}")
    rows = []
    for label, fa, fb in COMPARISONS:
        a, b = load(fa), load(fb)
        if a is None or b is None:
            print(f"{label:38}  (missing)")
            continue
        n, bb, cc, d, ci90, mde = analyze(a, b)
        eq5 = "YES" if ci90[0] > -0.05 and ci90[1] < 0.05 else "no"
        eq10 = "YES" if ci90[0] > -0.10 and ci90[1] < 0.10 else "no"
        print(f"{label:38}{n:>4}{100*d:>7.1f}  [{100*ci90[0]:>6.1f},{100*ci90[1]:>6.1f}]{eq5:>5}{eq10:>6}{100*mde:>9.1f}")
        rows.append({"comparison": label, "n": n, "b": bb, "c": cc, "diff_pp": 100*d,
                     "ci90_pp": [100*ci90[0], 100*ci90[1]], "equiv_5pp": eq5, "equiv_10pp": eq10, "mde_pp": 100*mde})
    json.dump(rows, open(os.path.join(EXP, "equivalence_power.json"), "w"), indent=2)
    print("\nNotes: d = treatment - baseline (negative = treatment worse).")
    print("eqX = TOST equivalence at +-X pp (90% CI within margin). MDE = min detectable diff @80% power.")
    print("saved -> experiments/equivalence_power.json")


if __name__ == "__main__":
    main()
