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
    DeviceBusyError,
    InvalidArgumentError,
    EXIT_FOR_CODE,
)


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
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        return 124, e.stdout or "", (e.stderr or "") + f"\n[timeout after {timeout_s}s]"
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
        r = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return {"name": check.get("name", "unnamed"),
                "success": False,
                "error": f"scope check timeout {timeout_s}s"}

    return {
        "name": check.get("name", "unnamed"),
        "expect": check.get("expect", "absent"),
        "success": r.returncode == 0,
        "exit_code": r.returncode,
        "stdout_tail": r.stdout[-1500:],
        "stderr_tail": r.stderr[-500:],
    }


def _run_rtl_precheck_gate(
    rtl_dir: str, l12_json: Optional[str] = None, timeout_s: int = 180,
) -> Tuple[int, Dict[str, Any]]:
    """v0.66: run the aggregated RTL auditor gate BEFORE burning.

    Looks up `rtl_precheck_gate.py` in the plugin's vibe-ic-d/programs/
    directory. The plugin is installed alongside mcp-eda in the
    AI_IC_design tree; we honour an explicit VIBE_IC_D_PROGRAMS_DIR env
    var for other layouts.

    Returns (exit_code, parsed_report_dict). The dict carries
    overall_pass + per-auditor results so the caller can surface them
    in its own JSON response.
    """
    gate_py = _find_plugin_program("rtl_precheck_gate.py")
    if gate_py is None:
        return -1, {
            "precheck_error": "rtl_precheck_gate.py not found",
            "hint": "set VIBE_IC_D_PROGRAMS_DIR to the plugin's programs/ dir",
        }
    argv = [sys.executable, gate_py, "--rtl-dir", rtl_dir]
    if l12_json and os.path.isfile(l12_json):
        argv += ["--l12-json", l12_json]
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return -2, {"precheck_error": f"gate timeout {timeout_s}s"}
    try:
        report = json.loads(r.stdout)
    except json.JSONDecodeError:
        report = {"precheck_error": "gate produced non-JSON stdout",
                  "stdout_tail": r.stdout[-1500:],
                  "stderr_tail": r.stderr[-500:]}
    return r.returncode, report


#: Directories that BELONG TO EVERYONE, so a marker found in one is evidence
#: about somebody else's litter, never about this SOF's project. `$HOME` and
#: `/` are here for the same reason: they are shared by every project the user
#: owns, so "a project root" is precisely what they cannot be.
_SHARED_ROOTS = ("/tmp", "/var/tmp", "/dev/shm", "/usr", "/var", "/etc", "/")


def _is_shared_directory(path: str) -> bool:
    """True when `path` is a directory no single project can own.

    WHY THIS EXISTS. `_resolve_project_root_from_sof` scores a directory by
    whether it CONTAINS a name like `input/`, `rtl/` or `waivers.json`. That is
    a proxy for "this is a project root", and in a shared directory the proxy
    fires without the property: measured on this machine, a stray
    `/tmp/waivers.json` left by an unrelated run in July made the resolver
    return `/tmp` for a SOF anywhere under it, so the pre-burn
    flow_compliance audit ran against `/tmp` as though it were the user's
    project.

    That is not only a test artefact -- it is what a user gets when they burn a
    SOF from a scratch directory. And because the litter is per-machine, the
    resulting failure is per-machine too: the same commit is green on a host
    with a clean `/tmp` and red on one without, which is the worst shape a
    check can have, because neither result is reproducible from the tree.
    """
    real = os.path.realpath(path)
    home = os.path.realpath(os.path.expanduser("~"))
    if real == home:
        return True
    for shared in _SHARED_ROOTS:
        if real == os.path.realpath(shared):
            return True
    return False


