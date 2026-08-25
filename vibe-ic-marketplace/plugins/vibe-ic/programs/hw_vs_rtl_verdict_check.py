#!/usr/bin/env python3
"""
hw_vs_rtl_verdict_check.py — Require N byte-identical FAILs before blaming hardware.

Source (v052 fresh-agent debugging lesson)
-------------------------------------------
Early in the v0.45 cycle the team concluded "hardware blocked" after two
RTL spins, but the tester response byte differed between spins — proving
the bug was still in the RTL. This gate enforces:

    Before declaring "hardware blocked", produce at least N (default 3)
    RTL variants and confirm the tester returns a byte-identical FAIL
    fingerprint across ALL of them. If responses differ, the bug is in
    RTL — keep iterating.

This program is IC-agnostic. It consumes a directory of per-variant JSON
response files produced by any external test harness.

Input file schema
-----------------
Every ``*.json`` under ``--responses-dir`` must have shape::

    {
      "rtl_id": "variant_a",
      "tester_response_hex": "BE AB BA D1 02 00 00 00",
      "fail": true
    }

``tester_response_hex`` is a whitespace-separated hex byte string.
``--field`` may narrow comparison to a single byte (e.g. ``byte6``
selects the 7th byte, zero-indexed).

Usage
-----
    hw_vs_rtl_verdict_check.py --responses-dir runs/
    hw_vs_rtl_verdict_check.py --responses-dir runs/ --min-variants 4
    hw_vs_rtl_verdict_check.py --responses-dir runs/ --field byte6
    hw_vs_rtl_verdict_check.py --responses-dir runs/ --layout frame_layout.json

``--layout`` is a PROJECT-SUPPLIED ``frame_layout.json`` (the tester is the
user's choice, so the field table is a per-project fact). When given, differing
responses are decoded field-by-field through ``tester_verdict_frame_decode``
and carry diagnosis hints (``frame_offset_shift`` / ``payload_truncated`` /
``crc_mismatch``) instead of being reported as bare byte indices. Absent, the
report is byte-for-byte what it was.

Exit codes
----------
    0 = hardware-blocked confirmed (all variants byte-identical FAIL)
    1 = RTL-blocked, not hardware (variants differ) OR insufficient variants
    2 = config / IO / parse error

ENFORCEMENT: advisory — it judges the REASONING about an on-board failure, not
the failure. Step 39's own `json_field_true` + `fpga_on_board_attestation_check`
clauses already decide whether the board passed; a second blocking verdict there
would refuse a sign-off over a blame campaign's bookkeeping. Wired at step 39 as
`advisory_program_exit_zero`, conditional on the campaign's own records.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class Finding:
    severity: str        # ERROR, WARNING, INFO, PASS
    category: str        # MISSING_DIR, INSUFFICIENT_VARIANTS, INVALID_VARIANT,
                         # DIFFERING_RESPONSES, NOT_ALL_FAIL, HARDWARE_BLOCKED_CONFIRMED
    message: str
    details: str = ""
    extras: dict = field(default_factory=dict)


def _parse_hex_bytes(s: str) -> List[int]:
    tokens = [t for t in re.split(r"\s+", s.strip()) if t]
    out: List[int] = []
    for t in tokens:
        # Accept "BE" or "0xBE"
        t_norm = t[2:] if t.lower().startswith("0x") else t
        if not re.fullmatch(r"[0-9A-Fa-f]{1,2}", t_norm):
            raise ValueError(f"invalid hex byte: {t!r}")
        out.append(int(t_norm, 16))
    return out


def _load_variants(dir_path: Path) -> Tuple[List[dict], List[Finding]]:
    """Load every *.json as a variant record. Returns (variants, findings)."""
    findings: List[Finding] = []
    variants: List[dict] = []

    if not dir_path.exists() or not dir_path.is_dir():
        findings.append(Finding(
            severity="ERROR",
            category="MISSING_DIR",
            message=f"responses directory does not exist: {dir_path}",
        ))
        return variants, findings

    for jf in sorted(dir_path.glob("*.json")):
        try:
            data = json.loads(jf.read_text(errors="replace"))
        except json.JSONDecodeError as e:
            findings.append(Finding(
                severity="ERROR",
                category="INVALID_VARIANT",
                message=f"{jf.name}: invalid JSON ({e})",
            ))
            continue
        if not isinstance(data, dict):
            findings.append(Finding(
                severity="ERROR",
                category="INVALID_VARIANT",
                message=f"{jf.name}: root is not a JSON object",
            ))
            continue
        for needed in ("rtl_id", "tester_response_hex", "fail"):
            if needed not in data:
                findings.append(Finding(
                    severity="ERROR",
                    category="INVALID_VARIANT",
                    message=f"{jf.name}: missing key '{needed}'",
                ))
                break
        else:
            try:
                data["_bytes"] = _parse_hex_bytes(data["tester_response_hex"])
            except ValueError as e:
                findings.append(Finding(
                    severity="ERROR",
                    category="INVALID_VARIANT",
                    message=f"{jf.name}: {e}",
                ))
                continue
            data["_source"] = jf.name
            variants.append(data)
    return variants, findings


def _resolve_field(field_spec: Optional[str]) -> Optional[int]:
    """Return the byte index to compare, or None for 'full'."""
    if field_spec is None or field_spec.lower() == "full":
        return None
    m = re.fullmatch(r"byte(\d+)", field_spec.lower())
    if not m:
        raise ValueError(
            f"--field must be 'full' or 'byte<N>' (got {field_spec!r})"
        )
    return int(m.group(1))


def _compare(variants: List[dict], byte_index: Optional[int]
             ) -> Tuple[bool, List[Tuple[int, List[int]]]]:
    """Compare variants byte-by-byte.

    Returns (identical, differing_bytes) where differing_bytes lists
    ``(byte_index, values_across_variants)`` tuples.
    """
    if byte_index is not None:
        values = []
        for v in variants:
            b = v["_bytes"]
            if byte_index >= len(b):
                values.append(None)
            else:
                values.append(b[byte_index])
        identical = len(set(values)) == 1 and values[0] is not None
        if identical:
            return True, []
        return False, [(byte_index, values)]

    # Full comparison: responses must all have identical length AND bytes
    lengths = {len(v["_bytes"]) for v in variants}
    if len(lengths) != 1:
        # Length mismatch — report as a synthetic differing "byte" of length
        lens = [len(v["_bytes"]) for v in variants]
        return False, [(-1, lens)]
    max_len = lengths.pop()
    differing: List[Tuple[int, List[int]]] = []
    for idx in range(max_len):
        vals = [v["_bytes"][idx] for v in variants]
        if len(set(vals)) > 1:
            differing.append((idx, vals))
    return (len(differing) == 0), differing


# THE "DIFFER HOW?" HALF, AND THE EDGE THAT REACHES IT.
#
# Everything above decides WHETHER the variants' tester frames are byte-
# identical. When they are not, this program's whole message is "the bug is
# still in RTL — keep iterating", and the next thing anybody asks is WHICH FIELD
# moved: a header that shifted, a payload that came back short, a CRC that no
# longer closes are three different bugs and the byte indices alone cannot tell
# them apart. `tester_verdict_frame_decode` was written to answer exactly that —
# per-byte annotation against a PROJECT-SUPPLIED `frame_layout.json`, plus the
# diagnosis hints `frame_offset_shift` / `payload_truncated` / `crc_mismatch` —
# and it was reachable from nothing but its own unit test, so every differing
# fingerprint this gate has ever reported was reported as bare byte indices.
#
# THE LAYOUT IS THE PROJECT'S, NEVER OURS. The tester is the user's choice, so
# the field table is a per-project fact; this file embeds no offset, no field
# name and no expected byte. Absent `--layout`, the report is byte-for-byte what
# it was before.
#
# AND AN ABSENT LAYOUT IS SAID OUT LOUD. A `--layout` naming a file that is not
# there records an INFO finding rather than decoding nothing quietly: "I could
# not look" must not reach a reader as "I looked and there was nothing to say".
# INFO, not ERROR — the decode is a diagnostic on top of the verdict, and a
# missing diagnostic must not manufacture a verdict this gate did not reach.
def _load_layout(layout_path: Optional[str]) -> Tuple[Optional[dict], List[Finding]]:
    """(layout, findings). None layout ⇒ decode is off or could not be read."""
    if not layout_path:
        return None, []
    p = Path(layout_path)
    if not p.is_file():
        return None, [Finding(
            severity="INFO",
            category="FRAME_LAYOUT_ABSENT",
            message=("--layout was given but no frame layout is there, so the "
                     "differing bytes are reported un-decoded"),
            details=str(p),
        )]
    try:
        layout = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, [Finding(
            severity="INFO",
            category="FRAME_LAYOUT_UNREADABLE",
            message="--layout could not be parsed; bytes reported un-decoded",
            details=f"{p}: {e}",
        )]
    if not isinstance(layout, dict) or not layout.get("fields"):
        return None, [Finding(
            severity="INFO",
            category="FRAME_LAYOUT_EMPTY",
            message=("--layout declares no `fields`, so it can decode nothing; "
                     "bytes reported un-decoded"),
            details=str(p),
        )]
    return layout, []


def _decode_variants(variants: List[dict], layout: dict) -> List[dict]:
    """Per-variant field decode + diagnosis hints, via the shared decoder.

    The decoder is IMPORTED, not re-implemented: a second copy of the offset /
    expected-byte / hint rules here would drift from the one the CLI publishes.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import tester_verdict_frame_decode as _tvfd

    out: List[dict] = []
    for v in variants:
        try:
            decoded = _tvfd.decode_frame(list(v["_bytes"]), layout)
        except Exception as e:                      # a malformed layout field
            decoded = {"error": f"{type(e).__name__}: {e}"}
        out.append({"rtl_id": v.get("rtl_id", v.get("_source", "?")),
                    "decode": decoded})
    return out


