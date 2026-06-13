"""v1.6.120 — for #36 Bug 9: SATA-spec literal picker (L3 commands).

Field-agent verbatim spec (issue #36 Bug 9):

  Apply to: litesata
  Pattern: literal speeds (1.5/3.0/6.0 Gbps), system clocks (37.5/75/
    150 MHz), state-machine literals (OOB, COMWAKE, COMINIT, K28.5,
    ALIGN/CONT inserter), addressing (48-bit sector LBA), commands
    (READ_DMA(_EXT)/WRITE_DMA(_EXT)/IDENTIFY_DEVICE).
  Output: L3.commands + L8.timing_constants + L9.submodules.

This module ships the L3.commands portion of Bug 9 — the most
concrete deliverable. It scans README text for ATA/SATA standard
command names and emits them in the existing L3.opcodes schema
with the canonical SATA / ATA-7+ command opcodes.

Speeds (Gbps) / system clocks (MHz) → L8.timing_constants and
state-machine literals (OOB / COMWAKE / COMINIT / K28.5 / ALIGN /
CONT inserter) → L9.submodules are higher-touch wiring jobs and
will ship in follow-up patches if the field agent requests them.

Chip-AGNOSTIC: pure regex over README text against a fixed
ATA / SATA standard-command vocabulary (industry standard, not
chip-specific identifiers).
"""
from __future__ import annotations

import re
from typing import List, Optional

# ATA / SATA standard command opcodes (per ATA-7+ / SATA 3.x).
# Chip-AGNOSTIC: these are industry-standard hex values.
_SATA_COMMANDS = {
    "READ_DMA":           0xC8,
    "READ_DMA_EXT":       0x25,
    "WRITE_DMA":          0xCA,
    "WRITE_DMA_EXT":      0x35,
    "IDENTIFY_DEVICE":    0xEC,
    "READ_FPDMA_QUEUED":  0x60,
    "WRITE_FPDMA_QUEUED": 0x61,
    "FLUSH_CACHE":        0xE7,
    "FLUSH_CACHE_EXT":    0xEA,
}

# Match any literal SATA command name. Names are sorted by length
# descending so that ``READ_DMA_EXT`` matches in preference to
# ``READ_DMA`` when both are candidates at the same position.
_ALL_NAMES = sorted(_SATA_COMMANDS.keys(), key=len, reverse=True)
_ANY_CMD_RE = re.compile(
    r"\b(?P<name>" + "|".join(re.escape(n) for n in _ALL_NAMES) + r")\b"
)

# Match the README shorthand ``<BASE>(_EXT)`` denoting "this
# command has both base and EXT variants" — emit BOTH on hit.
# A separate regex (rather than an optional group on _ANY_CMD_RE)
# because ``(_EXT)`` ends in ``)`` which prevents the trailing
# ``\b`` from anchoring on a single combined pattern.
_PAREN_EXT_RE = re.compile(
    r"\b(?P<base>READ_DMA|WRITE_DMA|FLUSH_CACHE)\(_EXT\)",
)

# Cluster floor: require at least 2 distinct SATA commands in a
# single document before emitting. A bare READ_DMA mention in an
# unrelated context does NOT count as a SATA command set.
_MIN_HITS_PER_FILE = 2


def extract_sata_commands_from_readme(
    readme_text: Optional[str],
) -> List[dict]:
    """Return SATA-command hits in the README.

    Each hit is shaped to populate the existing L3.opcodes schema:

        {
            "hex":           "0xC8",
            "name":          "READ_DMA",
            "raw_token":     "READ_DMA",
            "evidence_line": L,
        }

    Empty list when fewer than ``_MIN_HITS_PER_FILE`` distinct
    commands are mentioned. Chip-AGNOSTIC.
    """
    if not readme_text:
        return []

    seen: set = set()
    out: List[dict] = []
    for line_num, line in enumerate(readme_text.split("\n"), start=1):
        # Pass A — match every literal command name on the line.
        for m in _ANY_CMD_RE.finditer(line):
            name = m.group("name")
            if name in _SATA_COMMANDS and name not in seen:
                seen.add(name)
                out.append({
                    "hex":           f"0x{_SATA_COMMANDS[name]:02X}",
                    "name":          name,
                    "raw_token":     name,
                    "evidence_line": line_num,
                })
        # Pass B — `<BASE>(_EXT)` shorthand also synthesises the
        # `_EXT` variant if not already captured.
        for m in _PAREN_EXT_RE.finditer(line):
            base = m.group("base")
            ext_name = f"{base}_EXT"
            if ext_name in _SATA_COMMANDS and ext_name not in seen:
                seen.add(ext_name)
                out.append({
                    "hex":           f"0x{_SATA_COMMANDS[ext_name]:02X}",
                    "name":          ext_name,
                    "raw_token":     ext_name,
                    "evidence_line": line_num,
                })

    if len(out) < _MIN_HITS_PER_FILE:
        return []
    return out


__all__ = [
    "extract_sata_commands_from_readme",
]
