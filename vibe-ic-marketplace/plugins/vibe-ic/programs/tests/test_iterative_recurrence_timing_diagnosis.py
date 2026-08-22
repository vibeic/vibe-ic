"""Tests for iterative_recurrence_timing_diagnosis.py.

Covers the sta-review captured rule: a setup-limited ITERATIVE datapath whose
worst path is a single-register self-recurrence is loop-bound (retiming can't
help); the in-spec fix is a multi-cycle microarch split, never a relaxed clock.

Chip-agnostic: every fixture uses generic register names / slack numbers; no
vendor / SKU / IC literal drives any assertion.
"""
import json
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))

import iterative_recurrence_timing_diagnosis as mod  # noqa: E402


# ---- an OpenSTA report_checks block for a SELF-LOOP path (a_reg -> a_reg) ----
SELF_LOOP_RPT = """\
Startpoint: a_reg[5] (rising edge-triggered flip-flop clocked by clk)
Endpoint: a_reg[27] (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max

  Delay    Time   Description
  0.00     0.00   clock clk (rise edge)
  ...
  slack (VIOLATED)                  -3.85
"""

# ---- a FEED-FORWARD pipeline path (stage1_reg -> stage2_reg) ----
FEEDFWD_RPT = """\
Startpoint: stage1_reg[3] (rising edge-triggered flip-flop clocked by clk)
Endpoint: stage2_reg[3] (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max
  slack (VIOLATED)                  -1.20
"""

# ---- anonymised names (yosys _NNNN_), no bank identity visible ----
ANON_RPT = """\
Startpoint: _1234_ (rising edge-triggered flip-flop clocked by clk)
Endpoint: _5678_ (rising edge-triggered flip-flop clocked by clk)
Path Type: max
  slack (VIOLATED)                  -2.40
"""

# ---- a MET path (positive slack) ----
MET_RPT = """\
Startpoint: a_reg[0] (rising edge-triggered flip-flop clocked by clk)
Endpoint: a_reg[9] (rising edge-triggered flip-flop clocked by clk)
Path Type: max
  slack (MET)                        2.01
"""

# ---- slack line in the alternate ordering (number before 'slack') ----
ALT_ORDER_RPT = """\
Startpoint: acc_reg[7] (rising edge-triggered flip-flop clocked by clk)
Endpoint: acc_reg[0] (rising edge-triggered flip-flop clocked by clk)
Path Type: max
  -0.75  slack (VIOLATED)
"""


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


# --------------------------- parser --------------------------------------
def test_parse_self_loop(tmp_path):
    w = mod._parse_worst_path(SELF_LOOP_RPT)
    assert w is not None
    assert w.start.bank == "a_reg"
    assert w.end.bank == "a_reg"
    assert w.slack_ns == pytest.approx(-3.85)
    assert w.path_type == "max"


def test_parse_alt_slack_order(tmp_path):
    w = mod._parse_worst_path(ALT_ORDER_RPT)
    assert w.slack_ns == pytest.approx(-0.75)
    assert w.start.bank == w.end.bank == "acc_reg"


def test_bank_strips_bit_index_and_escape():
    assert mod._bank_of("\\a_reg[5]") == "a_reg"
    assert mod._bank_of("core/dp/a_reg[27]") == "core/dp/a_reg"
    assert mod._bank_of("_1234_") == "_1234_"


def test_worst_is_most_negative():
    two = SELF_LOOP_RPT + "\n" + FEEDFWD_RPT
    w = mod._parse_worst_path(two)
    # -3.85 (self-loop) is worse than -1.20 (feed-fwd) -> self-loop wins
    assert w.slack_ns == pytest.approx(-3.85)
    assert w.start.bank == "a_reg"


