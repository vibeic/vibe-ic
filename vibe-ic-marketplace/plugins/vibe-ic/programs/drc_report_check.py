#!/usr/bin/env python3
"""DRC report check — wrapper for eda_report_audit --mode drc.

TWO flow steps declare this program, and BOTH declare a ``--json`` audit path:

    Step 21 (routing)   drc_report_check . --mode drc --json reports/phase3/drc_router.json
    Step 31 (PV)        drc_report_check . --mode drc --json reports/phase3/drc_signoff.json

#490 — THE ARGV WAS DISCARDED ENTIRELY, so neither audit was ever written. The
old body was one line::

    sys.exit(main([sys.argv[1] if len(sys.argv) > 1 else ".", "--mode", "drc"]))

The list literal has no ``*passthrough``: every token after the first was
dropped on the floor. ``--json`` never reached ``eda_report_audit``, so the
DRC sign-off audit trail was never produced on any run.

MEASURED, before anything was changed, on a clean fixture project (a
tool-authentic KLayout report with a real ``total violations: 0``)::

    $ drc_report_check.py proj --mode drc --json out/drc_signoff.json
    rc=0                                  # gate GREEN
    $ ls out/drc_signoff.json
    No such file or directory             # and NO audit trail at all

and across the tracked corpus — 119 project snapshots under ``benchmark-data/``
— ``reports/phase3/drc_signoff.json`` appears **0** times and
``reports/phase3/drc_router.json`` **0** times, against 9 tracked
``reports/phase3/lvs.json`` and 28 tracked ``reports/phase3/sta*`` as controls.
The file has never been written, not "sometimes missing".

WHY THAT MATTERS BEYOND A MISSING FILE — a step that declares an output and
then exits 0 without producing it hands the tapeout checklist "there is no such
evidence" where it should hand it "the evidence says X". Those read completely
differently to a reviewer, and only one of them is true.

TWO FURTHER VECTORS THIS SHAPE CARRIED, both measured on the same fixture:

* ``--mode=power`` / ``--mode power`` from a caller were SILENTLY DISCARDED. A
  DRC audit was run and rc 0 returned with nothing said about the mode the
  caller actually asked for. That is the mirror image of #489's defect (where
  the caller's mode was silently HONOURED): both answer a question nobody
  asked, and neither says so.
* ``--json <path> <proj>`` — the ``--json`` value landing where the wrapper
  expected the project dir — reached argparse as ``["--json", "--mode", "drc"]``
  and exited **2**. rc 2 is credited by
  ``flow_compliance_check._check_program_exit_zero`` as a VACUOUS_PASS,
  returning ``passed=True`` UNCONDITIONALLY, so a command line argparse itself
  REJECTED turned the Step-21 and Step-31 DRC gates GREEN with no DRC audited.

WHAT REPLACES IT — the split now comes from the shared, value-aware
``_report_check_argv`` helper landed by #489 (a per-wrapper hand-rolled
splitter is exactly how this defect propagated across the family; this is an
adoption, not a fourth copy), plus the sign-off policy this domain owes:

* Both ``--mode drc`` and ``--mode=drc`` pin the drc audit.
* Any OTHER mode — either spelling, and a valueless ``--mode`` too — is
  REFUSED with a stated reason. Nothing is certified and the refusal is
  written to the declared ``--json`` path, so the artefact says why.
* The audit is ALWAYS emitted when ``--json`` is declared: if
  ``eda_report_audit`` could not write it, this wrapper writes it from the
  payload it captured; if even that fails, the run exits non-zero and SAYS the
  audit was not written.
* A PASS must disclose its denominator: rc 0 is re-checked against the audit's
  own ``summary.files_found`` and the disclosure — files found, how many of
  them yielded a determinable violation count, and the real violation total —
  is printed to STDERR.
* NO exit path returns 2. argparse's own rejections are caught and turned into
  rc 1.

WHY REFUSALS EXIT 1 AND NOT 2 — rc 2 is the repo's general "input does not
apply, NOT CHECKED" contract, and it is the wrong answer here for a mechanical
reason: ``_check_program_exit_zero`` credits rc 2 as a VACUOUS_PASS and returns
``passed=True`` unconditionally (unlike rc 3, which additionally requires a
stdout sentinel). A refusal exiting 2 would turn Steps 21 and 31 GREEN — a
cheaper false certificate than the one this change closes. A refused DRC
sign-off is not "this project has no DRC to check"; it is "nothing was
certified", which on a blocking gate is a FAIL. The unconditional rc-2 credit
is a separate defect with its own blast radius and is reported separately.

STDOUT IS THE AUDIT JSON AND NOTHING ELSE. Every disclosure goes to stderr,
which ``_check_program_exit_zero`` also captures into its evidence snippet.

WIRING — Steps 21 and 31 invoke this program in ``gate.all_of`` and a non-zero
exit fails the step. No ``ENFORCEMENT:`` intent line is declared, and that is
deliberate rather than an oversight: ``flow_gate_enforcement_audit`` classifies
a gate as ENFORCED only when a one-shot runner invokes it INLINE, and
``phase3_one_shot_runner._DECLARED_SIGNOFF_GATES`` carries ``sta_report_check``
and ``em_report_check`` but NOT this one (nor ``lvs_report_check``). Measured:
the audit reports this gate as AUDIT_ONLY. So the DRC gate stops a run only
when the compliance audit runs it, not during the run itself. Claiming
blocking here would be a contradiction the audit correctly exits 1 on — the
claim is the thing that would be wrong, not the audit.
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

MODE = "drc"

#: rc contract of this wrapper. 2 is deliberately absent — see the module
#: docstring (``_check_program_exit_zero`` credits rc 2 as a vacuous PASS).
RC_PASS = 0
RC_FAIL = 1


def denominator_of(payload: object) -> tuple:
    """``(ok, files_found, determined_files, real_total)`` for a drc payload.

    A PASS may only stand when the audit can name how many reports it actually
    read. ``_check_drc`` cannot currently return ``passed=True`` with
    ``files_found == 0`` — it returns early on an empty discovery, and its
    ``passed`` additionally requires ``determined_files > 0`` — so this is a
    TRIPWIRE, not a live filter, and its measured blast radius over the 119
    tracked snapshots is 0. It exists because four of the seven sibling modes
    DO have a ``_waived_for_pdk`` path that sets ``passed=True`` with a summary
    carrying no ``files_found`` at all (``power`` / ``em`` / ``ir_drop`` /
    ``antenna``). If ``drc`` ever grows one, a denominator-less PASS on a
    sign-off gate must not slip through unannounced.
    """
    summary = {}
    if isinstance(payload, dict) and isinstance(payload.get("summary"), dict):
        summary = payload["summary"]
    files_found = summary.get("files_found")
    determined = summary.get("determined_files")
    real_total = summary.get("real_violation_total")
    ok = isinstance(files_found, int) and not isinstance(files_found, bool) \
        and files_found >= 1
    return ok, files_found, determined, real_total


def _not_checked_payload(rule: str, message: str, project_dir: str) -> dict:
    """An eda_report_audit-shaped record saying NOTHING was certified.

    Schema-compatible with the audit it replaces (``program`` / ``passed`` /
    ``findings`` / ``summary``) so every downstream reader keyed on ``passed``
    sees ``False``. It can never manufacture a pass.
    """
    return {
        "program": "drc_report_check",
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
    """Drive the drc audit for ``caller_argv``; return this wrapper's rc.

    ``_audit`` is a seam for tests that need to exercise a payload shape
    ``eda_report_audit`` cannot currently produce; production always uses
    ``eda_report_audit.main``.
    """
    audit = _audit or _audit_main
    project_dir, passthrough, refusal = split_and_pin(caller_argv, mode=MODE)
    target = json_target(passthrough)

    if refusal:
        message = (
            f"REFUSED: {refusal}. This is the DRC sign-off auditor; an auditor "
            "whose audit domain a caller can change — or silently lose — by "
            "flag spelling is a false-certificate vector. NOTHING was "
            "certified."
        )
        payload = _not_checked_payload("DRC_MODE_PIN_REFUSED", message,
                                       project_dir)
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        wrote = _write_json(target, text) if target else False
        print(text)
        print(f"drc_report_check: {message}", file=sys.stderr)
        if target and not wrote:
            print(f"drc_report_check: NO AUDIT WRITTEN to {target}",
                  file=sys.stderr)
        return RC_FAIL

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = audit([project_dir, "--mode", MODE, *passthrough])
    except OSError as exc:
        # e.g. --json naming an existing directory. Before #490 the argv never
        # got this far, so the failure mode was invisible rather than absent.
        print(f"drc_report_check: NOT CHECKED — the audit could not be "
              f"written to {target!r} ({exc.__class__.__name__}: {exc}); no "
              f"DRC verdict was produced.", file=sys.stderr)
        return RC_FAIL
    except SystemExit as exc:
        # argparse ended the run without producing an audit — a rejected
        # command line or an early-exit action. EVERY such exit is mapped to
        # rc 1 here, INCLUDING argparse's own 2 and `--help`'s 0: rc 2 is
        # credited as a VACUOUS_PASS and rc 0 is a sign-off credit, so an
        # invocation that certified nothing must spend neither. Measured at
        # v1.7.66: `drc_report_check --json out.json proj` exited 2 and the
        # real gate runner recorded the step as PASSED.
        sys.stdout.write(buf.getvalue())
        print(f"drc_report_check: NOT CHECKED — eda_report_audit exited "
              f"without producing an audit (exit {exc.code}); no DRC verdict "
              f"was produced.", file=sys.stderr)
        return RC_FAIL

    payload_text = buf.getvalue()
    sys.stdout.write(payload_text)          # stdout stays pure audit JSON

    if target and not Path(target).is_file():
        if _write_json(target, payload_text.strip() + "\n"):
            print(f"drc_report_check: audit re-emitted to {target} by the "
                  f"wrapper (eda_report_audit left it absent).",
                  file=sys.stderr)
        else:
            print(f"drc_report_check: NO AUDIT WRITTEN to {target} — the "
                  f"verdict below was produced but could not be persisted.",
                  file=sys.stderr)
            return RC_FAIL

    if rc == RC_PASS:
        try:
            payload = json.loads(payload_text)
        except ValueError:
            payload = None
        ok, files_found, determined, real_total = denominator_of(payload)
        if not ok:
            print(f"drc_report_check: REFUSED a PASS that cannot name its "
                  f"denominator (summary.files_found={files_found!r}) — a "
                  f"sign-off gate must disclose how much it read.",
                  file=sys.stderr)
            return RC_FAIL
        print(f"drc_report_check: PASS over files_found={files_found} "
              f"determined_files={determined} "
              f"real_violation_total={real_total} project={project_dir}",
              file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
