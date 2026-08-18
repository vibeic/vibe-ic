"""v1.6.115 — for #36 Bug 8: SD-spec CMD table picker.

Field-agent verbatim spec (issue #36 Bug 8):

  Apply to: litesdcard
  Pattern: lines under "SD commands" / "SD init" heading matching
    ``(CMD|ACMD)\\d+\\s+-\\s*.*$``
  E.g. ``CMD0 - Reset``, ``ACMD41 - SD_SEND_OP_COND``,
        ``CMD7 - SELECT_CARD``
  Output: L3.commands (mapped to the existing L3.opcodes field).

The SD-card protocol identifies commands by an index (CMD0..CMD63,
ACMD41 etc.) plus a symbolic name. The existing L3 generator
strategies (tab-separated CMD-table and ``0xNN OP_NAME`` prose)
don't see this format. This picker bridges that gap.

Index encoding into the existing ``L3.opcodes`` schema:

  * CMDn → hex = ``0x{n:02X}``, name = ``<NAME>``
  * ACMDn → hex = ``0x{n:02X}``, name = ``ACMD_<NAME>``
    (the ACMD prefix is preserved in the name to disambiguate
    from a bare CMDn with the same index)

Chip-AGNOSTIC: pure regex over README markdown / spec text. The
picker requires ≥2 hits in a single file before emitting (single
isolated CMDn mentions are likely accidental, not a command list).
"""
from __future__ import annotations

import re
from typing import List, Optional

# Match an SD-CMD list line of the form
#   [bullet] [backtick] (CMD|ACMD)<digits> [backtick]
#       <separator> <name and/or description>
_CMD_LINE_RE = re.compile(
    r"^\s*"
    r"[-*+]?\s*"
    r"`?"
    r"(?P<prefix>CMD|ACMD)"
    r"(?P<idx>\d{1,2})\b"
    r"`?"
    r"\s*[-–—:|]\s*"
    r"(?P<rest>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# ALL_CAPS or snake-case symbolic name at the start of the
# description, e.g. "SD_SEND_OP_COND", "SELECT_CARD", "GO_IDLE_STATE",
# or "Reset" (just a capitalised word — accept too).
_NAME_AT_START_RE = re.compile(
    r"^\s*([A-Z][A-Z0-9_]{2,40}|[A-Z][A-Za-z0-9_-]{2,40})\b",
)

# v1.6.116 (#43) — lowercase narrative-description fallback.
# Real-world SD-spec MEMO / datasheet entries often phrase the
# description as plain prose:
#   CMD2     -identification
#   CMD7     -select card
#   ACMD41   -check if card can use requested voltage
# These fail the Capitalised-identifier floor above. Accept them
# when the entire description text is ≥5 chars of lowercase-led
# word/slash/dash/space content. The cluster floor
# (_MIN_HITS_PER_FILE=2) still guards against false positives.
# Chip-AGNOSTIC: pure prose-shape regex, no chip identifiers.
#
# v1.6.117 (#44 Defect A) — charset extended to include parentheses,
# commas, and periods. SD-spec narrative often carries clauses like
#   "send tuning block to the host (mandatory for SDR104)"
#   "voltage switch, 1.8V mode"
# The slugifier downstream still drops parenthetical and punctuation
# content via the 5-token cap on _slugify_lowercase_description, so
# the captured symbolic name remains clean.
_LOWERCASE_DESC_RE = re.compile(
    r"^[a-z][\w/\- ,().]{4,120}$",
)

_MIN_HITS_PER_FILE = 2


def _slugify_lowercase_description(text: str) -> Optional[str]:
    """Turn a lowercase narrative description into an upper-snake-case
    symbolic name. Take the first ≤5 word tokens, drop pure-digit
    runs, join with `_`, uppercase. Return None if no plausible name
    can be extracted (≥3 chars of slug after normalisation).
    """
    words = re.findall(r"[A-Za-z][A-Za-z0-9]*", text)
    if not words:
        return None
    slug = "_".join(words[:5]).upper()
    if len(slug) < 3:
        return None
    return slug


def _normalise_name(prefix: str, raw_rest: str) -> Optional[str]:
    """Take the description text after the separator and pull out a
    symbolic name. Return None if no plausible name can be extracted.

    Two tiers (chip-AGNOSTIC):
      Tier 1 — description starts with an ALL_CAPS / Capitalised
        identifier (e.g. ``SD_SEND_OP_COND``, ``Reset``).
      Tier 2 — description is lowercase narrative prose (≥5 chars
        of word/slash/dash/space, lowercase-led). Slugified to
        upper-snake-case from the first ≤5 words. Added in
        v1.6.116 / #43 after field-agent reproduction showed the
        real litesdcard MEMO uses lowercase narrative throughout.
    """
    m = _NAME_AT_START_RE.match(raw_rest)
    if m:
        name = m.group(1)
        # Normalise to upper snake-case (matches existing opcode-name style).
        name = re.sub(r"[\s-]+", "_", name).upper()
    else:
        if not _LOWERCASE_DESC_RE.match(raw_rest.strip()):
            return None
        slug = _slugify_lowercase_description(raw_rest)
        if not slug:
            return None
        name = slug
    if prefix.upper() == "ACMD" and not name.startswith("ACMD_"):
        name = f"ACMD_{name}"
    return name


def extract_sd_cmds_from_readme(
    readme_text: Optional[str],
) -> List[dict]:
    """Return a list of SD-CMD dicts found in the README.

    Each dict matches the L3.opcodes schema:

        {
            "hex":           "0x00",
            "name":          "RESET",
            "raw_token":     "CMD0",
            "evidence_line": L,
            "description":   "Reset",     # the rest of the line
        }

    Empty list when the README has fewer than two CMD-style lines
    (single isolated CMDn mention is rejected as not a command list).

    Chip-AGNOSTIC.
    """
    if not readme_text:
        return []

    matches: List[dict] = []
    seen_keys: set = set()
    for line_num, line in enumerate(readme_text.split("\n"), start=1):
        m = _CMD_LINE_RE.match(line)
        if not m:
            continue
        prefix = m.group("prefix").upper()
        idx_str = m.group("idx")
        try:
            idx = int(idx_str)
        except ValueError:
            continue
        if idx > 63:
            continue
        rest = m.group("rest").strip()
        rest = re.sub(r"^[`*_]+|[`*_]+$", "", rest).strip()
        name = _normalise_name(prefix, rest)
        if not name:
            continue
        # Dedup by (prefix, index, name) so the same CMD listed twice
        # in the same file (e.g. once in TOC + once in body) only
        # produces one entry.
        key = (prefix, idx, name)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        matches.append({
            "hex":           f"0x{idx:02X}",
            "name":          name,
            "raw_token":     f"{prefix}{idx}",
            "evidence_line": line_num,
            "description":   rest,
        })

    if len(matches) < _MIN_HITS_PER_FILE:
        return []
    return matches


__all__ = [
    "extract_sd_cmds_from_readme",
]
