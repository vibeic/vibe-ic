#!/usr/bin/env python3
"""The synth FAIL quoted the command line back at the operator.

MEASURED DEFECT
===============
`design_one_shot_runner.step_yosys_synth` built its verdict detail AND both
enricher triggers (#586 closure-preflight, #662 macro-deps) from ``out + err``
— whatever the LAST yosys invocation returned.

When the slang fallback frontend engages it writes the real diagnostics to the
log FILE and returns a stream whose tail is the ECHOED COMMAND LINE. So a real
run reported::

    rc=1 log_tail=<a list of .sv paths>          # cut mid-path

while the abort — ``unknown module 'aes_sbox_dom'`` /
``is not part of the design`` — sat in yosys.log and appeared nowhere in the
verdict. #586 tests that SAME stream for "is not part of the design": gated on
text the capture does not contain, it was dead code, and so was #662.

The sibling FAIL site in the same file already composed
``(out + err + log_content)``; this site had simply been left behind.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import design_one_shot_runner as D  # noqa: E402

_ABORT = ("ERROR: Module `\\aes_sbox_dom' referenced in module "
          "`$paramod\\aes_sbox\\SecSBoxImpl=...' is not part of the design.")
_COMMAND_TAIL = "yosys -p read_slang a.sv b.sv c.sv tlul_rsp_intg_gen.s"


def test_the_abort_in_the_log_reaches_the_diagnosed_text(tmp_path):
    log = tmp_path / "yosys.log"
    log.write_text("...\n" + _ABORT + "\n")

    text = D._synth_diag_text(_COMMAND_TAIL, "", log)

    assert "is not part of the design" in text, (
        "the abort lives only in the log file, so a detail built from "
        "out+err alone can never contain it — and #586, which greps this "
        "same text, can never fire")
    assert "aes_sbox_dom" in text


def test_stdout_and_stderr_are_still_carried(tmp_path):
    log = tmp_path / "yosys.log"
    log.write_text(_ABORT)

    text = D._synth_diag_text("OUT-MARKER", "ERR-MARKER", log)

    assert "OUT-MARKER" in text and "ERR-MARKER" in text


def test_a_missing_log_degrades_to_out_plus_err_and_does_not_raise(tmp_path):
    text = D._synth_diag_text("o", "e", tmp_path / "absent.log")
    assert "o" in text and "e" in text
