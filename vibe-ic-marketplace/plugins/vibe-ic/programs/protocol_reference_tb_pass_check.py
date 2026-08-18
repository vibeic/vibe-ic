#!/usr/bin/env python3
"""protocol_reference_tb_pass_check.py — Wave 28/29 (v0.119.60+) gate.

Wave 29 (v0.119.61) — runtime functional verification is non-waivable.
The plugin reference TB exists specifically to catch silent bugs that
escape static gates.  Allowing waiver re-opens the escape route.  If
the TB FAILs, fix the RTL.

Runtime functional verification gate.  Plugs the agent's RTL into the
plugin-provided AID-class reference testbench
(``tools/protocol_tb/aid_class_reference_tb.v``), compiles with
iverilog, runs with vvp, and parses stdout for the ``PROTOCOL_REFERENCE_TB_PASS``
sentinel.

Background
----------
Through 33 fresh-agent attempts (v0.119.27..v0.119.59), every project
hit ``Overall: PASS`` on 145 static structural-RTL gates yet still
produced byte[6]=0x02 deterministic FAIL on real silicon.  The
fundamental gap: each fresh-agent's RTL satisfied static patterns but
was functionally wrong in some uncovered dimension (dispatch arm
omitted, CRC routing wrong, wake-pulse not stopped after first RX,
…).

Wave 28 / v0.119.60 closes the loop with a runtime functional check.
The plugin ships a chip-AGNOSTIC reference TB that drives host-side
stimulus (BR break-pulse + cmd byte + tSRS gap) onto the open-drain
``id_bus`` and captures the DUT response by sampling the bus midway
through each bit cell.  The TB then verifies:

  Scenario 1 — GET_ID  (0x74):  DUT must reply 8 bytes, opcode 0x75,
              CRC residue 0x00.
  Scenario 2 — GET_STATE (0x72): DUT must reply at least 1 byte
              (response opcode warned but not enforced).
  Scenario 3 — GET_INFO (0x76):  DUT must reply at least 1 byte.

Detection algorithm
-------------------
1. Locate plugin TB at ``<plugin_root>/tools/protocol_tb/aid_class_reference_tb.v``.
2. Discover RTL dir: ``<project>/rtl/`` (or ``src/`` / ``hdl/``).
3. Identify top module name:
     a) explicit ``L9.integration_spec.top_module``;
     b) heuristic: file ``*top.sv`` / ``*_top.v`` whose module name ends
        in ``_top`` and that exposes an ``inout`` named id_bus / id_io;
     c) fall back to literal ``chip_top`` (TB default).
4. Identify chip clock period:
     a) ``L8.rtl_constants.clock_period_ns`` / ``CLOCK_PERIOD_NS``;
     b) heuristic: scan rtl/ for ``CLOCK_PERIOD_NS = NN``;
     c) fall back to 20 (= 50 MHz).
5. Run ``iverilog -g2012 -o <tmp>/tb -DDUT_TOP_NAME=<top> \\
       -DCLOCK_PERIOD_NS=<period> <rtl> <plugin_tb>``.
6. Run ``vvp <tmp>/tb`` (5 minute hard timeout).
7. PASS when stdout contains ``PROTOCOL_REFERENCE_TB_PASS``.
8. FAIL when stdout contains ``PROTOCOL_REFERENCE_TB_FAIL`` or
   compile error.
9. SKIP when no RTL dir / no top module / non-protocol design (no L3
   commands and no id_bus port in any RTL file).
10. WARN when ``iverilog`` is not on PATH — gate cannot run; project
    install required.  Returns exit 0 with a hint.
11. **Non-waivable as of Wave 29 / v0.119.61** — the previous waiver
    ``protocol_reference_tb_skipped_intentional`` is rejected.
    Following the Wave 23 (Phase 1 (doc-extraction)) precedent, every escape route
    has been used; runtime functional verification is now hard-gated.

Usage
-----
    python3 protocol_reference_tb_pass_check.py <project_dir>
        [--json <out>] [--keep-tmp]

Exit codes
----------
    0 — PASS / SKIP / PASS_WITH_WAIVER / WARN-only (no iverilog)
    1 — FAIL (compile error or TB ran and reported FAIL)
    2 — usage / IO error
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional


PLUGIN_TB_REL = "tools/protocol_tb/aid_class_reference_tb.v"

# Wave 29 — gate is non-waivable.  Sentinel kept to surface a clear
# diagnostic if a project still carries the legacy waiver key.
LEGACY_WAIVER_KEY = "protocol_reference_tb_skipped_intentional"


def legacy_waiver_present(project: Path) -> bool:
    p = project / "waivers.json"
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text())
        v = d.get(LEGACY_WAIVER_KEY)
        return isinstance(v, str) and v.strip() != ""
    except Exception:
        return False


# --- plugin TB discovery -----------------------------------------------
def find_plugin_tb() -> Optional[Path]:
    # This file lives at <plugin_root>/programs/<this>.py.
    # Plugin TB lives at <plugin_root>/tools/protocol_tb/aid_class_reference_tb.v.
    here = Path(__file__).resolve()
    plugin_root = here.parent.parent
    candidate = plugin_root / PLUGIN_TB_REL
    if candidate.is_file():
        return candidate
    return None


# --- iverilog discovery ------------------------------------------------
def have_iverilog() -> bool:
    return shutil.which("iverilog") is not None and shutil.which("vvp") is not None


# --- project introspection ---------------------------------------------
def find_rtl_dir(project: Path) -> Optional[Path]:
    for cand in ("phase2/stage1/rtl", "rtl", "src", "hdl"):
        d = project / cand
        if d.is_dir():
            files = list(d.glob("*.v")) + list(d.glob("*.sv"))
            if files:
                return d
    if any(project.glob("*.v")) or any(project.glob("*.sv")):
        return project
    return None


def list_rtl_files(rtl_dir: Path) -> list[Path]:
    files = sorted(list(rtl_dir.glob("*.v")) + list(rtl_dir.glob("*.sv")))
    # Exclude testbench files and simulation models that we don't want
    # iverilog to compile alongside the DUT.
    out = []
    for f in files:
        n = f.name.lower()
        if "_tb" in n or n.startswith("tb_") or n.endswith("_tb.v") or n.endswith("_tb.sv"):
            continue
        if "testbench" in n:
            continue
        out.append(f)
    # Hoist package files (*pkg*.sv) to the front so `import pkg::*`
    # resolves at parse time. iverilog (≤14) does not auto-resolve package
    # symbols across the whole compilation unit; ordering matters.
    pkg = [f for f in out if "pkg" in f.name.lower() and f.suffix == ".sv"]
    rest = [f for f in out if f not in pkg]
    return pkg + rest


_INOUT_ID_BUS = re.compile(
    r"\binout\b[^,;)]*\b(id_bus|id_io|idbus|id_data)\b",
    re.IGNORECASE,
)
_MODULE_DEF = re.compile(
    r"\bmodule\s+([A-Za-z_]\w*)\s*[#(]",
)


def find_top_module(project: Path, rtl_files: list[Path]) -> Optional[str]:
    # Build set of actually-defined module names in rtl_files so we can
    # validate any L9-declared top_module against reality.
    defined: set[str] = set()
    for f in rtl_files:
        try:
            txt = f.read_text(errors="ignore")
        except Exception:
            continue
        for m in _MODULE_DEF.findall(txt):
            defined.add(m)

    # 1) L9 integration spec explicit override — but only if the declared
    #    top_module actually exists as an RTL module (defends against L9
    #    stale-naming vs generator-emitted RTL drift)
    for sub in ("phase1/generated_docs", "generated_docs", "l_docs"):
        d = project / sub
        if d.is_dir():
            for cand in sorted(d.glob("L9*.json")):
                try:
                    j = json.loads(cand.read_text())
                except Exception:
                    continue
                # try several path conventions
                for path in (
                    ("integration_spec", "top_module"),
                    ("integration_spec", "top"),
                    ("top_module",),
                    ("top",),
                ):
                    cur = j
                    for k in path:
                        if isinstance(cur, dict) and k in cur:
                            cur = cur[k]
                        else:
                            cur = None
                            break
                    if isinstance(cur, str) and cur.strip():
                        name = cur.strip()
                        if (not defined) or name in defined:
                            return name

    # 2) heuristic: file with name ending _top + module declaration
    candidates: list[tuple[str, Path]] = []
    for f in rtl_files:
        try:
            txt = f.read_text(errors="ignore")
        except Exception:
            continue
        # Module name AND inout id_bus to be a likely top
        modules = _MODULE_DEF.findall(txt)
        has_id_bus = bool(_INOUT_ID_BUS.search(txt))
        for m in modules:
            score = 0
            if m.lower().endswith("_top") or m.lower().endswith("top"):
                score += 10
            if has_id_bus:
                score += 5
            stem = f.stem.lower()
            if "top" in stem:
                score += 3
            if score >= 8:
                candidates.append((m, f))
    if candidates:
        # Prefer one with the highest priority — the first in scan order.
        return candidates[0][0]

    # 3) fallback: literal "chip_top"
    return None


_CLOCK_PERIOD_RE = re.compile(
    r"\b(?:CLOCK_PERIOD_NS|CLK_PERIOD_NS|T_CLK_NS)\s*=\s*(\d+)",
)


def find_clock_period_ns(project: Path, rtl_files: list[Path]) -> int:
    # 1) L8 / rtl_constants
    for sub in ("phase1/generated_docs", "generated_docs", "l_docs"):
        d = project / sub
        if d.is_dir():
            for cand in sorted(d.glob("L8*.json")):
                try:
                    j = json.loads(cand.read_text())
                except Exception:
                    continue
                for path in (
                    ("rtl_constants", "CLOCK_PERIOD_NS"),
                    ("rtl_constants", "clock_period_ns"),
                    ("clock_period_ns",),
                ):
                    cur = j
                    for k in path:
                        if isinstance(cur, dict) and k in cur:
                            cur = cur[k]
                        else:
                            cur = None
                            break
                    try:
                        if cur is not None:
                            v = int(cur)
                            if 1 <= v <= 1000:
                                return v
                    except Exception:
                        pass

    # 2) RTL scan
    for f in rtl_files:
        try:
            txt = f.read_text(errors="ignore")
        except Exception:
            continue
        m = _CLOCK_PERIOD_RE.search(txt)
        if m:
            try:
                v = int(m.group(1))
                if 1 <= v <= 1000:
                    return v
            except Exception:
                pass

    # 3) default 50 MHz
    return 20


_AID_PROTOCOL_TYPE_TOKENS: tuple[str, ...] = (
    "aid",
    "apple id bus",
    "apple_id_bus",
    "single_wire_half_duplex",
    "single-wire half-duplex",
    "half_duplex_single_wire",
    "half-duplex single-wire",
    "id_bus",
    "open_drain_single_wire",
)


def _l2_says_aid_class(project: Path) -> bool:
    for sub in ("phase1/generated_docs", "generated_docs", "l_docs"):
        d = project / sub
        if not d.is_dir():
            continue
        for cand in sorted(d.glob("L2*.json")):
            try:
                j = json.loads(cand.read_text(errors="ignore"))
            except Exception:
                continue
            # Look for protocol_type / interface tokens.
            blob_parts: list[str] = []
            for path in (
                ("protocol_type",),
                ("protocol",),
                ("interface_type",),
                ("frs_doc", "protocol_type"),
                ("frs_doc", "interface"),
                ("physical_layer", "interface"),
            ):
                cur: object = j
                ok = True
                for k in path:
                    if isinstance(cur, dict) and k in cur:
                        cur = cur[k]
                    else:
                        ok = False
                        break
                if ok and isinstance(cur, str) and cur:
                    blob_parts.append(cur.lower())
            blob = " ".join(blob_parts)
            for tok in _AID_PROTOCOL_TYPE_TOKENS:
                if tok in blob:
                    return True
    return False


def is_protocol_design(project: Path, rtl_files: list[Path]) -> bool:
    """Wave 36 (v0.119.68) — AID-class reference TB only applies to
    half-duplex single-wire designs. Decision rule:

      (RTL declares `inout id_bus|id_io|idbus|id_data`)
      OR (L2.protocol_type matches an AID-class synonym)

    L3 commands alone do NOT trigger any more — every cmd-driven
    digital chip has L3 commands, but only AID-class ones share the
    open-drain BR/IBT framing the reference TB drives.  This change
    eliminates the FP_RISK F3-style contamination where a SPI / UART
    / I2C chip with L3 commands was forced through an AID-class TB.
    """
    has_inout_id_bus = False
    for f in rtl_files:
        try:
            txt = f.read_text(errors="ignore")
        except Exception:
            continue
        if _INOUT_ID_BUS.search(txt):
            has_inout_id_bus = True
            break
    if has_inout_id_bus:
        return True
    if _l2_says_aid_class(project):
        return True
    return False


# --- compile + run -----------------------------------------------------
def run_iverilog(rtl_files: list[Path], plugin_tb: Path,
                 top_name: Optional[str], clk_period_ns: int,
                 work_dir: Path, timeout_compile: int = 90,
                 timeout_run: int = 300,
                 ) -> tuple[str, str, int, str, int]:
    """Returns (compile_stdout, compile_stderr, compile_rc,
                  run_stdout, run_rc)."""
    tb_bin = work_dir / "aid_class_ref_tb"
    cmd = [
        "iverilog", "-g2012",
        "-o", str(tb_bin),
        f"-Pcaid_class_reference_tb.CLOCK_PERIOD_NS={clk_period_ns}",
    ]
    # iverilog -P only works on top-level params *of the toplevel*; safer
    # to use +define+CLOCK_PERIOD_NS to override the parameter value.
    # However, the TB declares it as a `parameter` with a default; using
    # `iverilog -P aid_class_reference_tb.CLOCK_PERIOD_NS=XX` is the
    # idiomatic form.  Falling back to define just sets a macro that is
    # ignored unless the TB referenced `CLOCK_PERIOD_NS as a `define.
    # We'll just rely on -P; if that fails we still produce a valid TB.
    cmd = [
        "iverilog", "-g2012",
        "-DSIMULATION",
        "-o", str(tb_bin),
        f"-Paid_class_reference_tb.CLOCK_PERIOD_NS={clk_period_ns}",
    ]
    if top_name:
        cmd.append(f"-DDUT_TOP_NAME={top_name}")
    for f in rtl_files:
        cmd.append(str(f))
    cmd.append(str(plugin_tb))

    try:
        # watchdog-exempt: bounded single-file iverilog compile (reference-TB +
        # RTL build); fixed timeout_compile budget adequate — not an open-ended
        # EDA generator.
        compile_proc = subprocess.run(
            cmd,
            capture_output=True, text=True,
            timeout=timeout_compile,
        )
    except subprocess.TimeoutExpired:
        return ("", "iverilog timed out", 124, "", 0)

    compile_stdout = compile_proc.stdout
    compile_stderr = compile_proc.stderr
    compile_rc = compile_proc.returncode

    if compile_rc != 0 or not tb_bin.exists():
        return (compile_stdout, compile_stderr, compile_rc, "", 0)

    try:
        run_proc = subprocess.run(
            ["vvp", str(tb_bin)],
            cwd=str(work_dir),
            capture_output=True, text=True,
            timeout=timeout_run,
        )
    except subprocess.TimeoutExpired as e:
        # Partial output may exist
        run_out = ""
        if e.stdout:
            run_out = (e.stdout if isinstance(e.stdout, str)
                       else e.stdout.decode("utf-8", errors="ignore"))
        return (compile_stdout, compile_stderr, compile_rc, run_out, 124)

    return (compile_stdout, compile_stderr, compile_rc,
            run_proc.stdout, run_proc.returncode)


# --- main checking entry ----------------------------------------------
def check(project: Path, keep_tmp: bool = False) -> dict:
    out: dict = {
        "pass": False,
        "findings": [],
        "warnings": [],
    }

    plugin_tb = find_plugin_tb()
    if plugin_tb is None:
        out["skip_reason"] = (
            "plugin reference TB not found (tools/protocol_tb/"
            "aid_class_reference_tb.v missing) — plugin install incomplete"
        )
        return out

    rtl_dir = find_rtl_dir(project)
    if rtl_dir is None:
        out["skip_reason"] = "no RTL directory found"
        return out

    rtl_files = list_rtl_files(rtl_dir)
    if not rtl_files:
        out["skip_reason"] = f"no .v / .sv files in {rtl_dir}"
        return out

    if not is_protocol_design(project, rtl_files):
        out["skip_reason"] = (
            "non-protocol design (no inout id_bus / no L3 commands) — "
            "AID-class TB not applicable"
        )
        return out

    if not have_iverilog():
        # WARN-only — return pass=True so we don't block the burn just
        # because the build host lacks iverilog.  Caller can treat the
        # warning as a hint to install.
        out["pass"] = True
        out["warnings"].append({
            "rule": "IVERILOG_NOT_AVAILABLE",
            "message": ("iverilog / vvp not on PATH — runtime "
                        "functional verification SKIPPED.  Install "
                        "iverilog (e.g. `apt install iverilog`) to "
                        "enable Wave 28 reference-TB gate."),
        })
        return out

    top_name = find_top_module(project, rtl_files)
    clk_period_ns = find_clock_period_ns(project, rtl_files)
    out["top_module"] = top_name or "chip_top"
    out["clock_period_ns"] = clk_period_ns

    with tempfile.TemporaryDirectory(prefix="protocol_ref_tb_") as tmp:
        work_dir = Path(tmp)
        if keep_tmp:
            keep_dir = project / ".protocol_ref_tb_artifacts"
            keep_dir.mkdir(exist_ok=True)
            work_dir = keep_dir
        # Stage OTP image in cwd so that any RTL containing
        # `$readmemh("X.hex", mem)` (or "otp_image.hex") loads real
        # values during simulation — the TB checks that DUT reply bytes
        # match the OTP content, so all-zero stubs would falsely PASS
        # only-CRC-correctness while masking missing OTP. v0.121 wave 50:
        # prefer real image from input/otp/, otp/, synth/, or fpga/;
        # fall back to all-zero stub only when no real image exists.
        # Chip-AGNOSTIC — no foundry / vendor / project-specific filename
        # hardcoded; we just glob for *.hex / *.mif under conventional dirs.
        try:
            real_image_bytes: bytes | None = None
            for hex_pat in ("input/otp/*.hex", "otp/*.hex",
                            "phase2/stage2/synth/*.hex", "phase2/stage1/fpga/*.hex", "phase2/stage1/rtl/*.hex"):
                for p_real in project.glob(hex_pat):
                    if p_real.is_file() and p_real.stat().st_size > 0:
                        real_image_bytes = p_real.read_bytes()
                        break
                if real_image_bytes is not None:
                    break
            if real_image_bytes is not None:
                # Stage under all conventional names so any $readmemh
                # filename in RTL resolves.
                for stem in ("apple.hex", "otp_image.hex"):
                    p = work_dir / stem
                    if not p.exists():
                        p.write_bytes(real_image_bytes)
            else:
                stub_lines = "\n".join(["00"] * 128) + "\n"
                for stem in ("apple.hex", "otp_image.hex"):
                    p = work_dir / stem
                    if not p.exists():
                        p.write_text(stub_lines)
        except Exception:
            pass
        compile_stdout, compile_stderr, compile_rc, run_stdout, run_rc = (
            run_iverilog(
                rtl_files, plugin_tb,
                top_name=top_name, clk_period_ns=clk_period_ns,
                work_dir=work_dir,
            )
        )

    out["compile_rc"] = compile_rc
    out["run_rc"] = run_rc
    # Trim outputs to bounded length to keep result.json sane.
    out["compile_stdout_tail"] = (compile_stdout or "")[-2000:]
    out["compile_stderr_tail"] = (compile_stderr or "")[-2000:]
    out["run_stdout_tail"] = (run_stdout or "")[-4000:]

    if compile_rc != 0:
        first_err = ""
        for ln in (compile_stderr or "").splitlines():
            if "error" in ln.lower():
                first_err = ln.strip()[:200]
                break
        out["findings"].append({
            "rule": "TB_COMPILE_ERROR",
            "message": (
                f"iverilog failed (rc={compile_rc}) on {len(rtl_files)} "
                f"RTL file(s) + plugin reference TB.  First error: "
                f"{first_err or '(no recognisable error line — see compile_stderr_tail)'}"
            ),
        })
        return out

    if "PROTOCOL_REFERENCE_TB_PASS" in (run_stdout or ""):
        out["pass"] = True
        return out

    if "PROTOCOL_REFERENCE_TB_FAIL" in (run_stdout or ""):
        # Wave 34 (Task 4): elevate PROTOCOL_VIOLATION_DEVICE_BR to a
        # specific rule code so agents diagnose the device-BR class
        # without re-reading TB stdout. Each violation line emitted by
        # the TB capture loop becomes a finding with rule
        # `TB_PROTOCOL_VIOLATION_DEVICE_BR`.
        violation_lines = [
            ln.strip() for ln in (run_stdout or "").splitlines()
            if "PROTOCOL_VIOLATION_DEVICE_BR" in ln
        ]
        for ln in violation_lines:
            out["findings"].append({
                "rule": "TB_PROTOCOL_VIOLATION_DEVICE_BR",
                "message": ln[:300],
            })
        # Distill specific FAIL lines (FAIL_GET_ID / FAIL_GET_STATE / …)
        fail_lines = [ln.strip() for ln in (run_stdout or "").splitlines()
                      if ln.strip().startswith("FAIL_")]
        for ln in fail_lines:
            # Map device-BR-specific FAIL lines to the dedicated rule.
            if "DEVICE_BR" in ln:
                out["findings"].append({
                    "rule": "TB_PROTOCOL_VIOLATION_DEVICE_BR",
                    "message": ln[:300],
                })
            else:
                out["findings"].append({
                    "rule": "TB_RUNTIME_FAIL",
                    "message": ln[:300],
                })
        if not fail_lines and not violation_lines:
            out["findings"].append({
                "rule": "TB_RUNTIME_FAIL",
                "message": ("TB reported PROTOCOL_REFERENCE_TB_FAIL "
                            "without distilled FAIL_* lines — see "
                            "run_stdout_tail"),
            })
        return out

    # No PASS / FAIL sentinel — could be watchdog or runtime crash
    out["findings"].append({
        "rule": "TB_NO_VERDICT",
        "message": (f"vvp ran (rc={run_rc}) but emitted no "
                    f"PROTOCOL_REFERENCE_TB_{{PASS|FAIL}} sentinel — "
                    f"see run_stdout_tail"),
    })
    return out


def main() -> int:
    p = argparse.ArgumentParser(
        description="Plugin reference TB runtime functional check (Wave 28).",
    )
    p.add_argument("project_dir", help="Path to the project directory.")
    p.add_argument("--json", default=None, help="Write JSON result here.")
    p.add_argument("--keep-tmp", action="store_true",
                   help="Keep iverilog work dir under "
                        ".protocol_ref_tb_artifacts/ for debugging.")
    args = p.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"Usage error: {project} is not a directory")
        return 2

    result = check(project, keep_tmp=args.keep_tmp)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(result, indent=2))

    if "skip_reason" in result:
        print(f"PASS_SKIP — {result['skip_reason']}")
        return 0

    if result["pass"]:
        if result.get("warnings"):
            print(f"PASS_WITH_WARN — reference TB skipped "
                  f"({len(result['warnings'])} warning(s))")
            for w in result["warnings"]:
                print(f"WARN: {w['rule']} — {w['message']}")
        else:
            print(
                f"PASS — PROTOCOL_REFERENCE_TB_PASS "
                f"(top={result.get('top_module', '?')}, "
                f"clk_period={result.get('clock_period_ns', '?')} ns)")
        return 0

    # Wave 29 — non-waivable.  Surface a clear diagnostic if a project
    # still carries the legacy waiver key so users know to remove it.
    if legacy_waiver_present(project):
        print(
            f"FAIL — Wave 29 (v0.119.61): protocol_reference_tb_pass_check "
            f"is now non-waivable. Legacy waiver "
            f"`{LEGACY_WAIVER_KEY}` is ignored. Remove it from "
            f"waivers.json and fix the RTL until the reference TB "
            f"reports PROTOCOL_REFERENCE_TB_PASS.")
    print(f"FAIL — reference TB did not pass "
          f"({len(result['findings'])} finding(s))")
    for f in result["findings"]:
        print(f"FAIL: {f['rule']} — {f['message']}")
    for w in result.get("warnings", []):
        print(f"WARN: {w['rule']} — {w['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
