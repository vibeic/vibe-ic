#!/usr/bin/env python3
"""DRC report check — wrapper for eda_report_audit --mode drc.

ARGV WAS DISCARDED, exactly as in ``sta_report_check.py`` / ``em_report_check.py``
(PR #473): the wrapper rebuilt the command line as
``main([sys.argv[1], "--mode", "drc"])`` and threw away the ``--json <path>``
steps 21 and 31 declare.

Measured before the change, on the real completed run
``campaign_pr427/spm/converge_ihp-sg13g2``::

    $ drc_report_check . --mode drc --json reports/phase3/drc_router.json
    rc=1                                   # real findings printed to stdout
    $ find reports/phase3 -iname '*drc*'
    reports/phase3/drc_router.rpt
    reports/phase3/drc_signoff.rpt         # neither .json ever written

Unlike the EM / IR-drop siblings there is no output-path collision here:
nothing in the plugin writes ``reports/phase3/drc_router.json`` or
``reports/phase3/drc_signoff.json``, so the declared audit-trail paths are free
and are left as the flow declares them.

The caller's argv is now forwarded verbatim. ``--mode drc`` is supplied only
when the caller states no mode, preserving the bare ``drc_report_check
<project>`` call shape driven by ``programs/tests/test_report_wrappers.py`` and
``test_drc_report_check.py``.

ENFORCEMENT: advisory here — this wrapper is not in
``phase3_one_shot_runner._DECLARED_SIGNOFF_GATES``; it runs when
``flow_compliance_check`` evaluates step 21's / step 31's gate. Forwarding argv
does not change the gate's rc, only whether the declared audit-trail file is
written.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from eda_report_audit import main  # noqa: E402

MODE = "drc"


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
