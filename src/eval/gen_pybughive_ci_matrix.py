"""Emit a GitHub Actions job matrix for the powered PyBugHive experiment.

Shards supported cases by (project, required Python version) into small chunks so
each CI job fits well inside the 6h limit, and maps each shard to the Docker image
that provides the required interpreter (python:X.Y-bullseye — x86_64, OpenSSL 1.1,
so 3.7/3.8 build cleanly, unlike ARM/modern hosts).

Usage (in CI):
  python src/eval/gen_pybughive_ci_matrix.py \
    --dataset-json data/ci/pybughive_current.json \
    --projects all > matrix.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.eval.evaluate_pybughive import load_cases

# Cases per shard: heavy C-extension builds (pandas) or huge dep trees (salt,
# spaCy) get small shards; pure-python projects can take more.
CHUNK_SIZE = {"pandas": 2, "salt": 2, "spaCy": 2, "jax": 3, "black": 4}
DEFAULT_CHUNK = 4
# poetry's install steps use pipx (no `pipenv --python X`); its Pipfile-less
# poetry-1.2 toolchain targets python3.8.
FALLBACK_PYVER = {"poetry": "3.8"}


def python_version(case: dict) -> str:
    match = re.search(r"pipenv\s+--python\s+(3\.\d+)", case.get("install_steps", ""))
    if match:
        return match.group(1)
    return FALLBACK_PYVER.get(case["repository"], "3.8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-json", default="data/ci/pybughive_current.json")
    parser.add_argument("--projects", nargs="+", default=["all"])
    args = parser.parse_args()

    projects = None if args.projects == ["all"] else set(args.projects)
    cases = load_cases(args.dataset_json, projects_filter=projects)

    groups: dict[tuple[str, str], list[int]] = {}
    for case in cases:
        key = (case["repository"], python_version(case))
        groups.setdefault(key, []).append(case["issue_id"])

    include = []
    for (project, pyver), issue_ids in sorted(groups.items()):
        chunk = CHUNK_SIZE.get(project, DEFAULT_CHUNK)
        for i in range(0, len(issue_ids), chunk):
            shard_ids = issue_ids[i : i + chunk]
            include.append(
                {
                    "name": f"{project}-py{pyver}-s{i // chunk + 1}",
                    "project": project,
                    "image": f"python:{pyver}-bullseye",
                    "needs_pipx": project == "poetry",
                    "issue_ids": " ".join(str(x) for x in shard_ids),
                }
            )

    print(json.dumps({"include": include}))
    print(f"[matrix] {len(include)} shards, {len(cases)} cases", file=sys.stderr)


if __name__ == "__main__":
    main()
