#!/usr/bin/env python3
"""mcp-eda / terasic-de10lite / driver.py — JSON-IO FPGA driver.

Standalone CLI driver for the Terasic DE10-Lite FPGA board (Intel/Altera
MAX10 10M50DAF484C7G + on-board USB-Blaster). Spoken to by the
mcp-eda device registry (src/devices/_registry.js); also runnable
by hand for one-off debug:

    python3 driver.py --mode detect --json-args '{}'
    python3 driver.py --mode program --json-args '{"sof_path":"/abs/path/to.sof"}'

Why this exists alongside keysight-scope:
    DE10-Lite (MAX10 10M50) was the FPGA we used to live-catch the
    v0.64 wake_ctrl tITO timer-freeze bug — the Keysight scope captured
    the periodic 5 ms wake-pulse pattern that the bug emits on ID_BUS.
    Pairing FPGA-program + scope-verify in the same MCP server enables
    fully automated bring-up flows: build SOF → burn → trigger DUT
    activity → arm scope → verdict, all through MCP tool calls and zero
    GUI interactions.

JSON-IO contract (matches keysight-scope/driver.py):
    stdin OR --json-args '<json>' (use '-' to mean stdin)
    stdout: exactly ONE JSON object on success or detected FAIL.
    stderr: progress / debug logs.
    exit codes:
        0 = success
        1 = detected FAIL (programmer ran but reported failure, OR
            recoverable runtime error: timeout/protocol/busy)
        2 = arg / IO / quartus_pgm-not-found error (device_not_found,
            permission_denied, vendor_tool_not_found, invalid_argument)

v0.67: All error returns go through the DeviceError taxonomy in
`../../_shared/errors.py`. MCP clients can branch on `error_code`
without parsing English messages.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Shared DeviceError taxonomy.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.normpath(os.path.join(_HERE, "..", "..", "_shared"))
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)
from errors import (  # noqa: E402
    DeviceError,
    DeviceNotFoundError,
    PermissionError_,
    DeviceTimeoutError,
    DeviceProtocolError,
    VendorToolNotFoundError,
    InvalidArgumentError,
    EXIT_FOR_CODE,
)

from pathlib import Path
# `_progress_run` lives in the plugin's `programs/`, which is not a sibling of
# this file. Walk UP until the directory that actually holds it is found, so
# this works from `tools/`, from `tools/<sub>/`, and from inside the flattened
# plugin cache where the marketplace path does not exist.
for _anc in Path(__file__).resolve().parents:
    for _cand in (_anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                  _anc / "programs"):
        if (_cand / "_progress_run.py").is_file():
            sys.path.insert(0, str(_cand))
            break
    else:
        continue
    break
import _progress_run as _pr  # noqa: E402


def find_quartus_pgm() -> Optional[str]:
    """Search $QUARTUS_ROOTDIR/bin, $PATH, common defaults, and external mounts.

    v1.6.18 expansion: many users keep Quartus on an external SSD mounted
    under /mnt/*; the driver process is also frequently spawned by tools
    (Claude Code, MCP, systemd) that don't source ~/.bashrc, so $QUARTUS_ROOTDIR
    is missing from os.environ even though the user's interactive shell has
    it. We now: (a) scan /mnt/* and /media/* for typical Quartus layouts,
    and (b) fall back to a `bash -lic 'echo $QUARTUS_ROOTDIR'` probe to
    capture the env from a login interactive shell.
    """
    # 1. Explicit env var.
    qroot = os.environ.get("QUARTUS_ROOTDIR")
    if qroot:
        cand = os.path.join(qroot, "bin", "quartus_pgm")
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    # 2. PATH.
    path_hit = shutil.which("quartus_pgm")
    if path_hit:
        return path_hit
    # 3. Common install roots (Linux). Glob to handle versioned dirs.
    patterns = [
        "/opt/intelFPGA*/quartus/bin/quartus_pgm",
        "/opt/intelFPGA*/*/quartus/bin/quartus_pgm",
        "/opt/altera*/quartus/bin/quartus_pgm",
        os.path.expanduser("~/intelFPGA*/quartus/bin/quartus_pgm"),
        os.path.expanduser("~/intelFPGA*/*/quartus/bin/quartus_pgm"),
        os.path.expanduser("~/altera*/quartus/bin/quartus_pgm"),
        # External-mount installs (USB SSDs, NAS).
        "/mnt/*/eda/quartus/quartus/bin/quartus_pgm",
        "/mnt/*/eda/quartus/bin/quartus_pgm",
        "/mnt/*/intelFPGA*/quartus/bin/quartus_pgm",
        "/mnt/*/intelFPGA*/*/quartus/bin/quartus_pgm",
        "/mnt/*/altera*/quartus/bin/quartus_pgm",
        "/media/*/eda/quartus/quartus/bin/quartus_pgm",
        "/media/*/intelFPGA*/quartus/bin/quartus_pgm",
    ]
    for pat in patterns:
        for hit in sorted(glob.glob(pat)):
            if os.access(hit, os.X_OK):
                return hit
    # 4. Last resort — ask a login interactive bash for QUARTUS_ROOTDIR
    # so users whose ~/.bashrc has `export QUARTUS_ROOTDIR=...` aren't
    # forced to also set it in every spawning environment. One-shot,
    # 5 s timeout; ignored on error.
    try:
        cp = subprocess.run(
            ["bash", "-lic", 'echo "${QUARTUS_ROOTDIR:-}"'],
            capture_output=True, text=True, timeout=5,
        )
        v = (cp.stdout or "").strip().splitlines()
        if v and v[0]:
            cand = os.path.join(v[0], "bin", "quartus_pgm")
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
    except Exception:
        pass
    return None


