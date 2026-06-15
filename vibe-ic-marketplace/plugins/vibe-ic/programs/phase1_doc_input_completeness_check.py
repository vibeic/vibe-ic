#!/usr/bin/env python3
"""
phase1_doc_input_completeness_check.py — strong gate
==============================================================

Per-doc completeness audit: for each input document, harvest every
distinct numeric+unit / hex / identifier / register / opcode token
using the same chip-AGNOSTIC regex families as
``extraction_coverage_denominator_audit`` + ``phase1_coverage_report_gen``,
then verify each token appears somewhere in the union of every
``generated_docs/L*.json`` text. A token is considered "captured"
when it appears as a substring in any L doc JSON serialization.

Why this gate exists
--------------------
``extraction_coverage_check`` measures *aggregate* coverage and is
gameable by stuffing tokens into one giant blob.
``l_doc_structured_field_count_check`` measures *typed structure*
per L doc.
Neither verifies that **every input doc's facts actually landed
somewhere**. A vendor PPT with 12 timing values can be silently
ignored if the L8 extractor regex doesn't match its filename, and
no existing gate flags it.

Per-input-doc accountability is what this gate adds:

  * For every ``input/docs/*.txt`` (or input_doc/*.txt),
    compute ``captured_pct = captured_tokens / distinct_tokens``.
  * FAIL if any single doc has ``captured_pct < 50%`` AND
    ``distinct_tokens >= 10``.
  * WARN (exit 0) if 50% <= pct < 80%.
  * Skip docs with <10 distinct tokens (boilerplate / index files).

Forbidden waiver prefix
-----------------------
``phase1_input_vs_generated_*`` is added to the forbidden-waiver
list in ``phase1_no_waivers_used_check``. This gate is structural;
deferring it would re-open the silent-skip vector it was built to
catch.

Usage
-----
    python3 phase1_doc_input_completeness_check.py <project_dir>

Exit codes: 0 PASS / WARN, 1 FAIL, 2 input error / silent-skip.
Writes report to ``reports/phase1_input_vs_generated_completeness.json``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
import _path_layout as _pl

# Wave 86 / v1.6.11 Fix 3 — class applicability. This gate measures
# completeness of vendor-doc tokens that landed in L*.json. Pure-analog
# blocks (PMIC / amplifier / no command protocol) do NOT extract opcodes /
# registers / interface bytes; running 100% token-capture against their
# scant L1/L2/L5/L8/L13 produces false-positive FAILs. Bare-FPGA scaffolds
# similarly have no fabbed-IC vendor docs to extract from. SKIP both.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from ic_class_profile import detect_ic_class  # noqa: E402
except Exception:  # pragma: no cover — defensive: never block on import
    detect_ic_class = None  # type: ignore[assignment]

_APPLICABLE_CLASSES = {
    "aid_class_half_duplex",
    "digital_cmd_driven",
    "mixed_signal_otp",
    "protocol_aid",      # alias seen in some profiles
    "mcu_class",         # alias
    "mixed_signal_aid",  # alias
    "unknown",           # fail-closed: when detection is unsure, run.
}

# v1.6.535 — for #363 ORGANIC. Switch the gate semantic from a
# narrow allow-list to a broad deny-list. The audit checks
# (`pin_count_min`, `register_count_min`, design-token capture,
# etc.) measure **structural** extractor completeness against the
# class-AGNOSTIC L1-L23 schema, so SKIP-by-default for any non
# whitelisted class wrongly blinded the gate on 7-of-8 ICs of the
# field-agent's RV-CPU + analog benchmark rotation (processor_cpu /
# pure_analog / bare_fpga / digital_arithmetic_primitive were all
# excluded). Audit runs everywhere by default; only synthetic /
# passive-RF / non-IC fixtures are deny-listed.
_V1_6_535_INAPPLICABLE_CLASSES = frozenset({
    "passive_rf",
    "non_ic",
    "external_test_fixture",
})


def _v1_6_535_should_run_audit(ic_class):
    """Default-allow gate. Returns False only for classes whose
    underlying input artefact set (e.g. RF passive component
    catalogue, tester fixture pinout) has no structural L1-L23
    mapping — for every other class, including processor_cpu /
    pure_analog / bare_fpga / digital_arithmetic_primitive /
    unknown, the audit MUST run so the extractor-quality gate is
    actually exercised. Chip-AGNOSTIC: deny-list contains only
    class labels, never chip-specific literals."""
    if not ic_class:
        return True  # unknown / missing → fail-closed, run.
    return ic_class not in _V1_6_535_INAPPLICABLE_CLASSES


# Chip-AGNOSTIC design-token regex families. Wave-on-fix v1.6.10
# narrowed the set vs `extraction_coverage_denominator_audit`'s six
# families because three classes were producing systemic noise that
# legitimately does NOT belong in any L*.json:
#   * `Section|Table|Figure \d+` — these are page-navigation pointers,
#     not design facts. Dropped.
#   * `@<single-hex-char>` (e.g. `@3`, `@a`) — too short to disambiguate
#     from PDF text-extraction garble. Dropped.
#   * `\d+\.\s+<unit>` (e.g. `1. V`, `4. V`) — list-numbering artefact
#     where the period is an enumeration marker, not a decimal point.
#     Filtered post-match (see `_is_design_token`).
_REGEX_FAMILIES = (
    # `@0x...` only — bare `@<hex>` was dominated by PDF/DOC binary
    # extraction garble (EMF font tables, embedded image cells) and
    # produced ~95% false positives on Word-derived input.
    re.compile(r"@0x[0-9A-Fa-f]+"),
    # v1.6.50 fix: lookbehind ensures `0x` is not preceded by another
    # hex digit. Prior bare `0x[0-9A-Fa-f]+` would harvest `0x480`
    # from a `<digit>+x<digit>+` resolution literal like `640x480`,
    # `1920x1080`, `3 X 0x3F`, where the `x` is a multiplication /
    # dimension separator and the leading `0` is the trailing digit
    # of the previous number. Chip-AGNOSTIC: applies to any vendor
    # PDF that quotes display-resolution / dimension literals.
    re.compile(r"(?<![0-9A-Fa-f])0x[0-9A-Fa-f]+"),
    re.compile(r"[A-Z][A-Z0-9_]*\[\d+\]"),
    # v1.6.50 fix: leading `(?<![A-Za-z])` plus trailing `\b`
    # bracket the numeric+unit literal. The lookbehind rejects cases
    # where a digit run is the suffix of a reference designator
    # (`C129 V-`, `R86 12 ns`, `Q1234 5 V`) or a chip-name prefix
    # (`<vendor-prefix><digits>`). The trailing `\b` ensures the unit
    # token is not the prefix of a longer word AND is not followed
    # by a digit. Prior alternation would match `V` from `Vertical`,
    # `us` from `user`, `ms` from `message`, `ns` from `news`, etc.
    # — across whitespace from any nearby digit run, producing tokens
    # like `11.02 V` (from a `<YYYY.MM.DD> ... Vertical` page footer),
    # `17 us` (from `17 user pins`), or `2016.06 V` (from a revision-
    # history row `2016.06   V1.0   Initial`). `\b` rejects all three:
    # `V→e`, `s→e`, `V→1` are all word-char-to-word-char, no boundary.
    # `V→ ` / `V→.` / `V→,` are word-to-non-word, boundary fires,
    # legitimate voltage tokens still harvest. Chip-AGNOSTIC: applies
    # to any vendor PDF / IDE user-manual / application note that
    # places a numeric value in column-aligned proximity to an
    # English word or revision-tag starting with the same letter as
    # a unit (V/m/n/k/u/p/Hz/Ω/F).
    re.compile(
        r"(?<![A-Za-z0-9])"
        r"\d+\.?\d*[ \t\r]*(?:us|ms|ns|MHz|Hz|kHz|mV|kΩ|Ω|pF|nF|μF|nm|V)"
        r"\b"),
    re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b"),
)
# Binary-context window: a match is rejected when ≥30% of the 30
# chars on either side are non-printable (control chars, NUL, very
# high unicode). Catches the case where pandoc / libreoffice leaks
# EMF / WMF / embedded-font binary blocks into the .txt extraction
# and the regex fires on a few ASCII chars surrounded by binary.
_BINARY_CTX_WINDOW = 30
_BINARY_CTX_THRESHOLD = 0.30
_STOPLIST = frozenset({
    "JSON", "TRUE", "FALSE", "NULL", "TODO", "FIXME", "NOTE",
    "TBD", "TBA", "RTL", "PASS", "FAIL", "WARN", "INFO",
    "MIN", "MAX", "AVG", "STD",
    "THE", "AND", "WITH", "FOR", "MUST", "SHALL", "WILL", "FROM",
    "INTO", "THIS", "THAT", "WHEN", "WHERE", "WHILE", "BETWEEN",
    "OVER", "UNDER", "EACH", "ANY", "ALL", "BOTH", "SUCH",
    "BASED", "USED", "USE", "USES", "NEW", "OLD", "ONLY",
    "ONE", "TWO", "THREE", "BIT", "BYTE", "WORD",
    # v1.6.50: generic English nouns that the all-caps regex
    # `[A-Z][A-Z0-9_]{2,}` would otherwise harvest verbatim from
    # connector / table-header text (e.g. `USB B-TYPE` → `TYPE`).
    "TYPE", "NAME", "PIN", "PINS", "PORT", "PORTS",
})
# Token-shape reject list — PDF/text-extraction artefacts that the
# regex above can match but which are not real design content.
# Each entry is a regex matched with re.fullmatch on the normalised
# token. Chip-AGNOSTIC.
#
# v1.6.10 round 2 — `\d{4,}\s*V` rule removed. It was blocking
# legitimate ESD spec rows like `±2000 V` (HBM) / `±6000 V` (IEC).
# The original target (`26100 V` from `<companion-IC> V cells`) is now
# handled by reference-doc exclusion.
_TOKEN_REJECT_RES = (
    # `1. V` / `4. V` — enumeration marker leaking into numeric_unit.
    re.compile(r"\d+\.\s+[A-Za-zμµΩ]+"),
)

# v1.6.10 — gate now requires 100% capture of design tokens
# (post AI patch). Anything less is FAIL. The previous 50% / 80%
# thresholds are kept for the per-doc verdict labels in the report
# but do not change the overall gate verdict.
_FAIL_PCT = 1.0
_WARN_PCT = 1.0
_MIN_TOKENS = 10
# Sample only first N chars per file — gate is a budget probe, not
# exhaustive. Picked large enough that representative datasheets
# (typical 200KB) fit fully; very long PDFs get the head sampled.
_MAX_FILE_CHARS = 600_000


_WS_RUN_RE = re.compile(r"[ \t]+")


def _normalize_token(tok: str) -> str:
    """Collapse internal whitespace runs to a single space.
    PDF text-extractors often leave multi-space gaps inside
    `<num>   <unit>` literals (e.g. `127        kΩ`); the
    generated_docs/ haystack typically stores these with no space
    or one space (`127kΩ` / `127 kΩ`). Compare on the collapsed
    form so PDF spacing variance does not produce false-positive
    'missing' findings."""
    return _WS_RUN_RE.sub(" ", tok).strip()


def _is_design_token(tok: str) -> bool:
    """Reject regex-noise tokens (PDF artefacts) that should not
    enter the gate's denominator. Chip-AGNOSTIC."""
    for rx in _TOKEN_REJECT_RES:
        if rx.fullmatch(tok):
            return False
    return True


