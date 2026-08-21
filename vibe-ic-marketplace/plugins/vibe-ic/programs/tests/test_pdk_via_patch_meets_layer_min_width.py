#!/usr/bin/env python3
"""Tests for pdk_via_patch_meets_layer_min_width_check.

The motivating measurement: a sky130A run whose sign-off deck reported 9
`m5.1` (min met5 width) violations on the shipped GDS. The offending geometry
was the PDK's own `VIA M4M5_PR ... LAYER met5 ; RECT -0.71 -0.71 0.71 0.71`
(1.42 um) on a layer the SAME tech LEF gives `WIDTH 1.6`. The router's own
in-loop DRC reported 0 for that layout.

Every fixture below is copied VERBATIM from the shape of the real tech LEF —
including the `SPACINGTABLE` row that carries the same number as the layer
rule, and the lead comment the file writes above one of the five vias.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "pdk_via_patch_meets_layer_min_width_check.py")

# The layer half, shared by both fixtures. `SPACINGTABLE`'s `WIDTH 0 1.6 ;` row
# is present on purpose: it carries the same number as the layer rule, so a
# parser that read the table row instead would agree with the rule for the
# wrong reason.
_LAYERS = """\
LAYER met4
  TYPE ROUTING ;
  WIDTH 0.3 ;
END met4

LAYER via4
  TYPE CUT ;
  WIDTH 0.8 ;
  ENCLOSURE ABOVE 0.31 0.31 ;
END via4

LAYER met5
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  WIDTH 1.6 ;
  SPACINGTABLE
     PARALLELRUNLENGTH 0
     WIDTH 0 1.6 ;
END met5
"""

# FORM 1 — the fixed via. -0.71 .. 0.71 = 1.42 um on a layer whose own minimum
# is 1.6.
_VIA_FORM = _LAYERS + """
VIA M4M5_PR DEFAULT
  LAYER via4 ;
  RECT -0.4 -0.4 0.4 0.4 ;
  LAYER met4 ;
  RECT -0.59 -0.59 0.59 0.59 ;
  LAYER met5 ;
  RECT -0.71 -0.71 0.71 0.71 ;
END M4M5_PR
"""

# FORM 2 — the generate rule, which states the SAME 1.42 um by different
# arithmetic: cut extent 0.8 + 2 x ENCLOSURE 0.31. Copied from the real file,
# where every `VIA` block has a `VIARULE` twin of the same name.
_VIARULE_FORM = _LAYERS + """
VIARULE M4M5_PR GENERATE
  LAYER met4 ;
  ENCLOSURE 0.19 0.19 ;
  LAYER met5 ;
  ENCLOSURE 0.31 0.31 ;
  LAYER via4 ;
  RECT -0.4 -0.4 0.4 0.4 ;
  SPACING 1.6 BY 1.6 ;
END M4M5_PR
"""

_BOTH_FORMS = _VIA_FORM + _VIARULE_FORM.split("END met5\n", 1)[1]

# The PDK fix, per form. 1.6 um exactly satisfies met5's own WIDTH, and
# 0.8 - 0.4 = 0.40 still clears `LAYER via4 ... ENCLOSURE ABOVE 0.31`.
_VIA_FIXED = _VIA_FORM.replace("RECT -0.71 -0.71 0.71 0.71 ;",
                               "RECT -0.8 -0.8 0.8 0.8 ;")
_VIARULE_FIXED = _VIARULE_FORM.replace("  ENCLOSURE 0.31 0.31 ;",
                                       "  ENCLOSURE 0.4 0.4 ;")


def _run(args):
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True)


def _check(tmp_path, text, *extra, name="t.tlef"):
    lef = tmp_path / name
    lef.write_text(text)
    out = tmp_path / f"{name}.json"
    r = _run(["--tech-lef", str(lef), "--json", str(out), *extra])
    return r, json.loads(out.read_text())


# --- the defect, in BOTH forms the PDK writes it ---------------------------

def test_the_fixed_via_form_is_found(tmp_path):
    r, rep = _check(tmp_path, _VIA_FORM)
    assert r.returncode == 1, r.stdout + r.stderr
    assert len(rep["findings"]) == 1
    f = rep["findings"][0]
    assert (f["form"], f["via"], f["layer"]) == ("VIA", "M4M5_PR", "met5")
    assert f["patch_x_um"] == 1.42 and f["patch_y_um"] == 1.42
    assert f["layer_min_width_um"] == 1.6


def test_the_viarule_generate_form_is_found(tmp_path):
    """0.8 + 2 x 0.31 = 1.42 — the same defect, stated as an ENCLOSURE.

    The first version of this checker matched only `^VIA <name>` and the word
    ENCLOSURE appeared nowhere in it, so this fixture produced 0 findings and
    rc 0. A router GENERATES vias from these rules; a gate blind to them
    certifies a half-applied PDK fix as clean.
    """
    r, rep = _check(tmp_path, _VIARULE_FORM)
    assert r.returncode == 1, r.stdout + r.stderr
    assert len(rep["findings"]) == 1
    f = rep["findings"][0]
    assert (f["form"], f["via"], f["layer"]) == ("VIARULE", "M4M5_PR", "met5")
    assert f["patch_x_um"] == 1.42 and f["patch_y_um"] == 1.42


def test_a_half_applied_pdk_fix_is_not_clean(tmp_path):
    """Growing the RECT and leaving the ENCLOSURE alone is still broken.

    This is the case the fork patch makes concrete: it edits BOTH forms, and a
    gate that saw only one would go green on half of it while the router kept
    generating 1.42 um patches.
    """
    half = _BOTH_FORMS.replace("RECT -0.71 -0.71 0.71 0.71 ;",
                               "RECT -0.8 -0.8 0.8 0.8 ;")
    r, rep = _check(tmp_path, half)
    assert r.returncode == 1, r.stdout + r.stderr
    assert [f["form"] for f in rep["findings"]] == ["VIARULE"]


def test_both_forms_fixed_is_clean(tmp_path):
    whole = (_VIA_FIXED
             + _VIARULE_FIXED.split("END met5\n", 1)[1])
    r, rep = _check(tmp_path, whole)
    assert r.returncode == 0, r.stdout + r.stderr
    assert rep["findings"] == []


def test_cut_layer_is_not_compared(tmp_path):
    """A CUT layer has no width rule of this kind, so a via's cut RECT is
    never compared against it however large that layer's WIDTH is stated."""
    r, rep = _check(tmp_path, _VIA_FORM.replace("  WIDTH 0.8 ;\nEND via4",
                                                "  WIDTH 5.0 ;\nEND via4"))
    assert all(f["layer"] != "via4" for f in rep["findings"])


