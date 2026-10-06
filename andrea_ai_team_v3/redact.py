from __future__ import annotations

"""Credential redaction shared by the job store, the builder and the write gate."""

import re
from typing import Any

# --------------------------------------------------------------------------

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"),                      # Telegram bot token
    re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}\b"),             # OpenAI / Anthropic keys
    re.compile(r"\bxai-[A-Za-z0-9_-]{16,}\b"),                           # xAI keys
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),                           # Google API keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),                       # GitHub tokens
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                                 # AWS access key id
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b"),  # JWT
    re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r'(?i)"([a-z0-9_-]*(?:token|secret|passw(?:or)?d|api[_-]?key|credential)[a-z0-9_-]*)"\s*:\s*"[^"]*"'),
    re.compile(
        r"(?i)\b([A-Z0-9_]*(?:api[_-]?key|token|secret|passw(?:or)?d|pwd|credential|auth)[A-Z0-9_]*)"
        r"(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
    ),
)


def sanitize(text: Any, limit: int = 4000) -> str:
    """Remove anything that looks like a credential and bound the length."""
    if text is None:
        return ""
    out = str(text).replace("\x00", "")
    for pattern in _SECRET_PATTERNS:
        if pattern.groups == 1 and pattern.pattern.startswith('(?i)"('):
            out = pattern.sub(lambda m: f'"{m.group(1)}": "[REDACTED]"', out)
        elif pattern.groups >= 3:
            out = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", out)
        else:
            out = pattern.sub("[REDACTED]", out)
    if len(out) > limit:
        out = out[: limit - 15] + "…[troncato]"
    return out
