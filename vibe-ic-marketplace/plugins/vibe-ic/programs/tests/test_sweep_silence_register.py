"""The silence bound is a SET, and a set has an asymmetry a count does not.

WHY THIS FILE EXISTS
====================
``sweep_reach_survey`` was bounded by ``--max-silent 27`` — a COUNT — and the
count was wrong in a way only a repair exposed. ``task_nature_route`` took it
from 27 to 28 without going silent: until ``ebe08a870`` its CLI died on
``UnboundLocalError`` for every invocation without ``--json``, a defect present
since the file's first commit, so the survey classified it NOT_DRIVABLE and it
never entered the denominator. Fixing the crash moved it into ``driven``, where a
silence that had always been there became visible. The tree got strictly better
and the gate went red.

A count is wrong in two directions at once and this file pins both:

  * it CANNOT REFUSE A SWAP. One member stops being silent, another starts, and
    the total does not move. Every count bound accepts that tree.
  * it PUNISHES TIGHTENING. The number went up for a repair, and the only way to
    make it green again was to raise the bound — which is to say, to stop
    bounding.

THE ASYMMETRY IS WRITTEN DOWN RATHER THAN INFERRED. A register entry records a
DEFECT. A defect that has been repaired must never be the thing that reddens the
gate, so ``tightened`` is reported and is never a failure, while
``unregistered`` fails. That is not a symmetric set-difference and a reader who
assumed it was would be wrong, so both halves are asserted here.

THE EXIT CODES ARE ASSERTED EXACTLY. rc 0 / 1 / 2 are three different answers —
"nothing unregistered", "an unsanctioned sweep is silent", "the bound could not
be read" — and a test that accepted "non-zero" would let the third pass for the
second, which is the vacuous-pass shape this whole survey exists to remove.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
SURVEY = PROGRAMS / "sweep_reach_survey.py"
SHIPPED_REGISTER = PROGRAMS / "sweep_silence_register.json"

sys.path.insert(0, str(PROGRAMS))
import sweep_reach_survey as S  # noqa: E402

RC_PASS, RC_FAIL, RC_REFUSED = 0, 1, 2

#: A sweep in the shape ``discover`` finds: argparse, one positional taking a
#: SET of targets. It reads every file it is handed and judges none of them.
_SWEEP = '''#!/usr/bin/env python3
"""Fixture-only probe sweep. Describes nothing real."""
import argparse
import sys
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="+")
    a = ap.parse_args(argv)
    examined = 0
    for t in a.paths:
        p = Path(t)
        for f in (sorted(p.rglob("*.v")) if p.is_dir() else [p]):
            try:
                f.read_text(errors="replace")
            except OSError:
                continue
            examined += 1
{disclosure}
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''
_DISCLOSES = '    print("VACUOUS_PASS: examined %d file(s), judged none" % examined)'
_SILENT = "    pass"


def _tree(root: Path, silent: "list[str]", loud: "list[str]") -> Path:
    progs = root / "programs"
    progs.mkdir(parents=True, exist_ok=True)
    for n in silent:
        (progs / n).write_text(_SWEEP.format(disclosure=_SILENT))
    for n in loud:
        (progs / n).write_text(_SWEEP.format(disclosure=_DISCLOSES))
    return progs


def _register(path: Path, permitted: "list[str]", untriaged: "list[str]" = ()) -> Path:
    path.write_text(json.dumps({
        "register": "sweep_silence_register",
        "permitted": {n: {"why_permitted": "fixture-only probe sweep"}
                      for n in permitted},
        "known_silent_untriaged": {n: {"why_not_permitted": "fixture-only probe"}
                                   for n in untriaged},
    }, indent=2, sort_keys=True) + "\n")
    return path


def _run(progs: Path, register: Path):
    return subprocess.run(
        [sys.executable, str(SURVEY), "--programs-dir", str(progs),
         "--silent-set", str(register)],
        text=True, capture_output=True, timeout=300)


def _silent_count(progs: Path) -> int:
    return S.survey(progs)["silent"]


# --------------------------------------------------------------- the two rules
class TestTheBoundIsASetAndNotACount:
    def test_a_swap_at_an_unchanged_total_is_REFUSED(self, tmp_path):
        """The case no count can reach: one member out, one unsanctioned in.

        This is the whole argument for a set. The two trees below carry the SAME
        number of silent sweeps, so ``--max-silent N`` accepts both for every N.
        """
        before = _tree(tmp_path / "before", silent=["s_a.py", "s_b.py"],
                       loud=["s_c.py"])
        after = _tree(tmp_path / "after", silent=["s_b.py", "s_c.py"],
                      loud=["s_a.py"])
        # The total genuinely does not move — asserted, not asserted-by-comment.
        assert _silent_count(before) == _silent_count(after) == 2

        reg = _register(tmp_path / "reg.json", permitted=["s_a.py", "s_b.py"])
        assert _run(before, reg).returncode == RC_PASS

        got = _run(after, reg)
        assert got.returncode == RC_FAIL
        assert "named in NEITHER list" in got.stderr
        assert "s_c.py" in got.stderr
        # And it must name the sweep that is actually unsanctioned, not the one
        # that left: quoting the wrong name is how a reader is sent to the wrong
        # file with a true-looking verdict.
        assert "s_a.py" not in got.stderr.split("named in NEITHER list")[1]

    def test_a_member_that_stops_being_silent_still_PASSES(self, tmp_path):
        """Tightening is reported and is NEVER a failure.

        A register entry records a defect. A repaired defect reddening the gate
        is the exact shape this bound replaced, so the set difference is
        deliberately one-sided.
        """
        progs = _tree(tmp_path / "t", silent=["s_a.py"], loud=["s_b.py", "s_c.py"])
        # Registered three; only one is still silent.
        reg = _register(tmp_path / "reg.json",
                        permitted=["s_a.py", "s_b.py", "s_c.py"])
        got = _run(progs, reg)
        assert got.returncode == RC_PASS, got.stdout + got.stderr
        assert "[TIGHTENED]" in got.stdout
        assert "s_b.py" in got.stdout and "s_c.py" in got.stdout
        assert "NOT a failure" in got.stdout

    def test_an_emptied_register_over_a_silent_tree_is_the_control(self, tmp_path):
        """The falsification the two rules above need: the gate CAN still fail.

        Without this, a bound that accepted everything would satisfy the
        tightening test and half of the swap test.
        """
        progs = _tree(tmp_path / "t", silent=["s_a.py"], loud=[])
        assert _run(progs, _register(tmp_path / "r.json", permitted=[])).returncode == RC_FAIL
        assert _run(progs, _register(tmp_path / "r2.json", permitted=["s_a.py"])).returncode == RC_PASS


class TestAnUnjustifiedEntryMayNotSilenceTheGate:
    def test_a_permitted_entry_with_no_argument_is_REFUSED(self, tmp_path):
        """rc 2, and NOT rc 0: an entry nobody can justify is precisely what
        makes a register worthless later, so it may not bless by being present."""
        progs = _tree(tmp_path / "t", silent=["s_a.py"], loud=[])
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"permitted": {"s_a.py": {"note": "later"}}}))
        got = _run(progs, bad)
        assert got.returncode == RC_REFUSED
        assert "carries no 'why_permitted'" in got.stderr

    @pytest.mark.parametrize("body", ["{not json", '["a list"]',
                                      '{"permitted": "a string"}'])
    def test_an_unreadable_register_is_REFUSED_not_passed(self, tmp_path, body):
        """"I could not read the bound" must never share an exit code with "I
        read it and nothing was unregistered"."""
        progs = _tree(tmp_path / "t", silent=["s_a.py"], loud=[])
        bad = tmp_path / "bad.json"
        bad.write_text(body)
        got = _run(progs, bad)
        assert got.returncode == RC_REFUSED
        assert "not a pass" in got.stderr.lower()

    def test_a_name_in_both_lists_is_REFUSED(self, tmp_path):
        """It cannot be both a claim of legitimacy and a refusal to make one."""
        progs = _tree(tmp_path / "t", silent=["s_a.py"], loud=[])
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({
            "permitted": {"s_a.py": {"why_permitted": "x"}},
            "known_silent_untriaged": {"s_a.py": {"why_not_permitted": "y"}}}))
        assert _run(progs, bad).returncode == RC_REFUSED


