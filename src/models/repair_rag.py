import os
import time
import random
import difflib
import json
import re
from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError
from dotenv import load_dotenv
from src.retrieval.index_store import embed_text, load_index_bundle
from src.retrieval.failure_state import make_failure_state
from src.retrieval.repair_metadata import (
    compatible_exception,
    compatible_failure_mode,
    infer_file_family,
    infer_repair_metadata,
    metadata_overlap,
)
from src.models.patch_utils import (
    PATCH_SCHEMA_VERSION,
    apply_line_range_response,
    format_numbered_snippet,
    select_patch_snippets,
)

# Load environment variables (explicit env vars take precedence over .env,
# so a per-run OPENAI_API_KEY / OPENAI_BASE_URL can target another provider)
load_dotenv(override=False)

# ============================================================================
# Load embedding model (same as build_index.py)
# ============================================================================
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("OPENAI_REQUEST_TIMEOUT", "30"))
MAX_API_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "3"))
MAX_RAG_EXAMPLES = 2
SEARCH_POOL_SIZE = 24
MAX_DIFF_HUNKS = 2
DIFF_CONTEXT_LINES = 6
MAX_SNIPPET_CHARS = 1200
MAX_CONTEXT_CHARS = 5000
MAX_DESCRIPTION_CHARS = 4000
MAX_FULL_CODE_CHARS = 40000
MAX_PATCH_SNIPPETS = 4
PATCH_WINDOW_LINES = 160
PATCH_WINDOW_STRIDE = 100
PATCH_RESPONSE_TOKENS = 3000
PATCH_FUZZY_MIN_RATIO = 0.93
PATCH_FUZZY_MIN_MARGIN = 0.03
PATCH_VALIDATION_RETRIES = int(os.getenv("PATCH_VALIDATION_RETRIES", "1"))
RETRIEVAL_VARIANTS = {
    "structured",
    "code_only",
    "raw_text",
    "raw_text_rerank",
}
IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
ATTRIBUTE_RE = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)")
RETURN_RE = re.compile(r"return\s+(.+)")
FUNCTION_NAME_RE = re.compile(r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
OPERATOR_RE = re.compile(r"(==|!=|<=|>=|//|\*\*|[-+*/%<>])")
ERROR_NAME_RE = re.compile(r"\b([A-Z][A-Za-z]+Error)\b")


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text

# ============================================================================
# OpenAI client
# ============================================================================
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL") or None,
    max_retries=0,
)

def safe_chat_completion(model, messages, temperature=0, max_retries=MAX_API_RETRIES, max_completion_tokens: int | None = None):
    """
    Retry logic for OpenAI API calls to handle RateLimitError.
    """
    delay = 1.0
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except (RateLimitError, APIConnectionError, APITimeoutError) as e:
            if attempt == max_retries - 1:
                print(f"[ERROR] Max retries reached for transient OpenAI error: {e}")
                raise
            
            print(f"[WARNING] Transient OpenAI error. Retrying in {delay:.2f}s... (Attempt {attempt+1}/{max_retries})")
            time.sleep(delay)
            delay *= 2
            delay += random.uniform(0, 0.5)
            
    return None