# Wave-on-fix v1.6.10 round 2 — Word/.doc structural markers are NOT
# binary garble: pandoc/libreoffice plain-text extraction emits these
# verbatim as table-cell / paragraph / page boundaries. Allow them so
# legitimate cells-in-tables (e.g. `0x08..0x23` OTP register address
# rows in A1101 CP, `2000 V`/`6000 V` ESD spec rows in <chip-class>) do not
# trigger the binary-context rejection.
#
#   0x07 BEL — Word table-cell mark
#   0x0B VT  — line feed within paragraph (Word soft-break)
#   0x0C FF  — page break
#   plus the existing tab / LF / CR already excluded
_WORD_STRUCTURAL_CHARS = frozenset(
    chr(o) for o in (0x07, 0x09, 0x0A, 0x0B, 0x0C, 0x0D))

_CONTROL_CHARS_FILTER = frozenset(
    chr(o) for o in range(0x20)
    if chr(o) not in _WORD_STRUCTURAL_CHARS
) | {chr(0x7F)}


def _looks_like_utf16_le_leak(window: str) -> bool:
    """Detect a UTF-16-LE-as-ASCII leak — every other byte is
    `\\x00` (high byte of an ASCII char in UTF-16 LE). When
    pandoc/libreoffice mishandles a Word/RTF table this is what
    comes out — it is structured encoding, NOT random binary
    garble. Real-world windows often carry a PARTIAL leak: e.g.
    a UTF-16-encoded label prefix followed by an ASCII-decoded
    table body. The detector therefore looks for any contiguous
    run of length ≥6 in which every second character is NUL,
    rather than requiring NUL to dominate the whole window."""
    if "\x00" not in window:
        return False
    # Slide a window-of-6 across `window` and check whether the
    # 0,2,4 indices are non-NUL printables and 1,3,5 are NUL.
    L = len(window)
    for i in range(0, L - 5):
        a, na, b, nb, c, nc = window[i:i + 6]
        if (na == "\x00" and nb == "\x00" and nc == "\x00"
                and a != "\x00" and b != "\x00" and c != "\x00"):
            return True
    return False


