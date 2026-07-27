#!/usr/bin/env python3
"""STA report check — wrapper for eda_report_audit --mode sta.

ARGV WAS DISCARDED. This wrapper used to rebuild the command line as
``main([sys.argv[1], "--mode", "sta"])``, which threw away every other flag
the caller passed — including the ``--json <path>`` the flow definition
declares for step 10 and step 23.

That is not cosmetic. ``reports/phase3/sta/post_route_summary.json`` is
step 23's own ``required_outputs`` entry and this wrapper is its ONLY
declared producer anywhere in the plugin; the same holds for step 10's
``reports/phase3/sta/pre_pnr_summary.json``. Because the flag was dropped,
neither file was ever written — by this program or any other — so a
declared sign-off output had no producer at all, on any run.

Measured before the change (real completed run
``campaign_pr427/spm/converge_ihp-sg13g2``)::

    $ sta_report_check . --mode phase3/stage3/sta \
          --json reports/phase3/sta/post_route_summary.json
    rc=0
    $ ls reports/phase3/sta/post_route_summary.json
    No such file or directory

The caller's argv is now forwarded verbatim. ``--mode sta`` is supplied only
when the caller states no mode, which preserves the bare
``sta_report_check <project>`` call shape used by
``programs/tests/test_report_wrappers.py`` and ``test_sta_report_check.py``.

A mode the caller DOES state is passed through to argparse rather than
silently replaced: a declaration naming a mode that is not an
``eda_report_audit`` choice is a broken declaration and must be visible, not
absorbed. (The flow yaml declared ``--mode phase3/stage3/sta``, which is a
path, not a mode; it is corrected in the same change, and
``test_report_wrappers.py`` now asserts every in-repo declaration names a
real mode so it cannot drift back.)

Only this wrapper and ``em_report_check.py`` are changed. The identically
shaped ``ir_drop_report_check`` / ``antenna_report_check`` /
``drc_report_check`` / ``lvs_report_check`` wrappers have the same defect but
are left alone deliberately — each needs its own blast-radius measurement.

ENFORCEMENT: blocking — `phase3_one_shot_runner.step_declared_signoff_gates`
invokes this gate inline and a non-zero exit fails the run. The declaration is
stated so `flow_gate_enforcement_audit` reports a CONTRADICTION if the wiring
is ever removed while the claim stays.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from eda_report_audit import main  # noqa: E402

MODE = "sta"


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
