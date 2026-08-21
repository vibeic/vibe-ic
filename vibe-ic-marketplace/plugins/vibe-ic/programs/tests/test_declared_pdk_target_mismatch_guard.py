"""The PDK actually loaded must match the PDK the design DECLARES.

Regression tests for `declared_pdk_target_guard`.

Shape of the defect this covers (chip-AGNOSTIC): Phase 1 records the PDK
target a design adopts. Phase 3 resolves a PDK independently and never
compares the two. When the resolved PDK is an open-source in-container
enablement and the design declared a different target, every downstream
verdict — timing, DRC, LVS, antenna, GDS streamout, foundry handoff — is
computed against a std-cell library the design never declared, and the run
says nothing.

The pre-existing `commercial_pdk_fallback_guard` does NOT cover this: it keys
on HOST config, and it returns None the moment `--pdk` names something
explicitly. An explicit `--pdk <oss-name>` is precisely how a contradicting
PDK is usually introduced, so this guard is deliberately indifferent to how
the PDK was selected.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phase3_one_shot_runner as p3  # noqa: E402


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _declare(project: Path, target, via="staging_read"):
    """Write a Phase-1 declared PDK target into the project."""
    if via == "staging_read":
        d = project / "reports" / "phase1"
        d.mkdir(parents=True, exist_ok=True)
        (d / "pdk_staging_read.json").write_text(
            json.dumps({"adopted_pdk_target": target}))
    else:
        d = project / "phase1" / "generated_docs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "L19_CONSTRAINTS_PDK.json").write_text(
            json.dumps({"fields": {"pdk_target": target}}))


# --------------------------------------------------------------------------
# NEGATIVE — the guard must FIRE
# --------------------------------------------------------------------------
def test_negative_resolved_oss_contradicts_declared_target(tmp_path):
    """The core case: design declares one target, an OSS PDK resolved."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _declare(proj, "Some Foundry ABC123-X1.0")
    msg = p3.declared_pdk_target_guard(proj, "sky130A")
    assert msg is not None
    assert "REFUSED" in msg
    assert "sky130A" in msg                        # names what resolved
    assert "--allow-pdk-target-mismatch" in msg    # names the escape hatch


def test_negative_fires_for_every_oss_enablement(tmp_path):
    """Not sky130-specific — any in-container OSS enablement is refused."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _declare(proj, "Some Foundry ABC123-X1.0")
    for name in p3._OSS_CONTAINER_PDKS:
        assert p3.declared_pdk_target_guard(proj, name) is not None, name


def test_negative_explicit_override_does_NOT_excuse_the_mismatch(tmp_path):
    """THE REGRESSION THIS PR EXISTS FOR.

    Naming the PDK explicitly is how a contradicting PDK gets introduced. The
    guard takes no argument for the override at all, so there is no lane in
    which an explicit selection can silence it.
    """
    proj = tmp_path / "proj"
    proj.mkdir()
    _declare(proj, "Some Foundry ABC123-X1.0")
    # The sibling guard is satisfied by an explicit override ...
    assert p3.commercial_pdk_fallback_guard(
        proj, "sky130A", "sky130A", commercial_configured=True) is None
    # ... this one is NOT.
    assert p3.declared_pdk_target_guard(proj, "sky130A") is not None


def test_negative_declared_via_l19_is_equally_binding(tmp_path):
    """The L-doc is a valid declaration source when the staging record is
    absent."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _declare(proj, "Some Foundry ABC123-X1.0", via="l19")
    assert p3.declared_pdk_target_guard(proj, "nangate45") is not None