def _truncate_text(text: str, max_chars: int = MAX_SNIPPET_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    keep = max_chars // 2
    return text[:keep].rstrip() + "\n...\n" + text[-keep:].lstrip()


def _truncate_description(text: str, max_chars: int = MAX_DESCRIPTION_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    keep = max_chars // 2
    return text[:keep].rstrip() + "\n...\n" + text[-keep:].lstrip()


def _estimate_completion_tokens(source_text: str) -> int:
    approx_tokens = max(1024, len(source_text) // 4)
    return min(16000, int(approx_tokens * 1.15) + 256)


def _extract_query_terms(description: str) -> list[str]:
    seen: list[str] = []
    for token in IDENTIFIER_RE.findall(description.lower()):
        if len(token) < 4:
            continue
        if token in {"traceback", "assertionerror", "optional", "description", "failed", "error"}:
            continue
        if token not in seen:
            seen.append(token)
    return seen[:24]


def _select_patch_snippets(buggy_code: str, description: str) -> list[dict]:
    return select_patch_snippets(
        buggy_code,
        description,
        max_snippets=MAX_PATCH_SNIPPETS,
        window_lines=PATCH_WINDOW_LINES,
        window_stride=PATCH_WINDOW_STRIDE,
    )


def _extract_json_object(text: str) -> str:
    stripped = _strip_code_fences(text)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return stripped
    return stripped[start:end + 1]


def _parse_patch_edits(text: str) -> list[dict]:
    payload = json.loads(_extract_json_object(text))
    edits = payload.get("edits")
    if not isinstance(edits, list) or not edits:
        raise ValueError("missing edits")
    normalized: list[dict] = []
    for item in edits:
        if not isinstance(item, dict):
            continue
        search = item.get("search")
        replace = item.get("replace")
        if isinstance(search, str) and isinstance(replace, str) and search:
            normalized_edit = {"search": search, "replace": replace}
            for key in ("start_line", "end_line"):
                value = _coerce_positive_int(item.get(key))
                if value is not None:
                    normalized_edit[key] = value
            normalized.append(normalized_edit)
    if not normalized:
        raise ValueError("no valid edits")
    return normalized


def _coerce_positive_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _apply_patch_edits(original: str, edits: list[dict]) -> str:
    updated = original
    for edit in edits:
        search = edit["search"]
        replace = edit["replace"]
        occurrences = updated.count(search)
        if occurrences == 1:
            updated = updated.replace(search, replace, 1)
            continue

        search_without_edge_newlines = search.strip("\n")
        if search_without_edge_newlines and search_without_edge_newlines != search:
            trimmed_occurrences = updated.count(search_without_edge_newlines)
            if trimmed_occurrences == 1:
                updated = updated.replace(search_without_edge_newlines, replace, 1)
                continue

        span = _find_line_range_patch_span(updated, search, edit.get("start_line"), edit.get("end_line"))
        if span is not None:
            start, end = span
            updated = updated[:start] + replace + updated[end:]
            continue

        span = _find_stripped_line_patch_span(updated, search)
        if span is not None:
            start, end = span
            updated = updated[:start] + replace + updated[end:]
            continue

        span = _find_fuzzy_patch_span(updated, search)
        if span is None:
            raise ValueError(f"search block must match exactly once, found {occurrences}")

        start, end = span
        updated = updated[:start] + replace + updated[end:]
    return updated


def _normalize_patch_line(line: str) -> str:
    return line.rstrip()


def _line_offsets(source_text: str) -> list[int]:
    offsets: list[int] = []
    offset = 0
    for line in source_text.splitlines(keepends=True):
        offsets.append(offset)
        offset += len(line)
    offsets.append(offset)
    return offsets


def _find_line_range_patch_span(
    source_text: str,
    search_text: str,
    start_line: int | None,
    end_line: int | None,
) -> tuple[int, int] | None:
    if start_line is None or end_line is None or start_line > end_line:
        return None
    source_lines = source_text.splitlines(keepends=True)
    if start_line < 1 or end_line > len(source_lines):
        return None

    candidate_lines = source_lines[start_line - 1:end_line]
    search_lines = search_text.splitlines(keepends=True)
    if not candidate_lines or not search_lines:
        return None

    normalized_candidate = [_normalize_patch_line(line) for line in candidate_lines]
    normalized_search = [_normalize_patch_line(line) for line in search_lines]
    ratio = difflib.SequenceMatcher(a=normalized_search, b=normalized_candidate).ratio()
    if ratio < 0.75:
        return None

    offsets = _line_offsets(source_text)
    return offsets[start_line - 1], offsets[end_line]


def _find_stripped_line_patch_span(source_text: str, search_text: str) -> tuple[int, int] | None:
    source_lines = source_text.splitlines(keepends=True)
    search_lines = search_text.splitlines(keepends=True)
    while search_lines and not search_lines[0].strip():
        search_lines = search_lines[1:]
    while search_lines and not search_lines[-1].strip():
        search_lines = search_lines[:-1]
    if not source_lines or not search_lines:
        return None

    normalized_search = [line.strip() for line in search_lines]
    search_len = len(normalized_search)
    offsets = _line_offsets(source_text)
    matches: list[tuple[int, int]] = []
    for start_line in range(0, len(source_lines) - search_len + 1):
        normalized_window = [line.strip() for line in source_lines[start_line:start_line + search_len]]
        if normalized_window == normalized_search:
            matches.append((offsets[start_line], offsets[start_line + search_len]))
            if len(matches) > 1:
                return None
    return matches[0] if len(matches) == 1 else None


def _find_fuzzy_patch_span(source_text: str, search_text: str) -> tuple[int, int] | None:
    source_lines = source_text.splitlines(keepends=True)
    search_lines = search_text.splitlines(keepends=True)
    if not source_lines or not search_lines:
        return None

    normalized_search = [_normalize_patch_line(line) for line in search_lines]
    search_len = len(search_lines)
    min_len = max(1, search_len - 2)
    max_len = min(len(source_lines), search_len + 2)
    candidates: list[tuple[float, float, int, int]] = []

    line_offsets = _line_offsets(source_text)

    for window_len in range(min_len, max_len + 1):
        for start_line in range(0, len(source_lines) - window_len + 1):
            window_lines = source_lines[start_line:start_line + window_len]
            normalized_window = [_normalize_patch_line(line) for line in window_lines]
            ratio = difflib.SequenceMatcher(a=normalized_search, b=normalized_window).ratio()
            if ratio < PATCH_FUZZY_MIN_RATIO:
                continue
            score = ratio - (abs(window_len - search_len) * 0.01)
            candidates.append((score, ratio, start_line, window_len))

    if not candidates:
        return None

    candidates.sort(reverse=True)
    best_score, best_ratio, best_start, best_len = candidates[0]
    if best_ratio < PATCH_FUZZY_MIN_RATIO:
        return None
    if len(candidates) > 1 and (best_score - candidates[1][0]) < PATCH_FUZZY_MIN_MARGIN:
        return None

    start_offset = line_offsets[best_start]
    end_offset = line_offsets[best_start + best_len]
    return start_offset, end_offset


def _focused_diff_snippet(buggy: str, fixed: str) -> tuple[str, str]:
    buggy_lines = buggy.splitlines()
    fixed_lines = fixed.splitlines()
    matcher = difflib.SequenceMatcher(a=buggy_lines, b=fixed_lines)

    buggy_chunks: list[str] = []
    fixed_chunks: list[str] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        buggy_start = max(0, i1 - DIFF_CONTEXT_LINES)
        buggy_end = min(len(buggy_lines), i2 + DIFF_CONTEXT_LINES)
        fixed_start = max(0, j1 - DIFF_CONTEXT_LINES)
        fixed_end = min(len(fixed_lines), j2 + DIFF_CONTEXT_LINES)

        buggy_chunks.append("\n".join(buggy_lines[buggy_start:buggy_end]).strip())
        fixed_chunks.append("\n".join(fixed_lines[fixed_start:fixed_end]).strip())

        if len(buggy_chunks) >= MAX_DIFF_HUNKS:
            break

    if not buggy_chunks or not fixed_chunks:
        return _truncate_text(buggy), _truncate_text(fixed)

    buggy_text = "\n...\n".join(chunk for chunk in buggy_chunks if chunk)
    fixed_text = "\n...\n".join(chunk for chunk in fixed_chunks if chunk)
    return _truncate_text(buggy_text), _truncate_text(fixed_text)


def _extract_identifiers(text: str) -> set[str]:
    return {
        token
        for token in IDENTIFIER_RE.findall(text)
        if len(token) > 2 and token not in {"def", "for", "while", "return", "true", "false", "none"}
    }


def _extract_attributes(text: str) -> set[str]:
    return set(ATTRIBUTE_RE.findall(text))


def _extract_operators(text: str) -> set[str]:
    return set(OPERATOR_RE.findall(text))


def _extract_function_name(text: str) -> str:
    match = FUNCTION_NAME_RE.search(text)
    return match.group(1) if match else ""


def _extract_error_names(text: str) -> set[str]:
    return set(ERROR_NAME_RE.findall(text))


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _scope_bonus(metadata: dict) -> float:
    scope = metadata.get("scope")
    if scope == "function":
        return 0.3
    if scope == "method":
        return 0.15
    return 0.0


def _length_similarity(target_code: str, candidate_code: str) -> float:
    target_lines = max(1, len(target_code.splitlines()))
    candidate_lines = max(1, len(candidate_code.splitlines()))
    ratio = min(target_lines, candidate_lines) / max(target_lines, candidate_lines)
    return ratio


def _build_retrieval_query(target_buggy: str, failure_signal: str, retrieval_variant: str) -> str:
    if retrieval_variant in {"structured", "code_only", "raw_text_rerank"}:
        return target_buggy
    if not failure_signal.strip():
        return target_buggy
    return (
        f"{target_buggy}\n\n"
        "Observed failing signal:\n"
        f"{failure_signal.strip()}"
    )


def _candidate_signal_text(candidate: dict) -> str:
    parts = [
        candidate.get("prompt", ""),
        candidate.get("failure_signal", ""),
        " ".join(candidate.get("tests") or []),
        candidate.get("bug_type", ""),
    ]
    return "\n".join(part for part in parts if part)


def _raw_text_rerank_score(
    target_buggy: str,
    failure_signal: str,
    candidate: dict,
    dense_rank: int,
) -> float:
    candidate_buggy = candidate.get("buggy_code", "")
    candidate_signal_text = _candidate_signal_text(candidate)
    metadata = candidate.get("metadata", {})
    target_ids = _extract_identifiers(target_buggy)
    candidate_ids = _extract_identifiers(candidate_buggy)
    identifier_overlap = len(target_ids & candidate_ids) / max(1, len(target_ids))
    attr_overlap = _jaccard_similarity(
        _extract_attributes(target_buggy),
        _extract_attributes(candidate_buggy),
    )
    operator_overlap = _jaccard_similarity(
        _extract_operators(target_buggy),
        _extract_operators(candidate_buggy),
    )
    target_fn = _extract_function_name(target_buggy)
    candidate_fn = _extract_function_name(candidate_buggy)
    function_bonus = 0.15 if target_fn and candidate_fn and target_fn == candidate_fn else 0.0

    changed_lines = min(int(metadata.get("changed_lines", 0) or 0), 120)
    files_changed = int(metadata.get("files_changed", 1) or 1)
    file_bonus = 0.2 if files_changed == 1 else 0.0
    size_penalty = changed_lines / 400.0
    dense_bonus = 1.0 / (dense_rank + 1)
    length_bonus = _length_similarity(target_buggy, candidate_buggy) * 0.3
    lexical_bonus = (identifier_overlap * 0.8) + (attr_overlap * 0.45) + (operator_overlap * 0.2)
    signal_bonus = 0.0

    if failure_signal.strip():
        signal_ids = _extract_identifiers(failure_signal)
        candidate_signal_ids = _extract_identifiers(candidate_signal_text)
        signal_attr_overlap = _jaccard_similarity(
            _extract_attributes(failure_signal),
            _extract_attributes(candidate_signal_text),
        )
        signal_operator_overlap = _jaccard_similarity(
            _extract_operators(failure_signal),
            _extract_operators(candidate_signal_text),
        )
        signal_error_overlap = _jaccard_similarity(
            _extract_error_names(failure_signal),
            _extract_error_names(candidate_signal_text),
        )
        signal_identifier_overlap = len(signal_ids & candidate_signal_ids) / max(1, len(signal_ids))
        signal_bonus = (
            signal_identifier_overlap * 0.7
            + signal_attr_overlap * 0.35
            + signal_operator_overlap * 0.2
            + signal_error_overlap * 0.7
        )

    return (
        dense_bonus
        + lexical_bonus
        + signal_bonus
        + function_bonus
        + _scope_bonus(metadata)
        + file_bonus
        + length_bonus
        - size_penalty
    )


def _structured_rerank_score(
    target_buggy: str,
    failure_signal: str,
    failure_state: dict,
    candidate: dict,
    dense_rank: int,
    disabled_components: frozenset[str] | None = None,
) -> tuple[float, dict]:
    disabled = disabled_components or frozenset()
    candidate_metadata = candidate.get("repair_metadata") or infer_repair_metadata(candidate)
    dense_rank_score = 1.0 / (dense_rank + 1)
    contract_tag_overlap = 0.0 if "contract_tags" in disabled else metadata_overlap(
        failure_state.get("contract_tags") or [],
        candidate_metadata.get("repair_pattern_tags") or [],
    )
    symbol_overlap = 0.0 if "suspicious_symbols" in disabled else metadata_overlap(
        failure_state.get("suspicious_symbols") or [],
        candidate_metadata.get("suspicious_symbols") or [],
    )
    exception_compat = 0.0 if "exception_type" in disabled else compatible_exception(
        failure_state.get("exception_type", ""),
        candidate_metadata,
    )
    failure_mode_compat = 0.0 if "failure_mode" in disabled else compatible_failure_mode(
        failure_state.get("failure_mode", ""),
        candidate_metadata,
    )
    query_family = infer_file_family(text=f"{target_buggy}\n{failure_signal}")
    file_family_bonus = 0.2 if query_family == candidate_metadata.get("file_family") else 0.0
    changed_lines = min(int(candidate_metadata.get("changed_lines", 0) or 0), 120)
    edit_size_penalty = changed_lines / 400.0
    score = (
        1.0 * dense_rank_score
        + 0.8 * contract_tag_overlap
        + 0.7 * symbol_overlap
        + 0.5 * exception_compat
        + 0.8 * failure_mode_compat
        + file_family_bonus
        - edit_size_penalty
    )
    components = {
        "dense_rank_score": dense_rank_score,
        "contract_tag_overlap": contract_tag_overlap,
        "symbol_overlap": symbol_overlap,
        "exception_compat": exception_compat,
        "failure_mode_compat": failure_mode_compat,
        "file_family_bonus": file_family_bonus,
        "edit_size_penalty": edit_size_penalty,
        "query_file_family": query_family,
        "candidate_repair_metadata": candidate_metadata,
    }
    return score, components


def _infer_repair_lesson(example: dict) -> str:
    buggy = example.get("buggy_code", "")
    fixed = example.get("fixed_code", example.get("correct_code", ""))
    buggy_snippet, fixed_snippet = _focused_diff_snippet(buggy, fixed)
    buggy_lower = buggy_snippet.lower()
    fixed_lower = fixed_snippet.lower()
    changed_text = f"{buggy_lower}\n{fixed_lower}"

    lessons: list[str] = []
    seen: set[str] = set()

    def add_lesson(message: str) -> None:
        if message in seen:
            return
        seen.add(message)
        lessons.append(message)

    buggy_attrs = set(ATTRIBUTE_RE.findall(buggy_snippet))
    fixed_attrs = set(ATTRIBUTE_RE.findall(fixed_snippet))
    added_attrs = fixed_attrs - buggy_attrs
    removed_attrs = buggy_attrs - fixed_attrs
    if added_attrs or removed_attrs:
        add_lesson("Use the correct object attributes and preserve the local data model.")

    buggy_return = RETURN_RE.findall(buggy_snippet)
    fixed_return = RETURN_RE.findall(fixed_snippet)
    if buggy_return and fixed_return and buggy_return != fixed_return:
        if any(token in fixed_lower for token in ("max(", "min(", "default", "none", "[]", "{}")):
            add_lesson("Handle edge cases explicitly in the returned value.")
        elif "+" in "".join(buggy_return) and "+" in "".join(fixed_return):
            add_lesson("Preserve the required output ordering when combining partial results.")
        else:
            add_lesson("Update the returned expression to match the intended contract.")

    if any(token in changed_text for token in ("heappush(", "heappop(", "heapq", "priority queue")):
        add_lesson("When using a heap, keep entries totally orderable and preserve the intended priority key.")

    if any(token in changed_text for token in ("incoming_nodes", "outgoing_nodes", "successors", "predecessors", "topological", "visited_nodes")):
        add_lesson("Preserve traversal ordering and update graph bookkeeping only when the dependency state is actually satisfied.")

    if any(token in changed_text for token in ("strip(", "lstrip(", "rstrip(", "splitlines(", "split(", "join(", "wrap(", "whitespace", "space")):
        add_lesson("Preserve exact whitespace and formatting semantics; avoid normalizing text that the contract expects to keep.")

    if any(token in changed_text for token in ("recursive", "recursion", "base case", "yield from")) or (
        "return" in changed_text and any(token in changed_text for token in ("if ", "elif ")) and any(token in changed_text for token in ("(", ")", "[]"))
    ):
        add_lesson("Keep the base case and recursive step aligned so the fix does not change termination behavior.")

    if " is " in changed_text or " is not " in changed_text:
        add_lesson("Use identity checks only for sentinel cases like None; use value equality for ordinary comparisons.")

    if any(token in changed_text for token in ("startswith(", "endswith(", "==", "!=", " is ", " is not ")):
        add_lesson("Tighten boolean guard conditions instead of relying on broad matches.")

    if any(token in changed_text for token in ("raise valueerror", "raise typeerror", "assert ", "if settings is none", "if crawler is none")):
        add_lesson("Validate preconditions before continuing with the main logic.")

    if any(token in changed_text for token in ("+ 1", "- 1", "<=", ">=", "range(", "end_index", "start_index", "boundary")):
        add_lesson("Fix boundary and off-by-one handling around the changed logic.")

    if any(token in changed_text for token in ("[", "]", ".append", ".pop", ".insert", ".successor", ".next", ".remove", ".extend")):
        add_lesson("Check collection updates and pointer-style state transitions carefully.")

    if any(token in changed_text for token in ("sorted(", ".sort(", "reverse(", "reversed(", "deque(", "queue")):
        add_lesson("Preserve deterministic ordering when requeuing or sorting intermediate state.")

    if any(token in changed_text for token in ("+", "-", "*", "/", "%", "sum(", "max(", "min(")):
        add_lesson("Verify accumulator and arithmetic updates after each step.")

    if not lessons:
        add_lesson("Match the fix to the local logic error instead of rewriting the whole function.")

    return " ".join(lessons[:2])

# ============================================================================
# Retrieve examples
# ============================================================================
def retrieve_examples(
    buggy_code: str,
    failure_signal: str = "",
    k=MAX_RAG_EXAMPLES,
    retrieval_profile: str | None = None,
    index_dir: str | None = None,
    retrieval_variant: str = "structured",
    failure_state: dict | None = None,
    return_debug: bool = False,
    disabled_components: frozenset[str] | None = None,
):
    if retrieval_variant not in RETRIEVAL_VARIANTS:
        raise ValueError(f"Unknown retrieval variant: {retrieval_variant}")

    faiss_index, db = load_index_bundle(profile=retrieval_profile, index_dir=index_dir)
    if faiss_index is None:
        return ([], {}) if return_debug else []

    structured_state = failure_state or make_failure_state(failure_signal, buggy_code).to_dict()
    retrieval_query = _build_retrieval_query(buggy_code, failure_signal, retrieval_variant)
    q_emb = embed_text(retrieval_query).reshape(1, -1)
    pool_size = min(len(db), max(k, SEARCH_POOL_SIZE))
    _, idxs = faiss_index.search(q_emb, pool_size)

    ranked: list[tuple[float, dict, dict]] = []
    seen_ids: set[str] = set()
    for dense_rank, idx in enumerate(idxs[0]):
        if idx == -1:
            continue
        candidate = db[idx]
        uid = candidate.get("id", str(idx))
        if uid in seen_ids:
            continue
        seen_ids.add(uid)

        if retrieval_variant in {"code_only", "raw_text"}:
            score = 1.0 / (dense_rank + 1)
            components = {"dense_rank_score": score}
        elif retrieval_variant == "raw_text_rerank":
            score = _raw_text_rerank_score(buggy_code, failure_signal, candidate, dense_rank)
            components = {"raw_text_rerank_score": score, "dense_rank_score": 1.0 / (dense_rank + 1)}
        else:
            score, components = _structured_rerank_score(
                buggy_code,
                failure_signal,
                structured_state,
                candidate,
                dense_rank,
                disabled_components=disabled_components,
            )

        ranked.append(
            (
                score,
                candidate,
                {
                    "id": uid,
                    "dense_rank": dense_rank,
                    "score": score,
                    "components": components,
                },
            )
        )

    ranked.sort(key=lambda item: item[0], reverse=True)
    examples = [candidate for _, candidate, _ in ranked[:k]]
    if not return_debug:
        return examples

    debug = {
        "retrieval_variant": retrieval_variant,
        "retrieval_query": retrieval_query,
        "failure_state": structured_state,
        "pool_size": pool_size,
        "candidate_pool": [item for _, _, item in ranked[:SEARCH_POOL_SIZE]],
        "selected_example_ids": [candidate.get("id") for candidate in examples],
    }
    return examples, debug

# ============================================================================
# Construct RAG repair prompt
# ============================================================================
def build_repair_prompt(buggy_code: str, description: str, examples):
    strategy_section = ""
    if description:
        strategy_section = f"Description (optional): {_truncate_description(description)}\n\n"

    return build_repair_prompt_with_strategy(
        buggy_code=buggy_code,
        description=strategy_section,
        examples=examples,
        strategy_note="",
    )


def build_repair_prompt_with_strategy(
    buggy_code: str,
    description: str,
    examples,
    strategy_note: str,
):
    header = (
        "You are an expert Python engineer.\n"
        "Your task is to FIX the following buggy Python code.\n"
        "STRICT RULES:\n"
        "1. Output ONLY corrected Python code.\n"
        "2. NO explanation, NO comments, NO markdown.\n"
        "3. Preserve the same function name.\n"
        "4. Ensure runnable, correct Python.\n\n"
    )

    context = "Below are compact buggy-to-fixed examples. Focus on the correction pattern.\n\n"
    used_chars = len(context)
    for ex in examples[:MAX_RAG_EXAMPLES]:
        buggy_snippet, fixed_snippet = _focused_diff_snippet(
            ex.get("buggy_code", ""),
            ex.get("fixed_code", ex.get("correct_code", "")),
        )
        lesson = _infer_repair_lesson(ex)
        formatted = (
            "# Repair lesson:\n"
            f"{lesson}\n\n"
            "# Buggy snippet:\n"
            f"{buggy_snippet}\n\n"
            "# Fixed snippet:\n"
            f"{fixed_snippet}\n\n"
        )
        if used_chars + len(formatted) > MAX_CONTEXT_CHARS:
            break
        context += formatted
        used_chars += len(formatted)

    strategy_block = ""
    if strategy_note:
        strategy_block = (
            "# Repair preference:\n"
            f"{strategy_note}\n\n"
        )

    final = (
        "\n# Now fix this code:\n"
        f"{buggy_code}\n\n"
        f"{description}"
        f"{strategy_block}"
        "# Your FIXED code:\n"
    )

    return header + context + final


def build_large_file_patch_prompt_with_strategy(
    buggy_code: str,
    description: str,
    examples: list[dict],
    strategy_note: str,
) -> tuple[list[dict], list[dict]]:
    trimmed_description = _truncate_description(description.strip(), max_chars=2500) if description else ""
    snippets = _select_patch_snippets(buggy_code, trimmed_description)

    lesson_blocks: list[str] = []
    for ex in examples[:MAX_RAG_EXAMPLES]:
        lesson = _infer_repair_lesson(ex)
        repair_metadata = ex.get("repair_metadata") or infer_repair_metadata(ex)
        buggy_snippet, fixed_snippet = _focused_diff_snippet(
            ex.get("buggy_code", ""),
            ex.get("fixed_code", ex.get("correct_code", "")),
        )
        lesson_blocks.append(
            "Retrieved edit constraint:\n"
            f"{lesson}\n"
            f"repair_pattern_tags: {repair_metadata.get('repair_pattern_tags') or []}\n"
            f"edit_scope: {repair_metadata.get('edit_scope') or ''}\n"
            f"changed_operators: {repair_metadata.get('changed_operators') or []}\n"
            f"suspicious_symbols: {repair_metadata.get('suspicious_symbols') or []}\n"
            "Buggy reference:\n"
            f"{buggy_snippet}\n"
            "Fixed reference:\n"
            f"{fixed_snippet}\n"
        )

    snippet_blocks = [
        format_numbered_snippet(snippet)
        for snippet in snippets
    ]

    strategy_block = f"\nRepair preference:\n{strategy_note}\n" if strategy_note else ""
    lesson_section = "\n".join(lesson_blocks) if lesson_blocks else "No retrieved examples.\n"

    system_prompt = (
        "You are an expert Python engineer fixing a large Python file with retrieval guidance.\n"
        "Return ONLY JSON with this shape:\n"
        "{\"edits\":[{\"start_line\":10,\"end_line\":12,\"original\":\"exact original text\",\"replacement\":\"new text\"}]}\n"
        "Rules:\n"
        "1. start_line and end_line are inclusive file line numbers from the snippets.\n"
        "2. original must be copied exactly from those file lines, without line-number prefixes.\n"
        "3. replacement must contain the complete replacement text for that line range.\n"
        "4. Use retrieved constraints as edit-pattern guidance, not as code to copy blindly.\n"
        "5. Make the smallest local edit that fixes the bug.\n"
        "6. Do not output the whole file.\n"
        "7. Prefer 1 edit; use at most 3 edits.\n"
        "8. Do not use search/replace keys.\n"
    )
    user_prompt = (
        f"Failure signal:\n{trimmed_description}\n"
        f"{strategy_block}\n"
        "Retrieved repair references:\n"
        f"{lesson_section}\n"
        "Candidate snippets from the file:\n\n"
        f"{chr(10).join(snippet_blocks)}\n\n"
        "Return the JSON edits now."
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ], snippets


def build_patch_retry_message(rejection_reason: str) -> dict:
    return {
        "role": "user",
        "content": (
            "The previous JSON patch was rejected before running tests.\n"
            f"Rejection reason: {rejection_reason}\n\n"
            "Return a corrected JSON patch using the same required schema:\n"
            "{\"edits\":[{\"start_line\":10,\"end_line\":12,\"original\":\"exact original text\",\"replacement\":\"new text\"}]}\n"
            "Rules:\n"
            "1. Use only line ranges from the snippets already shown.\n"
            "2. original must match those source lines exactly, except the final line ending may be omitted.\n"
            "3. Do not include line-number prefixes in original or replacement.\n"
            "4. Keep using the retrieved edit constraints as guidance.\n"
            "5. Return ONLY JSON."
        ),
    }


def generate_line_range_patch(
    buggy_code: str,
    messages: list[dict],
    model: str,
    temperature: float = 0,
    validation_retries: int = PATCH_VALIDATION_RETRIES,
):
    active_messages = list(messages)
    attempts: list[dict] = []
    patch_result = None
    for attempt_index in range(validation_retries + 1):
        response = safe_chat_completion(
            model=model,
            messages=active_messages,
            temperature=temperature,
            max_completion_tokens=PATCH_RESPONSE_TOKENS,
        )
        raw_response = response.choices[0].message.content
        patch_result = apply_line_range_response(buggy_code, raw_response)
        attempt_debug = patch_result.to_debug_dict()
        attempt_debug["patch_validation_attempt"] = attempt_index + 1
        attempts.append(attempt_debug)
        if patch_result.status == "applied":
            break
        if attempt_index >= validation_retries:
            break
        active_messages = [
            *active_messages,
            {"role": "assistant", "content": raw_response},
            build_patch_retry_message(patch_result.rejection_reason or "unknown reason"),
        ]
    return patch_result, attempts, active_messages


def serialize_retrieved_examples(examples: list[dict]) -> list[dict]:
    serialized: list[dict] = []
    for ex in examples[:MAX_RAG_EXAMPLES]:
        buggy_snippet, fixed_snippet = _focused_diff_snippet(
            ex.get("buggy_code", ""),
            ex.get("fixed_code", ex.get("correct_code", "")),
        )
        serialized.append(
            {
                "id": ex.get("id"),
                "metadata": ex.get("metadata", {}),
                "repair_metadata": ex.get("repair_metadata") or infer_repair_metadata(ex),
                "repair_lesson": _infer_repair_lesson(ex),
                "buggy_snippet": buggy_snippet,
                "fixed_snippet": fixed_snippet,
            }
        )
    return serialized

# ============================================================================
# Main RAG repair function
# ============================================================================
def repair_with_rag(
    buggy_code: str,
    description: str = "",
    k=MAX_RAG_EXAMPLES,
    model: str | None = None,
    retrieval_profile: str | None = None,
    index_dir: str | None = None,
    retrieval_variant: str = "structured",
    failure_state: dict | None = None,
    generation_temperature: float = 0,
    strategy_note: str = "",
    return_debug: bool = False,
    disabled_components: frozenset[str] | None = None,
):
    examples_result = retrieve_examples(
        buggy_code,
        failure_signal=description,
        k=k,
        retrieval_profile=retrieval_profile,
        index_dir=index_dir,
        retrieval_variant=retrieval_variant,
        failure_state=failure_state,
        return_debug=return_debug,
        disabled_components=disabled_components,
    )
    if return_debug:
        examples, retrieval_debug = examples_result
    else:
        examples = examples_result
        retrieval_debug = None

    if len(buggy_code) > MAX_FULL_CODE_CHARS:
        messages, snippets = build_large_file_patch_prompt_with_strategy(
            buggy_code=buggy_code,
            description=description,
            examples=examples,
            strategy_note=strategy_note,
        )
        patch_result, patch_attempts, final_messages = generate_line_range_patch(
            buggy_code=buggy_code,
            messages=messages,
            model=model or DEFAULT_MODEL,
            temperature=generation_temperature,
        )
        repaired_code = patch_result.code
        if return_debug:
            patch_debug = patch_result.to_debug_dict()
            return {
                "code": repaired_code,
                "prompt": final_messages[-1]["content"],
                "messages": final_messages,
                "retrieved_examples": serialize_retrieved_examples(examples),
                "patch_snippets": snippets,
                "patch_schema_version": PATCH_SCHEMA_VERSION,
                "patch_validation_retries": PATCH_VALIDATION_RETRIES,
                "patch_attempts": patch_attempts,
                **patch_debug,
                "generation_temperature": generation_temperature,
                "strategy_note": strategy_note,
                "retrieval_variant": retrieval_variant,
                "retrieval_debug": retrieval_debug,
                "failure_state": (retrieval_debug or {}).get("failure_state"),
            }
        return repaired_code

    prompt = build_repair_prompt_with_strategy(
        buggy_code=buggy_code,
        description=f"Description (optional): {_truncate_description(description)}\n\n" if description else "",
        examples=examples,
        strategy_note=strategy_note,
    )

    response = safe_chat_completion(
        model=model or DEFAULT_MODEL,
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=generation_temperature,
        max_completion_tokens=_estimate_completion_tokens(buggy_code),
    )

    repaired_code = _strip_code_fences(response.choices[0].message.content)
    if return_debug:
        return {
            "code": repaired_code,
            "prompt": prompt,
            "messages": [{"role": "user", "content": prompt}],
            "retrieved_examples": serialize_retrieved_examples(examples),
            "generation_temperature": generation_temperature,
            "strategy_note": strategy_note,
            "retrieval_variant": retrieval_variant,
            "retrieval_debug": retrieval_debug,
            "failure_state": (retrieval_debug or {}).get("failure_state"),
        }
    return repaired_code

# Test run
if __name__ == "__main__":
    test_bug = """
def square(n):
    return n ** 3   # BUG
"""
    print(repair_with_rag(test_bug))
