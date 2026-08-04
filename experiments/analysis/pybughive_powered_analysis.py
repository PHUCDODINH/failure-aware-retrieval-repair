"""Pool sharded PyBugHive CI results and run the powered coverage analysis.

Reads per-shard result JSONs named <shard>__<arm>.json (arms: baseline,
structured_normal, structured_planted), merges cases per arm, classifies
environment failures ([INSTALL FAILED] / [ERROR]) as unusable (excluded from the
paired analysis, matching B.5's "usable cases" methodology), and reports:
  - per-arm pass rates on the usable-in-all-arms case set
  - exact McNemar (two-sided binomial on discordant pairs) for
    baseline vs structured_planted (the coverage test) and
    baseline vs structured_normal (the realistic-corpus test)
  - per-project breakdown

Usage:
  python experiments/analysis/pybughive_powered_analysis.py \
    --results-dir all_results --output summary.json --markdown summary.md
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

ARMS = ["baseline", "structured_normal", "structured_planted"]


def exact_mcnemar(b: int, c: int) -> float:
    """Two-sided exact binomial p for discordant counts b, c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / 2**n
    return min(1.0, 2 * tail)


def env_failure(item: dict) -> bool:
    detail = item.get("detail") or ""
    return detail.startswith("[INSTALL FAILED]") or detail.startswith("[ERROR]")


def load_results(results_dir: Path) -> dict[str, dict[str, dict]]:
    """arm -> case_id -> result item (last write wins on duplicates)."""
    merged: dict[str, dict[str, dict]] = {arm: {} for arm in ARMS}
    for path in sorted(results_dir.rglob("*.json")):
        name = path.stem
        if "__" not in name:
            continue
        arm = name.rsplit("__", 1)[1]
        if arm not in merged:
            continue
        try:
            items = json.loads(path.read_text())
        except Exception:
            print(f"[WARN] unreadable {path}")
            continue
        for item in items:
            merged[arm][item["case_id"]] = item
    return merged


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--markdown", default=None)
    args = parser.parse_args()

    merged = load_results(Path(args.results_dir))
    arms_present = [arm for arm in ARMS if merged[arm]]
    if "baseline" not in arms_present:
        raise SystemExit("No baseline results found.")

    # usable = ran without env failure in every present arm
    common = set.intersection(*(set(merged[arm]) for arm in arms_present))
    usable = sorted(
        cid for cid in common
        if not any(env_failure(merged[arm][cid]) for arm in arms_present)
    )
    excluded = sorted(common - set(usable))

    summary: dict = {
        "arms": arms_present,
        "cases_attempted": len(common),
        "cases_usable": len(usable),
        "cases_excluded_env": len(excluded),
        "excluded_case_ids": excluded,
        "per_arm": {},
        "comparisons": {},
        "per_project": {},
    }

    for arm in arms_present:
        passed = sum(1 for cid in usable if merged[arm][cid]["pass"])
        summary["per_arm"][arm] = {
            "passed": passed,
            "total": len(usable),
            "rate": round(passed / len(usable), 4) if usable else None,
        }

    for arm in ("structured_planted", "structured_normal"):
        if arm not in arms_present:
            continue
        b = sum(1 for cid in usable if merged["baseline"][cid]["pass"] and not merged[arm][cid]["pass"])
        c = sum(1 for cid in usable if not merged["baseline"][cid]["pass"] and merged[arm][cid]["pass"])
        summary["comparisons"][f"baseline_vs_{arm}"] = {
            "baseline_only_pass_b": b,
            "arm_only_pass_c": c,
            "mcnemar_exact_p": round(exact_mcnemar(b, c), 6),
            "converted_baseline_failures": c,
            "regressed_baseline_passes": b,
        }

    per_project: dict[str, dict] = defaultdict(lambda: {arm: [0, 0] for arm in arms_present})
    for cid in usable:
        project = merged["baseline"][cid]["repository"]
        for arm in arms_present:
            per_project[project][arm][1] += 1
            if merged[arm][cid]["pass"]:
                per_project[project][arm][0] += 1
    summary["per_project"] = {
        project: {arm: f"{p}/{t}" for arm, (p, t) in arms.items()}
        for project, arms in sorted(per_project.items())
    }

    Path(args.output).write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))

    if args.markdown:
        lines = ["# PyBugHive powered experiment — pooled summary", ""]
        lines.append(f"Usable cases: **{len(usable)}** (attempted {len(common)}, "
                     f"env-excluded {len(excluded)})")
        lines.append("")
        lines.append("| arm | passed | rate |")
        lines.append("| --- | ---: | ---: |")
        for arm in arms_present:
            a = summary["per_arm"][arm]
            rate = f"{100 * a['rate']:.1f}%" if a["rate"] is not None else "-"
            lines.append(f"| {arm} | {a['passed']}/{a['total']} | {rate} |")
        lines.append("")
        for name, comp in summary["comparisons"].items():
            lines.append(
                f"**{name}**: converted {comp['converted_baseline_failures']} baseline "
                f"failures, regressed {comp['regressed_baseline_passes']} — exact McNemar "
                f"p = {comp['mcnemar_exact_p']}"
            )
        lines.append("")
        lines.append("| project | " + " | ".join(arms_present) + " |")
        lines.append("| --- |" + " --- |" * len(arms_present))
        for project, arms in summary["per_project"].items():
            lines.append(f"| {project} | " + " | ".join(arms[a] for a in arms_present) + " |")
        Path(args.markdown).write_text("\n".join(lines) + "\n")

if __name__ == "__main__":
    main()