def run(cmd: List[str], timeout_s: float = 90.0) -> Tuple[int, str, str]:
    print(f"+ {' '.join(shlex.quote(c) for c in cmd)}", file=sys.stderr)
    try:
        p = _pr.run(cmd, capture_output=True, text=True)
        return p.returncode, p.stdout, p.stderr
    except _pr.Stalled as e:
        # rc 124 meant "the clock ran out". This is a different finding — the
        # tool stopped moving — so it gets its own rc rather than borrowing the
        # one every caller reads as a deadline.
        return (_pr.RC_STALLED, e.stdout or "",
                (e.stderr or "") + f"\n[stalled: {e}]")
    except FileNotFoundError as e:
        return 127, "", str(e)


# ───────────────────────── parsing helpers ─────────────────────────
_CABLE_RE = re.compile(r"^\s*(\d+)\)\s*(.+?)\s*$")
_DEVICE_RE = re.compile(r"^\s*(\d+)\s+([0-9A-Fa-fxX]+)\s+(.+?)\s*$")
_DEVICE_RE_ALT = re.compile(r"Device\s+(\d+):\s+(\S+)\s+(.+)", re.I)


def parse_cable_list(stdout: str) -> List[Dict[str, Any]]:
    """Parse `quartus_pgm --list` output. The first section enumerates cables."""
    cables: List[Dict[str, Any]] = []
    for line in stdout.splitlines():
        m = _CABLE_RE.match(line)
        if m:
            cables.append({"index": int(m.group(1)), "name": m.group(2), "devices": []})
    return cables


def parse_device_list(stdout: str) -> List[Dict[str, Any]]:
    """Parse `quartus_pgm -c <cable> --auto` output for chained devices."""
    devices: List[Dict[str, Any]] = []
    for line in stdout.splitlines():
        m = _DEVICE_RE_ALT.search(line)
        if m:
            devices.append({"idx": int(m.group(1)), "id_hex": m.group(2), "name": m.group(3).strip()})
            continue
        m = _DEVICE_RE.match(line)
        if m and "0x" in m.group(2).lower():
            devices.append({"idx": int(m.group(1)), "id_hex": m.group(2), "name": m.group(3).strip()})
    return devices


def _coerce_int(name: str, val: Any) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        raise InvalidArgumentError(
            f"arg '{name}' must be an integer (got: {val!r})"
        )


