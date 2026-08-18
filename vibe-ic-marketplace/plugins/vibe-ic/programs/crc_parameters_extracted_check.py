#!/usr/bin/env python3
"""
crc_parameters_extracted_check.py — gate (LL-34) catching extractor
failures on CRC parameter sections in vendor docs.

Why this gate exists
====================
v0.119.30 <benchmark> vendor benchmark — fresh agent guessed CRC init=0x00
even though the vendor FRS dedicates a whole section to declaring
the CRC parameters explicitly (polynomial X^8+X^5+X^4+1, reflected
representation 0x8C, init=0xFF on every break, full reference
C-code, plus a verified vector table). pdftotext / libreoffice DO
capture the §-7-style block as plain text — the agent simply did
not parse it. Result: every CRC byte in the response was wrong on
real silicon, and connect_test FAILed.

This is a Cat A — extractor capability — gap, not a docs gap.

Rule
----
Trigger condition: an extracted text doc is found in one of:
    <project>/reports/pdf/*.txt
    <project>/input_doc/*.txt
    <project>/input/docs/*.txt
that contains BOTH

    (1)  a polynomial declaration:
            * the literal word "polynomial" or "polynomial function"
              (case-insensitive), AND
            * a hex value (`0x[0-9A-Fa-f]+`)
              OR a polynomial form (`X^? n + X^? n + ...`).

    (2)  one of:
            * "init"/"initial"/"seed"/"reset" near a hex value, OR
            * any of "LSB.first" / "MSB.first" / "reflected"
              / "reverse" / "bit order".

When triggered:
    * L3_CMD_PROTOCOL.json (under <project>/generated_docs/ or
      <project>/docs/ or <project>/) MUST emit a `crc_parameters`
      dict (or a `crc` dict — both accepted) whose declared
      sub-keys include all of:
          - polynomial_hex                (or `poly`)
          - init_hex                      (or `init`)
          - bit_order                     ("lsb_first"/"msb_first")
                                          (or `refin`/`refout`
                                          booleans)
      …with optional
          - polynomial_reflected_hex
          - xorout_hex
      …and:
          - vendor_evidence_path / decision_source / evidence /
            cite — citation string pointing to the doc + line range
            (e.g. "MDV-A1101-FRS §7 lines 1721-1766").

    * If a `source` field is present and equals
      `BRUTE_FORCED_FROM_VECTORS`, then `vendor_evidence_path`
      becomes mandatory — without an evidence path the gate FAILs
      because the doc has the §7-style block but the agent
      bypassed it.

Silent-skips when no extracted-text doc has CRC signals (general —
covers I2C-only ICs, pure analog, SPI ROM, etc.).

Honors waiver `crc_parameters_brute_forced_intentional` (≥40 chars).

Usage
-----
    python3 crc_parameters_extracted_check.py <project_dir>

Returns 0 on PASS / silent-skip / waived, 1 on FAIL.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


# Match either a 0x.. hex constant or an X^n + X^m + ... polynomial form.
HEX_VAL = re.compile(r"0[xX][0-9A-Fa-f]+")
POLY_FORM = re.compile(
    r"X\s*\^?\s*\d+\s*\+\s*X\s*\^?\s*\d+",
)
INIT_NEAR_HEX = re.compile(
    r"\b(init(?:ial)?|seed|reset)\b[^\n]{0,80}?0[xX][0-9A-Fa-f]+",
    re.IGNORECASE,
)
ORDER_HINT = re.compile(
    r"\b(LSB[\s\-]?first|MSB[\s\-]?first|reflected|reverse(?:d)?"
    r"|bit[\s\-]?order)\b",
    re.IGNORECASE,
)
POLY_LINE = re.compile(r"polynomial(?:\s+function)?", re.IGNORECASE)


def _extracted_text_files(project: Path) -> list[Path]:
    out: list[Path] = []
    bases = [
        (_pl.reports_phase1_dir(project) / "pdf"),
        _pl.input_doc_dir(project),
        project / "input" / "docs",
        (_pl.reports_phase1_dir(project) / "doc_extract"),
    ]
    for base in bases:
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() in {".txt", ".md"}:
                out.append(p)
    return out


def _crc_signals(text: str) -> tuple[bool, list[int]]:
    """Return (has_crc_signals, line_numbers_of_evidence).

    A doc qualifies iff it has BOTH a polynomial declaration with a
    hex / polynomial-form value AND an init/order signal."""
    lines = text.splitlines()
    poly_hits: list[int] = []
    order_hits: list[int] = []
    init_hits: list[int] = []
    for i, ln in enumerate(lines, 1):
        if POLY_LINE.search(ln) and (HEX_VAL.search(ln) or POLY_FORM.search(ln)):
            poly_hits.append(i)
        # also match polynomial declared in following lines
        elif POLY_LINE.search(ln):
            # look 4 lines ahead for hex / poly form
            for j in range(i, min(i + 4, len(lines))):
                if HEX_VAL.search(lines[j]) or POLY_FORM.search(lines[j]):
                    poly_hits.append(i)
                    break
        if INIT_NEAR_HEX.search(ln):
            init_hits.append(i)
        if ORDER_HINT.search(ln):
            order_hits.append(i)
    has_signals = bool(poly_hits) and bool(init_hits or order_hits)
    evidence = sorted(set(poly_hits + init_hits + order_hits))
    return has_signals, evidence


def _load_l3(project: Path) -> tuple[Path | None, dict | None]:
    for stem in ("L3_CMD_PROTOCOL.json", "L3_PROTOCOL.json"):
        for base in (
            _pl.generated_docs_dir(project),
            project / "docs",
            project,
        ):
            p = base / stem
            if p.is_file():
                try:
                    return p, json.loads(p.read_text(errors="replace"))
                except Exception:
                    return p, None
    return None, None


def _has_required_crc_params(d: dict) -> tuple[bool, list[str], dict]:
    """Walk top + nested dicts looking for a CRC-parameters block.

    Returns (ok, missing_subkeys, the_block_we_found).
    Accepts either canonical `crc_parameters` shape or the older
    `crc` shape with `poly`/`init`/`refin` etc.
    """
    candidates: list[dict] = []

    def _walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, dict):
                    if k.lower() in ("crc_parameters", "crc"):
                        candidates.append(v)
                    _walk(v)
                elif isinstance(v, list):
                    for item in v:
                        _walk(item)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(d)
    if not candidates:
        return False, ["crc_parameters (or crc) block missing entirely"], {}

    # Pick the first non-empty candidate.
    block = next((c for c in candidates if c), candidates[0])
    missing: list[str] = []
    keys_lc = {k.lower(): k for k in block.keys()}

    # poly
    if not (any(k in keys_lc for k in (
            "polynomial_hex", "polynomial", "poly"))):
        missing.append("polynomial_hex")
    # init
    if not (any(k in keys_lc for k in (
            "init_hex", "init", "init_value", "seed"))):
        missing.append("init_hex")
    # bit-order — accept either explicit `bit_order` or refin/refout
    has_order = (
        "bit_order" in keys_lc
        or "refin" in keys_lc
        or "refout" in keys_lc
        or "reflected" in keys_lc
    )
    if not has_order:
        missing.append("bit_order")

    return (not missing), missing, block


def _evidence_path_present(block: dict) -> bool:
    keys_lc = {k.lower(): k for k in block.keys()}
    for k in ("vendor_evidence_path", "evidence", "cite", "citation",
             "decision_source", "derived_from_vectors"):
        if k in keys_lc:
            v = block[keys_lc[k]]
            if isinstance(v, str) and v.strip():
                return True
            if isinstance(v, dict) and v:
                return True
    return False


def _waived(project: Path) -> bool:
    p = project / "waivers.json"
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text())
    except Exception:
        return False
    v = d.get("crc_parameters_brute_forced_intentional", "")
    return isinstance(v, str) and len(v.strip()) >= 40


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: crc_parameters_extracted_check.py <project_dir>")
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 1

    docs = _extracted_text_files(project)
    triggering_doc: Path | None = None
    triggering_lines: list[int] = []
    for d in docs:
        try:
            text = d.read_text(errors="replace")
        except Exception:
            continue
        has_signals, lines = _crc_signals(text)
        if has_signals:
            triggering_doc = d
            triggering_lines = lines
            break

    if triggering_doc is None:
        print("PASS — no extracted text doc declares CRC parameters "
              "(gate skipped)")
        return 0

    l3_path, l3 = _load_l3(project)
    if l3_path is None or l3 is None:
        if _waived(project):
            print(f"PASS_WITH_WAIVER — CRC params §-style block in "
                  f"{triggering_doc.name} (lines "
                  f"{triggering_lines[:6]}{'...' if len(triggering_lines) > 6 else ''}) "
                  f"but no L3_CMD_PROTOCOL.json — waived")
            return 0
        print(f"FAIL — CRC parameter declaration found in "
              f"{triggering_doc.name} (evidence lines: "
              f"{triggering_lines[:6]}{'...' if len(triggering_lines) > 6 else ''}) "
              f"but L3_CMD_PROTOCOL.json is missing.")
        print("Fix: cmd-protocol-gen must emit L3 with `crc_parameters` "
              "or `crc` block citing the vendor doc.")
        return 1

    ok, missing, block = _has_required_crc_params(l3)
    if not ok:
        if _waived(project):
            print(f"PASS_WITH_WAIVER — CRC params §-style block in "
                  f"{triggering_doc.name} but L3 missing "
                  f"{missing} — waived")
            return 0
        print(f"FAIL — CRC parameter declaration found in "
              f"{triggering_doc.name} (evidence lines: "
              f"{triggering_lines[:6]}{'...' if len(triggering_lines) > 6 else ''}) "
              f"but L3 ({l3_path.name}) is missing required sub-keys: "
              f"{missing}.")
        print("Fix: cmd-protocol-gen MUST emit `crc_parameters` (or "
              "`crc`) with polynomial_hex, init_hex, bit_order plus a "
              "`vendor_evidence_path` citation back to the doc + line "
              "range. See plugin SKILL.md for the canonical schema.")
        return 1

    # Has the block — check for BRUTE_FORCED without evidence.
    keys_lc = {k.lower(): k for k in block.keys()}
    src = ""
    if "source" in keys_lc:
        v = block[keys_lc["source"]]
        if isinstance(v, str):
            src = v.strip().upper()

    if src == "BRUTE_FORCED_FROM_VECTORS" and not _evidence_path_present(block):
        if _waived(project):
            print(f"PASS_WITH_WAIVER — CRC params marked "
                  f"BRUTE_FORCED_FROM_VECTORS without vendor_evidence_path "
                  f"despite {triggering_doc.name} having the §-block — "
                  f"waived")
            return 0
        print(f"FAIL — L3 declares CRC `source: "
              f"BRUTE_FORCED_FROM_VECTORS` but {triggering_doc.name} "
              f"contains a parameter declaration (evidence lines: "
              f"{triggering_lines[:6]}{'...' if len(triggering_lines) > 6 else ''}). "
              f"`vendor_evidence_path` is required when the doc has the §-block.")
        print("Fix: re-extract from the vendor doc and set "
              "`source: VENDOR_DOC_EXTRACTED` + "
              "`vendor_evidence_path: \"<doc> §<n> lines A-B\"`.")
        return 1

    print(f"PASS — CRC parameter block in L3 ({l3_path.name}) "
          f"covers polynomial/init/bit_order extracted from "
          f"{triggering_doc.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
