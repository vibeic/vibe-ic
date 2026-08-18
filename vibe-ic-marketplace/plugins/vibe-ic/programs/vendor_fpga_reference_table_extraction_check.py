#!/usr/bin/env python3
"""
vendor_fpga_reference_table_extraction_check.py — gate (LL-29) that
catches Category-A spec-extraction failures on vendor FPGA reference
timing tables.

Why this gate exists
====================
Surfaced by the v0.119.30 <benchmark> vendor benchmark (MIN_DIFF_ANALYSIS.md).
Vendor doc `input/docs/20230103-3.txt` lines 2-6 give an explicit FPGA
reference timing table:

    H1_MIN[1]    H1_MAX[192]
    H0_MIN[196]  H0_MAX[612]
    BR_MIN[637]  BR_MAX[1314]
    IBT_MIN[234] IBT_MAX[2000]
    WKP_MIN[738]

These are the exact RX-classifier tick thresholds the silicon-PASS
reference FPGA uses. Fresh agent ignored this table and re-derived
weaker thresholds from the spec range in `量測時序.pptx`. RTL compiled,
BFM passed, <half-duplex-tester> silently FAILed byte[6]=0x02.

The systemic fix: when input/docs contains an FPGA reference timing
table (filename or content match), L8_RTL_CONSTANTS.json MUST emit
those tick values verbatim under a `rx_classifier_ticks` (or equivalent)
key. The agent must not paraphrase or re-derive.

Rule
----
Trigger condition (silent-skip when none of these hit):
  • Any file under input/docs/ with name containing 'FPGA' (case-insens.)
    AND content matching the FPGA-table regex, OR
  • Any file under input/docs/ whose content contains BOTH
    `H[01]_(MIN|MAX)\\s*\\[\\s*\\d+\\s*\\]` and
    `BR_(MIN|MAX)\\s*\\[\\s*\\d+\\s*\\]`.

When triggered:
  1. Extract every `<KEY>_<MIN|MAX>\\[<NN>\\]` match from the input doc.
     Build a dict {h1_min:1, h1_max:192, ...}.
  2. Read L8_RTL_CONSTANTS.json (or L8_TIMING_WAVEFORM.json fallback).
     Look for a key `rx_classifier_ticks` (canonical) OR any of the
     same KEY names directly as top-level / nested fields.
  3. For every doc-table key present in L8, compare values. If any
     differs by >10% (relative), FAIL with the offending field.
  4. If L8 has no rx_classifier_ticks AND no individual KEY hits, FAIL
     ('vendor FPGA table present in docs but not extracted into L8').

Honors waivers.json key `vendor_fpga_table_alternative` (≥20 chars):
  use case is a vendor table superseded by a newer measurement run.

Usage
-----
python3 vendor_fpga_reference_table_extraction_check.py <project_dir>

Returns 0 on PASS / silent-skip / waived, 1 on FAIL, 2 on input error.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl

# Detect a "vendor FPGA reference timing table". Chip-agnostic: any
# pattern KEY_(MIN|MAX)[NN] occurrence is fair game. We need both
# H[01]_xxx (bit-detect thresholds) and BR_xxx (break/reset threshold)
# to count it as a reference table.
H_PAT = re.compile(r"\bH[01]_(MIN|MAX)\s*\[\s*(\d+)\s*\]", re.IGNORECASE)
BR_PAT = re.compile(r"\bBR_(MIN|MAX)\s*\[\s*(\d+)\s*\]", re.IGNORECASE)
# Generic KEY[NN] / KEY_MIN[NN] extractor. KEY = letters/digits/_.
GENERIC_PAT = re.compile(
    r"\b([A-Za-z][A-Za-z0-9]{0,15})_(MIN|MAX)\s*\[\s*(\d+)\s*\]",
    re.IGNORECASE,
)
# Single-bound (no MIN/MAX, e.g. WKP_MIN[738]).  Already covered above.
# Standalone bracketed (e.g. WKP[738]) — also accept.
SINGLE_PAT = re.compile(
    r"\b([A-Za-z][A-Za-z0-9]{0,15})\s*\[\s*(\d+)\s*\]\b",
)


def find_input_docs(project: Path) -> list[Path]:
    """Return readable text-ish files under input/docs/."""
    base = project / "input" / "docs"
    if not base.is_dir():
        return []
    out: list[Path] = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() in {
            ".txt", ".md", ".csv", ".json", ".yaml", ".yml",
            ".tsv", ".log", ""
        }:
            out.append(p)
    return out


def read_text_safe(p: Path) -> str:
    try:
        return p.read_text(errors="replace")
    except Exception:
        return ""


def doc_has_table(text: str, name_hint_fpga: bool) -> bool:
    """A vendor FPGA reference table is recognised when EITHER the
    filename hints 'FPGA' AND H_PAT hits at least once, OR both H_PAT
    and BR_PAT hit somewhere in the file."""
    h_hit = H_PAT.search(text) is not None
    br_hit = BR_PAT.search(text) is not None
    if name_hint_fpga and h_hit:
        return True
    return h_hit and br_hit


def _extract_table_from_segment(segment: str) -> dict[str, int]:
    """Extract KEY_MIN[NN] style entries from a single text segment."""
    out: dict[str, int] = {}
    for m in GENERIC_PAT.finditer(segment):
        key = f"{m.group(1).lower()}_{m.group(2).lower()}"
        try:
            out[key] = int(m.group(3))
        except ValueError:
            pass
    for m in SINGLE_PAT.finditer(segment):
        key = m.group(1).lower()
        if any(k.startswith(key + "_") for k in out):
            continue
        if len(key) < 3:
            continue
        if key in {"byte", "bit", "lines", "table", "ticks", "row"}:
            continue
        try:
            out[key] = int(m.group(2))
        except ValueError:
            pass
    return out


def _split_into_blocks(text: str) -> list[tuple[str, str]]:
    """Split text into labeled blocks based on heading patterns.

    Heuristic: headings of the form `FPGA - <name>`, `=== ORG ===`,
    `=== <NAME> ===`, or `## <NAME>` start a new block; bare separators
    like `----` or `====` (≥3 chars, no letters) also begin a new
    unlabeled block. Returns a list of (label, body) pairs. The label
    is the bare uppercase token from the heading (e.g. `FPGA`, `ORG`);
    falls back to `""` for unlabeled blocks.
    """
    HEADING_RE = re.compile(
        r"^\s*(?:#+\s*|=+\s*)?"
        r"(?:(FPGA)\b[^\n]*|=+\s*([A-Z]{2,16})\s*=+|"
        r"\b([A-Z]{2,16})\s*[:\-—–]\s*[^\n]{0,40})"
        r"\s*$",
        re.MULTILINE,
    )
    SEPARATOR_RE = re.compile(
        r"^\s*[-=_*]{3,}\s*$",
        re.MULTILINE,
    )
    # Combine: a heading or separator opens a new block.
    COMBINED_RE = re.compile(
        rf"({HEADING_RE.pattern})|({SEPARATOR_RE.pattern})",
        re.MULTILINE,
    )
    blocks: list[tuple[str, str]] = []
    cursor = 0
    label = ""
    for m in COMBINED_RE.finditer(text):
        body = text[cursor:m.start()]
        if body.strip():
            blocks.append((label, body))
        # Heading-named or separator-only?
        groups = m.groups()
        # Group order: (full_heading, FPGA, ALLCAPS, ALLCAPS_label, full_separator)
        new_label = (groups[1] or groups[2] or groups[3] or "")
        label = new_label.upper()
        cursor = m.end()
    blocks.append((label, text[cursor:]))
    return blocks


def extract_table(text: str) -> dict[str, int]:
    """Extract the FPGA-style reference table.

    LL-29 fix (BACKLOG-v13 P1.1): when text contains multiple
    `H1_MIN[]`-style blocks (e.g. FPGA + ORG sections), prefer the
    block whose preceding heading mentions FPGA. If no FPGA heading
    is found, prefer the FIRST block (silicon-PASS reference is
    usually first). If ≥2 disagreeing blocks exist, this function
    still returns the chosen block but `extract_table_with_diag`
    can be used to surface the disagreement.
    """
    table, _diag = extract_table_with_diag(text)
    return table


def extract_table_with_diag(
    text: str,
) -> tuple[dict[str, int], dict]:
    """Heading-aware extractor + diagnostic info."""
    blocks = _split_into_blocks(text)
    parsed: list[tuple[str, dict[str, int]]] = []
    for label, body in blocks:
        d = _extract_table_from_segment(body)
        if d:
            parsed.append((label, d))

    diag: dict = {"n_blocks": len(parsed), "labels": [p[0] for p in parsed]}
    if not parsed:
        return {}, diag

    # Prefer FPGA-labelled block.
    for label, d in parsed:
        if label and "FPGA" in label.upper():
            diag["chosen"] = label or "<first>"
            diag["reason"] = "fpga_heading"
            # Detect disagreement vs other blocks
            others = [d2 for lbl, d2 in parsed if d2 is not d]
            if others and any(
                d.get(k) != d2.get(k)
                for d2 in others
                for k in set(d) & set(d2)
            ):
                diag["disagreement"] = True
            return d, diag

    # Otherwise prefer the FIRST block.
    first_label, first = parsed[0]
    diag["chosen"] = first_label or "<first>"
    diag["reason"] = "first_block"
    if len(parsed) >= 2:
        for _, d2 in parsed[1:]:
            if any(first.get(k) != d2.get(k)
                   for k in set(first) & set(d2)):
                diag["disagreement"] = True
                break
    return first, diag


def find_l8_doc(project: Path) -> Path | None:
    for stem in ("L8_RTL_CONSTANTS.json", "L8_TIMING_WAVEFORM.json"):
        for base in (_pl.generated_docs_dir(project), project / "docs", project):
            p = base / stem
            if p.is_file():
                return p
    return None


def collect_keys_from_l8(node, found: dict[str, int]) -> None:
    """Walk JSON tree and collect any leaf int with a key name matching
    `<X>_<min|max>` or top-level `rx_classifier_ticks` map."""
    if isinstance(node, dict):
        for k, v in node.items():
            kl = k.lower()
            if kl == "rx_classifier_ticks" and isinstance(v, dict):
                for ck, cv in v.items():
                    if isinstance(cv, (int, float)):
                        found[ck.lower()] = int(cv)
                continue
            if isinstance(v, (int, float)) and re.match(
                r"^[A-Za-z][A-Za-z0-9]{0,15}(_min|_max)?$", kl
            ):
                found[kl] = int(v)
            elif isinstance(v, dict):
                # Also accept {"name":"H1_MIN","value":1} forms
                if "name" in v and "value" in v and isinstance(
                    v["value"], (int, float)
                ):
                    found[str(v["name"]).lower()] = int(v["value"])
                collect_keys_from_l8(v, found)
            elif isinstance(v, list):
                for item in v:
                    collect_keys_from_l8(item, found)
    elif isinstance(node, list):
        for item in node:
            collect_keys_from_l8(item, found)


def waived(project: Path) -> bool:
    p = project / "waivers.json"
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text())
        v = d.get("vendor_fpga_table_alternative", "")
        return isinstance(v, str) and len(v.strip()) >= 20
    except Exception:
        return False


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: vendor_fpga_reference_table_extraction_check.py "
              "<project_dir>")
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 1

    docs = find_input_docs(project)
    table_doc: Path | None = None
    table: dict[str, int] = {}
    diag: dict = {}
    for d in docs:
        text = read_text_safe(d)
        if not text:
            continue
        if doc_has_table(text, "fpga" in d.name.lower()):
            cand, cand_diag = extract_table_with_diag(text)
            if cand:
                table_doc = d
                table = cand
                diag = cand_diag
                break

    if diag.get("disagreement"):
        print(f"WARN — {table_doc.name if table_doc else '?'} contains "
              f"≥2 KEY_MIN/MAX[NN] blocks with disagreeing values "
              f"(labels: {diag.get('labels')}). LL-29 chose "
              f"'{diag.get('chosen')}' via {diag.get('reason')}. "
              "Verify this is the silicon-PASS reference table.")

    if not table_doc:
        print("PASS — no vendor FPGA reference timing table detected in "
              "input/docs/ (gate skipped)")
        return 0

    l8 = find_l8_doc(project)
    if not l8:
        if waived(project):
            print(f"PASS_WITH_WAIVER — vendor table found in "
                  f"{table_doc.name} but no L8 doc yet (waived)")
            return 0
        print(f"FAIL — vendor FPGA reference timing table present in "
              f"{table_doc.name} but L8_RTL_CONSTANTS.json / "
              f"L8_TIMING_WAVEFORM.json is missing.")
        print(f"  Doc table: {table}")
        print("  Fix: rtl-constants-gen / timing-waveform-gen must emit "
              "these ticks under `rx_classifier_ticks`.")
        return 1

    try:
        l8_data = json.loads(l8.read_text())
    except Exception as e:
        print(f"FAIL — cannot parse {l8.name}: {e}")
        return 1

    l8_keys: dict[str, int] = {}
    collect_keys_from_l8(l8_data, l8_keys)

    # Find overlap.
    overlap = sorted(set(table.keys()) & set(l8_keys.keys()))
    missing = [k for k in table.keys() if k not in l8_keys]
    mismatched: list[tuple[str, int, int]] = []
    for k in overlap:
        doc_v = table[k]
        l8_v = l8_keys[k]
        # Tolerance >10% relative (or >1 absolute when doc value is small)
        if doc_v == 0:
            continue
        if abs(doc_v - l8_v) / max(abs(doc_v), 1) > 0.10:
            mismatched.append((k, doc_v, l8_v))

    if not overlap and missing:
        if waived(project):
            print(f"PASS_WITH_WAIVER — vendor table {table_doc.name} not "
                  f"propagated into {l8.name} (waived)")
            return 0
        print(f"FAIL — vendor FPGA reference timing table in "
              f"{table_doc.name} but L8 has none of those keys.")
        print(f"  Doc table keys: {sorted(table.keys())}")
        print("  L8 must emit `rx_classifier_ticks: {h1_min, h1_max, "
              "h0_min, h0_max, br_min, br_max, ibt_min, ibt_max, "
              "wkp_min}` (or equivalent).")
        return 1

    if mismatched:
        if waived(project):
            print(f"PASS_WITH_WAIVER — {len(mismatched)} value mismatch(es) "
                  f"between vendor table and L8 (waived)")
            return 0
        print(f"FAIL — {len(mismatched)} L8 classifier tick(s) disagree "
              f"with vendor FPGA reference table from {table_doc.name} "
              f"by >10%:")
        for k, dv, lv in mismatched:
            ratio = (lv - dv) / dv if dv else 0
            print(f"  • {k}: doc={dv}  L8={lv}  delta={ratio:+.1%}")
        print()
        print("Fix: copy the vendor table values verbatim into L8")
        print("     `rx_classifier_ticks` (or equivalent) section.")
        print("     Re-derivation from a different timing source is the")
        print("     known root cause of <half-duplex-tester> byte[6]=0x02 silent FAILs.")
        return 1

    print(f"PASS — vendor FPGA reference timing table from "
          f"{table_doc.name} matches L8 ({len(overlap)} key(s) verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