def _require_quartus_pgm() -> str:
    pgm = find_quartus_pgm()
    if pgm is None:
        raise VendorToolNotFoundError(
            "quartus_pgm not in PATH or QUARTUS_ROOTDIR",
            context={"hint": "set QUARTUS_ROOTDIR or add Quartus bin/ to PATH"},
        )
    return pgm


def find_system_console() -> Optional[str]:
    """Search for Quartus system-console (JTAG TCL interface for ADC reads)."""
    qroot = os.environ.get("QUARTUS_ROOTDIR")
    if qroot:
        cand = os.path.join(qroot, "bin", "system-console")
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    path_hit = shutil.which("system-console")
    if path_hit:
        return path_hit
    patterns = [
        "/opt/intelFPGA*/quartus/sopc_builder/bin/system-console",
        "/opt/intelFPGA*/*/quartus/sopc_builder/bin/system-console",
        os.path.expanduser("~/intelFPGA*/quartus/sopc_builder/bin/system-console"),
        os.path.expanduser("~/intelFPGA*/*/quartus/sopc_builder/bin/system-console"),
        "/opt/intelFPGA*/quartus/bin/system-console",
        os.path.expanduser("~/intelFPGA*/quartus/bin/system-console"),
        os.path.expanduser("~/intelFPGA*/*/quartus/bin/system-console"),
    ]
    for pat in patterns:
        for hit in sorted(glob.glob(pat)):
            if os.access(hit, os.X_OK):
                return hit
    return None


def _require_system_console() -> str:
    sc = find_system_console()
    if sc is None:
        raise VendorToolNotFoundError(
            "system-console not in PATH or QUARTUS_ROOTDIR",
            context={"hint": "set QUARTUS_ROOTDIR or add Quartus sopc_builder/bin/ to PATH"},
        )
    return sc


