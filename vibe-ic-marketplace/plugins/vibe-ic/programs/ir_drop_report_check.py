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

ENFORCEMENT: advisory here — this wrapper is not in
``phase3_one_shot_runner._DECLARED_SIGNOFF_GATES``; it runs when
``flow_compliance_check`` evaluates step 24's gate. Forwarding argv does not
change the gate's rc, only whether the declared audit-trail file is written.

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


if __name__ == "__main__":
    sys.exit(main(build_argv(sys.argv[1:])))
