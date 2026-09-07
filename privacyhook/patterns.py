"""Regex patterns for secret and PII detection.

Patterns lifted from Iris's privacy_filter.py and workspace_guard.py (battle-tested
in production). Categories map to lowercase keys used as token labels in the
[WALL:<category>:<n>] format.
"""

from __future__ import annotations

import math
import re
from collections import Counter

# Categories that match a specific structured secret (high confidence).
SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "private_key_block": re.compile(
        r"-----BEGIN [A-Z ]+-----[\s\S]*?-----END [A-Z ]+-----"
    ),
    "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b"),
    "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{40,}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{10,}\b"),
    "jwt": re.compile(
        r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+\b"
    ),
}

# Categories that match PII (often contextual / lower confidence).
PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
    ),
    "private_ip": re.compile(
        r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        r"|192\.168\.\d{1,3}\.\d{1,3})\b"
    ),
    "internal_hostname": re.compile(
        r"\b[\w][\w.\-]*\.(?:internal|local|corp|intranet|lan)\b",
        re.IGNORECASE,
    ),
    "phone_fr": re.compile(
        r"(?:(?:\+|00)33[\s.\-]?|0)[1-9](?:[\s.\-]?\d{2}){4}\b"
    ),
}

# Filenames considered sensitive regardless of location.
SENSITIVE_FILENAMES: frozenset[str] = frozenset({
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.staging",
    ".env.test",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    ".netrc",
    ".pgpass",
    ".boto",
    "credentials",
    "secrets",
    "secrets.json",
    "service-account.json",
    "keyfile.json",
    ".npmrc",
    ".pypirc",
    "terraform.tfvars",
    "terraform.tfstate",
})

# Directories never scanned and whose contents are treated as sensitive.
SENSITIVE_DIRS: frozenset[str] = frozenset({
    ".git",
    ".ssh",
    ".aws",
    ".gnupg",
    ".gpg",
    ".terraform",
    ".kube",
    ".docker",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
})

# Suffixes that mark a file as a credential / key bundle.
SENSITIVE_SUFFIXES: frozenset[str] = frozenset({
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".crt",
    ".cer",
    ".der",
    ".jks",
    ".keystore",
})

# Heuristic high-entropy fallback for keys that don't match a known prefix.
_MIN_ENTROPY_KEY_LEN = 24
_MIN_ENTROPY_THRESHOLD = 3.5
_GENERIC_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_\-]{24,}\b")


def _entropy(s: str) -> float:
    if len(s) < 8:
        return 0.0
    counts = Counter(s)
    total = len(s)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def _looks_like_key(s: str) -> bool:
    if len(s) < _MIN_ENTROPY_KEY_LEN:
        return False
    has_lower = any(c.islower() for c in s)
    has_upper = any(c.isupper() for c in s)
    has_digit = any(c.isdigit() for c in s)
    if not (has_lower and has_upper and has_digit):
        return False
    return _entropy(s) >= _MIN_ENTROPY_THRESHOLD


def categorize_match(text: str) -> list[tuple[str, str, int, int]]:
    """Scan text and return all detected secret/PII matches.

    Returns list of (category, matched_text, start, end). Overlapping matches
    are deduplicated by start position, with structured-secret categories taking
    precedence over PII / generic high-entropy.
    """
    seen: dict[int, tuple[str, str, int, int]] = {}

    def _add(cat: str, m: re.Match[str]) -> None:
        start, end = m.start(), m.end()
        if start in seen:
            return
        for existing_start in list(seen.keys()):
            existing = seen[existing_start]
            if not (end <= existing[2] or start >= existing[3]):
                return
        seen[start] = (cat, m.group(0), start, end)

    for category, pat in SECRET_PATTERNS.items():
        for m in pat.finditer(text):
            _add(category, m)

    for category, pat in PII_PATTERNS.items():
        for m in pat.finditer(text):
            _add(category, m)

    for m in _GENERIC_TOKEN_RE.finditer(text):
        if _looks_like_key(m.group(0)):
            _add("generic_secret", m)

    return sorted(seen.values(), key=lambda t: t[2])
