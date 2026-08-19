#!/usr/bin/env bash
# Build the anonymized replication archive for double-blind review.
#
# Exports git-tracked files only (no .git history, no local corpora/indexes),
# scrubs machine-specific absolute paths from docs, excludes the paper source,
# adds an archive README, and verifies no identifying strings remain.
#
# Output: dist/replication_anonymized.zip
# Usage:  bash scripts/make_anonymized_archive.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$(mktemp -d)/replication"
OUT_DIR="$REPO_ROOT/dist"
OUT="$OUT_DIR/replication_anonymized.zip"

# Strings that must not appear anywhere in the archive.
IDENTIFIERS='dodinhphuc|PHUCDODINH|Do Dinh|vgtglobal|Structure-Failure-Aware-Retrieval|failure-aware-retrieval-repair'

mkdir -p "$STAGE" "$OUT_DIR"

# 1. Export tracked files (working-tree versions, no git metadata).
git -C "$REPO_ROOT" archive HEAD | tar -x -C "$STAGE"

# 2. Exclude the paper source (not part of the replication package).
rm -rf "$STAGE/paper"

# 3. Scrub machine-specific absolute paths -> repo-relative.
find "$STAGE" -name '*.md' -print0 | xargs -0 sed -i '' \
  -e 's|/Users/[^/]*/PycharmProjects/RAGtest/||g' \
  -e 's|/Users/[^/]*/PycharmProjects/RAGtest|.|g'

# 4. Archive README for reviewers.
cat > "$STAGE/ARCHIVE_README.md" <<'EOF'
# Replication package (anonymized for double-blind review)

Structured failure-aware retrieval for LLM program repair: code, analysis
scripts, CI experiment harness, and paper-facing results documentation.

Start here:
- `docs/PAPER_SYSTEM_AND_RESULTS.md` — consolidated system description and
  every result used in the paper, with pointers to the scripts that produced
  each number.
- `experiments/analysis/` — significance tests, equivalence/TOST + MDE,
  independent relevance metrics, oracle/planted analyses, blind-audit tooling.
- `src/` — retrieval pipeline, reranker, patch layer, evaluation harnesses.
- `.github/workflows/pybughive-powered.yml` — the powered real-bug experiment
  (116 PyBugHive cases, 10 projects) on x86 CI; `data/ci/` holds its fixtures.
- `README.md` — setup and per-benchmark run instructions.

Large artifacts (FAISS indexes, retrieval corpora, per-run traces) are
excluded from version control; every one is rebuildable from the committed
scripts and fixtures (see `docs/EXTERNAL_CORPUS_WORKFLOW.md` and
`src/datasets/build_pybughive_planted.py`).
EOF

# 5. Zip.
rm -f "$OUT"
(cd "$(dirname "$STAGE")" && zip -qr "$OUT" "$(basename "$STAGE")")

# 6. Verify.
if grep -r -i -E "$IDENTIFIERS" "$STAGE" -l; then
  echo "FATAL: identifying strings remain (files listed above)." >&2
  exit 1
fi
echo "OK: no identifying strings."
du -h "$OUT"
