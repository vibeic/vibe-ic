#!/usr/bin/env python3
"""cmd_response_conformance_check.py — v0.50 plugin gate

Close-loop protocol conformance test for command-and-response ICs (AID,
<chip-class>, I2C/SPI peripherals, etc.). Given:
  1. Expected CMD→RSP byte-for-byte vectors (from L3_CMD_PROTOCOL.json,
     crc_vectors.json, or a user-supplied JSON);
  2. A fully-compiled sim binary (iverilog vvp) OR a test harness invocation
     command-line recipe;
verify that the RTL implements every expected CMD→RSP pair exactly.

This fills the failure mode observed with the v0.50-pre HIGH <benchmark> pilot:
all structural + tapeout + parity gates pass (10/10 L*.json, 2872 cells,
0 PnR violations, strict 4/4 tapeout_signoff), yet hardware testing on
<half-duplex-tester> reveals the RTL never emits a valid response byte because the MAC
response-generator silently fabricated resp_base/resp_len/echo_opcode.

Input vectors format (JSON):
    {
      "cases": [
        {"cmd_hex": "74 00 01 FD",
         "expected_rsp_hex": "75 XX XX XX XX XX XX YY",
         "notes": "Get ID wake; XX = OTP[0..5]; YY = CRC-8 MAXIM"},
        ...
      ]
    }

The checker executes the sim via a user-supplied hook command that is
expected to print each captured RSP frame as a hex-byte list (one per CMD).
The hook is invoked with positional argument = path to cmd-vectors JSON,
and its stdout must be a JSON list of rsp strings in the same order.

Usage:
    python3 cmd_response_conformance_check.py <project_dir>
        --vectors <cmd_response_vectors.json>
        [--hook "iverilog -o tb sim/*.v rtl/*.v && vvp -n tb"]
        [--capture-json <path>]
        [--allow-regex]
        [--strict]

Exit codes:
    0 — every CMD → expected RSP byte match
    1 — one or more mismatches
    2 — input/setup error
"""
from __future__ import annotations
import argparse, json, subprocess, sys, re
from pathlib import Path


def load_vectors(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and "cases" in data:
        return data["cases"]
    if isinstance(data, list):
        return data
    raise ValueError(f"vectors must be list or {{'cases': [...]}} in {path}")


def parse_hex_list(s: str) -> list[int]:
    """Parse 'AB CD 12' → [0xAB, 0xCD, 0x12]. XX tokens preserved as -1."""
    out = []
    for tok in s.replace(",", " ").split():
        tok_u = tok.upper().replace("0X", "").lstrip("0X")
        if tok_u in ("XX", "YY", "??", "**") or re.match(r"^[A-F0-9]{1,2}$", tok_u):
            if tok_u.startswith("X") or tok_u.startswith("Y") or tok_u.startswith("?") or tok_u.startswith("*"):
                out.append(-1)
            else:
                out.append(int(tok_u, 16))
        else:
            # fallback: int hex
            try:
                out.append(int(tok, 16))
            except Exception:
                out.append(-1)
    return out


def match_bytes(expected: list[int], actual: list[int]) -> tuple[bool, str]:
    if len(actual) != len(expected):
        return False, f"length: expected {len(expected)}, got {len(actual)}"
    for i, (e, a) in enumerate(zip(expected, actual)):
        if e == -1:
            continue  # wildcard
        if a != e:
            return False, f"byte {i}: expected 0x{e:02X}, got 0x{a:02X}"
    return True, "ok"


def run_hook(hook: str, vectors_path: Path, cwd: Path) -> list[str]:
    """Execute sim hook — must return JSON list of rsp strings on stdout.

    SECURITY: ``hook`` is run through a shell (``shell=True``) by design — it is
    a sim-runner command line (e.g. ``python3 sim.py {VECTORS}``) supplied by
    the project's own test configuration, NOT by end-user / untrusted input.
    Treat it as TRUSTED INPUT ONLY. Never pass a ``hook`` string derived from an
    untrusted spec / fetched repo without sanitising it first — it executes
    arbitrary shell with this process's privileges.
    """
    cmd = hook.replace("{VECTORS}", str(vectors_path))
    r = subprocess.run(cmd, shell=True, cwd=str(cwd),  # nosec B602 — trusted config hook
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"hook exit {r.returncode}: {r.stderr[:500]}")
    # Parse stdout: expect JSON list (first { or [ to end of stdout)
    lines = r.stdout.strip()
    try:
        parsed = json.loads(lines)
    except json.JSONDecodeError:
        # try extracting the last JSON array
        m = re.search(r"\[.*\]", lines, re.DOTALL)
        if not m:
            raise RuntimeError(f"hook stdout not valid JSON: {lines[:500]}")
        parsed = json.loads(m.group(0))
    if not isinstance(parsed, list):
        raise RuntimeError(f"hook stdout must be a JSON list, got {type(parsed)}")
    return parsed


def check(project_dir: Path, vectors: list[dict],
          captured_rsps: list[str]) -> dict:
    findings = []
    passed = 0
    for i, case in enumerate(vectors):
        cmd = case.get("cmd_hex", "")
        exp = parse_hex_list(case.get("expected_rsp_hex", ""))
        got_str = captured_rsps[i] if i < len(captured_rsps) else ""
        got = parse_hex_list(got_str)
        ok, detail = match_bytes(exp, got)
        if ok:
            passed += 1
        else:
            findings.append({
                "severity": "FAIL",
                "rule": "cmd_response_conformance",
                "case_index": i,
                "cmd_hex": cmd,
                "expected_hex": case.get("expected_rsp_hex", ""),
                "got_hex": got_str,
                "message": detail,
            })
    return {
        "cases_total": len(vectors),
        "cases_passed": passed,
        "cases_failed": len(vectors) - passed,
        "findings": findings,
        "pass": len(findings) == 0 and passed == len(vectors),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir")
    ap.add_argument("--vectors", required=True)
    ap.add_argument("--hook", default=None,
                    help="shell command to run sim; must emit JSON list of rsp hex strings to stdout. "
                         "Use {VECTORS} as placeholder for the cmd_vectors.json path. "
                         "If omitted, --capture-json must supply pre-captured responses.")
    ap.add_argument("--capture-json", default=None,
                    help="Pre-captured JSON list of rsp hex strings (alternative to --hook)")
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    proj = Path(args.project_dir)
    vectors = load_vectors(Path(args.vectors))

    if args.capture_json:
        captured = json.loads(Path(args.capture_json).read_text())
    elif args.hook:
        captured = run_hook(args.hook, Path(args.vectors), proj)
    else:
        print("ERROR: must supply --hook or --capture-json", file=sys.stderr)
        return 2

    result = check(proj, vectors, captured)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
