#!/usr/bin/env python3
"""
tester_oracle_health_check.py — Prove the tester works before iterating RTL.

Source (v052 fresh-agent debugging lesson)
-------------------------------------------
Multiple v0.45-v0.51 iteration cycles burned on a broken HID test box that
returned the same byte for any RTL. The debug team kept re-spinning RTL
variants while the real bug was in the tester itself. This gate enforces:

    Before entering an RTL-fix loop that chases a hardware FAIL, you must
    burn a known-good SOF onto the FPGA and confirm the tester oracle
    returns its advertised PASS fingerprint. If it does not, STOP —
    fixing RTL is futile until the oracle is healthy.

This program is IC-agnostic: it is parameterised by a JSON config that
names the known-good SOF, the burn command, the tester command, and the
expected PASS / FAIL regex fingerprints.

Config schema (``oracle.json``)
-------------------------------
All 5 top-level keys are REQUIRED::

    {
      "known_good_sof": "path/to/known_good.sof",
      "burn_command": "quartus_pgm -m JTAG -c USB-Blaster -o p;{sof}@1",
      "tester_command": "python3 tools/hid_tester.py --send TEST",
      "pass_fingerprint": "byte\\\\[6\\\\]=0xF2",
      "fail_fingerprint": "byte\\\\[6\\\\]=0x02",
      "timeout_seconds": 30
    }

``burn_command`` may contain the ``{sof}`` placeholder which is filled
with the value of ``known_good_sof`` using str.format. Both commands are
tokenised with ``shlex.split`` and executed with ``shell=False``.

Usage
-----
    tester_oracle_health_check.py --config oracle.json
    tester_oracle_health_check.py --config oracle.json --json out.json
    tester_oracle_health_check.py --config oracle.json --dry-run

Exit codes
----------
    0 = oracle healthy (tester returned PASS fingerprint on known-good SOF)
    1 = oracle broken or returned unexpected output
    2 = config missing / invalid / IO error
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _watchdog                                        # noqa: E402
import _progress_run as _pr  # noqa: E402  — only exit_undetermined_on_stall(),
# the main-entry stall-to-rc2 wrapper main has no equivalent for; run_cmd()
# itself is fully on `_watchdog` (this file's own `Stalled`, not `_pr.Stalled`).


REQUIRED_KEYS = (
    "known_good_sof",
    "burn_command",
    "tester_command",
    "pass_fingerprint",
    "fail_fingerprint",
)


@dataclass
class Finding:
    severity: str       # ERROR, WARNING, INFO, PASS
    category: str       # CONFIG_MISSING, CONFIG_INVALID, BURN_FAIL, TESTER_FAIL, ORACLE_PASS, ORACLE_BROKEN, UNKNOWN_RESPONSE
    message: str
    details: str = ""
    extras: dict = field(default_factory=dict)


def load_config(path: Path) -> tuple[Optional[dict], List[Finding]]:
    findings: List[Finding] = []
    if not path.exists():
        findings.append(Finding(
            severity="ERROR",
            category="CONFIG_MISSING",
            message=f"Config file does not exist: {path}",
        ))
        return None, findings
    try:
        data = json.loads(path.read_text(errors="replace"))
    except json.JSONDecodeError as e:
        findings.append(Finding(
            severity="ERROR",
            category="CONFIG_INVALID",
            message=f"Config file is not valid JSON: {e}",
            details=str(path),
        ))
        return None, findings
    if not isinstance(data, dict):
        findings.append(Finding(
            severity="ERROR",
            category="CONFIG_INVALID",
            message="Config root is not a JSON object",
        ))
        return None, findings
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        findings.append(Finding(
            severity="ERROR",
            category="CONFIG_INVALID",
            message=f"Config missing required key(s): {', '.join(missing)}",
            details=f"required = {list(REQUIRED_KEYS)}",
        ))
        return None, findings
    return data, findings


#: What `run_cmd` raises when the job made NO FORWARD PROGRESS. Distinct from
#: `subprocess.TimeoutExpired`, and the distinction is the point: the old bound
#: fired on "it has been N seconds", which is a different question from "is it
#: working". A burn tool writing to a board over a slow link, or a tester
#: waiting on a device that is answering, is PROGRESSING and must run to
#: completion however long that legitimately takes.
class Stalled(RuntimeError):
    """The job was alive and produced nothing — no output, no CPU — for the
    whole grace. That is a wedged tool, and unlike a timeout it is a MEASURED
    statement about the tool rather than about the host's load."""