def _is_binary_context(text: str, span_start: int, span_end: int) -> bool:
    """Return True when the windowed surroundings of a regex match
    contain too many non-printable / control characters — the
    canonical signature of a PDF/Word binary blob leaking into
    pandoc / libreoffice plain-text extraction.

    Two independent triggers (chip-AGNOSTIC):
      A) ≥2 ASCII control chars (NUL/0x01..0x06/0x08/0x0E..0x1F/
         0x7F, excluding tab/LF/CR/BEL/VT/FF — the latter three are
         legitimate Word table-cell / soft-break / page markers) in
         the window — these never appear in legitimate prose; two
         is decisive.
      B) ≥`_BINARY_CTX_THRESHOLD` (30%) of the window characters fall
         outside printable-ASCII / CJK / common-CJK-punct.
    Either trigger rejects the match. UTF-16-LE leakage (alternating
    NUL bytes) is detected separately and exempted — it is regular
    encoding noise, not random binary, and the legitimate ASCII
    half-bytes carry real design content.
    """
    a = max(0, span_start - _BINARY_CTX_WINDOW)
    b = min(len(text), span_end + _BINARY_CTX_WINDOW)
    window = text[a:span_start] + text[span_end:b]
    if not window:
        return False
    if _looks_like_utf16_le_leak(window):
        return False
    ctrl_hits = sum(1 for ch in window if ch in _CONTROL_CHARS_FILTER)
    if ctrl_hits >= 2:
        return True
    bad = 0
    for ch in window:
        o = ord(ch)
        if ch in _WORD_STRUCTURAL_CHARS:  # tab/LF/CR/BEL/VT/FF
            continue
        if 0x20 <= o <= 0x7E:
            continue
        if 0x4E00 <= o <= 0x9FFF:  # CJK Unified Ideographs
            continue
        if 0x3000 <= o <= 0x33FF:  # CJK punctuation / katakana / etc
            continue
        bad += 1
    return (bad / len(window)) >= _BINARY_CTX_THRESHOLD


