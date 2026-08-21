"""#604 / #625 residual — an UNNAMED template made any top read as fixed-pinout.

`is_fixed_pinout_wrapper` decides whether `fault chain` inserts a boundary-scan
register. It matched a `def_template` hint whose `design_name` was `None`
against ANY top, on the reasoning that the extractor leaves the field unset when
the config omitted `DESIGN_NAME`.

But `extract_floorplan_contract` collects configs from the WHOLE input tree, so
a SUB-MACRO config that declares `FP_DEF_TEMPLATE` and omits `DESIGN_NAME`
produced exactly such a hint. DRIVEN against the submitted code:

    sub_blk config, FP_DEF_TEMPLATE set, DESIGN_NAME omitted
    is_fixed_pinout_wrapper(project, "padframe_chip")  ->  True

True means `--skip-boundary`, so a padframe chip whose ports really ARE pads
would silently lose its boundary-scan register.

THE DIRECTION IS WHAT MAKES THIS WORTH CLOSING. Getting it wrong the other way —
keeping the register on a wrapper — is the -0.73 ns setup violation that #604 is
about: loud, and it blocks sign-off. This way is a silent DFT loss on a chip that
needed the register, discovered at test time or not at all.

#625's own sub-macro negative control cannot see it: its sub-macro NAMES itself,
so the name comparison already excludes it.

THE RULE: an unnamed template counts only when it is the ONLY one — then there is
no other design it could belong to. With several and one unnamed, which governs
the top is not established, and not established takes the default rather than a
guess.
"""
from __future__ import annotations

import importlib
import json
import pathlib

FPC = importlib.import_module("floorplan_contract")


def _config(project, design_name, *, template, die=(0, 0, 200, 200)):
    """Stage an OpenLane-style config; `design_name=None` omits DESIGN_NAME."""
    d = project / "input" / "design_src" / (design_name or "unnamed")
    d.mkdir(parents=True, exist_ok=True)
    cfg = {"DIE_AREA": list(die), "FP_SIZING": "absolute",
           "FP_DEF_TEMPLATE": template}
    if design_name:
        cfg["DESIGN_NAME"] = design_name
    (d / "config.json").write_text(json.dumps(cfg), encoding="utf-8")


# ── the residual ────────────────────────────────────────────────────────────
def test_an_unnamed_sub_macro_template_does_not_capture_another_top(tmp_path):
    """THE DEFECT, reproduced. Two templates, one of them unnamed, and the top
    is named by neither: which governs it is not established."""
    _config(tmp_path, "sub_blk", template="dir::fixed/sub_blk.def")
    _config(tmp_path, None, template="dir::fixed/other.def",
            die=(0, 0, 300, 300))
    is_fixed, ev = FPC.is_fixed_pinout_wrapper(tmp_path, "padframe_chip")
    assert is_fixed is False, ev
    assert ev["def_template"] is None
    assert len(ev["all_def_templates"]) == 2, (
        "the evidence must still show what was seen and rejected")


def test_a_lone_unnamed_template_is_still_the_tops(tmp_path):
    """THE ACCEPT CASE, and the reason the rule is "only one" rather than
    "must be named": a design whose own config sets FP_DEF_TEMPLATE and omits
    DESIGN_NAME has no other design the template could belong to. Tightening
    to "named or nothing" would switch #604 off for exactly that shape."""
    _config(tmp_path, None, template="dir::fixed/top.def")
    is_fixed, ev = FPC.is_fixed_pinout_wrapper(tmp_path, "top_wrap")
    assert is_fixed is True, ev
    assert ev["def_template"].endswith("top.def")


def test_a_named_template_for_the_top_wins_over_an_unnamed_sibling(tmp_path):
    """The top names itself, so nothing has to be inferred — the unnamed
    sibling is irrelevant and must not suppress the match."""
    _config(tmp_path, "top_wrap", template="dir::fixed/top_wrap.def",
            die=(0, 0, 1234, 5678))
    _config(tmp_path, None, template="dir::fixed/other.def")
    is_fixed, ev = FPC.is_fixed_pinout_wrapper(tmp_path, "top_wrap")
    assert is_fixed is True, ev
    assert ev["def_template_design_name"] == "top_wrap"


def test_a_named_sub_macro_template_is_still_rejected(tmp_path):
    """#625's own control, kept: it must not regress while the unnamed case is
    tightened."""
    _config(tmp_path, "sub_blk", template="dir::fixed/sub_blk.def")
    assert FPC.is_fixed_pinout_wrapper(tmp_path, "padframe_chip")[0] is False


def test_no_template_at_all_keeps_the_boundary_register(tmp_path):
    """A padframe chip defines its own pads; it takes no outline from a parent.
    This is the population that must be byte-unchanged."""
    d = tmp_path / "input" / "design_src" / "padframe_chip"
    d.mkdir(parents=True)
    (d / "config.json").write_text(json.dumps(
        {"DESIGN_NAME": "padframe_chip", "DIE_AREA": [0, 0, 3000, 3000],
         "FP_SIZING": "absolute"}), encoding="utf-8")
    is_fixed, ev = FPC.is_fixed_pinout_wrapper(tmp_path, "padframe_chip")
    assert is_fixed is False
    assert "no FP_DEF_TEMPLATE" in ev["reason"]


def test_the_decision_is_auditable_either_way(tmp_path):
    """A bare boolean is not reviewable: whichever way it goes, the evidence
    has to say what was read."""
    _config(tmp_path, "top_wrap", template="dir::fixed/top_wrap.def")
    for top in ("top_wrap", "someone_else"):
        _is, ev = FPC.is_fixed_pinout_wrapper(tmp_path, top)
        assert ev["reason"].strip()
        assert ev["top_module"] == top
        assert isinstance(ev["all_def_templates"], list)
