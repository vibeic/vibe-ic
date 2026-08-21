#!/usr/bin/env python3
"""Antenna report check — wrapper for eda_report_audit --mode antenna.

ARGV WAS DISCARDED, exactly as in ``sta_report_check.py`` / ``em_report_check.py``
(PR #473): the wrapper rebuilt the command line as
``main([sys.argv[1], "--mode", "antenna"])`` and threw away the ``--json <path>``
step 26 declares.

Measured before the change, on a project holding a real
``reports/phase3/antenna.rpt``::

    $ antenna_report_check proj --mode antenna --json <path>
    rc=0        # and no file written

The caller's argv is now forwarded verbatim. ``--mode antenna`` is supplied only
when the caller states no mode, preserving the bare
``antenna_report_check <project>`` call shape driven by
``programs/tests/test_report_wrappers.py`` and ``test_antenna_report_check.py``.

OUTPUT-PATH COLLISION, fixed in the same change. Step 26 declared
``--json reports/phase3/antenna.json``, which is the PRODUCER's file:
``step_canonicalize_artefacts`` → ``_emit_antenna_report`` writes the
``check_antennas`` measurement there (``net_violations``, ``pin_violations``,
``clean``) and ``phase3_one_shot_runner`` reads it back as step 26's evidence.
The flow declaration now points at ``reports/phase3/antenna_signoff.json``.

SELF-CONSUMPTION, fixed in ``eda_report_audit._discover``. The antenna mode
globs ``*antenna*.json``, so the audit's own verdict document would have been
re-discovered as an input report on the next run (measured on a project holding
one real antenna.rpt: ``files_found`` 1 → 2). ``_discover`` now skips any
document carrying this program's own ``"program": "eda_report_audit:<mode>"``
field, which is why the audit output can be given a readable name at all.

ENFORCEMENT: advisory here — this wrapper is not in
``phase3_one_shot_runner._DECLARED_SIGNOFF_GATES``; it runs when
``flow_compliance_check`` evaluates step 26's gate. Forwarding argv does not
change the gate's rc, only whether the declared audit-trail file is written.

SIDE EFFECT — EVALUATION NOW WRITES INTO THE PROJECT. On the pre-change tree
this gate wrote nothing (the flag naming its output was discarded), so
evaluating step 26 was read-only. It now creates
``reports/phase3/antenna_signoff.json``, and step 26 declares that file as a
``required_output`` so the artefact is verified rather than merely produced.
Auditing a PUBLISHED ``benchmark-data/`` run with ``flow_compliance_check``
therefore dirties the working tree; that diff is expected and must not be
committed as a result. See ``drc_report_check.py`` for the same note.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from eda_report_audit import main  # noqa: E402

MODE = "antenna"


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
