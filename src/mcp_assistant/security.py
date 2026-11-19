"""Security helpers: secret redaction, prompt-injection scanning, read-only SQL guard.

These are heuristics -- defence in depth, not a guarantee. The real protections are the
permission policy, the human approval step, the sandboxed servers and least-privilege
credentials.
"""
from __future__ import annotations

import re
from typing import Any

# --------------------------------------------------------------------------- secrets
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "[REDACTED_GOOGLE_KEY]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"\bxox[abprs]-[0-9A-Za-z\-]{10,}"), "[REDACTED_SLACK_TOKEN]"),
    (re.compile(r"\bgh[pousr]_[0-9A-Za-z]{30,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\b(?:secret|ntn)_[0-9A-Za-z]{30,}"), "[REDACTED_NOTION_TOKEN]"),
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{20,}"), r"\1 [REDACTED]"),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@"), r"\1[REDACTED]@"),  # user:password@ in URLs
]
_SENSITIVE_KEY = re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key|authorization|cookie)")


def redact_secrets(text: str) -> str:
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def redact_args(obj: Any) -> Any:
    """Return a copy of tool arguments that is safe to write to the audit log."""
    if isinstance(obj, dict):
        return {
            k: ("[REDACTED]" if _SENSITIVE_KEY.search(str(k)) else redact_args(v)) for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_args(v) for v in obj]
    if isinstance(obj, str):
        return redact_secrets(obj)
    return obj


# --------------------------------------------------------------------- prompt injection
_INJECTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)ignore (all |any |the )?(previous|prior|above|earlier) (instructions|prompts?|rules)"), "override-instructions"),
    (re.compile(r"(?i)disregard (the |all |your )?(system|previous|prior) (prompt|instructions?)"), "override-instructions"),
    (re.compile(r"(?i)\bnew (system )?instructions?\s*:"), "new-instructions"),
    (re.compile(r"(?i)\byou are now\b"), "role-reassignment"),
    (re.compile(r"(?i)(send|email|forward|post|upload|exfiltrate)\b.{0,80}\b(password|api[_ -]?key|credentials?|secrets?|tokens?)"), "exfiltration"),
    (re.compile(r"(?i)do not (tell|inform|alert|notify) the user"), "concealment"),
    (re.compile(r"(?i)<\s*/?\s*(system|assistant|developer)\s*>"), "fake-role-tag"),
]


def injection_scan(text: str) -> list[str]:
    """Names of injection heuristics that matched (empty list = nothing suspicious)."""
    return sorted({name for pattern, name in _INJECTION_PATTERNS if pattern.search(text)})


# ------------------------------------------------------------------ read-only SQL guard
_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|merge|grant|revoke|attach|detach|pragma|"
    r"vacuum|reindex|call|exec|execute|copy|into|load_extension)\b|\breplace\s+into\b",
    re.I,
)
_ALLOWED_START = re.compile(r"(?is)^\s*(select|with|explain|show|describe)\b")


def assert_read_only(sql: str) -> str:
    """Raise ValueError unless ``sql`` is a single read-only statement; return it cleaned."""
    cleaned = _COMMENT.sub(" ", sql).strip().rstrip(";").strip()
    if not cleaned:
        raise ValueError("Empty SQL statement.")
    if ";" in cleaned:
        raise ValueError("Only a single SQL statement is allowed.")
    if not _ALLOWED_START.match(cleaned):
        raise ValueError("Only SELECT / WITH / EXPLAIN queries are allowed here.")
    hit = _FORBIDDEN.search(cleaned)
    if hit:
        raise ValueError(f"Keyword '{hit.group(0)}' is not allowed in read-only mode.")
    return cleaned