def _harvest_tokens(text: str):
    """Returns (design_tokens, garble_tokens).

    design_tokens — tokens whose surrounding context is clean text;
                    these are subject to the gate's 100% threshold.
    garble_tokens — tokens that matched the regex BUT sit inside a
                    PDF/DOC binary blob (control-char dense window)
                    OR match a known token-shape reject pattern.
                    Reported for transparency; do NOT gate.

    A token wins design status if AT LEAST ONE of its occurrences
    has clean context. So `OSC_PTRIM_CODE` appearing once in clean
    prose and once inside a font table is design, not garble.
    """
    seen_clean: set = set()
    seen_dirty: set = set()
    for rx in _REGEX_FAMILIES:
        for m in rx.finditer(text):
            tok = m.group(0)
            tok = tok.strip() if isinstance(tok, str) else ""
            if (not tok or "\n" in tok or "\r" in tok or "\t" in tok
                    or tok.upper() in _STOPLIST):
                continue
            normalised = _normalize_token(tok)
            if not _is_design_token(normalised):
                # token-shape rejects (`1. V`, `\d{4,} V`)
                seen_dirty.add(normalised)
                continue
            if _is_binary_context(text, m.start(), m.end()):
                seen_dirty.add(normalised)
                continue
            seen_clean.add(normalised)
    # Tokens that have BOTH a clean and a dirty occurrence count
    # as design (clean wins).
    seen_dirty -= seen_clean
    return seen_clean, seen_dirty


# Heuristic patterns for FPGA-board / PDK / OTP-cell / sibling-chip
# reference docs that ship inside `input/docs/` for context but do not
# describe the target chip itself. These are chip-AGNOSTIC filename
# stems published by mainstream vendors / commodity peripherals — the
# stems themselves carry no project-specific data. Auto-detection
# saves the user the per-project ritual of writing
# `completeness_check_config.json:reference_docs[]` for every fresh
# project that uses a standard DE10-Lite + Sky/MAX10 PDK + a TI/Apple
# protocol-reference IC. A user-supplied
# `completeness_check_config.json:reference_docs[]` is appended to,
# not replaced. To opt out, set `auto_reference_docs: false` in the
# config.
_AUTO_REFERENCE_DOC_GLOBS = (
    # Terasic FPGA boards
    "DE0*", "DE1*", "DE2*", "DE10*", "DE10-Lite*", "DE10-Nano*",
    "DE0-Nano*", "de0-*", "de1-*", "de2-*", "de10-*",
    # Intel / Altera MAX / Cyclone GPIO + family user guides
    "ug-m10-*", "ug-cyclone*", "ug-stratix*", "ug-arria*",
    # Generic OTP / EEPROM cell datasheets (fab IP, EO/EM/EE prefix)
    "EO[0-9]*", "EM[0-9]*", "EE[0-9]*",
    # Sibling-chip / competitor datasheets that ship as protocol refs
    # (TI bq*, Maxim DS*, microchip 24*)
    "bq[0-9]*",
)


def _load_reference_doc_globs(project: Path):
    """Optional `<project>/completeness_check_config.json` may carry
    a `reference_docs` list of filename glob patterns. Tokens from
    matching docs are still counted in the report but do NOT gate
    the verdict. Chip-AGNOSTIC: globs are user-supplied filename
    patterns, no IC-specific data.

    In addition, a built-in chip-AGNOSTIC heuristic auto-classifies
    common FPGA-board / PDK-OTP-cell / sibling-chip filename stems
    (DE10-Lite_*, ug-m10-*, EO[0-9]*, bq[0-9]* …) as reference docs
    so users do not have to write the same boilerplate per project.
    The user can opt out by setting `auto_reference_docs: false` in
    the config.
    """
    cfg = _pl.phase1_completeness_check_config_file(project)
    user_globs: list = []
    auto_enabled = True
    if cfg.is_file():
        try:
            data = json.loads(cfg.read_text())
            refs = data.get("reference_docs") or []
            user_globs = [g for g in refs if isinstance(g, str) and g]
            if data.get("auto_reference_docs") is False:
                auto_enabled = False
        except Exception:
            pass
    auto = list(_AUTO_REFERENCE_DOC_GLOBS) if auto_enabled else []
    # User globs win on dedup but both lists are honoured; fnmatch is
    # OR-semantics so order does not matter.
    seen: set = set()
    out: list = []
    for g in user_globs + auto:
        if g not in seen:
            seen.add(g)
            out.append(g)
    return out


def _is_reference_doc(name: str, globs):
    import fnmatch
    for g in globs:
        if fnmatch.fnmatch(name, g):
            return True
    return False


_AI_MARKER = "ai_deep_review_patch"


def _split_ai_vs_program(node):
    """Walk a parsed JSON node and return (ai_text, program_text)
    haystacks. Any dict containing `extraction_strategy:
    ai_deep_review_patch` (recursively, including ancestor dicts)
    is serialised into ai_text; everything else into program_text."""
    ai_parts: list = []
    prog_parts: list = []

    def _is_ai_dict(d):
        if not isinstance(d, dict):
            return False
        if d.get("extraction_strategy") == _AI_MARKER:
            return True
        if d.get("label") == _AI_MARKER:
            return True
        if d.get("strategy") == _AI_MARKER:
            return True
        return False

    def _walk(n):
        if _is_ai_dict(n):
            ai_parts.append(json.dumps(n, ensure_ascii=False))
            return
        if isinstance(n, dict):
            for k, v in n.items():
                if isinstance(v, (dict, list)):
                    _walk(v)
                else:
                    prog_parts.append(json.dumps({k: v},
                                                  ensure_ascii=False))
        elif isinstance(n, list):
            for it in n:
                if isinstance(it, (dict, list)):
                    _walk(it)
                else:
                    prog_parts.append(json.dumps(it,
                                                  ensure_ascii=False))
        else:
            prog_parts.append(json.dumps(n, ensure_ascii=False))

    _walk(node)
    return "\n".join(ai_parts), "\n".join(prog_parts)


