"""#564 — an L4 doc with no register fields passed the bit-position rule.

    PASS — every L4 register field has explicit bit position(s) (0 field(s) examined)
    rc=0

A universally quantified claim over an empty set is true, and rc 0 is what the
P0 umbrella aggregates, so a project whose L4_REGMAP.json declares no fields was
recorded as having a verified register map.

MEASURED over the 193 corpus projects that carry an L4 doc:

    164   L4 present, 0 fields      -> was PASS, now rc 2
     27   L4 present, 2..84 fields  -> unaffected
      2   real findings             -> unaffected, still rc 1

rc 2 is not a new convention here: `flow_compliance_check` already maps it to
VACUOUS_PASS ("the input-missing skip convention"), so the 164 move from a
silent pass to an explicit "not checked" rather than to a failure.

ONE THING THIS FIX GOT WRONG FIRST, recorded because the test suite is where it
would have been caught: I wrote `return 2`. This module's `main()` is invoked
bare at the bottom (`main()`, not `sys.exit(main())`), so the value was
discarded — the VACUOUS_PASS line printed while rc stayed 0. That is precisely
the message/exit-code split this issue is about, committed inside its own fix,
and only a run showed it. Every assertion below reads the EXIT CODE.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "regmap_bit_layout_check.py"


def _project(tmp_path, l4: dict) -> pathlib.Path:
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L4_REGMAP.json").write_text(json.dumps(l4), encoding="utf-8")
    return tmp_path


def _run(project) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), str(project)],
                          capture_output=True, text=True, timeout=45)


WITH_FIELDS = {
    "registers": [
        {"name": "CTRL", "offset": "0x00", "fields": [
            {"name": "EN", "bits": "0"},
            {"name": "MODE", "bits": "2:1"},
        ]},
    ],
}

NO_FIELDS = {"registers": [{"name": "CTRL", "offset": "0x00", "fields": []}]}
NO_REGISTERS = {"registers": []}


def test_zero_fields_refuses(tmp_path):
    proc = _run(_project(tmp_path, NO_FIELDS))
    assert proc.returncode == 2, (
        f"an L4 with no fields exited {proc.returncode}; the bit-position rule "
        f"is vacuously true over an empty field set and rc 0 is aggregated as "
        f"a pass")
    assert "VACUOUS_PASS" in proc.stderr, proc.stderr


def test_no_registers_at_all_refuses(tmp_path):
    proc = _run(_project(tmp_path, NO_REGISTERS))
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_real_fields_still_pass(tmp_path):
    """The accept case: 27 corpus projects are this, and they must not move."""
    proc = _run(_project(tmp_path, WITH_FIELDS))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "2 field(s) examined" in proc.stdout, proc.stdout
    assert "VACUOUS_PASS" not in proc.stderr


def test_a_missing_bit_position_still_fails(tmp_path):
    """The reject case in the other direction.

    Every change here makes the gate refuse more; without this, a program that
    refused everything would satisfy the tests above, and the 2 real corpus
    findings would be indistinguishable from the 164 vacuous ones.
    """
    broken = {"registers": [{"name": "CTRL", "offset": "0x00", "fields": [
        {"name": "EN", "bits": "0"},
        {"name": "MYSTERY"},          # no bit position at all
    ]}]}
    proc = _run(_project(tmp_path, broken))
    assert proc.returncode == 1, proc.stdout + proc.stderr


def test_absent_project_is_still_not_applicable(tmp_path):
    """No L4 doc is a different answer from an empty L4 doc.

    Collapsing the two would lose the distinction between "this project has no
    register map" and "this project declares one and it is empty".
    """
    proc = _run(tmp_path / "no-such-project")
    assert "not applicable" in (proc.stdout + proc.stderr)


def test_the_field_count_is_measured(tmp_path):
    """A count that does not track the input discloses nothing."""
    one = _run(_project(tmp_path / "a", WITH_FIELDS))
    three = {"registers": [{"name": "CTRL", "offset": "0x00", "fields": [
        {"name": "A", "bits": "0"}, {"name": "B", "bits": "1"},
        {"name": "C", "bits": "2"}]}]}
    other = _run(_project(tmp_path / "b", three))
    assert "2 field(s) examined" in one.stdout, one.stdout
    assert "3 field(s) examined" in other.stdout, other.stdout
