# src/models/repair_baseline.py

import os
import time
import random
import json
import re
import difflib
from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError
from dotenv import load_dotenv
from src.models.patch_utils import (
    PATCH_SCHEMA_VERSION,
    apply_line_range_response,
    format_numbered_snippet,
    select_patch_snippets,
)

# Load environment variables (explicit env vars take precedence over .env,
# so a per-run OPENAI_API_KEY / OPENAI_BASE_URL can target another provider)
load_dotenv(override=False)

# Placeholder key keeps import safe in keyless contexts (matrix generation,
# corpus building, --list-supported); real API calls still require a key.
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY") or "KEY_NOT_SET",
    base_url=os.getenv("OPENAI_BASE_URL") or None,
    max_retries=0,
)
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("OPENAI_REQUEST_TIMEOUT", "30"))
MAX_API_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "3"))
MAX_DESCRIPTION_CHARS = 4000
MAX_FULL_CODE_CHARS = 40000
MAX_PATCH_SNIPPETS = 4
PATCH_WINDOW_LINES = 160
PATCH_WINDOW_STRIDE = 100
PATCH_RESPONSE_TOKENS = 3000
PATCH_FUZZY_MIN_RATIO = 0.93
PATCH_FUZZY_MIN_MARGIN = 0.03
PATCH_VALIDATION_RETRIES = int(os.getenv("PATCH_VALIDATION_RETRIES", "1"))
IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


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

def build_repair_messages(buggy_code: str, description: str = "") -> list[dict]:
    trimmed_description = _truncate_description(description.strip()) if description else ""
    system_prompt = (
        "You are an expert Python engineer. "
        "Your task is to FIX the following buggy Python code.\n"
        "STRICT RULES:\n"
        "1. Output ONLY corrected Python code.\n"
        "2. NO explanation, NO comments, NO markdown.\n"
        "3. Preserve the same function name.\n"
        "4. Ensure the code is runnable.\n"
    )

    user_prompt = (
        f"Buggy code:\n{buggy_code}\n\n"
        f"Optional description:\n{trimmed_description}\n\n"
        "Please provide the FIXED code:"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def build_large_file_patch_messages(buggy_code: str, description: str = "") -> tuple[list[dict], list[dict]]:
    trimmed_description = _truncate_description(description.strip(), max_chars=2500) if description else ""
    snippets = _select_patch_snippets(buggy_code, trimmed_description)
    snippet_blocks = []
    for snippet in snippets:
        snippet_blocks.append(format_numbered_snippet(snippet))

    system_prompt = (
        "You are an expert Python engineer fixing a large Python file.\n"
        "Return ONLY JSON with this shape:\n"
        "{\"edits\":[{\"start_line\":10,\"end_line\":12,\"original\":\"exact original text\",\"replacement\":\"new text\"}]}\n"
        "Rules:\n"
        "1. start_line and end_line are inclusive file line numbers from the snippets.\n"
        "2. original must be copied exactly from those file lines, without line-number prefixes.\n"
        "3. replacement must contain the complete replacement text for that line range.\n"
        "4. Make the smallest local edit that fixes the bug.\n"
        "5. Do not output the whole file.\n"
        "6. Prefer 1 edit; use at most 3 edits.\n"
        "7. Do not use search/replace keys.\n"
    )
    user_prompt = (
        f"Failure signal:\n{trimmed_description}\n\n"
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
            "4. Return ONLY JSON."
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


def repair_without_rag(
    buggy_code: str,
    description: str = "",
    model: str | None = None,
    return_debug: bool = False,
):
    """
    Baseline repair:
    - Takes buggy code
    - Optionally takes a problem description
    - Returns FIXED code (no retrieval)
    """

    if len(buggy_code) > MAX_FULL_CODE_CHARS:
        messages, snippets = build_large_file_patch_messages(buggy_code, description)
        patch_result, patch_attempts, final_messages = generate_line_range_patch(
            buggy_code=buggy_code,
            messages=messages,
            model=model or DEFAULT_MODEL,
            temperature=0,
        )
        repaired_code = patch_result.code
        if return_debug:
            patch_debug = patch_result.to_debug_dict()
            return {
                "code": repaired_code,
                "prompt": final_messages[-1]["content"],
                "messages": final_messages,
                "patch_snippets": snippets,
                "patch_schema_version": PATCH_SCHEMA_VERSION,
                "patch_validation_retries": PATCH_VALIDATION_RETRIES,
                "patch_attempts": patch_attempts,
                **patch_debug,
            }
        return repaired_code

    messages = build_repair_messages(buggy_code, description)

    response = safe_chat_completion(
        model=model or DEFAULT_MODEL,
        messages=messages,
        temperature=0,
        max_completion_tokens=_estimate_completion_tokens(buggy_code),
    )

    repaired_code = _strip_code_fences(response.choices[0].message.content)
    if return_debug:
        return {
            "code": repaired_code,
            "messages": messages,
        }
    return repaired_code