def _resolve_sidecar_path(project: Path) -> Path | None:
    """Return the effective sidecar path, preferring the canonical
    `<project>/phase1/ai_deep_review_patches.json` (what the resolver +
    every gate read). If that file is absent but a same-named file exists
    at the PROJECT ROOT (`<project>/ai_deep_review_patches.json` — the path
    a fresh agent following an older doc may have written), emit a one-line
    WARNING to stderr and fall back to the ROOT file for backward-compat,
    so a misplaced sidecar is surfaced and still honoured instead of being
    silently dropped. Returns None when neither file exists.
    """
    canonical = _pl.phase1_ai_deep_review_patches_file(project)
    if canonical.is_file():
        return canonical
    root_legacy = project / "ai_deep_review_patches.json"
    if root_legacy.is_file():
        print(
            "WARNING — ai_deep_review_patches.json found at project ROOT "
            f"({root_legacy}); canonical location is "
            f"{canonical}. Reading the ROOT copy for backward-compat — "
            "please move it under phase1/.",
            file=sys.stderr,
        )
        return root_legacy
    return None


def _load_ai_patches_sidecar(project: Path):
    """Return a dict {layer_name: serialised_patches_text} from
    `<project>/phase1/ai_deep_review_patches.json`.

    The sidecar is the durable home of AI deep-review patches —
    storing them inside `generated_docs/L*.json` is unsafe because
    `phase1_one_shot_runner.py` rewrites those files from scratch
    on every Phase 1 (doc-extraction) run. The sidecar lives outside generated_docs
    and survives runner regeneration.

    Sidecar format:
        {
          "patches": {
            "L1_DATASHEET":      [{...}, {...}],
            "L3_CMD_PROTOCOL":   [...],
            ...
          }
        }
    Each patch entry is a dict that includes
    `extraction_strategy: "ai_deep_review_patch"`. The completeness
    gate treats sidecar entries as if they were inside the named
    L doc.
    """
    side = _resolve_sidecar_path(project)
    if side is None:
        return {}
    try:
        data = json.loads(side.read_text(errors="replace"))
    except Exception:
        return {}
    patches = data.get("patches") or {}
    out: dict = {}
    if not isinstance(patches, dict):
        return out
    for layer, lst in patches.items():
        if not isinstance(lst, list):
            continue
        try:
            out[layer] = json.dumps(lst, ensure_ascii=False)
        except Exception:
            continue
    return out


def _load_generated_haystacks(project: Path):
    """Return a dict {layer_name: blob_dict} per L*.json
    (plus AI patches merged from the sidecar).

    blob_dict carries:
      raw           — full file text (for verbatim substring search)
      norm          — whitespace-collapsed text (PDF-tolerant)
      no_space      — whitespace-stripped text (`127 kΩ` ↔ `127kΩ`)
      ai_count      — number of `ai_deep_review_patch` markers in
                       sidecar entries for this layer
      ai_text       — concatenated JSON of AI-patched sub-trees
                       (from L*.json AND sidecar)
      ai_text_ns    — `ai_text` with whitespace stripped
      prog_text     — everything that is NOT under an AI-patched
                       sub-tree
      prog_text_ns  — `prog_text` with whitespace stripped
    """
    gen_dir = _pl.generated_docs_dir(project)
    out: dict = {}
    if not gen_dir.is_dir():
        return out
    sidecar = _load_ai_patches_sidecar(project)
    for p in sorted(gen_dir.glob("L*.json")):
        try:
            raw = p.read_text(errors="replace")
        except Exception:
            continue
        layer = p.stem
        sidecar_text = sidecar.get(layer, "")
        # The full haystack = L doc raw + sidecar text. Norm /
        # no_space variants are computed on the combined text.
        combined_raw = raw + ("\n" + sidecar_text if sidecar_text else "")
        norm = _WS_RUN_RE.sub(" ", combined_raw)
        no_space = norm.replace(" ", "")
        ai_text_inline = ""
        prog_text = raw
        try:
            data = json.loads(raw)
            ai_text_inline, prog_text = _split_ai_vs_program(data)
        except Exception:
            pass
        ai_text = (ai_text_inline + "\n" + sidecar_text
                   if sidecar_text else ai_text_inline)
        ai_count = (raw.count(f'"{_AI_MARKER}"')
                    + sidecar_text.count(f'"{_AI_MARKER}"'))
        out[layer] = {
            "raw": combined_raw,
            "norm": norm,
            "no_space": no_space,
            "ai_count": ai_count,
            "ai_text": ai_text,
            "ai_text_ns": ai_text.replace(" ", ""),
            "prog_text": prog_text,
            "prog_text_ns": prog_text.replace(" ", ""),
        }
    # Layers that exist in sidecar but not in generated_docs/ —
    # uncommon but legitimate (e.g. user pre-staged patches before
    # phase1 ran). Surface them so their tokens still count.
    for layer, sidecar_text in sidecar.items():
        if layer in out or not sidecar_text:
            continue
        norm = _WS_RUN_RE.sub(" ", sidecar_text)
        out[layer] = {
            "raw": sidecar_text,
            "norm": norm,
            "no_space": norm.replace(" ", ""),
            "ai_count": sidecar_text.count(f'"{_AI_MARKER}"'),
            "ai_text": sidecar_text,
            "ai_text_ns": sidecar_text.replace(" ", ""),
            "prog_text": "",
            "prog_text_ns": "",
        }
    return out


