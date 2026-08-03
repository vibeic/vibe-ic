"""#687 — a POWER net with real terminals was silently retyped to SIGNAL.

`_pg_net_cleanup_tcl` exists for a real reason: a DANGLING non-special
POWER/GROUND tie stub makes TritonRoute abort all detailed routing, so it must
go. That is the zero-terminal branch, and it is correct and untouched.

The `else` branch was the defect. A POWER or GROUND net that HAS instance
terminals is not dangling — it is an UNROUTED SUPPLY, a genuine rail pdngen did
not stripe. Setting it to SIGNAL hands it to the detailed router at minimum
signal width, and every downstream gate then goes green on it:

  * it leaves SPECIALNETS, so any geometry gate that enumerates SPECIALNETS has
    nothing to examine and passes vacuously;
  * the PG connect audit tests `[$t getNet] eq "NULL"` and every terminal is
    attached, so it reports 0 unconnected;
  * detailed route succeeds, so DRC/ERC/PV all pass.

The only trace was one `PG_CLEANUP_SIG:` line in a multi-thousand-line log, with
no verdict attached to it — and `grep -c PG_CLEANUP` over the tree found FIVE
references, all of them in the emitter and none in a consumer.

Worst for a SECONDARY SUPPLY above the core voltage, where a macro vendor's own
deliverable requires the supply metal width to be at least the supply pin width.
Minimum signal width is roughly an order of magnitude under that: the flow
produced exactly the failure its own PDN code exists to prevent.

MEASURED on the log shape the emitter now produces — and note that
`PG_CONNECT_AUDIT: unconnected=0` holds in BOTH cases, which is why the new
verdict has to be reached BEFORE that audit's:

    with two unrouted rails -> [('VDD_IO','POWER','48','2'),
                                ('VSS_IO','GROUND','48','1')]
    with none               -> []
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "phase3_one_shot_runner", _PROGRAMS / "phase3_one_shot_runner.py")
R = importlib.util.module_from_spec(_spec)
sys.modules["phase3_one_shot_runner"] = R
try:
    _spec.loader.exec_module(R)
except SystemExit:
    pass

_SRC = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")
_BODY = "\n".join(l for l in _SRC.splitlines() if not l.lstrip().startswith("#"))


# ── the emitter ───────────────────────────────────────────────────────────
def test_it_no_longer_reclassifies_a_supply_to_SIGNAL():
    """The defect in one assertion."""
    assert "setSigType SIGNAL" not in R._pg_net_cleanup_tcl()
    assert "setSigType SIGNAL" not in _BODY


def test_the_dangling_stub_branch_is_UNCHANGED():
    """LOAD-BEARING. The zero-terminal destroy is the DRT-abort fix this block
    exists for; a net with terminals never caused that abort. Removing it to fix
    the other branch would trade one real failure for another."""
    tcl = R._pg_net_cleanup_tcl()
    assert "dbNet_destroy" in tcl
    assert "PG_CLEANUP_DEL" in tcl
    i = tcl.index("PG_CLEANUP_DEL")
    assert "getITerms]] == 0" in tcl[:i], "still gated on zero terminals"


def test_it_names_the_net_and_its_terminal_counts():
    """A finding that does not say WHICH net and HOW attached is one nobody can
    act on — and the old line said only the name."""
    tcl = R._pg_net_cleanup_tcl()
    assert "PG_CLEANUP_UNROUTED_SUPPLY" in tcl
    assert "iterms=" in tcl and "bterms=" in tcl


# ── the consumer ──────────────────────────────────────────────────────────
_RE = (r"^PG_CLEANUP_UNROUTED_SUPPLY:\s+(\S+)\s+\((POWER|GROUND)\)\s+"
       r"iterms=(\d+)\s+bterms=(\d+)")


def test_the_marker_is_actually_READ():
    """`grep -c PG_CLEANUP` found five references, all in the emitter. A marker
    nothing reads is this issue's own shape."""
    assert "PG_CLEANUP_UNROUTED_SUPPLY" in _BODY.replace(
        R._pg_net_cleanup_tcl(), "")


def test_the_regex_matches_what_the_emitter_writes():
    """Producer and consumer must agree on the line. They are in one file and
    can still drift — that is what a shared format is."""
    log = ("PG_CLEANUP_DEL: stub (POWER)\n"
           "PG_CLEANUP_UNROUTED_SUPPLY: VDD_IO (POWER) iterms=48 bterms=2\n"
           "PG_CLEANUP_UNROUTED_SUPPLY: VSS_IO (GROUND) iterms=48 bterms=1\n")
    assert re.findall(_RE, log, re.M) == [
        ("VDD_IO", "POWER", "48", "2"), ("VSS_IO", "GROUND", "48", "1")]


def test_a_clean_run_matches_nothing():
    log = ("PG_CLEANUP_DEL: stub (POWER)\n"
           "PG_CLEANUP_DONE: deleted=1 unrouted_supply=0\n"
           "PG_NET_OWNERSHIP_AUDIT: total=3337 no_net=0\n")
    assert re.findall(_RE, log, re.M) == []


def test_the_verdict_is_reached_BEFORE_the_net_ownership_audit():
    """THE ORDERING IS THE FIX. The ownership audit reads `no_net=0` in both
    cases — an unrouted rail's terminals are attached to exactly the right net,
    which is the whole reason a pointer test cannot see the defect. Checking
    afterwards lets the vacuous pass win the race.

    The audit was named `PG_CONNECT_AUDIT: unconnected=0` through v1.9.62;
    vibe-ic#699 renamed it to what it measures. The ordering property is
    unchanged — only the name it is anchored to."""
    i = _BODY.index("PG_CLEANUP_UNROUTED_SUPPLY")
    # the first ownership verdict return after the audit is parsed
    j = _BODY.index("PG_NET_OWNERSHIP_UNMEASURED")
    assert i < j, "the unrouted-supply check runs after the ownership audit"


def test_it_is_a_FAIL_not_an_advisory():
    """A supply the PDN failed to build is a result worth reporting, not a note.
    The old behaviour was already 'log it and continue'."""
    i = _BODY.index("PG_UNROUTED_SUPPLY")
    seg = _BODY[max(0, i - 300):i + 200]
    assert '"pnr", "FAIL"' in seg