# --------------------------- diagnose verdicts ---------------------------
def test_loop_bound_recommends_multicycle_when_spec_free(tmp_path):
    rc = mod.main(["--sta-report", str(_write(tmp_path, "s.rpt", SELF_LOOP_RPT)),
                   "--retiming-wns-delta", "0.0",
                   "--spec-microarch-free", "--spec-latency-unconstrained",
                   "--target-period-ns", "25.907",
                   "--json", str(tmp_path / "o.json")])
    assert rc == 0
    r = json.loads((tmp_path / "o.json").read_text())
    assert r["verdict"] == "LOOP_BOUND_RECURRENCE"
    assert r["remedy"] == "RECOMMEND_MULTICYCLE_SPLIT"
    assert r["signals"]["self_loop_by_name"] is True
    assert r["signals"]["retiming_ineffective"] is True


def test_loop_bound_honest_floor_when_spec_blocks(tmp_path):
    # self-loop, retiming ineffective, but spec does NOT free the microarch
    rc = mod.main(["--sta-report", str(_write(tmp_path, "s.rpt", SELF_LOOP_RPT)),
                   "--retiming-wns-delta", "0.02",
                   "--json", str(tmp_path / "o.json")])
    assert rc == 0
    r = json.loads((tmp_path / "o.json").read_text())
    assert r["verdict"] == "LOOP_BOUND_RECURRENCE"
    assert r["remedy"] == "SPEC_BLOCKS_MICROARCH_CHANGE"


def test_measured_retiming_improvement_overrides_name(tmp_path):
    # same-bank names, but retiming DID improve WNS -> not a pure self-loop
    rc = mod.main(["--sta-report", str(_write(tmp_path, "s.rpt", SELF_LOOP_RPT)),
                   "--retiming-wns-delta", "2.5",
                   "--json", str(tmp_path / "o.json")])
    assert rc == 0
    r = json.loads((tmp_path / "o.json").read_text())
    assert r["verdict"] == "RETIMING_EFFECTIVE_APPLY"


def test_feed_forward_is_not_self_loop(tmp_path):
    rc = mod.main(["--sta-report", str(_write(tmp_path, "s.rpt", FEEDFWD_RPT)),
                   "--json", str(tmp_path / "o.json")])
    assert rc == 0
    r = json.loads((tmp_path / "o.json").read_text())
    assert r["verdict"] == "NOT_SELF_LOOP"


def test_anonymized_names_inconclusive_without_retiming(tmp_path):
    rc = mod.main(["--sta-report", str(_write(tmp_path, "s.rpt", ANON_RPT)),
                   "--json", str(tmp_path / "o.json")])
    assert rc == 0
    r = json.loads((tmp_path / "o.json").read_text())
    assert r["verdict"] == "INCONCLUSIVE_NAMES_ANONYMIZED"
    assert r["signals"]["names_anonymized"] is True


def test_met_timing_needs_no_diagnosis(tmp_path):
    rc = mod.main(["--sta-report", str(_write(tmp_path, "s.rpt", MET_RPT)),
                   "--json", str(tmp_path / "o.json")])
    assert rc == 0
    r = json.loads((tmp_path / "o.json").read_text())
    assert r["verdict"] == "TIMING_MET"


def test_relax_clock_is_forbidden_tripwire(tmp_path):
    rc = mod.main(["--sta-report", str(_write(tmp_path, "s.rpt", SELF_LOOP_RPT)),
                   "--relax-clock-proposed",
                   "--json", str(tmp_path / "o.json")])
    assert rc == 1
    r = json.loads((tmp_path / "o.json").read_text())
    assert r["verdict"] == "CLOCK_RELAX_FORBIDDEN"


def test_missing_report_is_error(tmp_path):
    rc = mod.main(["--sta-report", str(tmp_path / "nope.rpt")])
    assert rc == 2


def test_empty_report_is_error(tmp_path):
    rc = mod.main(["--sta-report", str(_write(tmp_path, "e.rpt", "   \n"))])
    assert rc == 2


