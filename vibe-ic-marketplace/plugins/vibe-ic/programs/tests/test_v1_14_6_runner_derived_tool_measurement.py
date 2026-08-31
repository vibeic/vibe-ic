"""v1.14.6 — the runner states a tool measurement, read from the tool's output.

`_mcp_measurement`'s WRITER half is the MCP server's `measurementRecord()`. The
phase-3 runner never goes through it — it drives openroad / magic / klayout by
`docker exec` — so the third value was structurally absent for every physical
artefact on every design, and `provenance_check --require-measured` reported
UNDECLARED -> INCOMPLETE forever.

MEASURED spm x gf180mcuD, plugin v1.14.5, image sha256:fad41245fbff (2026-08-31):
`flow_compliance_check --phase all` returned FAIL through `forced_fail`, from 34
step-ordering violations rooted in four steps — 16 naming step 22 (Parasitic
Extraction) = INCOMPLETE, 7 naming step 31 (Physical Verification) = INCOMPLETE,
2 naming step 37. 25 of 34 were this one gate with nothing to read.

THE LOAD-BEARING NEGATIVE CONTROL is `test_the_flat_duration_measured_key_is_not
_a_tool_measurement`. The runner's invocation record ALREADY carries a flat
`"measured": True`, sitting directly under `"duration_ms": int(duration_ms),
# MEASURED, not a placeholder` — it states that the DURATION was measured.
Promoting THAT into the reader would assert "openroad extracted parasitics"
because a subprocess was timed, which is precisely the fabrication
`_mcp_measurement` was built to refuse. That test pins the distinction.
"""
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _mcp_measurement as mm            # noqa: E402

# IMPORTED SO THE PRE-FIX TREE CAN STILL RUN THIS FILE. A bare import makes the
# whole module error at COLLECTION on a tree without the fix, and "1 error"
# grades nothing: a bidirectional control has to produce a countable FAIL on the
# old tree and a countable PASS on the new one. This shim turns absence into an
# assertion failure inside each test instead.
try:
    import _runner_measurement as rm     # noqa: E402
except ImportError:                      # pre-fix tree
    rm = None


def _require_module():
    assert rm is not None, (
        "_runner_measurement is absent: the runner states no tool measurement, "
        "so every physical artefact stays UNDECLARED and "
        "provenance_check --require-measured reports INCOMPLETE")


def _w(d: Path, rel: str, text: str) -> Path:
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


_SPEF_HEAD = ('*SPEF "ieee 1481-1999"\n*DESIGN "x"\n*VENDOR "The OpenROAD Project"\n'
              '*PROGRAM "OpenROAD"\n*T_UNIT 1 NS\n')


def _spef(n):
    return _SPEF_HEAD + "".join(f"*D_NET net{i} 0.1\n*END\n" for i in range(n))


def _def(n):
    return f"VERSION 5.8 ;\nDESIGN x ;\nUNITS DISTANCE MICRONS 2000 ;\nCOMPONENTS {n} ;\nEND COMPONENTS\n"


def _rdb(items=0, *, top="x", deck="/pdk/x.drc", categories=1, closed=True):
    out = ['<?xml version="1.0"?>', "<report-database>"]
    if deck is not None:
        out.append(f"<generator>drc: script='{deck}'</generator>")
    if top is not None:
        out.append(f"<top-cell>{top}</top-cell>")
    out += [f"<category><name>R{i}</name></category>" for i in range(categories)]
    out.append("<items>")
    out += ["<item><category>R0</category></item>"] * items
    out.append("</items>")
    if closed:
        out.append("</report-database>")
    return "\n".join(out) + "\n"


# --- SPEF (step 22 — 16 of the 34 violations) ------------------------------

def test_spef_with_extracted_nets_is_measured(tmp_path):
    _require_module()
    _w(tmp_path, "x.spef", _spef(563))
    r = rm.derive(tmp_path, "x.spef", "openroad")
    assert r["measured"] is True
    assert "563" in r["operation"]


def test_spef_with_header_but_no_nets_is_a_hard_miss(tmp_path):
    """A tool that exited 0 having extracted nothing must NOT read as a pass."""
    _require_module()
    _w(tmp_path, "x.spef", _SPEF_HEAD)
    r = rm.derive(tmp_path, "x.spef", "openroad")
    assert r["measured"] is False
    assert r["not_measured_class"] == "TOOL_DID_NOT_RUN"
    assert mm.from_provenance_entry({"measurement": r}).hard_miss is True


def test_a_file_that_is_not_a_spef_yields_no_record(tmp_path):
    _require_module()
    _w(tmp_path, "x.spef", "this is not a spef\n")
    assert rm.derive(tmp_path, "x.spef", "openroad") is None


# --- DEF (step 21) ---------------------------------------------------------

def test_def_with_components_is_measured(tmp_path):
    _require_module()
    _w(tmp_path, "r.def", _def(3797))
    r = rm.derive(tmp_path, "r.def", "openroad")
    assert r["measured"] is True and "3797" in r["operation"]