# --- the gate must be able to FAIL on the defect it exists to catch --------

def test_nothing_suppresses_a_finding_by_recording_it(tmp_path):
    """There is no baseline, no waiver file and no key list.

    The first version shipped a baseline holding all 108 findings it could
    see, which measured out as `[PASS] 108 recorded, 0 new` on the real PDKs —
    a gate with nothing left in the shipped set that it could fail on, while
    the defect was open. Any file dropped beside the program must not change
    the verdict.
    """
    (tmp_path / "pdk_via_patch_min_width_baseline.json").write_text(
        json.dumps({"known": ["t.tlef::VIA M4M5_PR::met5"]}))
    r, rep = _check(tmp_path, _VIA_FORM)
    assert r.returncode == 1, r.stdout + r.stderr
    assert rep["verdict"] == "FAIL"
    assert len(rep["open_findings"]) == 1


def test_advisory_lowers_the_exit_code_and_hides_nothing(tmp_path):
    r, rep = _check(tmp_path, _VIA_FORM, "--advisory")
    assert r.returncode == 0, r.stdout + r.stderr
    assert rep["verdict"] == "FAIL"          # the verdict is unchanged
    assert "[ADVISORY]" in r.stdout
    assert "M4M5_PR" in r.stdout             # the finding is still printed
    assert "the verdict above is fail" in r.stdout.lower()


# --- the one mitigation that is checkable ----------------------------------

def test_a_layer_above_the_routing_range_is_mitigated(tmp_path):
    """A latent defect on a layer no signal is routed on cannot fire."""
    r, rep = _check(tmp_path, _BOTH_FORMS, "--routing-max-layer", "met4")
    assert r.returncode == 0, r.stdout + r.stderr
    assert rep["open_findings"] == []
    assert len(rep["mitigated_findings"]) == 2
    assert "[MITIGATED]" in r.stdout


def test_widening_the_routing_range_brings_it_straight_back(tmp_path):
    """Nothing was written down, so the mitigation cannot outlive its reason."""
    r, rep = _check(tmp_path, _BOTH_FORMS, "--routing-max-layer", "met5")
    assert r.returncode == 1, r.stdout + r.stderr
    assert len(rep["open_findings"]) == 2


# --- what the file says about itself ---------------------------------------

def test_a_lead_comment_denial_is_quoted_not_acted_on(tmp_path):
    """The sky130 file writes `we really do not want to use it` above one of
    the five vias it reports. The finding must say so, and must still count.

    RECORDED, never subtracted: if a comment could lower the verdict, the file
    under audit would hold the switch that silences the audit.
    """
    denied = _VIA_FORM.replace(
        "\nVIA M4M5_PR DEFAULT",
        "\n# Centered via rule, we really do not want to use it\n"
        "VIA M4M5_PR DEFAULT")
    r, rep = _check(tmp_path, denied)
    assert r.returncode == 1, r.stdout + r.stderr          # still counted
    assert rep["findings"][0]["source_denial"] == "not"
    assert "we really do not want to use it" in r.stdout


