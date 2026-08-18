#!/usr/bin/env python3
"""LVS report check — wrapper for eda_report_audit --mode lvs.

This is the Step-31 LVS HARD SIGN-OFF gate: flow/phase1_phase2_phase3.yaml
declares it as ``lvs_report_check . --mode lvs --json reports/phase3/lvs.json``
and it is the only declared producer of that audit path.

#489 — TWO ARGV DEFECTS, BOTH MEASURED HERE BEFORE THE CHANGE. The splitter
introduced by #507 lived inline in this module's ``__main__`` body and was
copied from; it was neither ``=``-spelling aware nor value aware.

1. ``--mode`` WAS NOT ACTUALLY PINNED. The old body dropped only ``tok ==
   "--mode"``. ``--mode=<x>`` starts with ``-``, so it was appended to the
   passthrough and handed to argparse AFTER the pinned pair, where last-wins
   gave the caller the mode. Measured at v1.7.66 on a fixture project::

       $ lvs_report_check.py proj --mode=power --json out/d1.json
       $ python3 -c 'import json;print(json.load(open("out/d1.json"))["program"])'
       eda_report_audit:power

   That is a false-certificate vector, not a cosmetic bug: Step 31's LVS gate is
   satisfied by exit 0, and a project whose power report is clean while its LVS
   is absent turns the LVS sign-off GREEN with no LVS ever audited.

2. THE SPLIT WAS NOT VALUE AWARE. ``--json out.json <proj>`` took the first bare
   token as the project dir, so the project became ``out.json`` and ``--json``
   took ``<proj>`` — a directory — as its output path. Measured::

       $ lvs_report_check.py --json out/d2.json proj
       IsADirectoryError: [Errno 21] Is a directory: 'proj'
       $ ls out/d2.json
       No such file or directory        # NO audit written at all

WHAT REPLACES IT — the split now comes from the shared, value-aware
``_report_check_argv`` helper (see that module for why it is shared and why the
other six sibling wrappers are deliberately NOT converted in this change), and
this wrapper adds the sign-off-specific policy on top:

* Both ``--mode lvs`` and ``--mode=lvs`` pin the lvs audit.
* Any OTHER mode — in either spelling, and a valueless ``--mode`` too — is
  REFUSED, explicitly, and nothing is certified.
* The audit is ALWAYS emitted when ``--json`` is declared: if
  ``eda_report_audit`` could not write it, this wrapper writes it from the
  payload it captured; if even that is impossible, the run exits non-zero and
  SAYS the audit was not written. Silently writing nothing on a hard sign-off
  step is the shape this repo keeps closing.
* A PASS must disclose its denominator: rc 0 is re-checked against the audit's
  own ``summary.files_found`` / ``summary.terminal_verdict`` and the disclosure
  is printed to STDERR. A PASS that cannot name a denominator is refused.

WHY THE REFUSAL EXITS 1 AND NOT 2 — the issue asks for rc 2 = NOT CHECKED, and
that is the right general contract, but it is NOT reachable from this gate.
``flow_compliance_check._check_program_exit_zero`` credits ``rc == 2`` from a
``program_exit_zero`` gate as a VACUOUS_PASS and returns ``passed=True``
UNCONDITIONALLY (unlike ``rc == 3``, which additionally requires a stdout
sentinel). A refusal that exited 2 would therefore turn Step 31 GREEN — a
cheaper false certificate than the one this refusal exists to prevent. A refused
hard sign-off is not "the input does not apply to this project"; it is "nothing
was certified", which on a blocking gate is a FAIL. The unconditional rc-2
credit is itself worth its own round and is reported separately.

STDOUT IS THE AUDIT JSON AND NOTHING ELSE — ``test_v0_2_97_issue477`` does
``json.loads(cp.stdout)``. Every disclosure this wrapper adds goes to stderr,
which ``_check_program_exit_zero`` also captures into its evidence snippet.

WIRING — flow/phase1_phase2_phase3.yaml Step 31 ``gate.all_of`` invokes this
program and a non-zero exit fails the step. No ``ENFORCEMENT:`` intent is
declared, and that is deliberate: ``flow_gate_enforcement_audit`` classifies a
gate as ENFORCED only when ``phase3_one_shot_runner`` invokes it INLINE, and the
runner's ``step_declared_signoff_gates`` table carries ``sta_report_check`` and
``em_report_check`` but NOT this one. Declaring blocking here would be a
contradiction the audit correctly rejects (verified: it does). So the LVS gate
stops a run only when the compliance audit runs it, not during the run — a real
gap, but a wiring decision with its own blast radius, reported separately rather
than smuggled in behind an argv fix.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _report_check_argv import json_target, split_and_pin  # noqa: E402
from eda_report_audit import main as _audit_main  # noqa: E402

MODE = "lvs"

#: rc contract of this wrapper. 2 is deliberately absent — see the module
#: docstring (``_check_program_exit_zero`` credits rc 2 as a vacuous PASS).
RC_PASS = 0
RC_FAIL = 1


def denominator_of(payload: object) -> tuple:
    """``(ok, files_found, terminal_verdict)`` for an eda_report_audit payload.

    A PASS is only allowed to stand when the audit can name how many reports it
    actually read. ``_check_lvs`` cannot currently return ``passed=True`` with
    ``files_found == 0`` — it returns early on an empty discovery — so this is a
    tripwire, not a live filter, and its measured blast radius is zero. It
    exists because four of the seven sibling modes DO have a
    ``_waived_for_pdk`` path that sets ``passed=True`` with a summary carrying
    no ``files_found`` at all — ``power`` / ``em`` / ``ir_drop`` / ``antenna``,
    at ``eda_report_audit.py`` lines 661 / 716 / 762 / 1023. If ``lvs`` ever
    grows one, a denominator-less PASS on a hard sign-off must not slip through
    unannounced.
    """
    summary = {}
    if isinstance(payload, dict) and isinstance(payload.get("summary"), dict):
        summary = payload["summary"]
    files_found = summary.get("files_found")
    verdict = summary.get("terminal_verdict")
    ok = isinstance(files_found, int) and not isinstance(files_found, bool) \
        and files_found >= 1
    return ok, files_found, verdict


def _not_checked_payload(rule: str, message: str, project_dir: str) -> dict:
    """An eda_report_audit-shaped record saying NOTHING was certified.

    Schema-compatible with the audit it replaces (``program`` / ``passed`` /
    ``findings`` / ``summary``) so every downstream reader keyed on ``passed``
    sees ``False``. It can never manufacture a pass.
    """
    return {
        "program": "lvs_report_check",
        "audited_program": f"eda_report_audit:{MODE}",
        "passed": False,
        "findings": [{"rule": rule, "severity": "ERROR",
                      "message": message, "file": ""}],
        "summary": {"files_found": 0, "checked": False,
                    "pinned_mode": MODE, "project_dir": project_dir,
                    "terminal_verdict": "NOT_CHECKED"},
    }


def _write_json(target: str, text: str) -> bool:
    try:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return True
    except OSError:
        return False


def run(caller_argv, _audit=None) -> int:
    """Drive the lvs audit for ``caller_argv``; return this wrapper's rc.

    ``_audit`` is a seam for tests that need to exercise a payload shape
    ``eda_report_audit`` cannot currently produce; production always uses
    ``eda_report_audit.main``.
    """
    audit = _audit or _audit_main
    project_dir, passthrough, refusal = split_and_pin(caller_argv, mode=MODE)
    target = json_target(passthrough)

    if refusal:
        message = (
            f"REFUSED: {refusal}. This is the LVS hard sign-off auditor; an "
            "auditor whose audit domain a caller can change by flag spelling "
            "is a false-certificate vector. NOTHING was certified."
        )
        payload = _not_checked_payload("LVS_MODE_PIN_REFUSED", message,
                                       project_dir)
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        wrote = _write_json(target, text) if target else False
        print(text)
        print(f"lvs_report_check: {message}", file=sys.stderr)
        if target and not wrote:
            print(f"lvs_report_check: NO AUDIT WRITTEN to {target}",
                  file=sys.stderr)
        return RC_FAIL

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = audit([project_dir, "--mode", MODE, *passthrough])
    except OSError as exc:
        # e.g. --json naming an existing directory. Before #489 this escaped as
        # an uncaught traceback and NO audit was written.
        print(f"lvs_report_check: NOT CHECKED — the audit could not be "
              f"written to {target!r} ({exc.__class__.__name__}: {exc}); no "
              f"LVS verdict was produced.", file=sys.stderr)
        return RC_FAIL
    except SystemExit as exc:
        # argparse ended the run without producing an audit — a rejected
        # command line (a second bare positional) or an early-exit action.
        # EVERY such exit is non-zero here, INCLUDING `--help`'s exit 0:
        # exit 0 from this program is a Step-31 sign-off credit, so an
        # invocation that certified nothing must never spend one. Measured at
        # v1.7.66: `lvs_report_check . --help` exited 0 and turned the gate
        # green with no LVS audited.
        sys.stdout.write(buf.getvalue())
        print(f"lvs_report_check: NOT CHECKED — eda_report_audit exited "
              f"without producing an audit (exit {exc.code}); no LVS verdict "
              f"was produced.", file=sys.stderr)
        return RC_FAIL

    payload_text = buf.getvalue()
    sys.stdout.write(payload_text)          # stdout stays pure audit JSON

    if target and not Path(target).is_file():
        if _write_json(target, payload_text.strip() + "\n"):
            print(f"lvs_report_check: audit re-emitted to {target} by the "
                  f"wrapper (eda_report_audit left it absent).",
                  file=sys.stderr)
        else:
            print(f"lvs_report_check: NO AUDIT WRITTEN to {target} — the "
                  f"verdict below was produced but could not be persisted.",
                  file=sys.stderr)
            return RC_FAIL

    if rc == RC_PASS:
        try:
            payload = json.loads(payload_text)
        except ValueError:
            payload = None
        ok, files_found, verdict = denominator_of(payload)
        if not ok:
            print(f"lvs_report_check: REFUSED a PASS that cannot name its "
                  f"denominator (summary.files_found={files_found!r}) — a "
                  f"hard sign-off must disclose how much it read.",
                  file=sys.stderr)
            return RC_FAIL
        print(f"lvs_report_check: PASS over files_found={files_found} "
              f"terminal_verdict={verdict} project={project_dir}",
              file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