def render_verdict(variants: List[dict], min_variants: int,
                   byte_index: Optional[int],
                   layout: Optional[dict] = None) -> List[Finding]:
    findings: List[Finding] = []
    if len(variants) < min_variants:
        findings.append(Finding(
            severity="ERROR",
            category="INSUFFICIENT_VARIANTS",
            message=(f"insufficient variants to render verdict: "
                     f"found {len(variants)}, need {min_variants}"),
            details=("Produce at least --min-variants RTL spins and record "
                     "their tester responses before declaring hardware-blocked."),
        ))
        return findings

    all_fail = all(bool(v.get("fail")) for v in variants)
    identical, differing = _compare(variants, byte_index)

    rtl_ids = [v.get("rtl_id", v.get("_source", "?")) for v in variants]

    if identical and all_fail:
        findings.append(Finding(
            severity="PASS",
            category="HARDWARE_BLOCKED_CONFIRMED",
            message=(f"hardware-blocked confirmed: {len(variants)} variants "
                     f"produced same FAIL fingerprint"),
            details=f"variants = {rtl_ids}",
        ))
        return findings

    if identical and not all_fail:
        findings.append(Finding(
            severity="ERROR",
            category="NOT_ALL_FAIL",
            message=("variants are byte-identical but not all marked fail=true "
                     "— verdict undefined"),
            details=f"fail flags = {[bool(v.get('fail')) for v in variants]}",
        ))
        return findings

    # Differing responses
    diff_summary = []
    for idx, vals in differing[:8]:
        if idx == -1:
            diff_summary.append(f"length varies across variants: {vals}")
        else:
            hex_vals = [("0x%02X" % x) if isinstance(x, int) else str(x)
                        for x in vals]
            diff_summary.append(f"byte[{idx}]: {hex_vals}")
    more = "" if len(differing) <= 8 else f" (+{len(differing) - 8} more)"
    extras = {"differing_bytes": [
        {"index": idx, "values": vals} for idx, vals in differing
    ]}
    # The decode rides ON the finding it explains, so a reader who sees
    # "byte[3] differs" sees which FIELD byte 3 is in the same object.
    if layout is not None:
        extras["frame_decode"] = _decode_variants(variants, layout)
    findings.append(Finding(
        severity="ERROR",
        category="DIFFERING_RESPONSES",
        message=("RTL-blocked, not hardware: variants produced different "
                 "responses — keep iterating RTL"),
        details="; ".join(diff_summary) + more,
        extras=extras,
    ))
    return findings