def test_no_path_parsed_is_error(tmp_path):
    rc = mod.main(["--sta-report",
                   str(_write(tmp_path, "j.rpt", "just some log noise\n"))])
    assert rc == 2


# ---- carry-chain (CPA-dominated) routing ---------------------------------
# A worst path whose delay sits overwhelmingly on carry-generate cells: the
# shape an area-mode mapper produces from a parallel-prefix adder.
CARRY_RPT = """\
Startpoint: acc_reg[5] (rising edge-triggered flip-flop clocked by clk)
Endpoint: acc_reg[27] (rising edge-triggered flip-flop clocked by clk)
Path Type: max

   Delay     Time   Description
   0.000    0.000   clock clk (rise edge)
   0.900    0.900 ^ acc_reg[5]/Q (generic_lib__dfxtp_4)
   1.000    1.900 ^ _001_/X (generic_lib__maj3_1)
   1.000    2.900 v _002_/X (generic_lib__maj3_2)
   1.000    3.900 v _003_/X (generic_lib__maj3_2)
   1.000    4.900 v _004_/X (generic_lib__maj3_4)
   1.000    5.900 v _005_/X (generic_lib__maj3_2)
   1.000    6.900 v _006_/X (generic_lib__maj3_1)
   0.200    7.100 v _007_/Y (generic_lib__nor2_1)
   0.000    7.100 v acc_reg[27]/D (generic_lib__dfxtp_1)
           7.100   data arrival time
  -1.500   slack (VIOLATED)
"""


def test_carry_chain_is_measured():
    w = mod._parse_worst_path(CARRY_RPT)
    assert w.carry is not None
    assert w.carry.carry_cell_stages == 6
    # 6.0 ns of carry delay out of 7.1 ns arrival
    assert w.carry.carry_delay_ns == pytest.approx(6.0)
    assert w.carry.carry_delay_fraction > mod.CARRY_DOMINANT_FRACTION


def test_cpa_dominated_without_attestation_blames_the_flow_first(tmp_path):
    """A carry chain is an unsettled FLOW question until measured post-route."""
    rc = mod.main(["--sta-report", str(_write(tmp_path, "c.rpt", CARRY_RPT)),
                   "--retiming-wns-delta", "0.0",
                   "--spec-microarch-free", "--spec-latency-unconstrained",
                   "--json", str(tmp_path / "o.json")])
    assert rc == 0
    r = json.loads((tmp_path / "o.json").read_text())
    assert r["verdict"] == "LOOP_BOUND_RECURRENCE"
    assert r["remedy"] == "MEASURE_SYNTH_KNOBS_POST_ROUTE_FIRST"


def test_cpa_dominated_with_attestation_breaks_the_carry_chain(tmp_path):
    """Only once synthesis is attested timing-driven is RTL surgery advised."""
    rc = mod.main(["--sta-report", str(_write(tmp_path, "c.rpt", CARRY_RPT)),
                   "--retiming-wns-delta", "0.0", "--timing-driven-synth",
                   "--spec-microarch-free", "--spec-latency-unconstrained",
                   "--json", str(tmp_path / "o.json")])
    assert rc == 0
    r = json.loads((tmp_path / "o.json").read_text())
    assert r["remedy"] == "BREAK_CARRY_CHAIN"


def test_non_carry_path_still_recommends_multicycle_split(tmp_path):
    """A self-loop that is NOT carry-dominated keeps the round-split remedy."""
    rc = mod.main(["--sta-report", str(_write(tmp_path, "s.rpt", SELF_LOOP_RPT)),
                   "--retiming-wns-delta", "0.0", "--timing-driven-synth",
                   "--spec-microarch-free", "--spec-latency-unconstrained",
                   "--json", str(tmp_path / "o.json")])
    assert rc == 0
    r = json.loads((tmp_path / "o.json").read_text())
    assert r["remedy"] == "RECOMMEND_MULTICYCLE_SPLIT"
