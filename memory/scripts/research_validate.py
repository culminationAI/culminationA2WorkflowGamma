#!/usr/bin/env python3
"""Research data validator — runs before pushing to research-data repo.

Usage:
    python3 memory/scripts/research_validate.py research/build-up/
    python3 memory/scripts/research_validate.py research/build-up/2026-03-02-correction.json
    python3 memory/scripts/research_validate.py --check research/build-up/
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_TYPES = {"correction", "routing", "workflow", "protocol_created"}

MAX_SUMMARY_LEN = 500
MAX_METRICS_FIELD_LEN = 200
MAX_RECORD_BYTES = 2048
WARN_SUMMARY_LEN = 300

REQUIRED_FIELDS = {"type", "version", "summary", "metrics", "timestamp"}
ALLOWED_FIELDS = REQUIRED_FIELDS  # no extra fields permitted

# PII detection patterns — key is a human-readable label, value is a compiled regex
PII_PATTERNS = {
    "email pattern": re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
    "unix home path (/Users/)": re.compile(r"/Users/"),
    "unix home path (/home/)": re.compile(r"/home/"),
    "windows path (C:\\)": re.compile(r"C:\\\\"),
    "windows path (C:/)": re.compile(r"C:/"),
    "API key (sk-)": re.compile(r"sk-"),
    "GitHub token (ghp_)": re.compile(r"ghp_"),
    "AWS key (AKIA)": re.compile(r"AKIA"),
    "bearer token": re.compile(r"Bearer "),
    "token= query param": re.compile(r"token="),
    "IP address": re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    "URL with credentials": re.compile(r"://[^/]*:[^/]*@"),
    "URL with ?token=": re.compile(r"\?token="),
    "URL with ?key=": re.compile(r"\?key="),
}

# Prompt injection / Cypher / SQL injection patterns
INJECTION_PATTERNS = {
    "role marker <|system|>": re.compile(r"<\|system\|>", re.IGNORECASE),
    "role marker <|user|>": re.compile(r"<\|user\|>", re.IGNORECASE),
    "role marker <|assistant|>": re.compile(r"<\|assistant\|>", re.IGNORECASE),
    "role marker [INST]": re.compile(r"\[INST\]", re.IGNORECASE),
    "role marker <<SYS>>": re.compile(r"<<SYS>>", re.IGNORECASE),
    "manipulation: ignore previous": re.compile(r"ignore previous", re.IGNORECASE),
    "manipulation: ignore above": re.compile(r"ignore above", re.IGNORECASE),
    "manipulation: you are now": re.compile(r"you are now", re.IGNORECASE),
    "manipulation: disregard": re.compile(r"disregard", re.IGNORECASE),
    "manipulation: forget everything": re.compile(r"forget everything", re.IGNORECASE),
    "manipulation: new instructions": re.compile(r"new instructions", re.IGNORECASE),
    "code: triple backticks": re.compile(r"```"),
    "code: <script": re.compile(r"<script", re.IGNORECASE),
    "code: eval(": re.compile(r"eval\(", re.IGNORECASE),
    "code: exec(": re.compile(r"exec\(", re.IGNORECASE),
    "code: __import__": re.compile(r"__import__"),
    "cypher: MERGE": re.compile(r"\bMERGE\b"),
    "cypher: CREATE": re.compile(r"\bCREATE\b"),
    "cypher: DELETE": re.compile(r"\bDELETE\b"),
    "cypher: DETACH": re.compile(r"\bDETACH\b"),
    "cypher: SET": re.compile(r"\bSET "),
    "cypher: REMOVE": re.compile(r"\bREMOVE\b"),
    "cypher: DROP": re.compile(r"\bDROP\b"),
    "cypher: CALL dbms": re.compile(r"CALL dbms", re.IGNORECASE),
    "cypher: CALL apoc": re.compile(r"CALL apoc", re.IGNORECASE),
    "sql: DROP TABLE": re.compile(r"DROP\s+TABLE", re.IGNORECASE),
    "sql: DELETE FROM": re.compile(r"DELETE\s+FROM", re.IGNORECASE),
    "sql: UNION SELECT": re.compile(r"UNION\s+SELECT", re.IGNORECASE),
    "sql: INSERT INTO": re.compile(r"INSERT\s+INTO", re.IGNORECASE),
    "sql: UPDATE...SET": re.compile(r"UPDATE\s+\S+\s+SET", re.IGNORECASE),
}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_schema(record: dict) -> List[str]:
    """Check required fields, allowed types, and field formats.

    Returns a list of error strings (empty = all OK).
    """
    errors: List[str] = []

    # 1. Required fields present
    missing = REQUIRED_FIELDS - record.keys()
    if missing:
        errors.append(f"Missing required fields: {', '.join(sorted(missing))}")

    # 2. No extra fields
    extra = record.keys() - ALLOWED_FIELDS
    if extra:
        errors.append(f"Extra fields not allowed: {', '.join(sorted(extra))}")

    # 3. type value
    record_type = record.get("type")
    if record_type is not None and record_type not in ALLOWED_TYPES:
        errors.append(
            f"Invalid type '{record_type}'. Allowed: {', '.join(sorted(ALLOWED_TYPES))}"
        )

    # 4. version pattern
    version = record.get("version")
    if version is not None:
        if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+", version):
            errors.append(
                f"Invalid version '{version}'. Must match \\d+\\.\\d+ (e.g. 1.0)"
            )

    # 5. timestamp — valid ISO8601
    timestamp = record.get("timestamp")
    if timestamp is not None:
        if not isinstance(timestamp, str):
            errors.append("timestamp must be a string")
        else:
            try:
                # Python 3.9 fromisoformat() doesn't support 'Z' suffix
                ts = timestamp.replace("Z", "+00:00")
                datetime.fromisoformat(ts)
            except ValueError:
                errors.append(f"Invalid ISO8601 timestamp: '{timestamp}'")

    # 6. metrics must be a dict; optional before/after must be strings
    metrics = record.get("metrics")
    if metrics is not None:
        if not isinstance(metrics, dict):
            errors.append("metrics must be a JSON object")
        else:
            for field in ("before", "after"):
                val = metrics.get(field)
                if val is not None and not isinstance(val, str):
                    errors.append(f"metrics.{field} must be a string")

    # 7. summary must be a string
    summary = record.get("summary")
    if summary is not None and not isinstance(summary, str):
        errors.append("summary must be a string")

    return errors


def validate_sizes(
    record: dict, raw_bytes: int
) -> Tuple[List[str], List[str]]:
    """Check size limits.

    Returns (errors, warnings).
    """
    errors: List[str] = []
    warnings: List[str] = []

    # Total record size
    if raw_bytes > MAX_RECORD_BYTES:
        errors.append(
            f"Record size {raw_bytes} bytes exceeds max {MAX_RECORD_BYTES} bytes (2 KB)"
        )

    # summary length
    summary = record.get("summary", "")
    if isinstance(summary, str):
        summary_len = len(summary)
        if summary_len > MAX_SUMMARY_LEN:
            errors.append(
                f"summary is {summary_len} chars (max {MAX_SUMMARY_LEN})"
            )
        elif summary_len > WARN_SUMMARY_LEN:
            warnings.append(
                f"Summary is {summary_len} chars (recommended max {WARN_SUMMARY_LEN})"
            )

    # metrics field lengths
    metrics = record.get("metrics")
    if isinstance(metrics, dict):
        for field in ("before", "after"):
            val = metrics.get(field, "")
            if isinstance(val, str) and len(val) > MAX_METRICS_FIELD_LEN:
                errors.append(
                    f"metrics.{field} is {len(val)} chars (max {MAX_METRICS_FIELD_LEN})"
                )

    return errors, warnings


def check_pii(text: str) -> List[str]:
    """Scan a text string for PII patterns.

    Returns a list of human-readable descriptions for each hit.
    """
    found: List[str] = []
    for label, pattern in PII_PATTERNS.items():
        if pattern.search(text):
            found.append(f"PII detected: {label}")
    return found


def check_injection(text: str) -> List[str]:
    """Scan a text string for prompt/code/Cypher/SQL injection patterns.

    Returns a list of human-readable descriptions for each hit.
    """
    found: List[str] = []
    for label, pattern in INJECTION_PATTERNS.items():
        if pattern.search(text):
            found.append(f"Injection pattern detected: {label}")
    return found


def _collect_text_values(record: dict) -> str:
    """Flatten all string values from a record into a single string for scanning."""
    parts: List[str] = []

    def _walk(obj: object) -> None:
        if isinstance(obj, str):
            parts.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(record)
    return " ".join(parts)


def validate_content_quality(record: dict) -> Tuple[List[str], List[str]]:
    """Check content quality of the summary field.

    Returns (errors, warnings).
    """
    errors: List[str] = []
    warnings: List[str] = []

    summary = record.get("summary", "")
    if not isinstance(summary, str):
        return errors, warnings  # already caught by schema check

    # Empty or whitespace-only
    if not summary.strip():
        errors.append("summary is empty or whitespace-only")
        return errors, warnings

    # Repeated character check — if >80% of non-space chars are the same char
    cleaned = summary.replace(" ", "")
    if cleaned:
        most_common_count = max(cleaned.count(c) for c in set(cleaned))
        if most_common_count / len(cleaned) > 0.8 and len(cleaned) > 4:
            errors.append("summary appears to be just repeated characters")

    return errors, warnings


# ---------------------------------------------------------------------------
# Top-level record and file validators
# ---------------------------------------------------------------------------


def validate_record(
    record: dict, raw_bytes: int
) -> Tuple[List[str], List[str]]:
    """Run all checks on a parsed record dict.

    Returns (errors, warnings).
    """
    all_errors: List[str] = []
    all_warnings: List[str] = []

    # Schema
    schema_errors = validate_schema(record)
    all_errors.extend(schema_errors)

    # Sizes
    size_errors, size_warnings = validate_sizes(record, raw_bytes)
    all_errors.extend(size_errors)
    all_warnings.extend(size_warnings)

    # PII — scan all string values
    text = _collect_text_values(record)
    pii_errors = check_pii(text)
    all_errors.extend(pii_errors)

    # Injection — scan all string values
    injection_errors = check_injection(text)
    all_errors.extend(injection_errors)

    # Content quality
    quality_errors, quality_warnings = validate_content_quality(record)
    all_errors.extend(quality_errors)
    all_warnings.extend(quality_warnings)

    return all_errors, all_warnings


def validate_file(path: Path) -> Tuple[bool, List[str], List[str]]:
    """Validate a single JSON file.

    Returns (passed, errors, warnings).
    - passed is True only when errors is empty.
    """
    errors: List[str] = []
    warnings: List[str] = []

    # Read raw bytes (needed for size check)
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        return False, [f"Cannot read file: {exc}"], []

    raw_size = len(raw_bytes)

    # Parse JSON
    try:
        record = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        return False, [f"Invalid JSON: {exc}"], []

    if not isinstance(record, dict):
        return False, ["Record must be a JSON object (dict), not a list or scalar"], []

    # Run all validators
    rec_errors, rec_warnings = validate_record(record, raw_size)
    errors.extend(rec_errors)
    warnings.extend(rec_warnings)

    passed = len(errors) == 0
    return passed, errors, warnings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _collect_json_files(target: Path) -> List[Path]:
    """Return sorted list of .json files from a file or directory path."""
    if target.is_file():
        return [target]
    if target.is_dir():
        return sorted(target.glob("*.json"))
    return []


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate research build-up records before pushing to research-data repo."
    )
    parser.add_argument(
        "target",
        help="Path to a JSON file or directory containing JSON files",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Dry-run mode: validate only, no changes to any files",
    )
    args = parser.parse_args()

    target = Path(args.target)

    if not target.exists():
        print(f"Error: path does not exist: {target}", file=sys.stderr)
        sys.exit(1)

    files = _collect_json_files(target)

    if not files:
        print(f"No JSON files found at: {target}", file=sys.stderr)
        sys.exit(1)

    passed_count = 0
    failed_count = 0
    warned_count = 0

    for file_path in files:
        passed, errors, warnings = validate_file(file_path)

        if not passed:
            failed_count += 1
            print(f"[FAIL] {file_path}")
            for err in errors:
                print(f"  - {err}")
            # Also show warnings alongside errors
            for warn in warnings:
                print(f"  ~ {warn}")
        elif warnings:
            warned_count += 1
            passed_count += 1
            print(f"[WARN] {file_path}")
            for warn in warnings:
                print(f"  - {warn}")
        else:
            passed_count += 1
            print(f"[PASS] {file_path}")

    print()
    parts = [f"{passed_count} passed", f"{failed_count} failed"]
    if warned_count:
        parts.append(f"{warned_count} warning{'s' if warned_count != 1 else ''}")
    print(f"Results: {', '.join(parts)}")

    if failed_count > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
