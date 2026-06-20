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
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
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


# ── ORGANIC #714: OSS_PNR_IMAGE (synth) requirement preflight ───────────────
# CVDP area-opt (cid007) problems carry a synth Dockerfile whose BASE image is
# the `__OSS_PNR_IMAGE__` template variable (distinct from `__OSS_SIM_IMAGE__`).
# If the scoring driver sets only OSS_SIM_IMAGE, OSS_PNR_IMAGE defaults to the
# UNPULLABLE proprietary commercial image, the synth container never builds,
# yosys never runs, and the synth subtest FALSE-FAILS on correct RTL. This
# preflight detects the requirement and FAILS CLOSED (REFUSE) when the env is
# unset — it never hardcodes a "magic image to force a pass" (no-cheating).
# chip-AGNOSTIC: keys on the official CVDP template token, same family as the
# existing __OSS_SIM_IMAGE__ handling; no design / vendor literal.
_OSS_PNR_TEMPLATE = "__OSS_PNR_IMAGE__"
_HARNESS_SCAN_SUFFIXES = (
    ".synth", ".sim", ".mk", ".sh", ".yaml", ".yml", ".json", ".env", ".cfg")
# After `run_benchmark.py` MATERIALIZES a harness, the `__OSS_PNR_IMAGE__`
# template is already SUBSTITUTED to whatever `OSS_PNR_IMAGE` resolved to — and
# in CVDP v1.1.0 the default is the GATED proprietary `nvidia/cvdp-sim:<tag>`
# (the upstream README pins `OSS_PNR_IMAGE=nvidia/cvdp-sim:v1.0.0`). A preflight
# that only looks for the pre-substitution `__OSS_PNR_IMAGE__` token therefore
# returns "not required" on the very score dir whose synth container pulls the
# gated image → `pull access denied` → the synth subtest FALSE-FAILS on correct
# RTL (field-measured: 16/302 area-opt problems, all logged as a ~650-byte
# "TRUNCATED"). Detect the materialized gated literal too. chip-AGNOSTIC: keys on
# the official CVDP gated-image repository name, no design/vendor-SKU literal.
_GATED_PNR_LITERAL = re.compile(r"\bnvidia/cvdp-sim:[\w.\-]+", re.I)


def harness_requires_pnr_image(problem_dir: Path) -> Tuple[bool, List[Path]]:
    """True iff any harness file under `problem_dir` references the
    `__OSS_PNR_IMAGE__` template (a pre-materialization area-opt / synth problem)
    OR a MATERIALIZED gated `nvidia/cvdp-sim:<tag>` base image (the template
    already substituted to the proprietary default). Returns (required, [files…]).
    Scans only cheap harness-shaped files."""
    hits: List[Path] = []
    if not problem_dir.is_dir():
        return False, hits
    for f in sorted(problem_dir.rglob("*")):
        if not f.is_file():
            continue
        if not (f.name.startswith("Dockerfile")
                or f.suffix in _HARNESS_SCAN_SUFFIXES):
            continue
        try:
            txt = f.read_text(errors="ignore")
        except OSError:
            continue
        if _OSS_PNR_TEMPLATE in txt or _GATED_PNR_LITERAL.search(txt):
            hits.append(f)
    return (len(hits) > 0), hits


