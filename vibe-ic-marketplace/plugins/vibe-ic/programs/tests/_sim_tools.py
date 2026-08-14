#!/usr/bin/env python3
"""One definition of "this test needs the simulators", for the cvdp gate suite.

WHY THIS EXISTS (vibe-ic#1128 / the #1311 cluster)
--------------------------------------------------
`cvdp_gate` REFUSES — rc=2 — when yosys is absent, deliberately:

    ERROR: yosys not available — the synthesizability smoke (#531) cannot be
    enforced; refusing to emit responses gated on iverilog alone (a yosys-absent
    host degraded the synth gate to a silent no-op PASS, #604)

So a host without yosys is not a host these tests can run on. `test_cvdp_gate`
guarded on iverilog ALONE, and its seven sibling files guarded on nothing at
all — so on such a host 38 tests across 8 files executed anyway, asserted
`rc == 0` against that refusal, and failed with a bare `assert 2 == 0` naming
neither tool.

MEASURED on 8HD-8 (`a38902d16`, iverilog present, yosys absent), by a full
sharded sweep of all 2467 test files:

    13  test_cvdp_gate.py
     8  test_v1_0_39_issue642_cvdp_top_flag.py
     7  test_v1_0_27_issue642_cvdp_gate_harness_top_name.py
     4  test_v1_0_42_issue642_round2_advisory.py
     3  test_v1_0_79_issue734_cvdp_context_unavailable_downgrade.py
     1  test_v1_0_78_issue715r2_context_module_overfire.py
     1  test_v1_0_80_issue740_finer_gates.py
     1  test_v1_0_74_issue715_cvdp_multifile_completeness.py
    ── 38 across 8 files

ONE DEFINITION, NOT EIGHT. Eight copies of `shutil.which("yosys")` is the
drift shape this repo removes from waiver registries and figure counts one at
a time: the copies agree on the day they are written and not after. A file
that needs the marker imports it.

APPLIED PER TEST, NEVER AS `pytestmark`. A module-level mark would skip every
test in the file, and these files are mixed — `test_v1_0_80_issue740_finer_gates`
has 27 tests of which exactly ONE needs a simulator, and
`test_v1_0_39_issue642_cvdp_top_flag` has 11 of which 8 do. Marking the module
would trade 25 honest failures for ~40 assertions that stop running, which is
the "a skip is green" hole vibe-ic#1128 is about — a strictly worse outcome
than the red it removes.

THE REASON NAMES THE MISSING TOOL. `skipped [1] … missing on this host: yosys`,
not "a tool is missing". A skip is green, and a green that does not say what it
stopped checking is unauditable; a reader of the run should learn which
coverage was lost and why, without opening the file.
"""
from __future__ import annotations

import shutil

import pytest

#: Both binaries the gate drives. iverilog runs the testbench; yosys runs the
#: synthesizability smoke (#531) that the gate refuses to proceed without.
_REQUIRED = ("iverilog", "yosys")

#: Resolved once, at import. `shutil.which` is a PATH walk and these markers are
#: evaluated at collection for every decorated test.
MISSING = tuple(t for t in _REQUIRED if shutil.which(t) is None)

#: The marker. Skips only when a required binary is genuinely absent — on a host
#: carrying both, every decorated test runs and asserts exactly what it did
#: before. Proven by putting a `yosys` on PATH: zero of the 38 then skip.
NEEDS_SIM = pytest.mark.skipif(
    bool(MISSING),
    reason="cvdp_gate needs iverilog AND yosys; missing on this host: "
           + ", ".join(MISSING or ("-",)))
