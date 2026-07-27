#!/usr/bin/env python3
"""EM report check — wrapper for eda_report_audit --mode em.

ARGV WAS DISCARDED, exactly as in ``sta_report_check.py``: the wrapper
rebuilt the command line as ``main([sys.argv[1], "--mode", "em"])`` and threw
away the ``--json <path>`` step 25 declares.

Measured before the change (real completed run
``campaign_pr427/spm/converge_ihp-sg13g2``)::

    $ em_report_check . --mode em --json reports/phase3/em.json
    rc=0
    # reports/phase3/em.json unchanged — still the PRODUCER's payload
    # {"verdict": "MEASURED", "max_segment_current_A": 0.0002532, ...}

Note the second defect that dropped flag was hiding: step 25 declared its
audit output at ``reports/phase3/em.json``, which is the path the PRODUCER
(``step_canonicalize_artefacts`` → ``_emit_ir_em_reports``) writes its
measurement to, and which ``phase3_one_shot_runner`` reads back as the EM
sign-off evidence. Had the flag ever been honoured, the checker would have
overwritten the measurement it was auditing. The flow declaration now points
at ``reports/phase3/em_signoff.json`` so measurement and verdict are separate
files.

The caller's argv is now forwarded verbatim; ``--mode em`` is supplied only
when the caller states no mode, preserving the bare
``em_report_check <project>`` call shape used by
``programs/tests/test_report_wrappers.py`` and ``test_em_report_check.py``.

PR #473 changed only this wrapper and ``sta_report_check.py`` and stated that
the identically shaped ir_drop / antenna / drc wrappers were "left alone
deliberately". They no longer are — the medium/low backlog follow-up forwarded
argv in all three and fixed the same output-path collision in steps 24 and 26.
See ``test_wrapper_argv_forwarding.py``. ``lvs_report_check.py`` is a different
shape and stays out of scope.

ENFORCEMENT: blocking — `phase3_one_shot_runner.step_declared_signoff_gates`
invokes this gate inline and a non-zero exit fails the run. The declaration is
stated so `flow_gate_enforcement_audit` reports a CONTRADICTION if the wiring
is ever removed while the claim stays.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from eda_report_audit import main  # noqa: E402

MODE = "em"


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
