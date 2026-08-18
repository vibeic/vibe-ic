"""v1.6.123 — for #36 Bug 9 (L9 portion): SATA state-machine literal picker.

Field-agent verbatim spec (issue #36 Bug 9, L9 sub-portion):

  Apply to: litesata
  Pattern: state-machine literals (OOB, COMWAKE, COMINIT, K28.5,
    ALIGN/CONT inserter).
  Output: L9.submodules.

These are SATA spec-defined entities every LiteSATA implementation
must instantiate:

  * OOB sequence states — OOB, COMINIT, COMRESET, COMWAKE, COMSAS
    (host-side / device-side initiation handshake).
  * 8B/10B comma / special characters — K28.5 (the SATA comma /
    ALIGN delimiter), K28.3, K27.7 (rare but legitimate).
  * Primitive inserters — ALIGN_inserter / CONT_inserter, which
    are the dedicated submodules that emit SATA primitives onto
    the lane.

The L9 submodule extractor's existing strategies (RTL `module
<name>(`, prose `submodule:`, README markdown file-list) miss
these because they live in README prose under SATA-spec wording
rather than identifier form.

Chip-AGNOSTIC: pure regex against industry-standard SATA spec
literals — these tokens are defined by the SATA standard, not by
any individual chip / project.
"""
from __future__ import annotations

import re
from typing import List, Optional

# OOB sequence states (host- / device-side initiation handshake).
_OOB_TOKENS = (
    "OOB",        # generic OOB sequence
    "COMINIT",    # device-side init
    "COMWAKE",    # host- and device-side wake
    "COMRESET",   # host-side reset
    "COMSAS",     # SAS-vs-SATA selection
)

# 8B/10B special / comma characters used by SATA framing.
_SPECIAL_CHARS = (
    "K28.5",  # ALIGN / SATA comma
    "K28.3",
    "K27.7",
)

# Primitive inserters — dedicated framing submodules.
_PRIMITIVE_INSERTERS = (
    "ALIGN_inserter",
    "CONT_inserter",
    "ALIGN inserter",
    "CONT inserter",
)

# Combined regex per category. Each pattern is a literal token (or a
# small alternation) anchored by word boundaries.
_OOB_RE = re.compile(
    r"\b(" + "|".join(_OOB_TOKENS) + r")\b",
)
_SPECIAL_CHAR_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _SPECIAL_CHARS) + r")\b",
)
_PRIMITIVE_INSERTER_RE = re.compile(
    r"\b(ALIGN|CONT)\s*[_\s]inserter\b",
    re.IGNORECASE,
)

# Canonical submodule name + role role per token.
_TOKEN_TO_SUBMODULE = {
    "OOB":             ("oob_sequencer",       "OOB initiation sequencer (SATA handshake)"),
    "COMINIT":         ("oob_cominit",         "device-side COMINIT primitive"),
    "COMWAKE":         ("oob_comwake",         "COMWAKE wake primitive"),
    "COMRESET":        ("oob_comreset",        "host-side COMRESET primitive"),
    "COMSAS":          ("oob_comsas",          "SAS / SATA selection primitive"),
    "K28.5":           ("k28p5_special_char",  "K28.5 / ALIGN comma special character"),
    "K28.3":           ("k28p3_special_char",  "K28.3 8B/10B special character"),
    "K27.7":           ("k27p7_special_char",  "K27.7 8B/10B special character"),
    "ALIGN_inserter":  ("align_inserter",      "ALIGN primitive inserter"),
    "CONT_inserter":   ("cont_inserter",       "CONT primitive inserter"),
}

_MIN_HITS_PER_FILE = 2


def extract_sata_state_literals_from_readme(
    readme_text: Optional[str],
) -> List[dict]:
    """Return SATA state-machine literal hits as L9.submodules
    entries.

    Each hit is shaped to populate the existing L9.submodules
    schema:

        {
            "name":          "k28p5_special_char",
            "role":          "K28.5 / ALIGN comma special character",
            "evidence_line": L,
            "matched_token": "K28.5",
        }

    Empty list when fewer than ``_MIN_HITS_PER_FILE`` distinct
    SATA state literals are mentioned. Chip-AGNOSTIC.
    """
    if not readme_text:
        return []

    out: List[dict] = []
    seen: set = set()
    for line_num, line in enumerate(readme_text.split("\n"), start=1):
        # OOB tokens — case-sensitive (these are ALL_CAPS spec terms).
        for m in _OOB_RE.finditer(line):
            token = m.group(1)
            if token not in _TOKEN_TO_SUBMODULE:
                continue
            name, role = _TOKEN_TO_SUBMODULE[token]
            if name in seen:
                continue
            seen.add(name)
            out.append({
                "name":          name,
                "role":          role,
                "evidence_line": line_num,
                "matched_token": token,
            })
        # 8B/10B special characters.
        for m in _SPECIAL_CHAR_RE.finditer(line):
            token = m.group(1)
            if token not in _TOKEN_TO_SUBMODULE:
                continue
            name, role = _TOKEN_TO_SUBMODULE[token]
            if name in seen:
                continue
            seen.add(name)
            out.append({
                "name":          name,
                "role":          role,
                "evidence_line": line_num,
                "matched_token": token,
            })
        # Primitive inserters (ALIGN inserter / CONT inserter).
        for m in _PRIMITIVE_INSERTER_RE.finditer(line):
            base = m.group(1).upper()
            key = f"{base}_inserter"
            if key not in _TOKEN_TO_SUBMODULE:
                continue
            name, role = _TOKEN_TO_SUBMODULE[key]
            if name in seen:
                continue
            seen.add(name)
            out.append({
                "name":          name,
                "role":          role,
                "evidence_line": line_num,
                "matched_token": m.group(0),
            })

    if len(out) < _MIN_HITS_PER_FILE:
        return []
    return out


__all__ = [
    "extract_sata_state_literals_from_readme",
]