def _resolve_project_root_from_sof(sof_path: str) -> Optional[str]:
    """Wave 20 (v0.119.52) helper: walk up from a SOF to the project
    root.

    Heuristic: SOF is normally under
        <project>/fpga/output_files/<top>.sof
    or
        <project>/fpga/<top>.sof

    Walk up looking for a directory that contains any of:
      - generated_docs/   (Phase 1 artefacts)
      - rtl/              (RTL sources)
      - input/            (Phase 1 inputs)
      - waivers.json
      - phase23_completion_audit.json

    Cap walk at 6 levels. Returns absolute project path or None when
    no match.
    """
    if not sof_path:
        return None
    cur = os.path.abspath(sof_path)
    # Walk up to 8 levels collecting candidate roots. Prefer the
    # candidate with the strongest evidence (matches the most hints) —
    # this avoids picking up a sub-stage like phase2/stage1/ that only
    # has rtl/, when the canonical project root above has input/ +
    # generated_docs/.
    candidates: list[tuple[int, str]] = []
    for _ in range(8):
        cur = os.path.dirname(cur)
        if not cur or cur == "/":
            break
        score = 0
        # high-priority hints (canonical project root markers)
        for hint in ("input", "generated_docs", "waivers.json"):
            if os.path.exists(os.path.join(cur, hint)):
                score += 2
        # weaker hints
        for hint in ("rtl", "phase23_completion_audit.json", "phase2", "phase3"):
            if os.path.exists(os.path.join(cur, hint)):
                score += 1
        if score > 0 and not _is_shared_directory(cur):
            candidates.append((score, cur))
    if not candidates:
        return None
    # pick highest-scoring candidate (ties broken by deepest, i.e. closest to SOF)
    candidates.sort(key=lambda x: (-x[0], -len(x[1])))
    return candidates[0][1]


