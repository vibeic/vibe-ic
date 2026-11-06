"""`selected_mode` and the contract's PRODUCTION_DEFAULTS (q7 PART 0, T109).

A lane that CUT OVER sets its step's production default here; a project
opts out by naming the step `direct` in its switch file. Before this table,
"no switch" could only ever mean `direct`, so no cut-over could land.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import _plugin_tree  # noqa: F401 — puts programs/ on sys.path
import librelane_contract as LC
import _owner_declared as _OD  # noqa: E402 — tests/, the one attestation fixture


def _switch(tmp_path, steps):
    p = tmp_path / "phase3" / "librelane_switch.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"steps": steps}))


def test_no_switch_follows_the_production_default(tmp_path, monkeypatch):
    monkeypatch.setitem(LC.PRODUCTION_DEFAULTS, "S1", "librelane")
    assert LC.selected_mode(tmp_path, "S1") == "librelane"
    assert LC.selected_mode(tmp_path, "S2") == "direct"
    _switch(tmp_path, {"S2": "dual"})          # file present, key absent
    assert LC.selected_mode(tmp_path, "S1") == "librelane"


def test_an_explicit_direct_is_the_projects_opt_out(tmp_path, monkeypatch):
    monkeypatch.setitem(LC.PRODUCTION_DEFAULTS, "S1", "librelane")
    _switch(tmp_path, {"S1": "direct"})
    assert LC.selected_mode(tmp_path, "S1") == "direct"


def test_analog_a6_a8_default_to_librelane_and_direct_is_an_opt_out(tmp_path):
    assert {step: LC.selected_mode(tmp_path, step)
            for step in ("A6", "A7", "A8")} == {
                "A6": "librelane", "A7": "librelane", "A8": "librelane"}
    _switch(tmp_path, {step: "direct" for step in ("A6", "A7", "A8")})
    assert {step: LC.selected_mode(tmp_path, step)
            for step in ("A6", "A7", "A8")} == {
                "A6": "direct", "A7": "direct", "A8": "direct"}


def test_an_invalid_mode_is_refused_from_either_source(tmp_path, monkeypatch):
    _switch(tmp_path, {"S1": "maybe"})
    with pytest.raises(LC.Refusal) as exc:
        LC.selected_mode(tmp_path, "S1")
    assert exc.value.code == "LL_INVALID_SWITCH"
    monkeypatch.setitem(LC.PRODUCTION_DEFAULTS, "S2", "bogus")
    with pytest.raises(LC.Refusal):
        LC.selected_mode(tmp_path, "S2")


def test_every_production_default_is_a_mode_the_contract_knows():
    assert all(m in ("direct", "librelane", "dual")
               for m in LC.PRODUCTION_DEFAULTS.values())


# ── T96: the chip path's class defaults for steps 15..20 ────────────────────
_CHAIN = ("15", "15.5ic", "17", "18", "19", "20")
_CHAIN_R4 = _CHAIN + ("21", "32")
#: The population, pinned by MEMBERS: T96 cut 15..20 over; T102 r4 added the
#: route (21, T99) and the post-route repair (32) as one chain.
_T96_MEMBERS = {"15", "15.5ic", "17", "18", "19", "20"}
_T102_MEMBERS = {"21", "32"}
#: CUT_W2 (1): sign-off STA on STAPostPNR (R-0929-TOOL-DEFAULT).
_CUTW2_MEMBERS = {"22", "23"}
#: R-0929-TOOL-DEFAULT Wave 1 (CUT_W1A): 8 dual, 10/26/26.5ic on the tool.
_W1A_MODES = {"8": "dual", "10": "librelane", "26": "librelane", "26.5ic": "librelane"}
_FRONTEND_MODES = {"7": "librelane", "9": "librelane"}


def _chip(tmp_path, deliverable="DIE", *, marker="SELF_TAPEOUT.txt"):
    """A project the flow routes onto the chip path (step 15.5ic's condition):
    a self-tape-out marker (or a slot file) beside a declaration."""
    st = tmp_path / "input" / "submission_template"
    st.mkdir(parents=True, exist_ok=True)
    if marker == "slots":
        (st / "slots").mkdir(exist_ok=True)
        (st / "slots" / "s1.yaml").write_text("name: s1\n")
    else:
        (st / marker).write_text("# self tape-out\n")
    if deliverable is not None:
        (st / "tapeout_declaration.json").write_text(json.dumps(_OD.attest(
            {"schema": "vibe-ic/tapeout_declaration/1",
             "answers": {"deliverable": deliverable}})))
    return tmp_path


def test_the_chip_path_runs_15_to_21_and_32_on_librelane_with_no_switch(tmp_path):
    project = _chip(tmp_path)
    assert LC.design_class(project) == LC.DESIGN_CLASS_CHIP_PAD_RING
    assert set(LC.CLASS_PRODUCTION_DEFAULTS[LC.DESIGN_CLASS_CHIP_PAD_RING]) \
        == _T96_MEMBERS | _T102_MEMBERS | _CUTW2_MEMBERS | set(_W1A_MODES) | set(_FRONTEND_MODES)
    assert {s: LC.selected_mode(project, s) for s in _CHAIN_R4} == dict.fromkeys(_CHAIN_R4, "librelane")
    assert LC.selected_mode(project, "23") == "librelane"
    assert LC.selected_mode(project, "22") == "librelane"
    assert {s: LC.selected_mode(project, s) for s in _W1A_MODES} == _W1A_MODES
    assert {s: LC.selected_mode(project, s) for s in _FRONTEND_MODES} == _FRONTEND_MODES
    # outside the cut-over, nothing moves
    for step in ("16", "37"):
        assert LC.selected_mode(project, step) == "direct"


def test_a_slot_catalogue_is_the_chip_path_too(tmp_path):
    project = _chip(tmp_path, deliverable=None, marker="slots")
    assert LC.selected_mode(project, "15") == "librelane"


@pytest.mark.parametrize("fixture", ["core_only", "hardmacro"])
def test_a_design_with_no_pad_ring_keeps_direct(tmp_path, fixture):
    project = (tmp_path if fixture == "core_only"
               else _chip(tmp_path, deliverable="HARDMACRO", marker="slots"))
    assert LC.design_class(project) is None
    assert {LC.selected_mode(project, s) for s in _CHAIN_R4} == {"direct"}
    assert {LC.selected_mode(project, s) for s in _W1A_MODES} == {"direct"}
    assert {LC.selected_mode(project, s) for s in _FRONTEND_MODES} == {"direct"}
    assert LC.selected_mode(project, "23") == "direct"
    assert LC.class_defaults_in_force(project) == {}


def test_the_class_predicate_is_the_runners_15_5ic_condition(tmp_path):
    for project, want in ((tmp_path / "a", False),
                          (_chip(tmp_path / "b"), True),
                          (_chip(tmp_path / "c", deliverable="HARDMACRO", marker="slots"), False),
                          (_chip(tmp_path / "d", deliverable="NOT_DETERMINED", marker="slots"), True)):
        project.mkdir(parents=True, exist_ok=True)
        assert (LC.design_class(project) is not None) is want


def test_an_opt_out_takes_the_steps_that_continue_it_back_to_direct(tmp_path):
    project = _chip(tmp_path)
    _switch(project, {"15.5ic": "direct"})
    assert {s: LC.selected_mode(project, s) for s in _CHAIN} == {
        "15": "direct", "15.5ic": "direct", "17": "direct", "18": "direct",
        "19": "librelane", "20": "librelane"}
    _switch(project, {"15": "direct"})       # the step-15 direct arm under a tool ring
    assert {s: LC.selected_mode(project, s) for s in _CHAIN} == {
        "15": "direct", "15.5ic": "librelane", "17": "direct", "18": "direct",
        "19": "librelane", "20": "librelane"}
    _switch(project, {"20": "direct"})       # 19/20 are one deck region
    assert (LC.selected_mode(project, "19"), LC.selected_mode(project, "20")) == ("direct", "direct")
    _switch(project, {"18": "direct"})       # 18 is inserted inside 17's placement
    assert (LC.selected_mode(project, "17"), LC.selected_mode(project, "18")) == ("direct", "direct")
    assert LC.selected_mode(project, "15") == "librelane"


def test_the_route_and_its_post_route_repair_opt_out_together(tmp_path):
    """T102 r4: 32's class default is the repair inside 21's LibreLane chain.
    Taking 21 direct takes 32 with it; 32 alone may still be opted out, and
    21 does not depend on 19/20 (T99 routed after direct CTS/hold too)."""
    project = _chip(tmp_path)
    _switch(project, {"21": "direct"})
    assert (LC.selected_mode(project, "21"), LC.selected_mode(project, "32")) == ("direct", "direct")
    assert LC.selected_mode(project, "20") == "librelane"
    _switch(project, {"32": "direct"})
    assert (LC.selected_mode(project, "21"), LC.selected_mode(project, "32")) == ("librelane", "direct")
    _switch(project, {"19": "direct", "20": "direct"})
    assert (LC.selected_mode(project, "21"), LC.selected_mode(project, "32")) == ("librelane", "librelane")
    _switch(project, {"21": "dual"})        # 32's own dual arm needs 21 on LibreLane: dual is
    assert LC.selected_mode(project, "32") == "direct"   # not `librelane`, so 32 is not defaulted
    _switch(project, {"21": "librelane", "32": "dual"})
    assert LC.selected_mode(project, "32") == "dual"
    assert "32" not in LC.class_defaults_in_force(project)


def test_the_switch_and_a_step_wide_default_outrank_the_class(tmp_path, monkeypatch):
    project = _chip(tmp_path)
    _switch(project, {"19": "dual", "20": "dual"})
    assert (LC.selected_mode(project, "19"), LC.selected_mode(project, "20")) == ("dual", "dual")
    monkeypatch.setitem(LC.PRODUCTION_DEFAULTS, "15", "direct")
    assert LC.selected_mode(project, "15") == "direct"
    assert "15" not in LC.class_defaults_in_force(project)
    assert "19" not in LC.class_defaults_in_force(project)


def test_every_class_default_is_a_mode_the_contract_knows():
    for defaults in LC.CLASS_PRODUCTION_DEFAULTS.values():
        assert set(defaults.values()) <= {"direct", "librelane", "dual"}
    assert set(LC.CLASS_DEFAULT_REQUIRES) <= set(
        LC.CLASS_PRODUCTION_DEFAULTS[LC.DESIGN_CLASS_CHIP_PAD_RING])