# ───────────────────────── modes ─────────────────────────
def mode_detect(_args: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    pgm = _require_quartus_pgm()
    rc, out, err = run([pgm, "--list"], timeout_s=20)
    if rc == 124:
        raise DeviceTimeoutError(
            "quartus_pgm --list timed out",
            last_seen_output=(out + err)[-500:],
        )
    if rc != 0:
        raise DeviceProtocolError(
            "quartus_pgm --list failed",
            last_seen_output=(out + err)[-500:],
            context={"exit_code": rc},
        )
    cables = parse_cable_list(out)
    # Per cable, ask Quartus for the chained devices.
    for cab in cables:
        rc2, out2, err2 = run([pgm, "-c", cab["name"], "--auto"], timeout_s=20)
        cab["devices"] = parse_device_list(out2)
        if rc2 != 0 and not cab["devices"]:
            cab["error"] = err2[-500:] or out2[-500:]
    return 0, {
        "success": True,
        "mode": "detect",
        "quartus_pgm": pgm,
        "cables": cables,
    }


def _find_plugin_program(name: str) -> Optional[str]:
    """Locate a helper Python program in the vibe-ic plugin tree.

    v1.6.0 merged vibe-ic + vibe-ic-d → unified `vibe-ic`. This
    lookup tries the merged path first, falls back to the legacy
    vibe-ic-d path for old installs. Honours VIBE_IC_PROGRAMS_DIR (new)
    and VIBE_IC_D_PROGRAMS_DIR (legacy) for explicit overrides.
    """
    for env_var in ("VIBE_IC_PROGRAMS_DIR", "VIBE_IC_D_PROGRAMS_DIR"):
        env_dir = os.environ.get(env_var)
        if env_dir:
            cand = os.path.join(env_dir, name)
            if os.path.isfile(cand):
                return cand
    here = os.path.dirname(os.path.abspath(__file__))
    # The driver lives bundled in two trees:
    #   (a) repo root: AI_IC_design/mcp-eda/src/devices/fpga/terasic-de10lite/driver.py
    #       → walk up 5 to AI_IC_design/, then vibe-ic-marketplace/plugins/<plugin>/programs/
    #   (b) plugin cache: AI_IC_design/vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/src/devices/fpga/terasic-de10lite/driver.py
    #       → walk up 7 to AI_IC_design/, same target
    # Try both unified ("vibe-ic") and legacy ("vibe-ic-d") plugin names.
    walk = here
    for _ in range(8):
        walk = os.path.dirname(walk)
        for plugin_name in ("vibe-ic", "vibe-ic-d"):
            cand = os.path.join(
                walk, "vibe-ic-marketplace", "plugins", plugin_name,
                "programs", name,
            )
            if os.path.isfile(cand):
                return cand
    # Last-resort: ~/.claude plugin cache (general-user install layout)
    home = os.path.expanduser("~")
    cache_root = os.path.join(home, ".claude", "plugins", "cache",
                              "vibe-ic-marketplace", "vibe-ic")
    if os.path.isdir(cache_root):
        try:
            versions = sorted(os.listdir(cache_root), reverse=True)
            for v in versions:
                cand = os.path.join(cache_root, v, "programs", name)
                if os.path.isfile(cand):
                    return cand
        except OSError:
            pass
    return None


def _run_post_burn_scope_check(
    check: Dict[str, Any], timeout_s: int = 60,
) -> Dict[str, Any]:
    """v0.66: after a successful burn, optionally drive the scope to
    assert the silicon behaves as specified. `check` is one dict from
    the program mode's `post_burn_scope_checks` input list."""
    scope_py = _find_plugin_program("scope_periodic_pulse_check.py")
    if scope_py is None:
        return {"name": check.get("name", "unnamed"),
                "success": False,
                "error": "scope_periodic_pulse_check.py not found in plugin"}

    argv: List[str] = [sys.executable, scope_py]
    # Map input dict → CLI flags. Unknown keys silently ignored.
    _flag_map = {
        "channel": "--channel",
        "span_ms": "--span-ms",
        "period_ms": "--period-ms",
        "period_tol_ms": "--period-tol-ms",
        "pulse_min_us": "--pulse-min-us",
        "pulse_max_us": "--pulse-max-us",
        "low_threshold_v": "--low-threshold-v",
        "high_threshold_v": "--high-threshold-v",
        "probe_attenuation": "--probe-attenuation",
        "vert_scale_v_per_div": "--vert-scale-v-per-div",
        "vert_offset_v": "--vert-offset-v",
        "trigger_slope": "--trigger-slope",
        "trigger_level_v": "--trigger-level-v",
        "trigger_timeout_s": "--trigger-timeout-s",
        "expect": "--expect",
        "min_periodic": "--min-periodic",
        "save_csv": "--save-csv",
    }
    for k, flag in _flag_map.items():
        v = check.get(k)
        if v is None or v == "":
            continue
        argv += [flag, str(v)]

    try:
        r = _pr.run(argv, capture_output=True, text=True)
    except _pr.Stalled as exc:
        return {"name": check.get("name", "unnamed"),
                "success": False,
                "error": f"scope check stalled (not slow): {exc}"}

    return {
        "name": check.get("name", "unnamed"),
        "expect": check.get("expect", "absent"),
        "success": r.returncode == 0,
        "exit_code": r.returncode,
        "stdout_tail": r.stdout[-1500:],
        "stderr_tail": r.stderr[-500:],
    }


def mode_program(args: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    sof_path = args.get("sof_path")
    if not sof_path or not isinstance(sof_path, str):
        raise InvalidArgumentError("sof_path is required (string)")
    cable = args.get("cable_name", "USB-Blaster")
    idx = _coerce_int("device_index", args.get("device_index", 1))
    if not os.path.isfile(sof_path):
        raise InvalidArgumentError(
            f"sof_path not found: {sof_path}", context={"sof_path": sof_path})

    pgm = _require_quartus_pgm()
    op = f"p;{sof_path}@{idx}"
    rc, out, err = run([pgm, "-m", "JTAG", "-c", cable, "-o", op], timeout_s=110)
    if rc == 124:
        raise DeviceTimeoutError(
            "quartus_pgm burn timed out",
            last_seen_output=(out + err)[-1000:],
            context={"sof_path": sof_path, "cable_name": cable})

    success_markers = (
        "Quartus Prime Programmer was successful",
        "Operations done",
    )
    success = (rc == 0) and any(m in out for m in success_markers)
    body: Dict[str, Any] = {
        "success": success,
        "mode": "program",
        "quartus_pgm": pgm,
        "sof_path": sof_path,
        "cable_name": cable,
        "device_index": idx,
        "exit_code": rc,
        "stdout_tail": out[-2000:],
        "stderr_tail": err[-1000:],
    }
    if not success:
        combined = (out + err).lower()
        if "cable" in combined and ("not found" in combined or "no cable" in combined):
            raise DeviceNotFoundError(
                f"quartus_pgm could not find cable '{cable}'",
                last_seen_output=(out + err)[-1000:],
                context={"exit_code": rc, "sof_path": sof_path})
        if "permission" in combined or "access denied" in combined:
            raise PermissionError_(
                "quartus_pgm reports permission denied on USB-Blaster",
                last_seen_output=(out + err)[-1000:],
                context={"exit_code": rc,
                         "hint": "install udev/*-usb-blaster.rules and add user to plugdev"})
        raise DeviceProtocolError(
            f"quartus_pgm did not report success (exit_code={rc})",
            last_seen_output=(out + err)[-1000:],
            context={"exit_code": rc, "sof_path": sof_path})

    scope_checks = args.get("post_burn_scope_checks") or []
    if scope_checks:
        results: List[Dict[str, Any]] = []
        for chk in scope_checks:
            if not isinstance(chk, dict):
                results.append({"success": False,
                                "error": f"check entry is not a dict: {chk!r}"})
                continue
            results.append(_run_post_burn_scope_check(chk))
        body["post_burn_scope_checks"] = results
        failed = [r.get("name", "(unnamed)") for r in results if not r.get("success")]
        if failed:
            body["success"] = False
            body["failed_scope_checks"] = failed
            body["error"] = (
                f"burn wrote the SOF but {len(failed)} post-burn scope "
                f"check(s) failed: {failed} — silicon behaviour does not "
                f"match spec"
            )
            return 1, body
    return 0, body


# ───────────────────────── ADC read mode ─────────────────────────
def mode_adc_read(args: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """Read MAX10 internal 12-bit ADC via JTAG system-console.

    Generates a TCL script that opens a JTAG master, reads the ADC
    controller Avalon-MM registers, averages N samples, and prints
    the result as a parseable line.  Requires an FPGA design with the
    ADC Controller Intel FPGA IP + JTAG-to-Avalon bridge instantiated.
    """
    sc = _require_system_console()
    channel = int(args.get("channel", 0))
    samples = int(args.get("samples", 100))
    ref_mv = int(args.get("reference_mv", 2500))
    base_addr = args.get("adc_base_addr", "0x00000000")

    if not (0 <= channel <= 7):
        raise InvalidArgumentError(
            f"ADC channel must be 0-7, got {channel}",
            context={"channel": channel},
        )
    if samples < 1 or samples > 10000:
        raise InvalidArgumentError(
            f"samples must be 1-10000, got {samples}",
            context={"samples": samples},
        )

    # ADC Controller IP register offsets (from Intel ADC Controller UG):
    #   base+0x00: write channel to start conversion
    #   base+0x00: read returns {valid[31], channel[4:0], data[11:0]}
    tcl_script = f"""\
set masters [get_service_paths master]
if {{[llength $masters] == 0}} {{
    puts "ERROR: no JTAG master found — ensure FPGA has JTAG-to-Avalon bridge"
    exit 1
}}
set m [lindex $masters 0]
open_service master $m

set base {base_addr}
set ch {channel}
set n {samples}
set sum 0
set valid_count 0

for {{set i 0}} {{$i < $n}} {{incr i}} {{
    master_write_32 $m $base $ch
    after 1
    set raw [master_read_32 $m $base 1]
    set val [lindex $raw 0]
    set data_valid [expr {{($val >> 31) & 1}}]
    if {{$data_valid}} {{
        set adc_code [expr {{$val & 0xFFF}}]
        set sum [expr {{$sum + $adc_code}}]
        incr valid_count
    }}
}}

close_service master $m

if {{$valid_count == 0}} {{
    puts "ADC_RESULT: valid=0 avg_code=0 voltage_mv=0 error=no_valid_samples"
}} else {{
    set avg_code [expr {{double($sum) / $valid_count}}]
    set voltage_mv [expr {{$avg_code / 4095.0 * {ref_mv}}}]
    puts [format "ADC_RESULT: valid=%d avg_code=%.2f voltage_mv=%.2f" $valid_count $avg_code $voltage_mv]
}}
"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "programs"))
    import vibeic_temp as tempfile
    tcl_path = os.path.join(tempfile.mkdtemp(prefix="de10_adc_"), "adc_read.tcl")
    with open(tcl_path, "w") as f:
        f.write(tcl_script)

    rc, out, err = run([sc, "--script", tcl_path], timeout_s=30)

    body: Dict[str, Any] = {
        "mode": "adc_read",
        "channel": channel,
        "samples_requested": samples,
        "reference_mv": ref_mv,
        "base_addr": base_addr,
        "system_console": sc,
    }

    if rc == 124:
        raise DeviceTimeoutError(
            "system-console ADC read timed out",
            last_seen_output=(out + err)[-500:],
        )

    result_match = re.search(
        r"ADC_RESULT:\s*valid=(\d+)\s+avg_code=([\d.]+)\s+voltage_mv=([\d.]+)(?:\s+error=(\S+))?",
        out,
    )
    if result_match:
        valid = int(result_match.group(1))
        avg_code = float(result_match.group(2))
        voltage_mv = float(result_match.group(3))
        adc_error = result_match.group(4)

        body["valid_samples"] = valid
        body["avg_code"] = round(avg_code, 2)
        body["voltage_mv"] = round(voltage_mv, 2)

        if adc_error:
            body["success"] = False
            body["error"] = f"ADC read error: {adc_error}"
            return 1, body

        body["success"] = True
        return 0, body

    body["success"] = False
    body["error"] = "failed to parse ADC result from system-console"
    body["stdout_tail"] = out[-500:]
    body["stderr_tail"] = err[-500:]
    return 1, body


# ───────────────────────── CLI scaffolding ─────────────────────────
def load_json_args(spec: Optional[str]) -> Dict[str, Any]:
    if spec is None:
        if not sys.stdin.isatty():
            data = sys.stdin.read().strip()
            return json.loads(data) if data else {}
        return {}
    if spec == "-":
        data = sys.stdin.read().strip()
        return json.loads(data) if data else {}
    return json.loads(spec)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Terasic DE10-Lite (MAX10) FPGA driver (mcp-eda device).",
        epilog="Reads JSON args from stdin or --json-args; emits one JSON object on stdout.",
    )
    ap.add_argument("--mode", choices=["program", "detect", "adc_read"], default="detect",
                    help="Tool mode (matches manifest.json 'tool_mode' field).")
    ap.add_argument("--json-args",
                    help="JSON-encoded args, or '-' to read JSON from stdin.")
    args = ap.parse_args(argv)

    try:
        params = load_json_args(args.json_args)
    except json.JSONDecodeError as e:
        err = InvalidArgumentError(f"invalid JSON args: {e}")
        print(json.dumps(err.as_json_body()))
        return EXIT_FOR_CODE[err.error_code]

    try:
        if args.mode == "detect":
            code, body = mode_detect(params)
        elif args.mode == "program":
            code, body = mode_program(params)
        elif args.mode == "adc_read":
            code, body = mode_adc_read(params)
        else:
            raise InvalidArgumentError(f"unknown mode: {args.mode}")
    except DeviceError as e:
        body = e.as_json_body()
        body["mode"] = args.mode
        print(json.dumps(body))
        return EXIT_FOR_CODE[e.error_code]
    except Exception as e:
        err = DeviceProtocolError(f"{type(e).__name__}: {e}")
        body = err.as_json_body()
        body["mode"] = args.mode
        print(json.dumps(body))
        return EXIT_FOR_CODE[err.error_code]

    print(json.dumps(body))
    return code


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
