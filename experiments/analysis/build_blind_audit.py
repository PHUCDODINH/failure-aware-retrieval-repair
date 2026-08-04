"""Generate a BLIND manual relevance-audit worksheet.

For each sampled problem, retrieve the top-1 example from each variant, then present
the four candidates anonymized as A/B/C/D (shuffled per problem) so the annotator
cannot tell which variant produced which. A hidden key maps labels back to variants.

Outputs:
  experiments/manual_audit_blind_worksheet.json  -> annotators fill "relevant": 0/1
  experiments/manual_audit_key.json              -> hidden label->variant mapping

Annotation criterion (put in the worksheet): mark 1 if the candidate's repair
pattern (buggy->fixed change) would plausibly guide fixing the TARGET bug, else 0.

Retrieval only (no LLM). QuixBugs by default; add PyBugHive cases via --pybughive-path.

Run: .venv312/bin/python experiments/analysis/build_blind_audit.py --n-quixbugs 20 --seed 7
"""
from __future__ import annotations
import argparse, json, os, random, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.eval.evaluate_quixbugs import autodetect_problems, find_test_file, select_buggy_source
from src.eval.eval_retrieval_relevance import load_counterpart_code
from src.models.repair_rag import retrieve_examples, _focused_diff_snippet

VARIANTS = ["code_only", "raw_text", "raw_text_rerank", "structured"]
LABELS = ["A", "B", "C", "D"]


def top1_snippet(buggy, failure_signal, variant, profile):
    exs = retrieve_examples(buggy, failure_signal=failure_signal, k=1,
                            retrieval_profile=profile, retrieval_variant=variant)
    if not exs:
        return {"candidate_id": "", "buggy_snippet": "", "fixed_snippet": ""}
    ex = exs[0]
    b, f = _focused_diff_snippet(ex.get("buggy_code", ""), ex.get("fixed_code", ex.get("correct_code", "")))
    return {"candidate_id": ex.get("id", ""), "buggy_snippet": b, "fixed_snippet": f}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrieval-profile", default="repair_clean")
    ap.add_argument("--n-quixbugs", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--worksheet", default="experiments/manual_audit_blind_worksheet.json")
    ap.add_argument("--key", default="experiments/manual_audit_key.json")
    args = ap.parse_args()
    rng = random.Random(args.seed)

    problems = autodetect_problems()[: args.n_quixbugs]
    worksheet, key = [], []
    for problem in problems:
        tf = find_test_file(problem)
        if tf is None:
            continue
        try:
            src = select_buggy_source(problem, tf)
        except Exception:
            continue
        buggy = src["code"]
        tb, _ = _focused_diff_snippet(buggy, load_counterpart_code(problem, src["label"]) or buggy)
        cands = {v: top1_snippet(buggy, src["failure_signal"], v, args.retrieval_profile) for v in VARIANTS}

        order = VARIANTS[:]
        rng.shuffle(order)
        label_map = dict(zip(LABELS, order))  # label -> variant
        entry = {
            "problem": problem,
            "benchmark": "quixbugs",
            "target_buggy_snippet": tb,
            "target_failure_signal": (src["failure_signal"] or "")[:600],
            "candidates": {
                lbl: {
                    "buggy_snippet": cands[label_map[lbl]]["buggy_snippet"],
                    "fixed_snippet": cands[label_map[lbl]]["fixed_snippet"],
                    "relevant": None,  # ANNOTATOR FILLS: 1 (fix-relevant) or 0 (not)
                }
                for lbl in LABELS
            },
        }
        worksheet.append(entry)
        key.append({"problem": problem, "label_to_variant": label_map,
                    "candidate_ids": {lbl: cands[label_map[lbl]]["candidate_id"] for lbl in LABELS}})
        print(f"  {problem}: labels shuffled")

    os.makedirs("experiments", exist_ok=True)
    header = {
        "_instructions": "For each problem, mark candidates[X]['relevant'] = 1 if that "
                         "candidate's buggy->fixed change would plausibly guide fixing the "
                         "target bug, else 0. Do NOT open the key file. Two annotators should "
                         "fill independent copies (worksheet_ann1.json, worksheet_ann2.json).",
        "tasks": worksheet,
    }
    json.dump(header, open(args.worksheet, "w"), indent=2)
    json.dump(key, open(args.key, "w"), indent=2)
    print(f"\nWorksheet ({len(worksheet)} tasks) -> {args.worksheet}")
    print(f"Hidden key -> {args.key}")


if __name__ == "__main__":
    main()