def _image_pullable(image: str, runner=None) -> Optional[bool]:
    """Best-effort: True if the image is present locally or its manifest is
    reachable; False if a CLEAR not-found; None if undeterminable (no docker /
    network error) — None must NOT trigger a false-refuse."""
    if shutil.which("docker") is None:
        return None
    if runner is None:
        def runner(cmd):
            return subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=60)
    try:
        if runner(["docker", "image", "inspect", image]).returncode == 0:
            return True
        r = runner(["docker", "manifest", "inspect", image])
        return True if r.returncode == 0 else False
    except Exception:
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="CVDP scoring-image preflight (#536 sim-image tool-spec "
                    "+ #714 OSS_PNR_IMAGE synth requirement).")
    ap.add_argument("--image", default=None,
                    help="the OSS_SIM_IMAGE docker tag to verify (#536)")
    ap.add_argument("--problem-dir", default=None,
                    help="a CVDP problem dir to scan for an OSS_PNR_IMAGE "
                         "(area-opt synth) requirement (#714)")
    ap.add_argument("--json", default=None, help="write JSON verdict here")
    args = ap.parse_args(argv)

    if not args.image and not args.problem_dir:
        print("ERROR: pass --image and/or --problem-dir", file=sys.stderr)
        return 2

    verdict: Dict = {}
    refuse = False
    deviations: List[str] = []

    # ── #536: sim-image tool-spec check (only when --image given) ──
    if args.image:
        if shutil.which("docker") is None:
            print("ERROR: docker not available — cannot verify the sim image; "
                  "refusing to bless scoring (#536)", file=sys.stderr)
            return 2
        rc, out = probe_image(args.image)
        if rc != 0 and not out.strip():
            print(f"ERROR: image {args.image!r} not runnable (rc={rc})",
                  file=sys.stderr)
            return 2
        results, sim_dev = check_versions(out)
        verdict.update({
            "image": args.image,
            "official_spec": {k: v[0] for k, v in OFFICIAL_SPEC.items()},
            "tools": results,
        })
        deviations.extend(sim_dev)

    # ── #714: OSS_PNR_IMAGE (synth) requirement scan (when --problem-dir) ──
    if args.problem_dir:
        required, hit_files = harness_requires_pnr_image(Path(args.problem_dir))
        verdict["oss_pnr_image_required"] = required
        if required:
            verdict["oss_pnr_image_template_files"] = [
                str(f) for f in hit_files]
            # A MATERIALIZED harness already baked the gated `nvidia/cvdp-sim`
            # literal into its synth Dockerfile — the env no longer matters for
            # THIS dir; it will pull the gated image and false-fail. Flag it
            # regardless of OSS_PNR_IMAGE so a post-materialization preflight
            # (the realistic check point) catches the block #714 only caught
            # pre-materialization.
            baked_gated = any(
                _GATED_PNR_LITERAL.search(f.read_text(errors="ignore"))
                for f in hit_files if f.is_file())
            verdict["oss_pnr_image_materialized_gated"] = baked_gated
            pnr = (os.environ.get("OSS_PNR_IMAGE") or "").strip()
            verdict["oss_pnr_image_set"] = bool(pnr)
            if baked_gated:
                deviations.append(
                    "area-opt synth harness has a MATERIALIZED gated "
                    "`nvidia/cvdp-sim:<tag>` base image baked into its synth "
                    "Dockerfile — that container pulls the proprietary image "
                    "(`pull access denied`) and the synth gate FALSE-FAILS on "
                    "correct RTL (#714 round-2: the template was already "
                    "substituted). Re-materialize with OSS_PNR_IMAGE set to a "
                    "verified OSS PnR image, or retag the OSS image to the gated "
                    "name before scoring.")
            elif not pnr:
                deviations.append(
                    "area-opt synth harness references __OSS_PNR_IMAGE__ but "
                    "OSS_PNR_IMAGE is UNSET — the synth container would default "
                    "to the unpullable proprietary image and the synth gate "
                    "would FALSE-FAIL (#714). Set OSS_PNR_IMAGE to the verified "
                    "OSS PnR image before scoring.")
            else:
                pull = _image_pullable(pnr)
                verdict["oss_pnr_image_pullable"] = (
                    "unverified-no-docker" if pull is None else pull)
                if pull is False:
                    deviations.append(
                        f"OSS_PNR_IMAGE={pnr!r} is set but NOT pullable / "
                        f"present — synth container build would fail (#714).")

    if deviations:
        refuse = True
    verdict["deviations"] = deviations
    verdict["verdict"] = "REFUSE" if refuse else "PASS"

    text = json.dumps(verdict, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(text + "\n")
    print(text)
    if refuse:
        for d in deviations:
            print(f"DEVIATION: {d}", file=sys.stderr)
        print("REFUSING to score: scoring-environment preflight failed "
              "(#536 sim-image spec and/or #714 OSS_PNR_IMAGE) — results "
              "would not be comparable.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
