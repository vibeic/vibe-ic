#!/usr/bin/env python3
"""
fpga_program_chain_attest_check.py — Audit the FPGA compile→program→test chain.

THE PROBLEM
-----------
A fresh agent runs `device_tester_md905_connect_test`, sees PASS, and
declares the design works on hardware. But that PASS may be from a
PREVIOUSLY-burned SOF still on the FPGA from a different session — the
agent never actually programmed its own bitstream.

This program enforces the chain integrity required for a legitimate
hardware-attestation PASS:

    1. There must be at least one `eda_fpga_compile` PASS in the
       manifest, with a recorded `compiled_artifact_sha256`.
    2. There must be at least one `eda_fpga_program` PASS *with the
       same `session_id`* and a `programmed_artifact_sha256` that
       matches the compile hash.
    3. Any `device_tester_md905_connect_test` PASS that the agent
       cites as evidence must come *after* the matching program step
       in the manifest, in the same session.

If any link is broken, this gate FAILs.

INPUT
-----
A `latest_results.jsonl` manifest (default: `<project>/latest_results.jsonl`)
containing entries from mcp-eda's `writeManifest()`. Each entry has at
minimum: timestamp, step, status, session_id (v0.99+), and step-specific
hash fields.

USAGE
-----
    python3 fpga_program_chain_attest_check.py <project_dir>
    python3 fpga_program_chain_attest_check.py <project_dir> --json out.json
    python3 fpga_program_chain_attest_check.py --manifest path/to/latest_results.jsonl

EXIT CODES
----------
    0 — chain is intact: compile + program + (optional) connect_test
        all reference the same session and matching artefact hash.
    1 — chain broken (missing step, hash mismatch, session mismatch,
        or connect_test PASS predates the program step).
    2 — IO / manifest error.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Finding:
    severity: str  # "ERROR" | "WARN" | "INFO"
    rule: str
    message: str


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        # Accept both Z and +00:00 forms
        ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _read_manifest(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # skip malformed lines
    return out


def audit(manifest_entries: List[Dict[str, Any]]) -> List[Finding]:
    findings: List[Finding] = []

    compiles = [e for e in manifest_entries
                if e.get("step") == "fpga_compile" and e.get("status") == "PASS"]
    programs = [e for e in manifest_entries
                if e.get("step") == "fpga_program" and e.get("status") == "PASS"]
    connects = [e for e in manifest_entries
                if e.get("step", "").startswith("device_tester_md905_connect_test")
                and e.get("status") == "PASS"]

    if not compiles:
        findings.append(Finding(
            "ERROR", "missing_compile_pass",
            "No `fpga_compile` PASS entry in the manifest. Hardware-attestation "
            "claims require this session to have actually compiled a bitstream.",
        ))
        return findings

    if not programs:
        findings.append(Finding(
            "ERROR", "missing_program_pass",
            "Compile PASS exists but no `fpga_program` PASS — the bitstream was "
            "never burned to a board this session. Any rig PASS observed is from "
            "a prior session and must NOT be cited as evidence.",
        ))
        return findings

    last_compile = compiles[-1]
    last_program = programs[-1]

    # Rule 1: same session
    cs = last_compile.get("session_id")
    ps = last_program.get("session_id")
    if cs and ps and cs != ps:
        findings.append(Finding(
            "ERROR", "session_mismatch",
            f"fpga_compile session_id={cs!r} but fpga_program session_id={ps!r}. "
            f"The programmer ran a SOF produced by a different mcp-eda session.",
        ))

    # Rule 2: hash matches
    ch = last_compile.get("compiled_artifact_sha256")
    ph = last_program.get("programmed_artifact_sha256")
    if not ch:
        findings.append(Finding(
            "ERROR", "compile_hash_missing",
            "fpga_compile manifest entry has no compiled_artifact_sha256. "
            "Update mcp-eda to v0.99 (the eda_fpga_compile tool now "
            "records the SHA-256 of the produced SOF/BIT).",
        ))
    if not ph:
        findings.append(Finding(
            "ERROR", "program_hash_missing",
            "fpga_program manifest entry has no programmed_artifact_sha256. "
            "Update mcp-eda to v0.99.",
        ))
    if ch and ph and ch != ph:
        findings.append(Finding(
            "ERROR", "artifact_hash_mismatch",
            f"compile artefact hash {ch!r} does not match programmed hash {ph!r}. "
            f"The bitstream actually burned to the board is NOT the one this "
            f"session compiled. Recompile + reprogram before claiming PASS.",
        ))
    if ch and ph and ch == ph and cs == ps:
        findings.append(Finding(
            "INFO", "compile_program_chain_ok",
            f"compile→program chain intact (session_id={cs}, "
            f"sha256={ch[:32]}...).",
        ))

    # Rule 3: any connect_test PASS must come AFTER the matching program
    # in the SAME session.
    if connects:
        prog_ts = _parse_iso(last_program.get("timestamp", ""))
        for ct in connects:
            cts = ct.get("session_id")
            ct_ts = _parse_iso(ct.get("timestamp", ""))
            if cts and ps and cts != ps:
                findings.append(Finding(
                    "ERROR", "connect_test_session_mismatch",
                    f"connect_test PASS at {ct.get('timestamp')} has "
                    f"session_id={cts!r} but the matching fpga_program "
                    f"session_id={ps!r}. The rig PASS predates this run.",
                ))
            elif prog_ts and ct_ts and ct_ts < prog_ts:
                findings.append(Finding(
                    "ERROR", "connect_test_before_program",
                    f"connect_test PASS at {ct.get('timestamp')} occurred "
                    f"BEFORE fpga_program at {last_program.get('timestamp')}. "
                    f"The rig was already PASSing on a previously-burned SOF.",
                ))

    return findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    ap.add_argument("project_dir", nargs="?",
                    help="Project directory containing latest_results.jsonl.")
    ap.add_argument("--manifest", default=None,
                    help="Explicit path to manifest (overrides --project_dir).")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH',
                    help="Emit JSON. With PATH writes to file; bare flag prints to stdout.")
    args = ap.parse_args(argv)

    if args.manifest:
        manifest_path = Path(args.manifest)
    elif args.project_dir:
        manifest_path = Path(args.project_dir) / "latest_results.jsonl"
    else:
        # Default location is /tmp where mcp-eda writes by default
        manifest_path = Path("/tmp/latest_results.jsonl")

    if not manifest_path.exists():
        print(f"error: manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    try:
        entries = _read_manifest(manifest_path)
    except OSError as e:
        print(f"error: cannot read {manifest_path}: {e}", file=sys.stderr)
        return 2

    findings = audit(entries)
    errors = [f for f in findings if f.severity == "ERROR"]

    report = {
        "manifest": str(manifest_path),
        "total_entries": len(entries),
        "findings": [asdict(f) for f in findings],
        "errors": len(errors),
        "verdict": "PASS" if not errors else "FAIL",
    }

    if args.json:
        _txt = json.dumps(report, indent=2)
        if args.json == '-':
            print(_txt)
        else:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(_txt + "\n")
    else:
        for f in findings:
            print(f"[{f.severity}] {f.rule}: {f.message}")
        print(f"\n{len(errors)} error(s); verdict: {report['verdict']}")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
