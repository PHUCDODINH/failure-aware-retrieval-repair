"""Build a planted PyBugHive retrieval corpus + FAISS index (reproducible).

For each supported PyBugHive case, extract the exact buggy->fixed single-file pair
(`git show <commit>:<path>` at the buggy/fixed commits) and emit it as a PLANT row.
Merge with the 551-row BugsInPy filler corpus, then optionally build a FAISS index.

This replaces the ad-hoc /tmp build used for the original `pybh_black_planted`
index (B.5) with a committed, re-runnable script. Plant rows follow the same
schema as that experiment: id=PLANT_<repository>-<issue_id>, source=pybughive_planted.

Examples:
  # plants for every supported project, merged with filler, indexed:
  python src/datasets/build_pybughive_planted.py \
    --filler data/ci/bugsinpy_filler_551.jsonl.gz \
    --output data/corpora/pybh_all_planted_corpus.jsonl \
    --index-dir data/indexes/pybh_all_planted

  # filler-only (the "normal corpus" arm):
  python src/datasets/build_pybughive_planted.py --no-plants \
    --filler data/ci/bugsinpy_filler_551.jsonl.gz \
    --output data/corpora/pybh_filler_only_corpus.jsonl \
    --index-dir data/indexes/pybh_filler_only
"""
from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.eval.evaluate_pybughive import ensure_repo, load_cases


def git_show(repo_dir: Path, commit: str, file_path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{file_path}"],
        cwd=repo_dir,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def open_maybe_gzip(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt")
    return open(path)


def build_plants(cases: list[dict], repo_cache_root: Path) -> list[dict]:
    plants: list[dict] = []
    for case in cases:
        repo_dir = ensure_repo(repo_cache_root, case["username"], case["repository"])
        if repo_dir is None:
            print(f"[WARN] repo unavailable, skipping {case['repository']}-{case['issue_id']}")
            continue
        buggy = git_show(repo_dir, case["buggy_commit"], case["file_path"])
        fixed = git_show(repo_dir, case["fixed_commit"], case["file_path"])
        if not buggy or not fixed:
            print(f"[WARN] missing file at commit, skipping {case['repository']}-{case['issue_id']}")
            continue
        if buggy == fixed:
            print(f"[WARN] buggy==fixed, skipping {case['repository']}-{case['issue_id']}")
            continue
        plants.append(
            {
                "id": f"PLANT_{case['repository']}-{case['issue_id']}",
                "buggy_code": buggy,
                "fixed_code": fixed,
                "source": "pybughive_planted",
                "repository": case["repository"],
                "file_path": case["file_path"],
            }
        )
    return plants


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-json", default="data/external_sources/PyBugHive/dataset/pybughive_current.json")
    parser.add_argument("--repo-cache-root", default="data/external_sources/repo_cache")
    parser.add_argument("--filler", default="data/corpora/repair_external_bugfix.jsonl",
                        help="Filler corpus JSONL (plain or .gz); pass empty string for plants-only")
    parser.add_argument("--projects", nargs="+", default=None)
    parser.add_argument("--no-plants", action="store_true", help="Emit filler only (normal-corpus arm)")
    parser.add_argument("--output", required=True)
    parser.add_argument("--plants-output", default=None, help="Optional separate plants-only JSONL")
    parser.add_argument("--index-dir", default=None, help="If set, build a FAISS index here")
    args = parser.parse_args()

    filler_rows: list[str] = []
    if args.filler:
        with open_maybe_gzip(Path(args.filler)) as handle:
            filler_rows = [line.rstrip("\n") for line in handle if line.strip()]
        print(f"Filler rows: {len(filler_rows)} from {args.filler}")

    plants: list[dict] = []
    if not args.no_plants:
        projects_filter = set(args.projects) if args.projects else None
        cases = load_cases(args.dataset_json, projects_filter=projects_filter)
        print(f"Supported cases: {len(cases)}")
        plants = build_plants(cases, Path(args.repo_cache_root))
        print(f"Plants extracted: {len(plants)}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as handle:
        for line in filler_rows:
            handle.write(line + "\n")
        for plant in plants:
            handle.write(json.dumps(plant) + "\n")
    print(f"Corpus ({len(filler_rows) + len(plants)} rows) -> {out_path}")

    if args.plants_output and plants:
        with open(args.plants_output, "w") as handle:
            for plant in plants:
                handle.write(json.dumps(plant) + "\n")
        print(f"Plants-only -> {args.plants_output}")

    if args.index_dir:
        from src.retrieval.build_index import build_index

        build_index(input_path=str(out_path), index_dir=args.index_dir)
        print(f"Index -> {args.index_dir}")


if __name__ == "__main__":
    main()