def _attribute_token(tok: str, layer_blobs):
    """Return a tuple `(layers_hit, source)` where:
      layers_hit = list of L doc names that contain the token
      source     = "ai" if any hit was inside an AI-patched
                   sub-tree, else "program" if any hit was in
                   deterministic content, else "missing".
    Token is matched under raw / single-space / no-space normalisation.
    """
    if not tok:
        return [], "missing"
    tok_ns = tok.replace(" ", "")
    layers_hit: list = []
    found_in_ai = False
    found_in_prog = False
    for layer, blob in layer_blobs.items():
        in_layer = ((tok in blob["raw"]) or
                    (tok in blob["norm"]) or
                    (tok_ns in blob["no_space"]))
        if not in_layer:
            continue
        layers_hit.append(layer)
        if (tok in blob["ai_text"]) or (tok_ns in blob["ai_text_ns"]):
            found_in_ai = True
        elif (tok in blob["prog_text"]) or (tok_ns in blob["prog_text_ns"]):
            found_in_prog = True
        else:
            # Substring landed in haystack but not in either split
            # (e.g. inside a key name or json-escape boundary).
            # Treat as program-captured by default.
            found_in_prog = True
    if not layers_hit:
        return [], "missing"
    if found_in_ai and not found_in_prog:
        return layers_hit, "ai"
    if found_in_ai and found_in_prog:
        # Both — prefer "program" since the deterministic capture
        # already had it; AI patch is then redundant.
        return layers_hit, "program"
    return layers_hit, "program"


def _is_captured(tok: str, layer_blobs):
    """Backwards-compat wrapper — returns just the list of layers
    a token appears in (legacy callers don't care about source)."""
    return _attribute_token(tok, layer_blobs)[0]


def _list_input_docs(project: Path):
    """Yield (logical_name, text) tuples for each input document.
    Prefer input_doc/*.txt (already plain text). Falls back to
    input/docs/*.txt for projects that pre-extracted manually."""
    seen_names: set = set()
    pairs = []
    p1 = _pl.input_doc_dir(project)
    if p1.is_dir():
        for p in sorted(p1.glob("*.txt")):
            if p.name in seen_names:
                continue
            seen_names.add(p.name)
            try:
                txt = p.read_text(errors="replace")[:_MAX_FILE_CHARS]
            except Exception:
                continue
            pairs.append((p.name, txt))
    p2 = project / "input" / "docs"
    if p2.is_dir():
        for p in sorted(p2.glob("*.txt")):
            if p.name in seen_names:
                continue
            seen_names.add(p.name)
            try:
                txt = p.read_text(errors="replace")[:_MAX_FILE_CHARS]
            except Exception:
                continue
            pairs.append((p.name, txt))
    return pairs