def run_cmd(cmd_str: str, timeout: int) -> tuple[int, str, str]:
    """Run a shell-style command with shell=False. Returns (rc, stdout, stderr).

    SUPERVISED BY PROGRESS, not by a wall clock. `timeout` is no longer "how
    long may this take" — it is the STALL GRACE, "how long may this be silent
    AND idle before we call it hung". Any of stdout/stderr growing or the
    process burning CPU resets it, so a job that is doing something is never
    killed; a job doing nothing at all for the grace raises `Stalled`.

    THE CALLER'S NUMBER IS HONOURED AS GIVEN — no floor is imposed on it. An
    earlier draft of this function floored the grace at a measured process
    launch cost, on the theory that a grace under the boot cost kills the child
    during startup. That is the same defect v1.12.22 removed from
    `design_one_shot_runner._run`: a floor silently overrides a caller that
    declared a short bound and meant it, and the reason it is not needed is
    that `run_host_supervised` DERIVES the poll cadence as a quarter of the
    grace, so the job is looked at several times over whatever grace it was
    given. Startup is also not silent to the probe — the interpreter burns CPU
    before it prints anything, and the CPU reading is what keeps it alive.

    `run_host_supervised` rather than a hand-rolled `run_supervised`: it is the
    canonical host primitive and already injects the whole-process-TREE /proc
    reading. The bespoke probe this replaced read only the direct child, so a
    burn tool that forks its real work was invisible to it.
    """
    tokens = shlex.split(cmd_str)
    if not tokens:
        raise ValueError("empty command")
    res = _watchdog.run_host_supervised(tokens, stall_grace_s=float(timeout))
    if res.outcome in ("stalled", "ceiling"):
        raise Stalled(
            f"`{cmd_str}` produced no output and used no CPU for "
            f"{res.elapsed_s:.0f}s and was stopped. It was not slow — it was "
            f"doing nothing.")
    return res.rc, res.out or "", res.err or ""


