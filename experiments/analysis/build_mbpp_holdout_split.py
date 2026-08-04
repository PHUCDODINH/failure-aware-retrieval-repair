"""Build the contamination-safe MBPP held-out repair split.

Splits the 374 MBPP problems (from data/mbpp/mbpp_bugfix.jsonl, 1041 buggy
variants) 50/50 by problem number (seed=42). Test = one buggy variant per test
problem (preferring harder logic-bug types); corpus = all variants of the
disjoint corpus problems. Verified: 0 problem overlap between test and corpus.

Outputs:
  data/mbpp/mbpp_holdout_test.jsonl       (187 test instances)
  data/corpora/mbpp_holdout_corpus.jsonl  (508 corpus pairs)

Then build the index:
  python src/retrieval/build_index.py --input-path data/corpora/mbpp_holdout_corpus.jsonl --profile mbpp_holdout

Run: .venv312/bin/python experiments/analysis/build_mbpp_holdout_split.py
"""
import collections, json, os, random, re

SRC = "data/mbpp/mbpp_bugfix.jsonl"
PREF = ["mutate_operator", "mutate_off_by_one", "mutate_return", "mutate_variable"]


def pnum(r):
    return re.match(r"(\d+)", r["id"]).group(1)


def main():
    rows = [json.loads(l) for l in open(SRC)]
    by_prob = collections.defaultdict(list)
    for r in rows:
        by_prob[pnum(r)].append(r)
    problems = sorted(by_prob)
    random.seed(42)
    random.shuffle(problems)
    half = len(problems) // 2
    test_probs, corpus_probs = set(problems[:half]), set(problems[half:])

    corpus = [r for p in corpus_probs for r in by_prob[p]]
    test = []
    for p in sorted(test_probs):
        v = sorted(by_prob[p], key=lambda r: PREF.index(r["bug_type"]) if r["bug_type"] in PREF else 99)
        test.append(v[0])

    os.makedirs("data/corpora", exist_ok=True)
    with open("data/corpora/mbpp_holdout_corpus.jsonl", "w") as f:
        for r in corpus:
            f.write(json.dumps(r) + "\n")
    with open("data/mbpp/mbpp_holdout_test.jsonl", "w") as f:
        for r in test:
            f.write(json.dumps(r) + "\n")

    overlap = {pnum(r) for r in test} & {pnum(r) for r in corpus}
    print(f"test instances: {len(test)} | corpus pairs: {len(corpus)} | contamination: {len(overlap)}")
    print("test bug_type dist:", dict(collections.Counter(r["bug_type"] for r in test)))


if __name__ == "__main__":
    main()
