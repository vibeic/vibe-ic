"""readme_deep_parser — Capability 1 of GitHub issue #27.

The Phase 1 (doc-extraction) v1.6.94 README parser only extracts ``ic_name`` +
``auto_discovered_identifiers``. Genuine spec facts that live in
README prose (key sizes / block width / S-box parallelism / supported
cipher modes / cited public-standards URLs) end up either in the
unstructured catch-all or nowhere at all. The ten thin-input projects
all have L1-L23 structured fields at zero, even though a human reader
of the same README extracts ten times more.

This module ships in v1.6.95 as the deeper README parser. Each regex
pattern is verbatim from the field-agent draft attached to issue #27;
each match is wrapped in the existing evidence shape carrying
``extraction_strategy: "readme_deep_parser"`` so a one-grep audit shows
where every fact came from.

Capabilities 2 + 3 (cited-standards fetcher + web-search resolver for
unhyperlinked standard names) are deferred. The oracle-guard module
they depend on (programs/url_oracle_guard.py) ships now so they plug in
without re-architecting.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse


# v1.6.299 — for #198 ORGANIC. URL-derived name helper for the
# numbered-bracket bibliography pass. The placeholder `ref-{idx}`
# carried no human-readable information; downstream consumers
# (Markdown renderer, docs-index generator, review tooling) had to
# open each URL to identify it. Strip the URL path tail, drop the
# file extension, deslug underscores / hyphens to spaces. Fall back
# to the registered hostname when no path tail exists, then to the
# raw placeholder. Chip-AGNOSTIC: structural URL parsing only.
def _v1_6_299_name_from_url(url: str, idx: str | int) -> str:
    try:
        parsed = urlparse(url)
        path = (parsed.path or "").strip("/")
        if path:
            last_seg = path.rsplit("/", 1)[-1]
            name = re.sub(r"\.\w{2,5}$", "", last_seg)
            name = re.sub(r"[_\-]+", " ", name).strip()
            if name:
                return name
        netloc = (parsed.netloc or "").strip()
        if netloc:
            return netloc.replace("www.", "")
        return f"ref-{idx}"
    except Exception:
        return f"ref-{idx}"

# Import url_oracle_guard from the same programs/ directory. We avoid a
# package-relative import because ``programs/`` is not a Python package
# (no __init__.py) — runners load these modules either by absolute path
# or with ``programs/`` on sys.path.
try:
    import url_oracle_guard as _ug  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — fallback for direct-path import
    import importlib.util as _ilu
    import os as _os
    _spec = _ilu.spec_from_file_location(
        "url_oracle_guard",
        _os.path.join(_os.path.dirname(__file__), "url_oracle_guard.py"),
    )
    _ug = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
    assert _spec and _spec.loader
    _spec.loader.exec_module(_ug)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Regex patterns (verbatim from field-agent draft in issue #27)
# ---------------------------------------------------------------------------

# Key sizes — "supports 128 and 256 bit keys" / "supports 128, 192,
# 256-bit keys" / "implements ChaCha with support for 128 and 256 bit
# keys" / "supports key lengths of 128 / 192 / 256 bits" /
# "configurable key width: 128, 256".
# v1.6.157 (#66) — extended alias verb group covering paraphrases the
# AES/chacha READMEs use interchangeably. Same number-list parser
# downstream (`_split_int_list`). chip-AGNOSTIC: alias group is
# documented English phrasing.
_RE_KEY_LENGTHS = re.compile(
    r"(?i)\b(?:"
    r"supports?|"
    r"support\s+for|"
    r"implements?(?:\s+[A-Za-z][A-Za-z0-9_-]{0,30})?\s+with\s+support\s+for|"
    r"(?:configurable\s+)?key\s+(?:length|width)s?\s*[:=]?|"
    r"key\s+lengths?\s+of"
    r")\s+"
    r"((?:\d+(?:\s*,\s*|\s+and\s+|\s*/\s*))*\d+)"
    r"\s*[-\s]?bit\s+keys?"
)

# Block / word width — "process one 128 bit block" / "process one 128 block at a time"
# Per v1.6.101 fix #27: 'bit' between number and 'block' is now optional;
# real-world READMEs phrase the architecture as "process one 128 block at a time"
# while the 'bit' word may belong to a separate sentence about key lengths.
_RE_BLOCK_WIDTH = re.compile(
    r'\bprocess(?:es)?\s+(?:one\s+)?(\d+)(?:\s+bit)?\s+(?:bit[-\s]?)?block\b',
    re.IGNORECASE,
)

# S-box parallelism — "4 S-boxes in the data path"
_RE_SBOX_PARALLELISM = re.compile(
    r"(?i)\b(\d+)\s+S[-\s]?boxes?\s+in\s+the\s+(?:data[-\s]?path|datapath)"
)

# Supported modes — "cipher modes such as CTR, CCM, CMAC, GCM."
# NOTE: non-greedy ``+?`` against a stop-set (``.`` or newline) so the
# capture stops at the first sentence terminator. The field-agent draft
# used ``([\w/,\s]+?)`` which by itself is too lax — paired with the
# explicit ``(?=[.\n])`` lookahead it becomes well-bounded.
_RE_SUPPORTED_MODES = re.compile(
    r"(?i)cipher\s+modes?\s+(?:such\s+as\s+)?([\w/,\s]+?)(?=[.\n])"
)

# Markdown reference link — "[NIST FIPS 197](https://csrc.nist.gov/...)"
# v1.6.172 (#71) — tightened to:
#   * single-line label (no \n inside the capture)
#   * label first char not `>` (excludes rst section heads like
#     `[> Getting started`)
#   * label first char not `#` (excludes `[# Section` rare form)
#   * 1..200 char label cap (defensive against runaway match)
#   * inline-link form `[lbl](url)` — `url` must not contain `)` or
#     whitespace
# Pre-v1.6.172 used `\[([^\]]+)\]\((https?://[^)]+)\)` which allowed
# multi-line labels — on LiteX-family READMEs the parser walked from
# an rst section header `[> Title\n----\nbody` all the way to the
# next URL inside a downstream paragraph, polluting L1.references.
_RE_MD_REFERENCE = re.compile(
    r"\[(?P<lbl>[^\]\n>#][^\]\n]{0,200})\]"
    r"\((?P<url>https?://[^)\s]+)\)"
)

# v1.6.295 — for #188 ORGANIC. Badge / shields.io / CI workflow URL
# deny patterns. Used by the markdown_inline_link walker to reject
# image-badge entries (CI status, license, coverage badges) from
# `L1.references`. Pre-v1.6.295 every open-source IP whose README
# opens with CI badges had `L1.references` dominated by SVG image
# URLs rather than real citations. The deny list covers the
# dominant badge proxies (shields.io / badge.svg / workflow.svg /
# coveralls / codecov SVG / travis-ci / circleci SVG / etc.)
# Chip-AGNOSTIC: generic URL fragment deny-list, no chip literals.
_V1_6_295_RE_BADGE_URL_RDP = re.compile(
    r"(shields\.io|badge\.svg|workflow\.svg|"
    r"github\.com/[^/]+/[^/]+/actions/workflow|"
    r"github\.com/[^/]+/[^/]+/workflows/[^/]+/badge|"
    r"coveralls|codecov\.io/[^\s]*svg|"
    r"travis-ci|circleci\.com/[^\s]*svg|"
    r"img\.shields\.io|api\.travis-ci)",
    re.IGNORECASE,
)

# v1.6.296 — for #188 round-2 NOT VERIFIED. The v1.6.295 deny list
# only covered shields.io / GitHub Actions / Travis / CircleCI. Field-
# agent verification surfaced additional badge-proxy hosts widely used
# by open-source IP READMEs that still slipped through:
#   * `badges.gitter.im/<org>/<repo>.svg` — chat-room badges
#   * `readthedocs.org/.../badge/?...` — docs build badges
#   * `gitlab.com/.../badges/...` — pipeline / coverage badges
#   * generic `workflow.svg` is already covered but broaden to match
#     bare `github.com/.../actions/workflow` segment without the trailing
#     `/badge.svg` suffix as some references render the workflow page URL
#     embedded as a click target
# Chip-AGNOSTIC: structural URL fragment deny-list, no chip literals.
_V1_6_296_RE_BADGE_URL_RDP = re.compile(
    r"(shields\.io|badge\.svg|workflow\.svg|"
    r"github\.com/[^/]+/[^/]+/actions/workflow|"
    r"github\.com/[^/]+/[^/]+/workflows/[^/]+/badge|"
    r"badges\.gitter|"
    r"readthedocs\.org/[^\s]*badge|"
    r"gitlab\.com/[^\s]*badges|"
    r"coveralls|codecov\.io/[^\s]*svg|"
    r"travis-ci|circleci\.com/[^\s]*svg|"
    r"img\.shields\.io|api\.travis-ci)",
    re.IGNORECASE,
)


def _v1_6_295_is_badge_image_or_url(name_text: str,
                                     url_text: str) -> bool:
    """v1.6.295 — for #188 ORGANIC. Return True when the (name, url)
    pair is a CI status badge / shields.io image / image-embed
    entry rather than a real citation. Image-embed shape detected
    when `name_text` starts with the Markdown image prefix `![`
    (the `!` distinguishes image-embed from inline-link). URL deny
    catches every entry whose URL points at a badge SVG image
    regardless of the label shape.

    v1.6.296 — for #188 round-2 NOT VERIFIED. Also accept a label
    starting with `!` (no `[`) so the nested
    `[![alt](badge)](click)` shape — where the harvested label is
    literally `![alt](badge)` — is caught. Switch URL deny over to
    the broader `_V1_6_296_RE_BADGE_URL_RDP`.

    Chip-AGNOSTIC.
    """
    if isinstance(name_text, str) and name_text.lstrip().startswith("!"):
        return True
    if isinstance(url_text, str) and _V1_6_296_RE_BADGE_URL_RDP.search(url_text):
        return True
    return False


# v1.6.297 — for #192 ORGANIC. Reference-name cleaner. The v1.6.295
# markdown_inline_link harvester (and the companion numbered-bracket
# bibliography collector) captured anchor text verbatim and copied it
# into `L1.references[*].name`. Common open-source RTL READMEs leak
# cosmetic residue into the name field:
#   * Numeric-citation form `[1](http://...)` — the prev-token of the
#     match is `[`, the regex captures `1`, the name becomes `[1` /
#     `[2` after a partial collapse. Generic numeric citations carry
#     no bibliographic name; they belong in `bibtex_id` (which the
#     numbered-bracket bibliography pass already does).
#   * Quoted anchors `"Foo"` — straight or curly quotes wrap the
#     citation title; the cosmetic quote wrapper is not part of the
#     bibliographic name.
#   * Generic anchor words — `here`, `click`, `this`, `link`, `more`,
#     `see`, `read`, `download`, `github`, `pdf`. These are
#     call-to-action labels with no bibliographic signal.
# The cleaner strips wrapping brackets / quotes and returns None for
# any anchor that has no bibliographic value after cleaning. Caller
# must drop the reference entry (or stamp `name: null`) when this
# returns None.
# Chip-AGNOSTIC: pure typographic / anchor-word vocabulary, no
# chip-class literals.
_V1_6_297_RE_NUMERIC_BRACKET_REF = re.compile(r"^\[?\s*(\d+)\s*\]?$")
_V1_6_297_GENERIC_ANCHOR_WORDS = frozenset({
    "here", "click", "this", "link", "more", "see", "read",
    "download", "github", "pdf",
})


def _v1_6_297_clean_reference_name(name: object) -> Optional[str]:
    """v1.6.297 — for #192 ORGANIC. Clean a harvested reference-name
    anchor. Returns the trimmed bibliographic name when it carries
    real signal, or None when the anchor is just typographic
    residue / a generic call-to-action word / a bare numeric cite.

    Chip-AGNOSTIC: pure typographic + English-prose vocabulary.
    """
    if not isinstance(name, str):
        return None
    out = name.strip()
    # Strip wrapping `[ ... ]` (raw bracket prefix `[1` / `[2`
    # survives v1.6.295 because the numeric-cite regex captures `1`
    # but leaves the `[` as part of the label).
    out = out.lstrip("[").rstrip("]").strip()
    # Strip wrapping straight / curly quotes / backticks (left- and
    # right-side curly quotes treated as a single class).
    out = out.strip("\"'`‘’“”")
    if not out:
        return None
    # Generic call-to-action anchor (case-insensitive).
    if out.lower() in _V1_6_297_GENERIC_ANCHOR_WORDS:
        return None
    # Bare numeric citation (with or without brackets) — caller
    # should populate `bibtex_id` instead via the numbered-bracket
    # bibliography pass.
    if _V1_6_297_RE_NUMERIC_BRACKET_REF.match(out):
        return None
    return out
# v1.6.289 — for #169 ORGANIC. Numbered-bracket bibliography pass.
# `_RE_MD_REFERENCE` only catches inline Markdown link syntax
# `[label](url)`. The canonical academic / IEEE / RFC reference list
# convention used by many open-source IP cores is:
#
#     ## References
#     [1] https://example.org/some-paper
#     [2] https://example.org/another-spec
#
# Pre-v1.6.289 the `## References` heading was detected by other
# passes but the numbered URL list under it was never harvested.
# Chip-AGNOSTIC: structural pattern only — `^[heading-level]
# references` + `[N] url` numbered list.
_RE_REFERENCES_HEADING = re.compile(
    r"(?im)^#{1,6}\s+references?\s*$"
)
_RE_NUMBERED_REFERENCE = re.compile(
    r"^\s*\[(\d+)\]\s+(https?://\S+)", re.M
)
# Defensive: an `rst-style` section head (`[> Title` immediately
# followed by an underline row `----`) is NOT a markdown link. The
# parser explicitly looks past these.
_RE_RST_UNDERLINE_AFTER_BRACKET = re.compile(
    r"\[[^\]\n]*\n[=\-~`'\"^+\*#]{3,}\s*\n"
)


# Mode-token shape filter. Real cipher modes are 2-8 chars, uppercase,
# AND must look like a mode (3-letter abbreviation, contain a digit,
# contain a hyphen, or appear in the curated known-mode whitelist).
# This rejects English prose tokens like THE / GREAT / BIG which would
# otherwise pass a naive shape check.
_RE_MODE_TOKEN_SHAPE = re.compile(r"^[A-Z][A-Z0-9-]{1,7}$")
# Curated whitelist of well-known cipher / hash / authentication modes.
# Add new entries as they appear in real benchmark READMEs — this is a
# whitelist not a blocklist by deliberate choice (it's the class of
# tokens we have a statistical right to harvest from open prose).
_KNOWN_CIPHER_MODES = frozenset({
    "ECB", "CBC", "CTR", "CFB", "OFB", "GCM", "CCM", "CMAC", "HMAC",
    "GMAC", "XTS", "OCB", "EAX", "SIV", "MAC", "PCBC",
    "GCM-SIV", "AES-GCM", "AES-CCM",
    # Stream ciphers / stream modes
    "POLY1305",
    # Hash / KDF prefixes that sometimes appear here
    "SHA-1", "SHA-2", "SHA-3", "MD5",
})
# Words a human would never confuse for a cipher mode (common English).
_MODE_TOKEN_NOISE = frozenset({
    "THE", "AND", "OR", "OF", "FOR", "TO", "IS", "ARE", "WAS", "WERE",
    "BE", "BEEN", "BEING", "A", "AN", "IN", "ON", "AT", "BY", "WITH",
    "FROM", "AS", "BUT", "NOT", "NO", "YES",
})


def _looks_like_cipher_mode(tok: str) -> bool:
    """True iff ``tok`` plausibly names a cipher mode.

    Accepts:
      * any token in :data:`_KNOWN_CIPHER_MODES`
      * tokens containing a digit (CTR16, AES-128, OFB8)
      * tokens containing a hyphen with both parts uppercase (GCM-SIV)
    Rejects everything else, including all-letter English words that
    happen to be 3-8 chars long.
    """
    if tok in _KNOWN_CIPHER_MODES:
        return True
    if any(ch.isdigit() for ch in tok):
        return True
    if "-" in tok and all(part for part in tok.split("-")):
        return True
    return False


# ---------------------------------------------------------------------------
# Data class — one entry per extracted fact
# ---------------------------------------------------------------------------

@dataclass
class ParsedReadme:
    """Structured facts extracted from a single README. Every field that
    landed here carries an ``evidence`` dict downstream so the
    extraction_evidence_schema gate sees correct provenance.
    """
    key_lengths: List[Dict[str, Any]] = field(default_factory=list)
    block_width_bits: Optional[Dict[str, Any]] = None
    parallelism_sboxes: Optional[Dict[str, Any]] = None
    supported_modes: List[Dict[str, Any]] = field(default_factory=list)
    references: List[Dict[str, Any]] = field(default_factory=list)
    # v1.6.155 (#61) — LiteX-style `> Features` section with optional
    # sub-headers (PHY / Core / Frontend / etc). When sub-headers are
    # present, bullets are grouped under each lowercase key. When the
    # Features header has bullets but no sub-section dividers, they
    # land under "unstructured". Each entry carries evidence with
    # extraction_strategy="litex_features_section_match".
    features: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    # The README's parsed self-repo (fed to oracle_guard). Exposed for
    # tests + downstream loggers.
    self_repo: Optional[str] = None
    # v1.6.295 — for #188 ORGANIC. CI status badges / shields.io
    # image-embed entries rejected from `references` for provenance
    # auditing. Empty list when no badges were rejected.
    ignored_badges: List[Dict[str, Any]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.key_lengths or self.block_width_bits
                    or self.parallelism_sboxes or self.supported_modes
                    or self.references or self.features)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _line_of(text: str, offset: int) -> int:
    """1-based line number of ``offset`` in ``text``."""
    return text.count("\n", 0, offset) + 1


def _ev(source: str, line: int, label: str) -> Dict[str, Any]:
    """Common evidence-shape for every readme_deep_parser entry."""
    return {
        "source": source,
        "line": line,
        "extraction_strategy": "readme_deep_parser",
        "label": label,
    }


def _split_int_list(blob: str) -> List[int]:
    """Parse e.g. "128 and 256" / "128, 192, 256" / "128/256" → ints."""
    out: List[int] = []
    for tok in re.split(r"\s*,\s*|\s+and\s+|\s*/\s*", blob.strip()):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok))
        except ValueError:
            continue
    return out


def _parse_modes_blob(blob: str) -> List[str]:
    """Split a mode-list capture into clean uppercase tokens.

    Filter chain (each must pass):
      1. uppercase-shape (``_RE_MODE_TOKEN_SHAPE``)
      2. not in English noise list (``_MODE_TOKEN_NOISE``)
      3. ``_looks_like_cipher_mode`` — known mode OR has digit OR has hyphen
    Token order preserved, duplicates removed.
    """
    raw = re.split(r"[,\s/]+", blob.strip())
    out: List[str] = []
    for tok in raw:
        tok = tok.strip().upper()
        if not tok:
            continue
        if tok in _MODE_TOKEN_NOISE:
            continue
        if not _RE_MODE_TOKEN_SHAPE.match(tok):
            continue
        if not _looks_like_cipher_mode(tok):
            continue
        if tok in out:  # dedupe, preserve order
            continue
        out.append(tok)
    return out


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

# v1.6.155 (#61) — LiteX-family `> Features` section parser. The
# LiteX ecosystem (litedram / litesata / litesdcard / litescope /
# liteiclink) uses a consistent 4-tier convention:
#
#     [> Features                <- LiteX-style header (also ## Features
#       > PHY:                       in plain markdown)
#         - Auto-Precharge
#         - Periodic refresh/ZQ short calibration
#       > Core:
#         - Native, AXI-MM or Wishbone user interface
#         - ECC
#         - BIST
#       > Frontend:
#         - Crossbar
#         - N-Mirroring or RAID
#
# Without a structured extractor, every bullet collapses into
# L1.auto_discovered_identifiers (flat acronym list), losing the
# PHY/Core/Frontend grouping that phase2's RTL templater needs to
# decide PHY variant / ECC enable / BIST presence.
#
# The regex set below recognizes BOTH the LiteX `> Features` heading
# style and the plain markdown `# Features` / `## Features` /
# `### Features` form, plus sub-section headers and bullets at
# various indent levels.
_RE_FEATURES_HEADER = re.compile(
    # `[> Features`, `> Features`, `# Features`, `## Features`, `### Features`
    # are all accepted. The leading prefix class includes `[` so the
    # LiteX-style `[> Features` form matches.
    r"(?im)^[\s>\[]*#{0,4}\s*Features\s*:?\s*$"
)
_RE_FEATURES_SUBSECTION = re.compile(
    r"(?im)^[\s>]*"
    # 1-3 caps-leading words, optionally separated by spaces / hyphens
    # / slashes (e.g. "PHY", "Core", "Frontend", "Storage / Trigger").
    r"([A-Z][A-Za-z]+(?:\s*[/\-]?\s*[A-Z][A-Za-z]+){0,3})\s*:\s*$"
)
_RE_FEATURES_BULLET = re.compile(
    r"(?m)^[\s>]*[-*+]\s+(.+?)\s*$"
)
# Header tokens that terminate the Features block — any next markdown
# header that isn't a sub-section starts the new section. Matches H1-H4
# (`# Heading` / `## Heading` / ...) and LiteX-style `[> Heading` lines
# that are NOT followed by a colon (sub-sections END with `:` and must
# NOT terminate the Features block).
_RE_NEXT_TOP_HEADER = re.compile(
    r"(?im)^[\s>\[]*(?:#{1,4}\s+\S+|\[\s*>\s+\S+(?<!:))"
)


def _slugify_subsection(s: str) -> str:
    """Convert a sub-section header like `PHY` / `Storage / Trigger`
    to a lowercase key (`phy` / `storage_trigger`)."""
    cleaned = re.sub(r"[/\-\s]+", "_", s.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned.lower()


def extract_features_block(
    readme_text: str,
    source: str = "input/docs/README.md",
) -> Dict[str, List[Dict[str, Any]]]:
    """Locate the Features section in README prose and return a dict
    keyed by lowercase sub-section name → list of bullet entries.

    Falls back to `{"unstructured": [...]}` when the Features header
    is present but no sub-sections are detected. Returns `{}` when no
    Features header is found.

    chip-AGNOSTIC: pattern is markdown / LiteX heading style, applies
    to any IC class.
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    if not readme_text:
        return out
    hm = _RE_FEATURES_HEADER.search(readme_text)
    if not hm:
        return out
    # Slice from the line AFTER the header to the next top-level
    # header (or end-of-text).
    start = hm.end()
    nm = _RE_NEXT_TOP_HEADER.search(readme_text, pos=start)
    end = nm.start() if nm else len(readme_text)
    body = readme_text[start:end]
    if not body.strip():
        return out

    # Walk the body line by line. Track which sub-section we're in.
    current_key: Optional[str] = None
    lines = body.splitlines()
    # Offset from start of `body` so line numbers we record are
    # correct relative to the original `readme_text`.
    line_cursor = readme_text.count("\n", 0, start)
    for i, raw_ln in enumerate(lines):
        ln_no = line_cursor + i + 1  # 1-indexed
        # Sub-section header?
        sm = _RE_FEATURES_SUBSECTION.match(raw_ln)
        if sm:
            current_key = _slugify_subsection(sm.group(1))
            out.setdefault(current_key, [])
            continue
        # Bullet?
        bm = _RE_FEATURES_BULLET.match(raw_ln)
        if bm:
            value = bm.group(1).strip()
            if not value:
                continue
            key = current_key or "unstructured"
            out.setdefault(key, []).append({
                "value": value,
                "evidence": {
                    "source": source,
                    "line": ln_no,
                    "label": "feature bullet",
                    "extraction_strategy":
                        "litex_features_section_match",
                },
            })
    # Strip empty sub-sections (e.g. a sub-header with no bullets that
    # followed). Keep `unstructured` only if it has entries.
    out = {k: v for k, v in out.items() if v}
    return out