def check_oracle(config: dict, dry_run: bool = False) -> tuple[List[Finding], dict]:
    findings: List[Finding] = []
    report_extras: dict = {}

    sof_path = config["known_good_sof"]
    burn_cmd_template = config["burn_command"]
    tester_cmd = config["tester_command"]
    pass_re = config["pass_fingerprint"]
    fail_re = config["fail_fingerprint"]
    timeout = int(config.get("timeout_seconds", 30))

    # Format burn_command with {sof}
    try:
        burn_cmd = burn_cmd_template.format(sof=sof_path)
    except (KeyError, IndexError) as e:
        findings.append(Finding(
            severity="ERROR",
            category="CONFIG_INVALID",
            message=f"burn_command placeholder error: {e}",
            details=burn_cmd_template,
        ))
        return findings, report_extras

    report_extras["burn_command_resolved"] = burn_cmd
    report_extras["tester_command"] = tester_cmd
    report_extras["timeout_seconds"] = timeout

    if dry_run:
        findings.append(Finding(
            severity="INFO",
            category="ORACLE_PASS",
            message="dry-run: config validated, subprocesses not executed",
        ))
        return findings, report_extras

    # Burn SOF
    try:
        rc, out, err = run_cmd(burn_cmd, timeout)
    except FileNotFoundError as e:
        findings.append(Finding(
            severity="ERROR",
            category="BURN_FAIL",
            message=f"burn_command executable not found: {e}",
            details=burn_cmd,
        ))
        return findings, report_extras
    except Stalled as exc:
        # STILL AN ERROR, and deliberately so: this gate's subject IS "does the
        # burn/test path work", and a burn command that is alive and doing
        # nothing is a broken one. What changed is that this is now reached only
        # when nothing moved at all — the old message, "timed out after Ns",
        # was equally reachable by a correct tool on a loaded host, and said the
        # ORACLE was broken about a fact concerning the machine.
        findings.append(Finding(
            severity="ERROR",
            category="BURN_FAIL",
            message=f"burn_command made no forward progress: {exc}",
            details=burn_cmd,
        ))
        return findings, report_extras
    except Exception as e:
        findings.append(Finding(
            severity="ERROR",
            category="BURN_FAIL",
            message=f"burn_command raised exception: {e}",
            details=burn_cmd,
        ))
        return findings, report_extras

    report_extras["burn_returncode"] = rc
    if rc != 0:
        findings.append(Finding(
            severity="ERROR",
            category="BURN_FAIL",
            message=f"burn_command returned non-zero exit {rc}",
            details=(err or out)[:500],
        ))
        return findings, report_extras

    # Run tester
    try:
        rc_t, out_t, err_t = run_cmd(tester_cmd, timeout)
    except FileNotFoundError as e:
        findings.append(Finding(
            severity="ERROR",
            category="TESTER_FAIL",
            message=f"tester_command executable not found: {e}",
            details=tester_cmd,
        ))
        return findings, report_extras
    except Stalled as exc:
        # Same correction as the burn arm above.
        findings.append(Finding(
            severity="ERROR",
            category="TESTER_FAIL",
            message=f"tester_command made no forward progress: {exc}",
            details=tester_cmd,
        ))
        return findings, report_extras
    except Exception as e:
        findings.append(Finding(
            severity="ERROR",
            category="TESTER_FAIL",
            message=f"tester_command raised exception: {e}",
            details=tester_cmd,
        ))
        return findings, report_extras

    report_extras["tester_returncode"] = rc_t
    combined = (out_t or "") + "\n" + (err_t or "")
    report_extras["tester_stdout_head"] = (out_t or "")[:500]

    try:
        pass_hit = re.search(pass_re, combined) is not None
    except re.error as e:
        findings.append(Finding(
            severity="ERROR",
            category="CONFIG_INVALID",
            message=f"pass_fingerprint is not a valid regex: {e}",
            details=pass_re,
        ))
        return findings, report_extras
    try:
        fail_hit = re.search(fail_re, combined) is not None
    except re.error as e:
        findings.append(Finding(
            severity="ERROR",
            category="CONFIG_INVALID",
            message=f"fail_fingerprint is not a valid regex: {e}",
            details=fail_re,
        ))
        return findings, report_extras

    if pass_hit:
        findings.append(Finding(
            severity="PASS",
            category="ORACLE_PASS",
            message="oracle returned PASS fingerprint on known-good SOF",
            details=f"matched /{pass_re}/",
        ))
        return findings, report_extras

    if fail_hit:
        findings.append(Finding(
            severity="ERROR",
            category="ORACLE_BROKEN",
            message="oracle returns FAIL on known-good SOF — tester broken",
            details=f"matched /{fail_re}/ — stop RTL iteration and repair oracle",
        ))
        return findings, report_extras

    findings.append(Finding(
        severity="ERROR",
        category="UNKNOWN_RESPONSE",
        message="oracle returns unknown response",
        details=(f"neither PASS /{pass_re}/ nor FAIL /{fail_re}/ matched "
                 f"tester output"),
    ))
    return findings, report_extras


def build_report(findings: List[Finding], config_path: str,
                 extras: dict, passed: bool) -> dict:
    return {
        "program": "tester_oracle_health_check",
        "version": "1.0.0",
        "config": config_path,
        "summary": {
            "findings_count": len(findings),
            "pass": passed,
            **extras,
        },
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Prove the tester oracle is healthy before iterating "
                     "RTL to chase a hardware FAIL."),
    )
    parser.add_argument("--config", required=True,
                        help="Path to oracle.json config file")
    parser.add_argument("--json", default=None,
                        help="Optional path to write JSON report")
    parser.add_argument("--dry-run", action="store_true",
                        help=("Validate config and return PASS without "
                              "executing burn / tester subprocesses."))
    args = parser.parse_args(argv)

    cfg_path = Path(args.config)
    config, findings = load_config(cfg_path)
    report_extras: dict = {}

    if config is None:
        report = build_report(findings, str(cfg_path), report_extras, False)
        out_txt = json.dumps(report, indent=2, ensure_ascii=False)
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(out_txt)
        print(out_txt)
        return 2

    oracle_findings, report_extras = check_oracle(config, dry_run=args.dry_run)
    findings.extend(oracle_findings)

    passed = all(f.severity not in ("ERROR",) for f in findings) and any(
        f.category == "ORACLE_PASS" for f in findings
    )

    report = build_report(findings, str(cfg_path), report_extras, passed)
    out_txt = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out_txt)
    print(out_txt)
    return 0 if passed else 1


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