def test_def_with_zero_components_is_a_hard_miss(tmp_path):
    _require_module()
    _w(tmp_path, "r.def", _def(0))
    r = rm.derive(tmp_path, "r.def", "openroad")
    assert r["measured"] is False
    assert r["not_measured_class"] == "TOOL_DID_NOT_RUN"


# --- KLayout RDB (step 31) -------------------------------------------------

def test_complete_rdb_is_measured_whether_or_not_it_found_violations(tmp_path):
    _require_module()
    for n in (0, 5):
        _w(tmp_path, f"d{n}.rpt", _rdb(n, categories=763))
        r = rm.derive(tmp_path, f"d{n}.rpt", "klayout")
        assert r["measured"] is True, n
        # The DECK is named, and the exact number — the item count — is stated.
        # No category tally: `<category>` occurs both as a deck rule and as a
        # per-item reference, so a raw count is deck-size + items and would
        # misreport the deck. Presence gates; only the exact number is quoted.
        assert "/pdk/x.drc" in r["operation"]
        assert f"{n} violation item" in r["operation"]
        assert "category" not in r["operation"]


@pytest.mark.parametrize("kw", [
    {"closed": False},          # truncated mid-write
    {"top": "UNKNOWN"},         # the Magic-casualty shape
    {"top": ""},
    {"deck": None},             # cannot say WHICH rules ran
    {"categories": 0},          # no deck enumerated
])
def test_incomplete_rdb_states_nothing(tmp_path, kw):
    _require_module()
    _w(tmp_path, "d.rpt", _rdb(0, **kw))
    assert rm.derive(tmp_path, "d.rpt", "klayout") is None


# --- refusing to answer ----------------------------------------------------

def test_unknown_extension_states_nothing(tmp_path):
    _require_module()
    _w(tmp_path, "a.gds", "anything")
    assert rm.derive(tmp_path, "a.gds", "magic") is None


def test_empty_and_missing_files_state_nothing(tmp_path):
    _require_module()
    _w(tmp_path, "e.spef", "")
    assert rm.derive(tmp_path, "e.spef", "openroad") is None
    assert rm.derive(tmp_path, "nope.spef", "openroad") is None


# --- the contract round-trip ----------------------------------------------

def test_every_record_is_readable_by_the_reader_half(tmp_path):
    """A record the READER cannot parse is not a record. This is the one
    assertion that keeps the two halves of the contract joined."""
    _require_module()
    _w(tmp_path, "x.spef", _spef(2))
    _w(tmp_path, "r.def", _def(9))
    _w(tmp_path, "d.rpt", _rdb(0))
    for rel, tool in (("x.spef", "openroad"), ("r.def", "openroad"),
                      ("d.rpt", "klayout")):
        rec = rm.derive(tmp_path, rel, tool)
        m = mm.from_provenance_entry({"measurement": rec})
        assert m.declared is True, rel
        assert m.undeclared is False, rel


def test_records_are_labelled_runner_derived(tmp_path):
    """A runner-derived reading must never be mistaken in the ledger for a
    tool's own self-report."""
    _require_module()
    _w(tmp_path, "x.spef", _spef(1))
    assert rm.derive(tmp_path, "x.spef", "openroad")["stated_by"] == "runner-derived"


# --- THE LOAD-BEARING NEGATIVE CONTROL ------------------------------------

def test_the_flat_duration_measured_key_is_not_a_tool_measurement():
    """The runner's invocation record carries a flat `"measured": True` that is
    a literal about `duration_ms`. It must NOT satisfy the reader: a timed
    subprocess is not a tool that did its work.

    NO MODULE GUARD, DELIBERATELY. This must hold on the PRE-fix tree too — it
    asserts what the reader refuses, not what this change adds, and a control
    that only runs after the fix cannot show the fix left the refusal alone.
    """
    entry = {"record": "invocation", "tool": "openroad", "exit_code": 0,
             "duration_ms": 811, "measured": True}
    assert mm.from_provenance_entry(entry).undeclared is True


def test_a_hard_miss_outranks_a_positive_sibling(tmp_path):
    """One artefact whose evidence says nothing was produced is not cured by a
    sibling that was — the same precedence `_mcp_measurement.worst` uses."""
    _require_module()
    _w(tmp_path, "good.spef", _spef(4))
    _w(tmp_path, "bad.def", _def(0))
    r = rm.derive_for_outputs(tmp_path, {"good.spef": "sha256:x",
                                         "bad.def": "sha256:y"}, "openroad")
    assert r["measured"] is False
    assert r["not_measured_class"] == "TOOL_DID_NOT_RUN"


def test_outputs_with_no_readable_artefact_state_nothing(tmp_path):
    _require_module()
    _w(tmp_path, "a.gds", "x")
    assert rm.derive_for_outputs(tmp_path, {"a.gds": "sha256:x"}, "magic") is None
