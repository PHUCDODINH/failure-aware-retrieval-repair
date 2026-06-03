"""MBPP repair evaluation harness.

Repairs buggy MBPP functions (data/mbpp/mbpp_bugfix.jsonl format) with the
baseline or retrieval-augmented repairer and runs the assert-style tests.

Unlike eval_mbpp.py (code generation from scratch), this exercises the actual
repair pipeline (buggy_code + failure_state + retrieval variants), so it can
test whether structured failure-aware retrieval converts to downstream repair
gains in a knowledge-gap regime.

Includes robust code extraction so weak models that wrap output in prose/markdown
are scored on their logic, not their formatting (the confound seen on Llama-3-8B).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import traceback
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.models.repair_baseline import repair_without_rag
from src.models.repair_rag import repair_with_rag
from src.retrieval.failure_state import make_failure_state

DEFAULT_INPUT = "data/mbpp/mbpp_holdout_test.jsonl"
PREAMBLE = (
    "from typing import *\n"
    "import math\n import re\n import itertools\n import collections\n"
    "import heapq\n import bisect\n import functools\n"
).replace("\n ", "\n")
TEST_TIMEOUT_SECONDS = int(os.getenv("MBPP_REPAIR_TIMEOUT_SECONDS", "5"))
FENCE_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)
CODE_START_RE = re.compile(r"^\s*(import |from |def |class |@)")


class InfrastructureFailure(Exception):
    pass


def extract_code(text: str) -> str:
    """Robustly pull Python code out of a possibly prose/markdown-wrapped answer."""
    if not text:
        return ""
    blocks = FENCE_RE.findall(text)
    if blocks:
        return max(blocks, key=len).strip()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if CODE_START_RE.match(line):
            return "\n".join(lines[i:]).strip()
    return text.strip()


def load_tasks(path: str) -> list[dict[str, Any]]:
    with open(path) as handle:
        return [json.loads(l) for l in handle if l.strip()]


def load_existing_results(path: str) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        with open(path) as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_results(path: str, results: list[dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as handle:
        json.dump(results, handle, indent=2)


def write_trace(trace_dir: str | None, mode: str, tid: str, payload: dict) -> None:
    if not trace_dir:
        return
    os.makedirs(trace_dir, exist_ok=True)
    (Path(trace_dir) / f"{mode}__{tid}.json").write_text(json.dumps(payload, indent=2))


def build_failure_signal(task: dict) -> str:
    tests = task.get("tests") or []
    return "\n".join(
        s for s in [
            f"Problem: {task.get('prompt', '')}",
            f"Bug type: {task.get('bug_type', '')}",
            "Failing tests:\n" + "\n".join(tests),
        ] if s.strip()
    )


def run_candidate(code: str, tests: list[str]) -> tuple[bool, str]:
    source = PREAMBLE + "\n" + code + "\n\n" + "\n".join(tests) + "\n"
    ns: dict[str, Any] = {}

    def _timeout(signum, frame):
        raise TimeoutError(f"exceeded {TEST_TIMEOUT_SECONDS}s")

    prev = signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(TEST_TIMEOUT_SECONDS)
    try:
        exec(compile(source, "<candidate>", "exec"), ns)
        return True, ""
    except Exception:
        return False, traceback.format_exc()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prev)


def evaluate_task(task, mode, model, retrieval_profile, index_dir, retrieval_variant, trace_dir):
    buggy = task["buggy_code"]
    tests = task["tests"]
    failure_signal = build_failure_signal(task)
    failure_state = make_failure_state(failure_signal, buggy).to_dict()

    want_debug = bool(trace_dir)
    if mode == "baseline":
        out = repair_without_rag(buggy, description=failure_signal, model=model, return_debug=want_debug)
    else:
        out = repair_with_rag(
            buggy, description=failure_signal, model=model,
            retrieval_profile=retrieval_profile, index_dir=index_dir,
            retrieval_variant=retrieval_variant, failure_state=failure_state,
            return_debug=want_debug,
        )
    debug = out if isinstance(out, dict) else None
    raw = out["code"] if isinstance(out, dict) else out
    code = extract_code(raw)

    passed, err = run_candidate(code, tests)
    result = {
        "id": task["id"], "mode": mode,
        "retrieval_variant": retrieval_variant if mode == "rag" else None,
        "bug_type": task.get("bug_type"), "pass": passed, "stderr": err[-500:],
    }
    if trace_dir:
        payload = {**result, "buggy_code": buggy, "generated_code": code,
                   "failure_state": failure_state}
        if debug:
            payload["retrieval_debug"] = debug.get("retrieval_debug")
            payload["retrieved_examples"] = debug.get("retrieved_examples")
        write_trace(trace_dir, mode, task["id"], payload)
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input-path", default=DEFAULT_INPUT)
    p.add_argument("--mode", choices=["baseline", "rag"], default="baseline")
    p.add_argument("--model", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--results-path", default=None)
    p.add_argument("--trace-dir", default=None)
    p.add_argument("--retrieval-profile", default="mbpp_holdout")
    p.add_argument("--retrieval-index-dir", default=None)
    p.add_argument("--retrieval-variant", choices=["structured", "code_only", "raw_text", "raw_text_rerank"], default="structured")
    args = p.parse_args()

    tasks = load_tasks(args.input_path)
    if args.limit:
        tasks = tasks[: args.limit]
    results_path = args.results_path or f"experiments/mbpp_repair_{args.mode}.json"
    results = load_existing_results(results_path)
    done = {r["id"] for r in results}

    print(f"Detected {len(tasks)} MBPP repair tasks.")
    for task in tasks:
        if task["id"] in done:
            continue
        try:
            row = evaluate_task(task, args.mode, args.model, args.retrieval_profile,
                                args.retrieval_index_dir, args.retrieval_variant, args.trace_dir)
        except Exception as exc:
            if exc.__class__.__name__ in {"APIConnectionError", "APITimeoutError"}:
                raise InfrastructureFailure(str(exc)) from exc
            row = {"id": task["id"], "mode": args.mode, "pass": False, "stderr": f"[ERR] {exc}"}
        print(f"{task['id']}: {'PASS' if row['pass'] else 'FAIL'}")
        results.append(row)
        done.add(task["id"])
        save_results(results_path, results)

    passed = sum(1 for r in results if r.get("pass"))
    print(json.dumps({"results_path": results_path, "passed": passed, "total": len(results)}, indent=2))


if __name__ == "__main__":
    main()