def test_a_compound_non_is_not_read_as_a_denial(tmp_path):
    """The same file writes `metals are along the non prefered direction` above
    another of the five. `non` prefixes a noun; it does not deny the block."""
    r, rep = _check(tmp_path, _VIA_FORM.replace(
        "\nVIA M4M5_PR DEFAULT",
        "\n# Plus via rule, metals are along the non prefered direction\n"
        "VIA M4M5_PR DEFAULT"))
    assert r.returncode == 1
    assert rep["findings"][0]["source_denial"] is None


def test_a_file_header_denial_does_not_reach_the_blocks(tmp_path):
    """`# This Techfile contains not correct Parasitic Information.` is the
    real header of the real file. A file- or paragraph-scoped rule would
    attach it to every block below it."""
    r, rep = _check(
        tmp_path,
        "# This Techfile contains not correct Parasitic Information.\n\n"
        + _VIA_FORM)
    assert rep["findings"][0]["source_denial"] is None


# --- identity, and refusing to guess ---------------------------------------

def test_two_pdks_shipping_one_file_name_are_not_one_entry(tmp_path):
    """Keying on the basename would let a finding in one PDK read as a finding
    in the other."""
    a = tmp_path / "pdkA" / "libX" / "techlef"
    b = tmp_path / "pdkB" / "libY" / "techlef"
    for d in (a, b):
        d.mkdir(parents=True)
        (d / "same_name.tlef").write_text(_VIA_FORM)
    out = tmp_path / "r.json"
    r = _run(["--pdk-root", str(tmp_path), "--json", str(out)])
    assert r.returncode == 1, r.stdout + r.stderr
    keys = {f["lef_key"] for f in json.loads(out.read_text())["findings"]}
    assert len(keys) == 2, keys
    assert all(k.endswith("/techlef/same_name.tlef") for k in keys)


def test_pdk_key_root_states_the_key_scope(tmp_path):
    d = tmp_path / "pdkA" / "libX" / "techlef"
    d.mkdir(parents=True)
    (d / "t.tlef").write_text(_VIA_FORM)
    out = tmp_path / "r.json"
    _run(["--pdk-root", str(tmp_path), "--pdk-key-root", str(tmp_path),
          "--json", str(out)])
    f = json.loads(out.read_text())["findings"][0]
    assert f["lef_key"] == "pdkA/libX/techlef/t.tlef"
    assert f["key_scope"] == "pdk-root"


def test_no_readable_lef_refuses_instead_of_reporting_clean(tmp_path):
    """An unchecked PDK is not a clean PDK — rc=2, not rc=0."""
    r = _run(["--tech-lef", str(tmp_path / "nope.tlef")])
    assert r.returncode == 2
    assert "REFUSE" in r.stderr


def test_an_unreachable_image_is_not_a_clean_pdk(tmp_path):
    """`--from-image` on an image that cannot be opened is rc 2, never 0.

    The reference is deliberately MALFORMED rather than a real-looking tag:
    docker rejects it without a network round trip, and a version-shaped tag
    in a test file is a live image pointer the sync gate would then have to
    track to an image that will never exist.
    """
    r = _run(["--from-image", "--image", "not a valid image reference"])
    assert r.returncode == 2, r.stdout + r.stderr
    assert "REFUSE" in r.stderr


# --- MINWIDTH outranks WIDTH ----------------------------------------------

def test_minwidth_outranks_width(tmp_path):
    """`WIDTH` on a routing layer is the DEFAULT routing width; `MINWIDTH` is
    the minimum legal width, which is the rule this comparison is about.

    Latent on every PDK the image ships (66 routing layers state both and all
    66 are equal), so the fixture states them apart to exercise it at all —
    in BOTH directions, because a precedence that only ever silences findings
    would pass a test that only checks the quiet one.
    """
    # MINWIDTH 1.2 < the 1.42 patch: reading MINWIDTH clears it, reading the
    # 1.6 WIDTH would not.
    r, rep = _check(tmp_path, _VIA_FORM.replace(
        "  WIDTH 1.6 ;\n", "  MINWIDTH 1.2 ;\n  WIDTH 1.6 ;\n"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert rep["findings"] == []

    # MINWIDTH 1.8 > the 1.42 patch and > WIDTH: reading MINWIDTH fires it,
    # and names 1.8 rather than 1.6.
    r, rep = _check(tmp_path, _VIA_FORM.replace(
        "  WIDTH 1.6 ;\n", "  MINWIDTH 1.8 ;\n  WIDTH 1.6 ;\n"),
        name="hi.tlef")
    assert r.returncode == 1, r.stdout + r.stderr
    f = rep["findings"][0]
    assert f["layer_min_width_um"] == 1.8
    assert f["layer_min_width_from"] == "MINWIDTH"