def test_negative_fires_with_no_host_commercial_config(tmp_path):
    """Keyed on the DESIGN's declaration, not on host config — so it protects
    a design on a host where nothing is configured."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _declare(proj, "Some Foundry ABC123-X1.0")
    # Host-config-keyed guard stays silent here ...
    assert p3.commercial_pdk_fallback_guard(
        proj, "sky130A", "auto", commercial_configured=False) is None
    # ... declaration-keyed guard still refuses.
    assert p3.declared_pdk_target_guard(proj, "sky130A") is not None


# --------------------------------------------------------------------------
# POSITIVE — the guard must stay SILENT
# --------------------------------------------------------------------------
def test_positive_design_declares_the_pdk_that_resolved(tmp_path):
    """A design that declares the OSS PDK it got is correct, not a mismatch."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _declare(proj, "sky130A")
    assert p3.declared_pdk_target_guard(proj, "sky130A") is None


def test_positive_declared_target_naming_the_pdk_in_prose(tmp_path):
    """Containment, not equality — a target that names the PDK among other
    words still matches."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _declare(proj, "sky130A (SkyWater 130nm, 1.8V)")
    assert p3.declared_pdk_target_guard(proj, "sky130A") is None


def test_positive_design_declares_nothing(tmp_path):
    """A design that expressed no preference cannot be contradicted."""
    proj = tmp_path / "proj"
    proj.mkdir()
    assert p3.declared_pdk_target_guard(proj, "sky130A") is None
    _declare(proj, None)
    assert p3.declared_pdk_target_guard(proj, "sky130A") is None
    _declare(proj, "   ")
    assert p3.declared_pdk_target_guard(proj, "sky130A") is None


def test_positive_project_staged_pdk_resolved(tmp_path):
    """A `custom:<dir>` resolution means nothing was substituted."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _declare(proj, "Some Foundry ABC123-X1.0")
    assert p3.declared_pdk_target_guard(proj, "custom:pdk") is None


def test_positive_explicit_written_acknowledgement(tmp_path):
    """The operator may accept the mismatch in writing."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _declare(proj, "Some Foundry ABC123-X1.0")
    assert p3.declared_pdk_target_guard(
        proj, "sky130A", allow_mismatch=True) is None


def test_positive_unknown_resolution_is_not_judged(tmp_path):
    """No resolved name, or a non-OSS name, is out of scope."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _declare(proj, "Some Foundry ABC123-X1.0")
    assert p3.declared_pdk_target_guard(proj, None) is None
    assert p3.declared_pdk_target_guard(proj, "") is None


def test_positive_unreadable_declaration_does_not_crash(tmp_path):
    """Malformed Phase-1 records degrade to 'no declaration', never a crash."""
    proj = tmp_path / "proj"
    (proj / "reports" / "phase1").mkdir(parents=True)
    (proj / "reports" / "phase1" / "pdk_staging_read.json").write_text("{ not json")
    assert p3.declared_pdk_target_guard(proj, "sky130A") is None


# --------------------------------------------------------------------------
# NDA / hygiene
# --------------------------------------------------------------------------
def test_refusal_message_never_prints_the_declared_identifier(tmp_path):
    """The declared target may be under NDA — the message must describe the
    disagreement without quoting it."""
    proj = tmp_path / "proj"
    proj.mkdir()
    secret = "Some Foundry ABC123-X1.0"
    _declare(proj, secret)
    msg = p3.declared_pdk_target_guard(proj, "sky130A")
    assert msg is not None
    assert secret not in msg
    for tok in ("ABC123", "X1.0", "Some Foundry"):
        assert tok not in msg
    # but it MUST point at where the identifier can be read
    assert "pdk_staging_read.json" in msg


@pytest.mark.parametrize("declared,resolved,fires", [
    ("sky130A", "sky130A", False),
    ("sky130B", "sky130A", True),
    ("gf180mcuD", "gf180mcuD", False),
    ("gf180mcuD", "sky130A", True),
])
def test_matrix_declared_vs_resolved(tmp_path, declared, resolved, fires):
    """Two OSS PDKs disagreeing with each other is the same defect."""
    proj = tmp_path / f"p_{declared}_{resolved}"
    proj.mkdir()
    _declare(proj, declared)
    got = p3.declared_pdk_target_guard(proj, resolved)
    assert (got is not None) is fires