def build_report(findings: List[Finding], responses_dir: str,
                 min_variants: int, field_spec: str,
                 variant_count: int, passed: bool) -> dict:
    return {
        "program": "hw_vs_rtl_verdict_check",
        "version": "1.0.0",
        "responses_dir": responses_dir,
        "summary": {
            "min_variants": min_variants,
            "field": field_spec,
            "variants_found": variant_count,
            "findings_count": len(findings),
            "pass": passed,
        },
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Confirm N RTL variants produce byte-identical FAIL "
                     "responses before declaring hardware-blocked."),
    )
    parser.add_argument("--responses-dir", required=True,
                        help="Directory containing per-variant JSON records")
    parser.add_argument("--min-variants", type=int, default=3,
                        help="Minimum number of variants required (default 3)")
    parser.add_argument("--field", default="full",
                        help=("Which bytes to compare: 'full' (default) or "
                              "'byte<N>' to select a single byte (e.g. byte6)."))
    parser.add_argument("--layout", default=None,
                        help=("Optional project-supplied frame_layout.json. "
                              "When given, differing tester frames are DECODED "
                              "field-by-field (offset / expected / value map) "
                              "with diagnosis hints, instead of being reported "
                              "as bare byte indices."))
    parser.add_argument("--json", default=None,
                        help="Optional path to write JSON report")
    args = parser.parse_args(argv)

    try:
        byte_index = _resolve_field(args.field)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    layout, layout_findings = _load_layout(args.layout)

    dir_path = Path(args.responses_dir)
    variants, load_findings = _load_variants(dir_path)
    findings = list(load_findings) + layout_findings

    has_io_error = any(f.category == "MISSING_DIR" for f in findings)
    has_invalid = any(f.category == "INVALID_VARIANT" for f in findings)

    if not has_io_error:
        verdict_findings = render_verdict(variants, args.min_variants,
                                          byte_index, layout)
        findings.extend(verdict_findings)

    passed = (not has_io_error and not has_invalid
              and any(f.category == "HARDWARE_BLOCKED_CONFIRMED"
                      for f in findings))

    report = build_report(findings, str(dir_path), args.min_variants,
                          args.field, len(variants), passed)
    out_txt = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out_txt)
    print(out_txt)

    if has_io_error:
        return 2
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