def main(argv=None) -> int:
    # Wave 86 / v1.6.11 Fix 4 — argparse with optional flag.
    #
    #   --baseline-allow-incomplete : 100% threshold downgraded to WARN
    #     (rc=0). Use ONLY for legacy-project regression where the
    #     baseline coverage is already known to be < 100% and we want
    #     the gate to *report* without breaking CI. Fresh / production
    #     projects MUST NOT pass this flag — strict 100% is the contract.
    parser = argparse.ArgumentParser(
        prog="phase1_doc_input_completeness_check",
        description="Per-doc completeness gate: every input doc's "
                    "harvested tokens must land somewhere in the union "
                    "of generated_docs/L*.json.",
    )
    parser.add_argument("project_dir",
                        help="Path to project directory.")
    parser.add_argument(
        "--baseline-allow-incomplete",
        action="store_true",
        help=("Downgrade the 100%% threshold to WARN (rc=0) instead of "
              "FAIL. Baseline mode for legacy regression only. Formal "
              "acceptance MUST NOT use this flag."),
    )
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        parser.print_usage()
        return 2
    args = parser.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 2

    # v1.6.535 — for #363 ORGANIC. Class-gate semantic inverted from
    # allow-list (Wave 86) to deny-list. The Wave-86 allow-list was
    # added because token-capture against scant L docs produced
    # false-positive FAILs on pure-analog / bare-FPGA scaffolds, but
    # excluding processor_cpu / pure_analog / bare_fpga /
    # digital_arithmetic_primitive blinded the field-agent's audit
    # gate on 7-of-8 ICs in the RV-CPU + analog rotation. The new
    # gate runs by default and only SKIPs for classes whose entire
    # artefact set sits outside the L1-L23 contract (passive RF /
    # tester-fixture pinouts / non-IC inputs). Chip-AGNOSTIC.
    if detect_ic_class is not None:
        try:
            profile = detect_ic_class(project) or {}
            ic_class = profile.get("ic_class", "unknown")
        except Exception:  # pragma: no cover — fail-closed on detection
            ic_class = "unknown"
        if not _v1_6_535_should_run_audit(ic_class):
            print(f"SKIP — not applicable for IC class {ic_class}.")
            return 0

    layer_blobs = _load_generated_haystacks(project)
    if not layer_blobs:
        print("SKIP — no generated_docs/L*.json present "
              "(run phase1 first).")
        return 0

    pairs = _list_input_docs(project)
    if not pairs:
        print("SKIP — no input docs found "
              "(input_doc/ or input/docs/).")
        return 0

    ref_globs = _load_reference_doc_globs(project)

    # Per-doc and aggregate accounting. For each input doc we
    # split its tokens into three buckets:
    #   program_captured — present in deterministic phase1 output
    #   ai_captured      — present only inside an AI-patched
    #                       sub-tree (extraction_strategy =
    #                       ai_deep_review_patch)
    #   missing          — not present in any L*.json
    all_tokens: set = set()
    all_garble: set = set()
    program_tokens_global: set = set()
    ai_tokens_global: set = set()
    reference_docs_seen: list = []
    per_doc = []
    fail_docs = []
    warn_docs = []
    for name, text in pairs:
        is_ref = _is_reference_doc(name, ref_globs)
        if is_ref:
            reference_docs_seen.append(name)
        design_toks, garble_toks = _harvest_tokens(text)
        # Reference docs do not contribute to the global denominator —
        # their tokens describe a different chip/platform and have no
        # reason to appear in our L*.json. They are still reported per
        # doc for transparency.
        if not is_ref:
            all_tokens |= design_toks
            all_garble |= garble_toks
        n = len(design_toks)
        n_garble = len(garble_toks)
        if n < _MIN_TOKENS:
            per_doc.append({
                "doc": name,
                "distinct": n,
                "raw_total": n + n_garble,
                "garble_or_artefact": n_garble,
                "program_captured": n, "ai_captured": 0,
                "missing": 0,
                "captured_pct": 1.0,
                "verdict": ("SKIP_REFERENCE" if is_ref
                            else "SKIP_LOW_TOKENS"),
                "missing_sample": [],
                "reference_doc": is_ref,
            })
            continue
        prog_cnt = 0
        ai_cnt = 0
        missing = []
        for tok in design_toks:
            _layers, source = _attribute_token(tok, layer_blobs)
            if source == "program":
                prog_cnt += 1
                if not is_ref:
                    program_tokens_global.add(tok)
            elif source == "ai":
                ai_cnt += 1
                if not is_ref:
                    ai_tokens_global.add(tok)
            else:
                missing.append(tok)
        captured = prog_cnt + ai_cnt
        pct = captured / n if n else 1.0
        missing_sample = sorted(missing,
                                key=lambda x: (-len(x), x))[:30]
        if is_ref:
            verdict = "SKIP_REFERENCE"
        elif pct < 1.0:
            verdict = "FAIL"
            fail_docs.append(name)
        else:
            verdict = "PASS"
        per_doc.append({
            "doc": name,
            "distinct": n,
            "raw_total": n + n_garble,
            "garble_or_artefact": n_garble,
            "program_captured": prog_cnt,
            "ai_captured": ai_cnt,
            "missing": len(missing),
            "captured": captured,
            "captured_pct": round(pct, 4),
            "verdict": verdict,
            "missing_sample": missing_sample,
            "reference_doc": is_ref,
        })

    # Per-Layer cell roll-up. For each L*.json:
    #   caught_cells       = unique input-doc tokens that appear in
    #                        this layer (substring under any norm).
    #   ai_patched_cells   = entries in this L doc carrying
    #                        `extraction_strategy: ai_deep_review_patch`
    #                        (semantic AI patches applied by
    #                        phase1-completeness-deep-review skill).
    # Plus a synthetic 'unallocated' row for tokens that no L doc
    # captured.
    per_layer = []
    captured_anywhere = 0
    captured_by_layer = {layer: set() for layer in layer_blobs}
    for tok in all_tokens:
        hits = _is_captured(tok, layer_blobs)
        if hits:
            captured_anywhere += 1
            for layer in hits:
                captured_by_layer[layer].add(tok)
    for layer in sorted(layer_blobs.keys()):
        per_layer.append({
            "layer": layer,
            "caught_cells": len(captured_by_layer[layer]),
            "ai_patched_cells": layer_blobs[layer]["ai_count"],
        })
    missing_anywhere = len(all_tokens) - captured_anywhere
    per_layer.append({
        "layer": "(unallocated)",
        "caught_cells": 0,
        "ai_patched_cells": 0,
        "missing_cells": missing_anywhere,
    })

    # 100% threshold (post AI patch). Any non-reference doc with
    # missing tokens FAILs the gate.
    #
    # Wave 86 Fix 4 — `--baseline-allow-incomplete` downgrades FAIL → WARN.
    # WARN exits 0 so legacy-project regression does not always-FAIL CI;
    # the report still names every short doc and the verdict in the JSON
    # is preserved as "WARN" so a human / outer pipeline can see what was
    # tolerated. NEVER pass this flag for tapeout-bound projects.
    if not fail_docs:
        overall = "PASS"
    elif args.baseline_allow_incomplete:
        overall = "WARN"
    else:
        overall = "FAIL"

    report = {
        "gate": "phase1_doc_input_completeness_check",
        "verdict": overall,
        "fail_threshold_pct": _FAIL_PCT,
        "warn_threshold_pct": _WARN_PCT,
        "min_tokens_for_audit": _MIN_TOKENS,
        "total_distinct_tokens_across_inputs": len(all_tokens),
        "tokens_captured_in_any_layer": captured_anywhere,
        "tokens_missing_everywhere": missing_anywhere,
        "fail_docs": fail_docs,
        "warn_docs": warn_docs,
        "reference_docs": reference_docs_seen,
        "ai_captured_tokens_count": len(ai_tokens_global),
        "per_layer": per_layer,
        "per_doc": per_doc,
    }
    # v1.6.27: route via auto-router → reports/phase1/.
    out = _pl.report_path(project, "phase1_input_vs_generated_completeness.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    # Companion Markdown — per-document AND per-Layer tables. The
    # per-document view answers "for each input doc, what did the
    # deterministic phase1 programs capture, what did AI patch,
    # what is still missing"; the per-Layer view answers "what
    # ended up in each L*.json".
    raw_total_global = len(all_tokens) + len(all_garble)
    md_lines = [
        "# Phase 1 (doc-extraction) — input → generated_docs cell completeness",
        "",
        f"**Verdict**: {overall}",
        f"**Raw cell matches across non-reference docs**: "
        f"{raw_total_global}",
        f"  - design cells (clean context, gated): "
        f"{len(all_tokens)}",
        f"  - garble / PDF-DOC binary artefact cells "
        f"(reported, NOT gated): {len(all_garble)}",
    ]
    if all_tokens:
        md_lines.append(
            f"**Captured (program + AI)**: {captured_anywhere} "
            f"({captured_anywhere / len(all_tokens):.1%})")
        md_lines.append(
            f"**Program-only cells**: "
            f"{len(program_tokens_global)}")
        md_lines.append(
            f"**AI-only cells (extraction_strategy = "
            f"ai_deep_review_patch)**: {len(ai_tokens_global)}")
        md_lines.append(f"**Missing everywhere**: {missing_anywhere}")
    md_lines.extend([
        "",
        "## Per-document cell counts",
        "",
        "| Document | raw_total | design | garble | "
        "program_captured | ai_captured | missing | verdict |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    # Render docs in deterministic order — by raw_total descending so
    # the heavyweight datasheets are at the top.
    for d in sorted(per_doc, key=lambda r: -r.get("raw_total", 0)):
        md_lines.append(
            f"| {d['doc']} | {d.get('raw_total', d['distinct'])} | "
            f"{d['distinct']} | "
            f"{d.get('garble_or_artefact', 0)} | "
            f"{d.get('program_captured', 0)} | "
            f"{d.get('ai_captured', 0)} | {d.get('missing', 0)} | "
            f"{d['verdict']} |")
    md_lines.extend([
        "",
        "## Per-Layer cell counts",
        "",
        "| Layer | caught_cells | ai_patched_cells | missing_cells |",
        "| --- | ---: | ---: | ---: |",
    ])
    for row in per_layer:
        md_lines.append(
            f"| {row['layer']} | {row.get('caught_cells', 0)} | "
            f"{row.get('ai_patched_cells', 0)} | "
            f"{row.get('missing_cells', '')} |")
    md_lines.append("")
    md_lines.append("Cell = chip-AGNOSTIC vendor token harvested "
                    "from input docs (numeric+unit, hex const, "
                    "register / pin / opcode identifier, section "
                    "ref, etc.). `program_captured` = caught by "
                    "deterministic phase1 programs. `ai_captured` "
                    "= caught only inside an AI-patched sub-tree "
                    "(`extraction_strategy: ai_deep_review_patch`) "
                    "added by the `phase1-completeness-deep-review` "
                    "skill. `missing` = present in input doc but "
                    "in no L*.json.")
    # v1.6.27: route via auto-router → reports/phase1/.
    md_out = _pl.report_path(project, "phase1_input_vs_generated_completeness.md")
    md_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    if overall in ("FAIL", "WARN"):
        verb = ("WARN (baseline-allow-incomplete)"
                if overall == "WARN" else "FAIL")
        print(f"{verb} — {len(fail_docs)} input doc(s) below 100% "
              f"capture (program + AI). Per-doc report: "
              f"{out.relative_to(project)}")
        for d in per_doc:
            if d["verdict"] == "FAIL":
                print(f"  - {d['doc']}: {d['captured']}/"
                      f"{d['distinct']} = {d['captured_pct']:.1%}; "
                      f"missing {d['missing']}; "
                      f"sample: {', '.join(d['missing_sample'][:6])}")
        print()
        print("v1.6.10 threshold: every non-reference input doc must "
              "reach 100% (deterministic phase1 + AI deep-review "
              "patches combined). Fix path: invoke "
              "`phase1-completeness-deep-review` skill — AI inspects "
              "each missing token, classifies it, patches L*.json with "
              "extraction_strategy=ai_deep_review_patch, and submits a "
              "community-backlog entry for any systematic gap. "
              "Reference / competitor docs may be marked in "
              "<project>/completeness_check_config.json:reference_docs[] "
              "to exempt them. NO waiver allowed (forbidden prefix "
              "`phase1_input_vs_generated_*`).")
        return 0 if overall == "WARN" else 1
    print(f"PASS — all {len([d for d in per_doc if not d.get('reference_doc')])} "
          f"non-reference input doc(s) at 100% capture; "
          f"{len(reference_docs_seen)} reference doc(s) exempted; "
          f"{len(ai_tokens_global)} cell(s) caught by AI deep-review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