def _run_flow_compliance_pre_burn(
    project_root: str, timeout_s: int = 180,
) -> Tuple[int, Dict[str, Any]]:
    """Wave 20 (v0.119.52) / Wave 21 (v0.119.53): run
    flow_compliance_check.py --phase 2 --strict-structural before
    burning.

    Wave 21 scope correction: --strict-structural decides the verdict
    SOLELY on structural-RTL gates (chip-AGNOSTIC pattern checkers).
    Step-level gates that need real EDA tool harnesses (lint coverage,
    CDC report, Verilator coverage, SymbiYosys formal proof, post-
    route STA, etc.) are REPORTED separately as informational warnings
    and do NOT block the burn.

    Returns (exit_code, parsed_report_dict). exit_code 0 = PASS / safe
    to burn (also covers PASS_WITH_WAIVERS); >0 = FAIL → reject burn.
    Negative codes = the gate itself could not run (treated as
    diagnostic, not an automatic block, so legacy callers / projects
    without flow_compliance still work).

    The returned dict carries:
      flow_compliance_verdict: "PASS"|"PASS_WITH_WAIVERS"|"FAIL"|"UNKNOWN"
      failed_gates:            list of structural-RTL gate names that FAILed
      step_level_warnings:     list of step-level gate FAIL/MISSING lines
                               (informational only — surfaced as warnings
                               in the burn response but not blocking)
      exit_code, stdout_tail, stderr_tail, command
    """
    gate_py = _find_plugin_program("flow_compliance_check.py")
    if gate_py is None:
        return -1, {
            "flow_compliance_error":
                "flow_compliance_check.py not found",
            "hint": "set VIBE_IC_D_PROGRAMS_DIR to the plugin's "
                    "programs/ dir",
        }
    # v0.114.1 (issue #32) — forward --allow-thin-input unconditionally.
    # Safe because the plugin's --allow-thin-input flag is itself gated by
    # the v1.6.98 coverage-shape predicate (eligible iff input docs have
    # genuine thin-input shape). Thick-input projects hitting the same
    # gates STAY FAIL even with the flag set, so passing it here cannot
    # weaken the burn-block for normal projects — it just stops the
    # pre-burn audit from blocking burns on legitimate thin-input
    # WAIVED-DEFERRED gates (ticket=thin-input-v1.6.97).
    argv = [
        sys.executable, gate_py, project_root,
        "--phase", "2", "--strict-structural",
        "--allow-thin-input",
    ]
    # v1.6.145 (#57) — pre-burn audit IS the FPGA prototype stage gate.
    # Set PHASE23_ANALOG_FPGA_STUB=1 in the subprocess env so the 5
    # analog / mixed-signal gates wired in v1.6.144 plus the
    # send_test_active_drive_check (v1.6.145) downgrade missing-per-
    # block-artifact FAILs to PASS_WITH_WAIVERS. The driver already
    # accepts the aggregated `PASS_WITH_WAIVERS` verdict (line ~800,
    # Wave 30 contract). Tapeout signoff does NOT go through this
    # function so the same gates remain strict for foundry handoff.
    env = dict(os.environ)
    env["PHASE23_ANALOG_FPGA_STUB"] = "1"
    try:
        r = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout_s,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return -2, {
            "flow_compliance_error": f"audit timeout {timeout_s}s",
        }

    out_text = (r.stdout or "") + "\n" + (r.stderr or "")

    # Wave 30 (v0.119.62, mcp-eda v0.99.8) — primary signal is the
    # canonical JSON artifact emitted by flow_compliance_check itself
    # at `<project>/reports/phase23_completion_audit.json`. Stdout
    # regex parsing is retained as a backup but no longer authoritative.
    # Replaces the brittle parser at this site that produced
    # `failed_gates=[]` for 14 real structural FAILs in v0.119.61
    # (35th-attempt root cause) by stripping line whitespace and then
    # requiring a leading delimiter that no longer existed.
    verdict = "UNKNOWN"
    failed_gates: List[str] = []
    step_level_warnings: List[str] = []
    # Canonical path (v1.6.27+ — emitted by flow_compliance_check via
    # _path_layout's auto-router into `reports/audit/`). Legacy path
    # (`reports/phase23_completion_audit.json`) is retained as fallback
    # for older project trees that still hold the artefact at the root
    # of `reports/`.
    canonical_audit_path = os.path.join(
        project_root, "reports", "audit", "phase23_completion_audit.json")
    legacy_audit_path = os.path.join(
        project_root, "reports", "phase23_completion_audit.json")
    if os.path.isfile(canonical_audit_path):
        audit_json_path = canonical_audit_path
    else:
        audit_json_path = legacy_audit_path
    audit_json_present = os.path.isfile(audit_json_path)
    audit_json_data: Optional[Dict[str, Any]] = None
    audit_json_error: Optional[str] = None

    if audit_json_present:
        try:
            with open(audit_json_path, "r", encoding="utf-8") as f:
                audit_json_data = json.load(f)
            if isinstance(audit_json_data, dict):
                v = audit_json_data.get("verdict")
                if isinstance(v, str):
                    verdict = v.upper()
                gates_list = audit_json_data.get("failed_gates") or []
                if isinstance(gates_list, list):
                    failed_gates = [str(g) for g in gates_list
                                    if isinstance(g, str)]
                slw_list = audit_json_data.get(
                    "step_artifact_fail_lines") or []
                if isinstance(slw_list, list):
                    step_level_warnings = [str(s) for s in slw_list
                                           if isinstance(s, str)]
        except Exception as e:
            audit_json_error = str(e)

    # Backup: stdout-regex parser (chip-AGNOSTIC, robust to whitespace
    # and em-dash separators). Only used if the JSON artifact is
    # absent or malformed. We still fail closed downstream when the
    # audit JSON is missing — this branch only refines diagnostics.
    if verdict == "UNKNOWN":
        if "Overall: PASS_WITH_WAIVERS" in out_text:
            verdict = "PASS_WITH_WAIVERS"
        elif "Overall: PASS" in out_text:
            verdict = "PASS"
        elif "Overall: FAIL" in out_text:
            verdict = "FAIL"

    if not failed_gates:
        # Robust regex: matches `<gate_name>_check` anywhere on a line
        # followed by a separator (em-dash, hyphen, colon) and a FAIL
        # / ERROR token. Does not depend on leading whitespace
        # delimiters — closes the v0.119.61 35th-attempt parsing hole.
        seen: set = set()
        for line in out_text.splitlines():
            m = re.search(
                r"\b(\w+_check)\b\s*[—\-:]\s*(?:\[)?(FAIL|ERROR)\b",
                line)
            if m and m.group(1) not in seen:
                failed_gates.append(m.group(1))
                seen.add(m.group(1))
        # Also harvest the explicit listing block as a third fallback.
        in_struct = False
        for line in out_text.splitlines():
            if ("structural gates FAILed" in line
                    or "strict-structural mode" in line):
                in_struct = True
                continue
            if in_struct:
                stripped = line.strip()
                if not stripped:
                    in_struct = False
                    continue
                m2 = re.search(r"\b(\w+_check)\b", stripped)
                if m2 and m2.group(1) not in seen:
                    failed_gates.append(m2.group(1))
                    seen.add(m2.group(1))

    if not step_level_warnings:
        in_step = False
        for line in out_text.splitlines():
            if ("Step-level gates (informational" in line
                    or "strict-step-artifacts mode" in line):
                in_step = True
                continue
            if in_step:
                stripped = line.strip()
                if not stripped:
                    in_step = False
                    continue
                if "Use --strict-step-artifacts" in stripped:
                    in_step = False
                    continue
                if stripped.startswith(("•", "-")):
                    step_level_warnings.append(stripped.lstrip("•- "))

    return r.returncode, {
        "flow_compliance_verdict": verdict,
        "exit_code": r.returncode,
        "failed_gates": failed_gates,
        "step_level_warnings": step_level_warnings,
        "audit_json_present": audit_json_present,
        "audit_json_path": audit_json_path,
        "audit_json_error": audit_json_error,
        "stdout_tail": (r.stdout or "")[-2500:],
        "stderr_tail": (r.stderr or "")[-500:],
        "command": argv[1:],
    }


