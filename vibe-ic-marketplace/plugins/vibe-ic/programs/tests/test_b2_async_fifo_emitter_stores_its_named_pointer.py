"""The async-FIFO emitter must not ship the defect the plugin's own conformance
rule names.

MEASURED 2026-09-06 on the frozen RTLLM asyn_fifo, host 8HD-6, image 0.3.46: the
emitted candidate mismatched 20 of the 48 reference samples, first on `wfull`.
Changing ONLY `wptr <= bin2gray(waddr_bin + wen)` to `bin2gray(waddr_bin)` (and
the read counterpart) turned the official testbench from `Error` to `Your Design
Passed`. The prompt had already named it: "The converted write and read pointers
are stored in registers wptr and rptr" — the conversion OF THE POINTER, not of
the pointer's next value. Registering the next value makes the gray pointer lead
the binary pointer by a cycle, and every flag compared against it moves with it.

This test is the SELF-CONSISTENCY pin: the emitter is one of this repo's own
producers, and `spec_conformance_check`'s `derived-register-leads-named-source`
rule is this repo's own judge of that class. A producer that ships what its own
judge rejects is the shape that keeps costing blind runs.
"""
import re
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import canonical_primitive_synth as C          # noqa: E402
import spec_conformance_check as S             # noqa: E402

# The naming sentence the rule keys on, in the words a spec of this family uses.
_SPEC = (
    "The write and read pointers are represented by binary registers, "
    "waddr_bin and raddr_bin, respectively. The write and read pointers are "
    "converted to Gray code using XOR operations with right-shifted values. "
    "The converted write and read pointers are stored in registers wptr and "
    "rptr, respectively."
)


def test_emitted_gray_pointer_stores_the_conversion_of_its_binary_pointer():
    rtl = C._TPL_FIFO
    assert "bin2gray(waddr_bin)" in rtl, rtl[:400]
    assert "bin2gray(raddr_bin)" in rtl
    # the leading form must not come back under any spelling
    assert not re.search(r"bin2gray\(\s*waddr_bin\s*\+", rtl)
    assert not re.search(r"bin2gray\(\s*raddr_bin\s*\+", rtl)


def test_the_repos_own_conformance_rule_is_silent_on_its_own_emitter():
    assert S._derived_register_leads_named_source(_SPEC, C._TPL_FIFO) == []


def test_the_rule_would_have_caught_the_shipped_form():
    # The other direction, on the exact text the emitter used to produce: the
    # judge must FIRE on it, or this pin proves nothing.
    leading = (C._TPL_FIFO
               .replace("bin2gray(waddr_bin);", "bin2gray(waddr_bin + wen);")
               .replace("bin2gray(raddr_bin);", "bin2gray(raddr_bin + ren);"))
    hits = S._derived_register_leads_named_source(_SPEC, leading)
    assert {(h[0], h[1]) for h in hits} == {("wptr", "waddr_bin"),
                                            ("rptr", "raddr_bin")}, hits
