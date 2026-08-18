"""v1.6.105 — best-effort vendor extraction from README text.

Closes GitHub issue #37 (P3): Phase 1 (doc-extraction) v1.6.103 emitted
``L1.ordering_info.vendor = "see datasheet"`` as a hardcoded
placeholder on 10/10 thin-input ICs whose README did not match
``_infer_vendor``'s manufacturer-anchored patterns. That placeholder
is the same scaffolded-default anti-pattern as the L7
``engineer_mode_unlock_sequence`` placeholder closed by issue #15
(switched to ``null`` + ``no_engineer_mode_unlock_sequence_in_input``)
and the L11 OTP placeholder closed by issue #19.

This module adds five small heuristics so thin-input README files
that DO carry a vendor signal (SPDX copyright header, plain
``Copyright (C)`` line, ``Maintained|Authored|Designed by`` line,
markdown ``Maintainer: [name](url)`` link, or a
``github.com/<org>/<repo>`` badge) yield a real vendor token rather
than a placeholder. When no signal is present the caller is expected
to emit ``vendor: null`` + ``no_vendor_in_input: true`` per the
sibling-issue null+flag convention.

Chip-AGNOSTIC: pure regex over README prose, no project-specific
paths or vendor-name allow-lists.
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple


# SPDX-FileCopyrightText: <year> <vendor> [<email>]
_SPDX_COPYRIGHT_RE = re.compile(
    r"SPDX-FileCopyrightText:\s*(?:\d{4}\s+)?"
    r"([A-Za-z][A-Za-z0-9_.\-\s]{1,60}?)(?:\s*<|\s*$|\s*,)",
    re.MULTILINE,
)

# (C) <year> <vendor>  /  Copyright (C) <year> <vendor>
_COPYRIGHT_RE = re.compile(
    r"(?:Copyright\s+)?\(c\)\s*(?:\d{4}\s+)?"
    r"([A-Za-z][A-Za-z0-9_.\-\s]{1,60}?)"
    r"(?:\s*<|\s*$|\s*,|\s*\.)",
    re.IGNORECASE | re.MULTILINE,
)

# "Maintained by <name>" / "Author(s): <name>" / "Designed by <name>"
_AUTHOR_LINE_RE = re.compile(
    r"(?:Maintained|Authored|Designed|Developed)\s+by\s+"
    r"\[?([A-Za-z][A-Za-z0-9_.\-\s]{1,60}?)\]?"
    r"(?:\s*\(|\s*<|\s*$)",
    re.IGNORECASE | re.MULTILINE,
)


# v1.6.393 — for #284 P3 ORGANIC. The legacy `_AUTHOR_LINE_RE`
# non-greedy `{1,60}?` quantifier slid past the vendor name into
# trailing prose when the line contained continuation conjunctions
# / prepositions (e.g. `Maintained by Acme Labs but is not part of
# X` captured the whole prose tail). Without a stop-word lookahead
# the non-greedy `?` happily extends rightward when it cannot match
# the trailing `( | < | $` anchors immediately.
#
# Fix: replace the trailing anchor with a stop-word lookahead group
# covering common English continuation conjunctions / prepositions,
# punctuation, and the legacy `( | < | $` terminators. Companion
# `_v1_6_393_trim_vendor_capture` caps the capture to the first 4
# whitespace tokens and strips trailing punctuation so even in the
# pathological case the emitted vendor stays short and clean.
#
# Legacy `_AUTHOR_LINE_RE` is kept defined above for backward
# compat (any external pinned test still imports it). Call sites
# switch to `_V1_6_393_AUTHOR_LINE_RE`.
#
# Chip-AGNOSTIC: pure English-prose grammar; no chip-class string
# literal participates.
_V1_6_393_AUTHOR_LINE_RE = re.compile(
    r"(?:Maintained|Authored|Designed|Developed)\s+by\s+"
    r"\[?(?P<vendor>[A-Za-z][A-Za-z0-9_.\-\s]{1,60}?)\]?"
    r"(?="
    r"\s+(?:but|and|who|which|that|since|for|on|in|to|via|"
    r"although|despite|including|with|under|as)\b"
    r"|\s*[,;.:]"
    r"|\s*\("
    r"|\s*<"
    r"|\s*$"
    r")",
    re.IGNORECASE | re.MULTILINE,
)


def _v1_6_393_trim_vendor_capture(raw: str) -> str:
    """v1.6.393 — for #284 P3 ORGANIC. Cap the captured vendor to
    the first 4 whitespace-separated tokens and strip trailing
    punctuation. Defence-in-depth in case the stop-word lookahead
    misses a previously unseen continuation idiom.

    Chip-AGNOSTIC: pure structural string operation.
    """
    tokens = (raw or "").strip().split()
    capped = " ".join(tokens[:4])
    return capped.rstrip(".,;:")

# Markdown link: "Maintainer: [<name>](<url>)" / "Author: [<name>](<url>)"
_AUTHORSHIP_LINK_RE = re.compile(
    r"(?:Maintainer|Author|Vendor|Designed\s+by)\s*:\s*"
    r"\[([A-Za-z][A-Za-z0-9_.\-\s]{1,60}?)\]\(",
    re.IGNORECASE | re.MULTILINE,
)

# GitHub badge URL: github.com/<org>/<repo>
_GITHUB_ORG_RE = re.compile(
    r"github\.com[:/]([A-Za-z][A-Za-z0-9_.\-]{1,40})/[A-Za-z]",
)


_JUNK_TOKENS = {
    "todo", "tbd", "tba", "see", "the", "a", "an", "n/a", "na",
    "unknown", "anonymous",
}


def _clean(token: str) -> str:
    """Trim whitespace and dangling punctuation from a vendor token."""
    return token.strip().rstrip(",.;:")


def _is_junk(vendor: str) -> bool:
    if len(vendor) < 2:
        return True
    if vendor.lower() in _JUNK_TOKENS:
        return True
    # All-numeric / all-punctuation tokens are noise.
    if not re.search(r"[A-Za-z]", vendor):
        return True
    return False


def extract_vendor(
    readme_text: str,
) -> Tuple[Optional[str], Optional[Dict]]:
    """Return ``(vendor_name, evidence_dict)`` on first match, else
    ``(None, None)``.

    Patterns are tried in priority order:

      1. ``SPDX-FileCopyrightText:`` (highest signal)
      2. ``Copyright (C)`` line
      3. Markdown ``Maintainer: [name](url)`` authorship link
      4. ``Maintained|Authored|Designed by <name>`` line
      5. ``github.com/<org>/<repo>`` badge (low confidence)

    The evidence dict carries ``source``, ``line``, ``matched_token``,
    and ``extraction_strategy``. When the GitHub-badge fall-through
    fires, the evidence dict additionally carries
    ``low_confidence: True`` so downstream gates can flag the field
    for human review.
    """
    if not readme_text:
        return None, None

    # v1.6.393 — for #284 P3 ORGANIC. Replaced `_AUTHOR_LINE_RE`
    # with `_V1_6_393_AUTHOR_LINE_RE` (stop-word lookahead) so the
    # non-greedy capture can no longer slide past the vendor name
    # into trailing prose. Each capture also passes through
    # `_v1_6_393_trim_vendor_capture` for defence-in-depth word-
    # cap + trailing-punctuation strip.
    patterns = [
        (_SPDX_COPYRIGHT_RE, "spdx_copyright_match", False),
        (_COPYRIGHT_RE, "copyright_line_match", False),
        (_AUTHORSHIP_LINK_RE, "authorship_link_match", False),
        (_V1_6_393_AUTHOR_LINE_RE, "author_line_match_v1_6_393", False),
        (_GITHUB_ORG_RE, "github_badge_org_match", True),
    ]

    lines = readme_text.split("\n")
    for pattern, strategy, low_conf in patterns:
        for lineno, line in enumerate(lines, start=1):
            m = pattern.search(line)
            if not m:
                continue
            # v1.6.393 — for #284: the author-line regex uses a
            # named `vendor` capture group; fall back to group(1)
            # for the other patterns. Then apply the v1.6.393
            # word-cap + punctuation-strip helper.
            if "vendor" in pattern.groupindex:
                raw = m.group("vendor")
            else:
                raw = m.group(1)
            vendor = _v1_6_393_trim_vendor_capture(_clean(raw or ""))
            if _is_junk(vendor):
                continue
            evidence = {
                "source": "input/docs/README.md",
                "line": lineno,
                "matched_token": m.group(0)[:80],
                "extraction_strategy": strategy,
            }
            if low_conf:
                evidence["low_confidence"] = True
            return vendor, evidence

    return None, None
