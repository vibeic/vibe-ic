#!/usr/bin/env python3
"""hardware_pass_attestation_check.py — v0.50 plugin gate (third layer)

Refuses to mark a project "production-ready" unless real-hardware tester
PASS evidence is attached. Complements structural + sim-conformance gates
with the only authoritative sign-off: actual tester bytes.

Motivation: the 2026-04-24 <benchmark> regen experiment showed a fresh-agent
build can achieve:
  - 19/19 vendor docs traced to RTL (input_docs_coverage_check PASS)
  - 10/10 L*.json + 3/3 L10-L12 extension layers (phase1 + layer_extension
    presence PASS)
  - fill-to-floor parity PASS
  - iverilog sim 8/8 CMD→RSP byte-for-byte (cmd_response_conformance PASS)
  - tapeout_signoff 4/4 + flow_compliance 28/28
and still FAIL a real <half-duplex-tester> hardware test (tester returns only `02 02 02`
padding; no device bytes). Only the human-engineer v037v2 build returns
the golden signature `F2 ... BE AB BA D1 CD D0 D1 D2 AF CD CD D1 B5 AC D2
C1 B8 ... FA`. The delta between spec-matching and tester-passing lies in
lab-measured tuning that vendor docs don't capture.

This gate enforces that you cannot declare "production-ready" until you
have real-hardware evidence. If no tester PASS exists yet, the plugin is
honest about it being a simulation / tapeout certification rather than a
proven-silicon certification.

Usage:
    python3 hardware_pass_attestation_check.py <project_dir>
        [--l13 <path>]                  (default: <proj>/generated_docs/L13_LAB_CALIBRATION.json)
        [--require-tester-bytes]        (default on)
        [--json <out>]

Exit codes:
    0 — L13 contains at least one known_pass_bitstream+transcript with
        non-padding device-payload bytes
    1 — no real-hardware PASS evidence OR evidence looks like padding/fake
    2 — input error
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
import _path_layout as _pl


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _is_padding_only(hex_str: str, padding_byte: str = "02",
                     min_distinct_non_padding: int = 4) -> bool:
    """Return True if the byte stream is empty / too short / consists
    overwhelmingly of one padding byte (default 0x02 for the original
    cable-side-id-ic benchmark)."""
    if not hex_str:
        return True
    bytes_ = re.findall(r"[0-9A-Fa-f]{2}", hex_str)
    if len(bytes_) < min_distinct_non_padding:
        return True
    pad = padding_byte.upper().lstrip("0X")
    pad = pad.zfill(2)
    non_pad = [b for b in bytes_ if b.upper() not in (pad, "00")]
    return len(non_pad) < min_distinct_non_padding


# v0.56: criterion registry — different IC classes need different
# real-hardware-PASS criteria. <chip-class>-style cable-plug ID ICs use
# `distinct_non_padding_bytes`; ADCs use `monotonic_adc_sweep`; memory
# ICs use `memory_readback_match`; etc. The L13_LAB_CALIBRATION.json
# `known_pass_transcript.criterion` field selects which validator runs.
# Default (when unspecified) is `distinct_non_padding_bytes` to preserve
# backwards compatibility with v0.50-v0.55 L13 docs.

def _crit_distinct_non_padding_bytes(tx: dict, params: dict) -> tuple[bool, str]:
    rx = tx.get("hid_tool_rx_bytes") or tx.get("rx_bytes") or tx.get("raw_bytes") or ""
    if not isinstance(rx, str):
        return False, "hid_tool_rx_bytes / rx_bytes / raw_bytes missing or wrong type"
    pad = params.get("padding_byte", "02")
    min_d = int(params.get("min_distinct_non_padding", 4))
    if _is_padding_only(rx, padding_byte=pad, min_distinct_non_padding=min_d):
        return False, (f"transcript is padding-only: `{rx[:60]}...` — "
                       "this is the FAIL mode, not PASS")
    return True, "ok"


def _crit_monotonic_adc_sweep(tx: dict, params: dict) -> tuple[bool, str]:
    """For ADCs: list of (input_v, output_code) samples must be
    monotonic non-decreasing. params: `min_samples` (default 5)."""
    samples = tx.get("samples_v_in_code_out") or tx.get("samples") or []
    if not isinstance(samples, list):
        return False, "samples_v_in_code_out missing or wrong type"
    min_n = int(params.get("min_samples", 5))
    if len(samples) < min_n:
        return False, (f"need >= {min_n} samples to assert monotonicity, "
                       f"got {len(samples)}")
    try:
        codes = [float(s[1]) for s in samples]
    except (IndexError, TypeError, ValueError) as e:
        return False, f"sample shape must be [[v_in, code], …]: {e}"
    for i in range(1, len(codes)):
        if codes[i] < codes[i - 1]:
            return False, (f"non-monotonic at sample {i}: "
                           f"code {codes[i-1]:g} → {codes[i]:g}")
    if codes[-1] == codes[0]:
        return False, ("ADC samples are flat — every code identical. "
                       "A real ADC sweep must show non-zero range.")
    return True, "ok"


def _crit_memory_readback_match(tx: dict, params: dict) -> tuple[bool, str]:
    """For memory ICs (EEPROM/RAM/Flash): readback must match the
    write data. params: optional `min_pages` (default 1)."""
    pairs = tx.get("write_readback_pairs") or []
    min_n = int(params.get("min_pages", 1))
    if not isinstance(pairs, list) or len(pairs) < min_n:
        return False, (f"need >= {min_n} write/readback pair(s), "
                       f"got {len(pairs) if isinstance(pairs, list) else 'invalid'}")
    for i, p in enumerate(pairs):
        try:
            w = re.findall(r"[0-9A-Fa-f]{2}", str(p.get("written", "")))
            r = re.findall(r"[0-9A-Fa-f]{2}", str(p.get("readback", "")))
        except AttributeError:
            return False, f"pair {i} must be {{written, readback}} dict"
        if not w or not r:
            return False, f"pair {i} has empty written or readback"
        if [b.upper() for b in w] != [b.upper() for b in r]:
            return False, (f"pair {i} write/readback mismatch: "
                           f"wrote {' '.join(w[:8])}…, "
                           f"read {' '.join(r[:8])}…")
    return True, "ok"


def _crit_register_write_read_roundtrip(tx: dict, params: dict) -> tuple[bool, str]:
    """For register-bus ICs: write a value, read it back. params:
    optional `min_registers` (default 1)."""
    pairs = tx.get("register_roundtrip") or tx.get("write_readback_pairs") or []
    min_n = int(params.get("min_registers", 1))
    if not isinstance(pairs, list) or len(pairs) < min_n:
        return False, (f"need >= {min_n} register write/read pair(s), "
                       f"got {len(pairs) if isinstance(pairs, list) else 'invalid'}")
    for i, p in enumerate(pairs):
        if not isinstance(p, dict):
            return False, f"pair {i} must be a dict"
        addr = p.get("addr")
        wv = p.get("written")
        rv = p.get("readback")
        if addr is None or wv is None or rv is None:
            return False, f"pair {i} needs {{addr, written, readback}}"
        if str(wv).lower().lstrip("0x") != str(rv).lower().lstrip("0x"):
            return False, (f"pair {i} addr={addr}: wrote {wv}, "
                           f"read {rv} — mismatch")
    return True, "ok"


def _crit_comparator_alert_on_threshold(tx: dict, params: dict) -> tuple[bool, str]:
    """For comparators: ALERT pin must assert when input crosses the
    configured threshold. params: optional `min_events` (default 2)."""
    events = tx.get("threshold_events") or []
    min_n = int(params.get("min_events", 2))
    if not isinstance(events, list) or len(events) < min_n:
        return False, (f"need >= {min_n} threshold-cross events, "
                       f"got {len(events) if isinstance(events, list) else 'invalid'}")
    asserted = [e for e in events if e.get("alert_state") in (1, "1", True, "high")]
    deasserted = [e for e in events if e.get("alert_state") in (0, "0", False, "low")]
    if not asserted:
        return False, "no events show ALERT asserted"
    if not deasserted:
        return False, "no events show ALERT deasserted (alert never released)"
    return True, "ok"


_CRITERIA = {
    "distinct_non_padding_bytes":      _crit_distinct_non_padding_bytes,
    "monotonic_adc_sweep":              _crit_monotonic_adc_sweep,
    "memory_readback_match":            _crit_memory_readback_match,
    "register_write_read_roundtrip":    _crit_register_write_read_roundtrip,
    "comparator_alert_on_threshold":    _crit_comparator_alert_on_threshold,
}


def _known_pass_transcript_ok(tx: dict | None) -> tuple[bool, str]:
    if not tx:
        return False, "no known_pass_transcript block"
    crit_name = tx.get("criterion", "distinct_non_padding_bytes")
    fn = _CRITERIA.get(crit_name)
    if fn is None:
        return False, (f"unknown criterion `{crit_name}`. Valid values: "
                       f"{sorted(_CRITERIA.keys())}")
    params = tx.get("criterion_params", {}) or {}
    return fn(tx, params)


def check(project_dir: Path, l13_path: Path) -> dict:
    l13 = _load_json(l13_path)
    findings = []
    if not l13:
        findings.append({
            "severity": "FAIL",
            "rule": "l13_exists",
            "message": f"L13_LAB_CALIBRATION.json not found at {l13_path}",
        })
        return {"pass": False, "findings": findings}

    kb = l13.get("known_pass_bitstream") or {}
    tx = l13.get("known_pass_transcript") or {}
    tester = l13.get("tester")

    if not kb:
        findings.append({
            "severity": "FAIL",
            "rule": "known_pass_bitstream",
            "message": "L13 missing known_pass_bitstream block",
        })
    else:
        if not kb.get("sof_path") and not kb.get("sha256") and not kb.get("gds_path"):
            findings.append({
                "severity": "FAIL",
                "rule": "known_pass_bitstream_identity",
                "message": "known_pass_bitstream must identify the binary (sof_path or sha256 or gds_path)",
            })

    ok, detail = _known_pass_transcript_ok(tx)
    if not ok:
        findings.append({
            "severity": "FAIL",
            "rule": "known_pass_transcript",
            "message": detail,
        })

    if not tester:
        findings.append({
            "severity": "WARN",
            "rule": "tester_identity",
            "message": "L13 missing `tester` field — record which tester produced the transcript",
        })

    pass_ = not any(f["severity"] == "FAIL" for f in findings)
    return {
        "project_dir": str(project_dir),
        "l13_path": str(l13_path),
        "tester": tester,
        "findings": findings,
        "pass": pass_,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir")
    ap.add_argument("--l13", default=None)
    ap.add_argument("--require-tester-bytes", action="store_true")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    proj = Path(args.project_dir)
    if not proj.exists():
        print(f"ERROR: project_dir {proj} not found", file=sys.stderr)
        return 2

    if args.l13:
        l13_path = Path(args.l13)
    else:
        legacy = proj / "phase1" / "generated_docs" / "L13_LAB_CALIBRATION.json"
        canonical = _pl.generated_docs_dir(proj) / "L13_LAB_CALIBRATION.json"
        l13_path = legacy if legacy.exists() else canonical

    result = check(proj, l13_path)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
