#!/usr/bin/env python3
"""IR-drop report check — wrapper for eda_report_audit --mode ir_drop.

ARGV WAS DISCARDED, exactly as in ``sta_report_check.py`` / ``em_report_check.py``
(PR #473): the wrapper rebuilt the command line as
``main([sys.argv[1], "--mode", "ir_drop"])`` and threw away the ``--json <path>``
step 24 declares.

Measured before the change, on a project holding a real
``reports/phase3/ir_drop.rpt``::

    $ ir_drop_report_check proj --mode ir_drop --json <path>
    rc=0        # and no file written

The caller's argv is now forwarded verbatim. ``--mode ir_drop`` is supplied only
when the caller states no mode, which preserves the bare
``ir_drop_report_check <project>`` call shape driven by
``programs/tests/test_report_wrappers.py`` and ``test_ir_drop_report_check.py``.
A mode the caller DOES state reaches argparse rather than being silently
replaced: a declaration naming a mode that is not an ``eda_report_audit``
choice is a broken declaration and must be visible.

OUTPUT-PATH COLLISION, fixed in the same change. Step 24 declared
``--json reports/phase3/ir_drop.json``, which is the PRODUCER's file:
``step_canonicalize_artefacts`` → ``_emit_ir_em_reports`` writes the PSM
measurement there (``worst_ir_uv``, ``budget_uv``, ``verdict``) and
``phase3_one_shot_runner`` reads it back as step 24's sign-off evidence — it is
also step 24's own ``required_outputs`` entry. Honouring the dropped flag
without moving the path would have destroyed the measurement it audits, so the
flow declaration now points at ``reports/phase3/ir_drop_signoff.json``.

ENFORCEMENT: this wrapper runs in step 24's existing flow-compliance gate.
An ordinary native producer must adopt the current LibreLane primary before
report keywords can pass. Explicit direct mode preserves the legacy audit;
this does not add another whole-IC acceptance prerequisite.

SIDE EFFECT — EVALUATION NOW WRITES INTO THE PROJECT. On the pre-change tree
this gate wrote nothing (the flag naming its output was discarded), so
evaluating step 24 was read-only. It now creates
``reports/phase3/ir_drop_signoff.json``, and step 24 declares that file as a
``required_output`` so the artefact is verified rather than merely produced.
Auditing a PUBLISHED ``benchmark-data/`` run with ``flow_compliance_check``
therefore dirties the working tree; that diff is expected and must not be
committed as a result. See ``drc_report_check.py`` for the same note.
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from eda_report_audit import main  # noqa: E402

MODE = "ir_drop"


def build_argv(caller_argv):
    """Forward the caller's argv, defaulting the mode this wrapper names."""
    argv = list(caller_argv)
    if not argv:
        argv = ["."]
    if not any(a == "--mode" or a.startswith("--mode=") for a in argv):
        argv += ["--mode", MODE]
    return argv


def _run_and_emit(caller_argv):
    """Run the audit, then hand its outcome to the one metrics schema.

    step_metrics_adoption_check: a step that declares this program must emit
    through `step_metrics`. The step is read from the flow clause that ran it
    (program + `--json` path), never assumed -- one program may serve
    several steps. Best-effort by construction: the metric can never change
    the gate's rc.
    """
    argv = build_argv(caller_argv)
    project = Path(argv[0])
    from _prestream_native import final_state
    final = final_state(project) is not None
    primary = project / "reports/phase3/ir_drop_librelane.json"
    import em_current_density_check as emc
    try:
        ir = json.loads((project / "reports/phase3/ir_drop.json").read_text())
        switch = project / "phase3/librelane_switch.json"
        steps = json.loads(switch.read_text()).get("steps", {}) if switch.is_file() else {}
    except (OSError, ValueError, AttributeError):
        ir, steps = {}, {}
    expects_primary = (str(ir.get("producer", "")).startswith("librelane:")
                       or (emc.native_project(project / "reports/phase3/em_segments.csv") is not None
                           and steps.get("24") != "direct"))
    if final or expects_primary or (primary.is_file() and steps.get("24") != "direct"):
        binding = emc.validate_primary_ir(project)
        if final:
            # #62b: use the native checker verdict, not the writer's budget.
            rc = (0 if binding["verdict"] == "PASS" else 1) if binding["valid"] else 2
            if "--json" in argv:
                path = Path(argv[argv.index("--json") + 1])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"program": "ir_drop_report_check",
                    "verdict": binding["verdict"], "primary_ir": binding}, indent=2) + "\n")
            import step_metrics
            step_metrics.emit_gate_outcome(Path(__file__).stem, argv, rc)
            return rc
        if not binding["valid"]:
            # Preserve a separately bound measured FAIL from the EM session's
            # IR cross-check. An incomplete primary must not dilute that FAIL.
            measured = emc.validate_native_density(project)
            rc = 1 if measured["valid"] and ir.get("verdict") == "FAIL" else 2
            print(f"NOT_MEASURED: {binding['rule']}: {binding['reason']}")
            if "--json" in argv:
                path = Path(argv[argv.index("--json") + 1])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"program": "ir_drop_report_check", "verdict": "FAIL" if rc == 1 else "NOT_MEASURED",
                                             "primary_ir": binding}, indent=2) + "\n")
            import step_metrics
            step_metrics.emit_gate_outcome(Path(__file__).stem, argv, rc)
            return rc
    rc = main(argv)
    import step_metrics  # noqa: PLC0415
    step_metrics.emit_gate_outcome(Path(__file__).stem, argv, rc)
    return rc


if __name__ == "__main__":
    sys.exit(_run_and_emit(sys.argv[1:]))