def parse_readme(readme_text: str,
                 source: str = "input/docs/README.md") -> ParsedReadme:
    """Run all v1.6.95 README-deep regex passes over ``readme_text``.

    ``source`` is the path stamped into each ``evidence`` entry.

    URL-bearing references are filtered through the oracle-guard so the
    project's own GitHub repo never ends up in ``L1.references``. When
    a URL is denied, an INFO line is logged to stderr in the shape
    ``[oracle_guard] URL denied: <url> reason=<reason>``.
    """
    p = ParsedReadme()
    if not readme_text:
        return p

    # Identify the project's own repo first — fed to oracle-guard for
    # every URL we extract below.
    p.self_repo = _ug.parse_project_self_repo(readme_text)

    # ------ Key sizes ------
    for m in _RE_KEY_LENGTHS.finditer(readme_text):
        ks = _split_int_list(m.group(1))
        if not ks:
            continue
        p.key_lengths.append({
            "value": ks,
            "evidence": _ev(source, _line_of(readme_text, m.start()),
                            "key lengths (bits)"),
        })

    # ------ Block width ------
    for m in _RE_BLOCK_WIDTH.finditer(readme_text):
        try:
            n = int(m.group(1))
        except ValueError:
            continue
        if p.block_width_bits is None:  # first match wins
            p.block_width_bits = {
                "value": n,
                "evidence": _ev(source, _line_of(readme_text, m.start()),
                                "block / word width (bits)"),
            }

    # ------ S-box parallelism ------
    for m in _RE_SBOX_PARALLELISM.finditer(readme_text):
        try:
            n = int(m.group(1))
        except ValueError:
            continue
        if p.parallelism_sboxes is None:  # first match wins
            p.parallelism_sboxes = {
                "value": n,
                "evidence": _ev(source, _line_of(readme_text, m.start()),
                                "S-box parallelism (datapath)"),
            }

    # ------ Supported cipher modes ------
    for m in _RE_SUPPORTED_MODES.finditer(readme_text):
        modes = _parse_modes_blob(m.group(1))
        if not modes:
            continue
        for mode in modes:
            p.supported_modes.append({
                "value": mode,
                "evidence": _ev(source, _line_of(readme_text, m.start()),
                                "supported cipher mode"),
            })

    # ------ v1.6.155 (#61) LiteX `> Features` block ------
    p.features = extract_features_block(readme_text, source=source)

    # ------ Markdown references — URL-bearing, oracle-guard filtered ------
    # v1.6.172 (#71) — uses tightened `_RE_MD_REFERENCE` that:
    #   * forbids `\n` inside the label capture (single-line only)
    #   * rejects labels whose first char is `>` or `#` (rst section
    #     heads / blockquote starts)
    #   * caps label at 200 chars
    # Additional pre-emptive guard: if the matched label is followed
    # within ±2 lines by an rst-underline row (`-{3,}` / `={3,}`),
    # treat the `[` as an rst section head and skip the match.
    # v1.6.295 — for #188 ORGANIC. Track rejected badge entries so
    # the post-parse caller can surface them on `L1.ignored_badges`
    # for provenance auditing. Pre-v1.6.295 every image-embed badge
    # and shields.io URL landed in `L1.references` as if it were a
    # real citation; doc renderers printed them and search-index
    # consumers tokenised badge URLs.
    p_ignored_badges: List[Dict[str, Any]] = []
    for m in _RE_MD_REFERENCE.finditer(readme_text):
        name = m.group("lbl").strip()
        url = m.group("url").strip()
        # Defensive: drop multi-line labels that somehow slipped past
        # the single-line capture (the `[^\]\n]` class should have
        # caught these, but belt-and-suspenders).
        if "\n" in name or name.startswith(">"):
            continue
        # Skip rst-section-head false positives.
        # Look for an rst underline within the next 3 lines after the
        # match's start position.
        line_idx = _line_of(readme_text, m.start())
        lines = readme_text.splitlines()
        skip = False
        for ahead in lines[line_idx:line_idx + 3]:
            if re.fullmatch(r"[=\-~`'\"^+\*#]{3,}\s*", ahead or ""):
                skip = True
                break
        if skip:
            continue
        # v1.6.295 — for #188 ORGANIC. Image-embed lookback. The
        # `_RE_MD_REFERENCE` regex captures the `[label](url)` form
        # but does NOT see the leading `!` of an image-embed
        # `![alt](url)`. Check the char immediately before the
        # match — if it is `!`, the match is the image-embed inner
        # `[alt](url)` and the entry is a badge image, not a
        # citation. Combine with the badge-URL deny so the two
        # shapes both route to `L1.ignored_badges`.
        #
        # v1.6.296 — for #188 round-2 NOT VERIFIED. The prev-char
        # lookback only catches the SIMPLE `![alt](url)` shape. Real
        # benchmark READMEs use the NESTED click-wrapped image form
        # `[![alt](badge_url)](click_url)` where the non-greedy regex
        # matches the OUTER `[lbl](click_url)`; the outer `[`'s
        # prev_char is whitespace/BOL, not `!`, so `is_image_embed`
        # never fires. The captured label `lbl` is literally
        # `![alt](badge_url)` — i.e. starts with `!`. Detect that
        # explicitly via `name.startswith("!")` so the nested shape is
        # routed to `ignored_badges` alongside the simple shape.
        # Also switch the URL deny over to the broader
        # `_V1_6_296_RE_BADGE_URL_RDP` so badges.gitter / readthedocs
        # badges / gitlab pipeline badges are caught too.
        # Chip-AGNOSTIC.
        prev_char = readme_text[m.start() - 1] if m.start() > 0 else ""
        is_image_embed = (prev_char == "!")
        is_nested_image_embed = isinstance(name, str) and name.startswith("!")
        is_badge_url = bool(_V1_6_296_RE_BADGE_URL_RDP.search(url))
        if is_image_embed or is_badge_url or is_nested_image_embed:
            p_ignored_badges.append({
                "name": name,
                "url": url,
                "is_image_embed": is_image_embed,
                "is_nested_image_embed": is_nested_image_embed,
                "is_badge_url": is_badge_url,
                "evidence": _ev(source,
                                _line_of(readme_text, m.start()),
                                "image-embed / badge URL reject"),
                "extraction_strategy": "v1_6_296_badge_reject",
            })
            continue
        allowed, reason = _ug.url_allowed(url, p.self_repo)
        if not allowed:
            sys.stderr.write(
                f"[oracle_guard] URL denied: {url} reason={reason}\n"
            )
            continue
        # v1.6.297 — for #192 ORGANIC. Clean the anchor name before
        # appending. Drop the entry entirely when the cleaner rejects
        # the anchor as cosmetic residue (`[1`, `here`, `"Verible"`,
        # ...). Real bibliographic names survive unchanged.
        cleaned_name = _v1_6_297_clean_reference_name(name)
        if cleaned_name is None:
            continue
        p.references.append({
            "name": cleaned_name,
            "url": url,
            "evidence": _ev(source, _line_of(readme_text, m.start()),
                            "markdown reference"),
            "extraction_strategy": "markdown_inline_link",
        })
    # v1.6.295 — for #188 ORGANIC. Stamp the badge-reject list on
    # the parsed object so the L1 emitter can surface it under
    # `L1.ignored_badges`.
    if p_ignored_badges:
        p.ignored_badges = p_ignored_badges

    # v1.6.289 — for #169 ORGANIC. Numbered-bracket bibliography pass.
    # Walks each `## References` (or any heading-level ATX) section and
    # harvests `[N] https://...` numbered entries within a 4000-char
    # window after the heading. Each URL is passed through the same
    # `oracle_guard` so deny-list / out-of-scope domain rules still
    # apply. Provenance: `extraction_strategy =
    # "numbered_bracket_bibliography"`.
    #
    # Chip-AGNOSTIC: structural anchor + URL pattern only.
    _seen_numbered_urls = {r.get("url") for r in p.references}
    for h in _RE_REFERENCES_HEADING.finditer(readme_text):
        section = readme_text[h.end(): h.end() + 4000]
        for ref in _RE_NUMBERED_REFERENCE.finditer(section):
            idx = ref.group(1)
            url = ref.group(2).strip().rstrip(".,;)")
            if url in _seen_numbered_urls:
                continue
            allowed, reason = _ug.url_allowed(url, p.self_repo)
            if not allowed:
                sys.stderr.write(
                    f"[oracle_guard] URL denied: {url} reason={reason}\n"
                )
                continue
            # Recover the absolute offset in `readme_text` for line
            # numbering — `ref.start()` is local to `section`.
            abs_offset = h.end() + ref.start()
            _seen_numbered_urls.add(url)
            # v1.6.299 — for #198 ORGANIC. Derive `name` from the
            # URL path tail so the human-facing entry carries
            # meaningful text; preserve the original bracket index
            # as `ref_id` for evidence-chain traceability.
            derived_name = _v1_6_299_name_from_url(url, idx)
            p.references.append({
                "name": derived_name,
                "ref_id": idx,
                "url": url,
                "evidence": _ev(source, _line_of(readme_text, abs_offset),
                                "numbered-bracket bibliography"),
                "extraction_strategy": "numbered_bracket_bibliography",
            })

    return p


def find_readme_text(extracted: Dict[str, str]) -> Tuple[Optional[str],
                                                         Optional[str]]:
    """Pick the README text out of the ``extracted`` mapping that
    Phase 1 (doc-extraction)'s L generators consume. Returns (text, source_path) or
    (None, None) if the project has no README.

    v1.6.274 — for #140 ORGANIC. Prefer the legacy ``input/docs/``
    convention when both an ``input/docs/`` README and a chip-root
    README (with marker prefix ``__chip_root__/``) exist; fall through
    to the chip-root entry when no input/docs/ README is present.
    Source-path provenance reflects the true on-disk location so
    downstream evidence chains don't claim ``input/docs/`` for a
    chip-root file.
    """
    # First pass — prefer input/docs/ provenance when present.
    for fname, text in extracted.items():
        low = fname.lower()
        if "readme" in low and not fname.startswith("__chip_root__/"):
            return text, f"input/docs/{fname}"
    # Second pass — chip-root README fallback (v1.6.274).
    for fname, text in extracted.items():
        if not fname.startswith("__chip_root__/"):
            continue
        if "readme" in fname.lower():
            basename = fname[len("__chip_root__/"):]
            return text, basename
    return None, None