# ------------------------------------------------- applied to the real register
class TestTheShippedRegisterIsUsable:
    def test_it_loads_and_every_entry_carries_its_argument(self):
        entries = S.load_silent_set(SHIPPED_REGISTER)
        assert entries, "the shipped register names no sweep at all"
        for name, e in entries.items():
            key = ("why_permitted" if e["_list"] == "permitted"
                   else "why_not_permitted")
            assert e[key].strip(), name

    def test_the_untriaged_list_makes_no_claim_of_legitimacy(self):
        """The two lists must not quietly become one. An untriaged entry is a
        recorded defect, and reading it as a blessing is how the register stops
        meaning anything."""
        entries = S.load_silent_set(SHIPPED_REGISTER)
        untriaged = [n for n, e in entries.items()
                     if e["_list"] == "known_silent_untriaged"]
        assert untriaged, "nothing is recorded as untriaged — say so explicitly"
        for n in untriaged:
            assert "why_permitted" not in entries[n], n

    def test_task_nature_route_is_untriaged_and_says_how_it_got_here(self):
        """The sweep that caused this change is in the file with its history:
        it did not go silent, a crash that hid its silence was repaired."""
        e = S.load_silent_set(SHIPPED_REGISTER)["task_nature_route.py"]
        assert e["_list"] == "known_silent_untriaged"
        assert "ebe08a870" in e["how_it_entered"]