def mode_program(args: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    sof_path = args.get("sof_path")
    if not sof_path or not isinstance(sof_path, str):
        raise InvalidArgumentError("sof_path is required (string)")
    cable = args.get("cable_name", "USB-Blaster")
    idx = _coerce_int("device_index", args.get("device_index", 1))

    # v0.66: pre-burn RTL static-auditor gate runs BEFORE sof existence
    # check — a buggy RTL tree should fail loud even if the caller also
    # made a typo in sof_path. Burn-blocking engineering errors beat
    # tool-misuse errors for priority.
    rtl_dir = args.get("rtl_dir")
    l12_json = args.get("l12_json")
    allow_known_bugs = bool(args.get("allow_known_bugs", False))
    skip_precheck = bool(args.get("skip_rtl_precheck", False))
    # v0.99.3: per-auditor waiver list. Caller may waive specific
    # auditor names (e.g. ["pulse_decoder_edge_check",
    # "fsm_error_invariant"]) while keeping the rest gating. Replaces
    # the all-or-nothing `allow_known_bugs=true` override for projects
    # where one auditor is known to false-flag but the other 5 still
    # need to gate.
    waive_auditors = args.get("waive_auditors") or []
    if not isinstance(waive_auditors, list):
        raise InvalidArgumentError(
            "waive_auditors must be a list of auditor name strings",
            context={"got": type(waive_auditors).__name__},
        )
    waive_auditors = {str(a).strip() for a in waive_auditors if str(a).strip()}

    precheck_report: Optional[Dict[str, Any]] = None
    if skip_precheck:
        precheck_report = {"skipped": True,
                           "reason": "skip_rtl_precheck=true"}
    elif not rtl_dir:
        precheck_report = {"skipped": True,
                           "reason": "rtl_dir not supplied — auditors not run"}
    elif not os.path.isdir(rtl_dir):
        raise InvalidArgumentError(
            f"rtl_dir not a directory: {rtl_dir}",
            context={"rtl_dir": rtl_dir},
        )
    else:
        gate_rc, gate_report = _run_rtl_precheck_gate(rtl_dir, l12_json)
        precheck_report = gate_report
        if gate_rc < 0:
            # Gate itself failed to run (missing / timeout / parse error).
            # Fail closed unless --allow-known-bugs.
            if not allow_known_bugs:
                raise VendorToolNotFoundError(
                    "rtl_precheck_gate could not run",
                    context={"rtl_precheck": precheck_report,
                             "hint": "set VIBE_IC_D_PROGRAMS_DIR or pass "
                                     "skip_rtl_precheck=true if SOF is pre-built"},
                )
        elif gate_rc != 0:
            # Gate ran and reported FAIL. Hard-block unless override.
            failed_audit_names = [
                a["name"] for a in precheck_report.get("auditors", [])
                if not a.get("passed", True)
            ]
            # v0.99.3: per-auditor waiver — if EVERY failing auditor
            # is in waive_auditors, treat as PASS-WITH-WAIVER. Anything
            # outside the waive set still hard-blocks.
            unwaived = [n for n in failed_audit_names
                        if n not in waive_auditors]
            if waive_auditors and not unwaived:
                # All failures waived — record + continue.
                precheck_report["waived_auditors"] = sorted(
                    set(failed_audit_names) & waive_auditors)
                precheck_report["status"] = "PASS_WITH_WAIVER"
            elif not allow_known_bugs:
                return 1, {
                    "success": False,
                    "error": "rtl_precheck_gate FAIL — refusing to burn",
                    "error_code": "precheck_failed",
                    "recoverable": False,
                    "last_seen_output": "",
                    "context": {
                        "failed_auditors": failed_audit_names,
                        "unwaived_failures": unwaived,
                        "waive_auditors_hint": (
                            "pass `waive_auditors=[\"<name>\", ...]` to "
                            "selectively waive specific auditors, OR "
                            "allow_known_bugs=true for blanket override"),
                        "rtl_precheck": precheck_report,
                        "hint": "fix the offending RTL pattern, OR waive "
                                "specific auditors with rationale in your "
                                "provenance notes.",
                    },
                }

    # Wave 20 (v0.119.52) — pre-burn flow_compliance RTL repair guard.
    #
    # Even when rtl_precheck_gate passes, agents have historically
    # silently burned a SOF while structural-RTL gates were FAILing
    # (e.g. 25th attempt: 12 unaddressed structural gate FAILs +
    # `bypass: true` mentality). Hard-block this by re-running
    #     flow_compliance_check.py <project> --phase 2 --strict-structural
    # before quartus_pgm. Caller may bypass intentionally with
    # `bypass_pre_burn_check=true` for emergency / manual debug
    # (e.g. burning a known-PASS oracle SOF whose project tree is
    # not on this host).
    bypass_pre_burn = bool(args.get("bypass_pre_burn_check", False))
    flow_report: Optional[Dict[str, Any]] = None
    if bypass_pre_burn:
        flow_report = {
            "skipped": True,
            "reason": "bypass_pre_burn_check=true (emergency override)",
        }
        print(
            "WARNING: pre-burn flow_compliance check bypassed by "
            "caller (bypass_pre_burn_check=true). Burning without "
            "structural-gate audit.",
            file=sys.stderr,
        )
    else:
        project_root = _resolve_project_root_from_sof(sof_path)
        if project_root is None:
            flow_report = {
                "skipped": True,
                "reason": (
                    "could not resolve project root from sof_path "
                    f"{sof_path!r} — no generated_docs/ / rtl/ / input/ "
                    "/ waivers.json found within 6 parent levels. "
                    "Pre-burn flow_compliance audit cannot run. Set "
                    "bypass_pre_burn_check=true to proceed anyway."
                ),
            }
        else:
            fc_rc, flow_report = _run_flow_compliance_pre_burn(
                project_root)
            flow_report["project_root"] = project_root
            verdict = flow_report.get("flow_compliance_verdict",
                                      "UNKNOWN")
            failed_gates = flow_report.get("failed_gates", [])
            step_level_warnings = flow_report.get(
                "step_level_warnings", [])
            audit_json_present = bool(
                flow_report.get("audit_json_present", False))

            # Wave 30 (v0.119.62, mcp-eda v0.99.8) — fail-closed
            # semantic. PASS / PASS_WITH_WAIVERS allow; everything
            # else blocks regardless of the parsed `failed_gates`
            # list. The previous "soft_skip" path at verdict=FAIL +
            # failed_gates=[] was the v0.119.61 35th-attempt root-
            # cause hole: the regex parser stripped leading whitespace
            # then required a leading delimiter that no longer
            # existed, so 14 real FAILs were parsed as 0 and the burn
            # was allowed under a "step-level only" rationale.
            if fc_rc < 0:
                # Gate itself could not run (subprocess timeout / not
                # found) — fail closed.
                return 1, {
                    "ok": False,
                    "success": False,
                    "error": "BURN_BLOCKED_PRE_BURN_AUDIT_UNAVAILABLE",
                    "error_code": "burn_blocked_pre_burn_audit_unavailable",
                    "recoverable": False,
                    "message": (
                        "Pre-burn flow_compliance audit could not "
                        f"run (rc={fc_rc}). Wave 30 fail-closed "
                        "policy blocks the burn. Set "
                        "VIBE_IC_D_PROGRAMS_DIR or pass "
                        "bypass_pre_burn_check=true for emergency "
                        "/ oracle SOF burns from foreign project "
                        "trees."
                    ),
                    "flow_compliance": flow_report,
                    "rtl_precheck": precheck_report,
                }
            if verdict in ("PASS", "PASS_WITH_WAIVERS"):
                # Allow. PASS_WITH_WAIVERS surfaces as a warning
                # downstream via the existing step_level_warnings
                # path.
                pass
            else:
                # verdict in ("FAIL", "UNKNOWN", "ERROR") — block.
                # Even an empty failed_gates list still blocks: that
                # is the canonical "verdict-parsing-unable-to-extract-
                # gates" case which previously soft-skipped.
                if not audit_json_present:
                    msg = (
                        "Pre-burn audit JSON missing at "
                        f"{flow_report.get('audit_json_path')!r}. "
                        "phase23_completion_audit.json was not "
                        "emitted by flow_compliance_check.py — agent "
                        "did not run the Phase 2+3 self-audit. Wave "
                        "30 fail-closed policy blocks the burn. Run "
                        "flow_compliance_check.py --phase 2 "
                        "--strict-structural in the project root."
                    )
                    error_code = "burn_blocked_audit_json_missing"
                elif failed_gates:
                    msg = (
                        "Pre-burn structural-gate audit FAILed for "
                        f"project {project_root!r}. "
                        f"{len(failed_gates)} structural-RTL gate(s) "
                        "failing. Run flow_compliance_check.py with "
                        "--strict-structural and converge RTL repair/retry loop "
                        "before re-attempting burn. To override "
                        "intentionally pass bypass_pre_burn_check=true."
                    )
                    error_code = "burn_blocked_structural_gates_fail"
                else:
                    msg = (
                        f"Pre-burn audit verdict={verdict!r} but no "
                        "structural-RTL gates extracted from output. "
                        "verdict_parsing_unable_to_extract_gates — "
                        "fail closed (Wave 30). Inspect the attached "
                        "stdout_tail / phase23_completion_audit.json "
                        "and fix the underlying gate before retrying."
                    )
                    error_code = "burn_blocked_verdict_fail_no_gates"
                return 1, {
                    "ok": False,
                    "success": False,
                    "error": "BURN_BLOCKED_STRUCTURAL_GATES_FAIL",
                    "error_code": error_code,
                    "recoverable": False,
                    "message": msg,
                    "failed_gates": failed_gates,
                    "step_level_warnings": step_level_warnings,
                    "flow_compliance": flow_report,
                    "rtl_precheck": precheck_report,
                }

    # Now safe to check SOF existence — gate already cleared this RTL.
    if not os.path.isfile(sof_path):
        raise InvalidArgumentError(
            f"sof_path not found: {sof_path}",
            context={"sof_path": sof_path, "rtl_precheck": precheck_report},
        )

    pgm = _require_quartus_pgm()
    op = f"p;{sof_path}@{idx}"
    rc, out, err = run([pgm, "-m", "JTAG", "-c", cable, "-o", op], timeout_s=110)

    if rc == 124:
        raise DeviceTimeoutError(
            "quartus_pgm burn timed out",
            last_seen_output=(out + err)[-1000:],
            context={"sof_path": sof_path, "cable_name": cable,
                     "rtl_precheck": precheck_report},
        )

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
        "rtl_precheck": precheck_report,
        "flow_compliance": flow_report,
    }

    # Wave 33 (mcp-eda v0.99.9): on success, write
    # `<project>/reports/burn_provenance.json` with the audit-JSON
    # SHA, verdict, and SOF SHA. Gives RESULT.md a verifiable
    # citation source and lets future forensics distinguish guarded
    # vs unguarded burns trivially.
    burn_provenance_path: Optional[str] = None
    if success and isinstance(flow_report, dict):
        proj_root = flow_report.get("project_root")
        audit_json_path_str = flow_report.get("audit_json_path")
        if proj_root and os.path.isdir(proj_root):
            try:
                import hashlib
                from datetime import datetime, timezone

                def _sha256_of(path: Optional[str]) -> Optional[str]:
                    if not path or not os.path.isfile(path):
                        return None
                    h = hashlib.sha256()
                    with open(path, "rb") as f:
                        for chunk in iter(lambda: f.read(65536), b""):
                            h.update(chunk)
                    return f"sha256:{h.hexdigest()}"

                reports_dir = os.path.join(proj_root, "reports")
                os.makedirs(reports_dir, exist_ok=True)
                burn_provenance_path = os.path.join(
                    reports_dir, "burn_provenance.json")
                provenance = {
                    "burn_at": datetime.now(timezone.utc).isoformat(),
                    "sof_path": sof_path,
                    "sof_sha256": _sha256_of(sof_path),
                    "audit_json_path": audit_json_path_str,
                    "audit_sha256": _sha256_of(audit_json_path_str),
                    "audit_verdict": flow_report.get(
                        "flow_compliance_verdict", "UNKNOWN"),
                    "guard_invoked": True,
                    "tool": "device_fpga_de10lite_program",
                }
                with open(burn_provenance_path, "w",
                          encoding="utf-8") as f:
                    json.dump(provenance, f, indent=2)
                body["burn_provenance_path"] = burn_provenance_path
                body["burn_provenance"] = provenance
            except Exception as e:
                body["burn_provenance_error"] = str(e)
    # Wave 21: surface step-level gate FAIL/MISSING as informational
    # warnings on the burn response. These do NOT block the burn but
    # let the operator see what real-EDA-tool artefacts are missing
    # (lint coverage, CDC, Verilator coverage, formal proof, etc.).
    if isinstance(flow_report, dict):
        slw = flow_report.get("step_level_warnings") or []
        if slw:
            body["warnings"] = body.get("warnings", []) + [
                {
                    "kind": "step_level_artifact_missing",
                    "summary": (
                        f"{len(slw)} step-level gate(s) reported "
                        "FAIL/MISSING — informational, did NOT block "
                        "burn. Use --strict-step-artifacts in "
                        "flow_compliance_check.py for tape-out-ready "
                        "audit."
                    ),
                    "entries": slw,
                }
            ]
    if not success:
        # quartus_pgm returned something (not a missing-tool error) but
        # didn't report success. Could be cable unplugged
        # (device_not_found) or a real protocol error. Map by heuristic.
        combined = (out + err).lower()
        if "cable" in combined and ("not found" in combined or "no cable" in combined):
            raise DeviceNotFoundError(
                f"quartus_pgm could not find cable '{cable}'",
                last_seen_output=(out + err)[-1000:],
                context={"exit_code": rc, "sof_path": sof_path,
                         "rtl_precheck": precheck_report},
            )
        if "permission" in combined or "access denied" in combined:
            raise PermissionError_(
                "quartus_pgm reports permission denied on USB-Blaster",
                last_seen_output=(out + err)[-1000:],
                context={"exit_code": rc,
                         "hint": "install udev/*-usb-blaster.rules and add user to plugdev",
                         "rtl_precheck": precheck_report},
            )
        raise DeviceProtocolError(
            f"quartus_pgm did not report success (exit_code={rc})",
            last_seen_output=(out + err)[-1000:],
            context={"exit_code": rc, "sof_path": sof_path,
                     "rtl_precheck": precheck_report},
        )

    # v0.66: post-burn silicon attestation via scope.
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
    import tempfile
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
    sys.exit(main())
