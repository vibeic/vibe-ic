"""v1.6.113 — for #36 Bug 5: README markdown file-list submodule extractor.

Many open-source IPs ship a README section that enumerates the RTL
files that compose the IP, with a one-line role description per file.
Examples (verbatim from the field-agent's #36 deferred-bug list):

    sha1_core.v - The core itself
    sha1_w_mem.v - The W message block memory
    sha256_core.v - SHA-256 core
    sha256_w_mem.v - W message-block memory
    sha256_k_constants.v - K constants table

These file-lists are unambiguous evidence of the IP's submodule
structure — but the existing strategy-A (RTL `module <name>(`
parser) and strategy-B (prose `submodule: <name>`) extractors
don't see them when (a) the source RTL is not checked into the
project tree (e.g. only the README is indexed) and (b) the README
doesn't use the literal word "submodule".

This module adds a third strategy: scan markdown for lines whose
first non-bullet token is a snake_case identifier ending in
``.v`` / ``.sv`` followed by a separator (dash / em-dash / colon /
pipe) and a description. The identifier (sans extension) is
recorded as a submodule name; the description is recorded as its
role.

Chip-AGNOSTIC: pure regex over README prose. Structural floor
prevents single-word generic file names (``core.v``, ``top.v``)
from being recorded — only multi-word snake_case names with at
least one underscore are accepted, which matches both the
field-agent's verbatim examples and avoids collisions with
ubiquitous generic file names that vendor docs use as examples.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# Match a markdown file-list line of the form:
#   [bullet] [backtick] <snake_case_with_underscore>.<v|sv> [backtick]
#       <separator> <role description>
# where:
#   - bullet  is optional `-`, `*`, `+`, or none
#   - backtick is optional ` ` (markdown inline code)
#   - identifier MUST contain at least one underscore (structural
#     floor — single-word names like `core`, `top`, `chip` are too
#     generic and appear in vendor manuals as examples, not
#     submodule declarations)
#   - separator is one of `-`, `–` (en-dash), `—` (em-dash),
#     `:`, `|`
#   - description is the rest of the line (≥1 char after stripping)
_FILELIST_LINE_RE = re.compile(
    r"^\s*"                                   # leading whitespace
    r"[-*+]?\s*"                              # optional bullet
    r"`?"                                     # optional opening backtick
    r"([a-z][a-z0-9]*(?:_[a-z0-9]+)+)"        # snake_case ≥2 words
    r"\.(?:sv|v)\b"                           # .v or .sv extension
    r"`?"                                     # optional closing backtick
    r"\s*[-–—:|]\s*"                # separator
    r"(.+?)\s*$",                             # role description
    re.IGNORECASE | re.MULTILINE,
)

# Block names that look like real file names but are generic
# placeholders / dev-kit boilerplate appearing in vendor / tool
# READMEs (Intel UG, Yosys, OpenROAD examples). Reject. Chip-
# AGNOSTIC list — these are tool-vendor terms, not chip-specific.
_GENERIC_FILENAME_DENY = frozenset({
    "test_bench", "tb_top", "test_top", "my_module",
    "your_module", "example_top", "dut_top",
})


def extract_submodules_from_readme_filelist(
    readme_text: Optional[str],
) -> List[dict]:
    """Extract submodule names + roles from a README markdown
    file-list section.

    Returns a list of dicts compatible with the phase1 runner's
    L9.submodules schema:

        [{
            "name":         "sha1_core",
            "role":         "The core itself",
            "evidence_line": 12,
            "matched_filename": "sha1_core.v",
        }, ...]

    Order preserved (first-occurrence wins on duplicates). Empty
    list when the README contains no file-list lines.

    Chip-AGNOSTIC: pure regex over README markdown. No project /
    chip-specific identifiers.
    """
    if not readme_text:
        return []

    seen: set = set()
    results: List[dict] = []
    for line_num, line in enumerate(readme_text.split("\n"), start=1):
        m = _FILELIST_LINE_RE.match(line)
        if not m:
            continue
        name = m.group(1).lower()
        if name in seen:
            continue
        if name in _GENERIC_FILENAME_DENY:
            continue
        # Reconstruct the matched filename for evidence (preserves
        # the original extension as written).
        filename_match = re.search(
            r"([a-z][a-z0-9_]+\.(?:sv|v))",
            line, re.IGNORECASE,
        )
        matched_filename = filename_match.group(1) if filename_match else f"{name}.v"
        role = m.group(2).strip()
        # Strip surrounding markdown emphasis from the role text.
        role = re.sub(r"^[`*_]+|[`*_]+$", "", role).strip()
        if not role:
            continue
        seen.add(name)
        results.append({
            "name":             name,
            "role":             role,
            "evidence_line":    line_num,
            "matched_filename": matched_filename,
        })

    return results


__all__ = [
    "extract_submodules_from_readme_filelist",
]
