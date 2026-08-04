"""Unblind and score the manual relevance audit.

Takes one or two filled worksheets (annotators fill candidates[X]['relevant']=0/1)
plus the hidden key, maps A/B/C/D back to variants, and reports per-variant human
relevance rate. With two annotators, also reports Cohen's kappa inter-rater
agreement and scores on the agreed subset.

Run:
  .venv312/bin/python experiments/analysis/score_blind_audit.py \\
    --worksheets experiments/worksheet_ann1.json experiments/worksheet_ann2.json \\
    --key experiments/manual_audit_key.json
"""
from __future__ import annotations
import argparse, json
from collections import defaultdict

VARIANTS = ["code_only", "raw_text", "raw_text_rerank", "structured"]
LABELS = ["A", "B", "C", "D"]


def load_tasks(path):
    d = json.load(open(path))
    return d["tasks"] if isinstance(d, dict) and "tasks" in d else d


def cohens_kappa(pairs):
    # pairs: list of (a,b) binary judgments
    n = len(pairs)
    if n == 0:
        return float("nan")
    po = sum(1 for a, b in pairs if a == b) / n
    pa1 = sum(1 for a, _ in pairs if a == 1) / n
    pb1 = sum(1 for _, b in pairs if b == 1) / n
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    return (po - pe) / (1 - pe) if pe != 1 else 1.0


def collect(tasks, key):
    keymap = {k["problem"]: k["label_to_variant"] for k in key}
    out = defaultdict(dict)  # problem -> variant -> relevant
    for t in tasks:
        lm = keymap.get(t["problem"])
        if not lm:
            continue
        for lbl in LABELS:
            v = lm.get(lbl)
            rel = t["candidates"][lbl].get("relevant")
            if v is not None and rel is not None:
                out[t["problem"]][v] = int(rel)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--worksheets", nargs="+", required=True)
    ap.add_argument("--key", required=True)
    args = ap.parse_args()
    key = json.load(open(args.key))
    anns = [collect(load_tasks(w), key) for w in args.worksheets]

    # per-variant rate per annotator
    print("=== per-variant human relevance rate ===")
    for i, ann in enumerate(anns):
        print(f"  annotator {i+1}:")
        for v in VARIANTS:
            vals = [ann[p][v] for p in ann if v in ann[p]]
            if vals:
                print(f"    {v:<16} {sum(vals)}/{len(vals)} = {100*sum(vals)/len(vals):.1f}%")

    if len(anns) == 2:
        pairs = []
        for p in anns[0]:
            for v in VARIANTS:
                if v in anns[0].get(p, {}) and v in anns[1].get(p, {}):
                    pairs.append((anns[0][p][v], anns[1][p][v]))
        print(f"\n=== inter-rater agreement (n={len(pairs)} judgments) ===")
        print(f"  raw agreement: {100*sum(1 for a,b in pairs if a==b)/len(pairs):.1f}%")
        print(f"  Cohen's kappa: {cohens_kappa(pairs):.3f}")
        # agreed-subset per-variant rate
        print("\n=== per-variant rate on AGREED judgments ===")
        for v in VARIANTS:
            agreed = [anns[0][p][v] for p in anns[0]
                      if v in anns[0].get(p, {}) and v in anns[1].get(p, {}) and anns[0][p][v] == anns[1][p][v]]
            if agreed:
                print(f"  {v:<16} {sum(agreed)}/{len(agreed)} = {100*sum(agreed)/len(agreed):.1f}%")


if __name__ == "__main__":
    main()
