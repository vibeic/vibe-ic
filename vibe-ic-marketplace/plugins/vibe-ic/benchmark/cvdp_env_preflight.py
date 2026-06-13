#!/usr/bin/env python3
"""cvdp_env_preflight.py — verify the CVDP scoring sim image matches the
official Dockerfile.sim tool spec BEFORE any scoring run (ORGANIC #536).

Field evidence: a self-built image carried Yosys 0.62 while the official
Dockerfile.sim pins yosys-0.40. 0.62's `stat` output format (columnar
`891 cells`) differs from the 0.40 format the harness `parse_yosys_log`
expects (`Number of cells: 891`) → every synth-gate problem false-FAILed
via `KeyError: 'Number of cells'` even though the RTL synthesized fully.
Three scoring rounds were polluted and the misdiagnosis burned two
close-loop rounds. The deviation was SILENT because the sim half of the
image (icarus/cocotb) happened to match.

This preflight runs the image and compares each tool's version against the
official spec at the MAJOR/TAG level (patch/build-string tolerance — an
icarus devel build suffix must not false-refuse). Any mismatch → REFUSE
scoring (exit 1, deviations listed).

Official spec (from the upstream cvdp-benchmark Dockerfile.sim, v1.1.0):
    iverilog  v13_0   (Icarus Verilog 13.x)
    yosys     0.40
    cocotb    2.0.1
    verilator v5.038

Exit codes:
    0  image matches the official spec
    1  ≥1 deviation (listed on stderr) — scoring must not proceed
    2  bad input / docker unavailable / image not runnable

chip-AGNOSTIC: pure tool-version comparison; no design knowledge.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

# The official Dockerfile.sim spec — (tool, expected, comparison level).
# Comparison levels: 'major' (first numeric component), 'major.minor',
# 'exact-3' (three components). Build/suffix strings are always ignored.
OFFICIAL_SPEC = {
    "iverilog": ("13", "major"),
    "yosys": ("0.40", "major.minor"),
    "cocotb": ("2.0.1", "exact-3"),
    "verilator": ("5.038", "major.minor"),
}

_PROBE_CMD = (
    "iverilog -V 2>&1 | head -1; "
    "echo '---'; yosys -V 2>&1 | head -1; "
    "echo '---'; verilator --version 2>&1 | head -1; "
    "echo '---'; python3 -c 'import cocotb; print(cocotb.__version__)' 2>&1"
)


def _extract_version(tool: str, line: str) -> Optional[str]:
    """Pull the numeric version out of a tool's banner line."""
    line = line.strip()
    if not line:
        return None
    if tool == "iverilog":
        # 'Icarus Verilog version 13.0 (devel) (s20221226-568-g62b00ee6d)'
        m = re.search(r"version\s+(\d+)[._](\d+)", line, re.I)
        return f"{m.group(1)}.{m.group(2)}" if m else None
    if tool == "yosys":
        # 'Yosys 0.40 (git sha1 ...)' / 'Yosys 0.62+...'
        m = re.search(r"Yosys\s+(\d+)\.(\d+)", line, re.I)
        return f"{m.group(1)}.{m.group(2)}" if m else None
    if tool == "verilator":
        # 'Verilator 5.038 2025-...'
        m = re.search(r"Verilator\s+(\d+)\.(\d+)", line, re.I)
        return f"{m.group(1)}.{m.group(2)}" if m else None
    if tool == "cocotb":
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", line)
        return f"{m.group(1)}.{m.group(2)}.{m.group(3)}" if m else None
    return None


def _matches(found: str, expected: str, level: str) -> bool:
    f = found.split(".")
    e = expected.split(".")
    if level == "major":
        return f[0] == e[0]
    if level == "major.minor":
        return f[0] == e[0] and (len(e) < 2 or (len(f) > 1 and f[1] == e[1]))
    return f[:3] == e[:3]


def probe_image(image: str, runner=None) -> Tuple[int, str]:
    """Run the probe command in the image; returns (rc, combined output).
    `runner` is injectable for tests."""
    if runner is None:
        def runner(cmd):
            cp = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=300)
            return cp.returncode, (cp.stdout or "") + (cp.stderr or "")
    return runner(["docker", "run", "--rm", "--entrypoint", "sh",
                   image, "-c", _PROBE_CMD])


def check_versions(probe_output: str) -> Tuple[List[Dict], List[str]]:
    """Parse the 4-section probe output → ([{tool, found, expected, ok}],
    [deviation strings])."""
    sections = [s.strip() for s in probe_output.split("---")]
    order = ["iverilog", "yosys", "verilator", "cocotb"]
    results: List[Dict] = []
    deviations: List[str] = []
    for i, tool in enumerate(order):
        line = sections[i] if i < len(sections) else ""
        found = _extract_version(tool, line)
        expected, level = OFFICIAL_SPEC[tool]
        if found is None:
            results.append({"tool": tool, "found": None,
                            "expected": expected, "ok": False})
            deviations.append(f"{tool}: version not detectable from "
                              f"{line!r} (expected {expected})")
            continue
        ok = _matches(found, expected, level)
        results.append({"tool": tool, "found": found,
                        "expected": expected, "ok": ok})
        if not ok:
            deviations.append(
                f"{tool}: image has {found}, official Dockerfile.sim pins "
                f"{expected} ({level} comparison) — output formats may "
                f"differ and silently false-FAIL the harness (#536)")
    return results, deviations


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="CVDP scoring-image tool-spec preflight (#536).")
    ap.add_argument("--image", required=True,
                    help="the OSS_SIM_IMAGE docker tag to verify")
    ap.add_argument("--json", default=None, help="write JSON verdict here")
    args = ap.parse_args(argv)

    if shutil.which("docker") is None:
        print("ERROR: docker not available — cannot verify the sim image; "
              "refusing to bless scoring (#536)", file=sys.stderr)
        return 2
    rc, out = probe_image(args.image)
    if rc != 0 and not out.strip():
        print(f"ERROR: image {args.image!r} not runnable (rc={rc})",
              file=sys.stderr)
        return 2
    results, deviations = check_versions(out)
    verdict = {
        "image": args.image,
        "official_spec": {k: v[0] for k, v in OFFICIAL_SPEC.items()},
        "tools": results,
        "deviations": deviations,
        "verdict": "PASS" if not deviations else "REFUSE",
    }
    text = json.dumps(verdict, indent=2, ensure_ascii=False)
    if args.json:
        from pathlib import Path
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(text + "\n")
    print(text)
    if deviations:
        for d in deviations:
            print(f"DEVIATION: {d}", file=sys.stderr)
        print("REFUSING to score: the sim image deviates from the official "
              "Dockerfile.sim spec — results would not be comparable "
              "(#536).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
