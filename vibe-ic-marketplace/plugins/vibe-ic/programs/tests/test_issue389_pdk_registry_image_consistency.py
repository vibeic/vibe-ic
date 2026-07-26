"""issue #389 — registry <-> EDA-image drift must be reported in BOTH
directions, and the newly-registered PDK entry must carry the keys that make a
TAPLESS PDK sign off correctly.

Two things are pinned here:

  1. `pdk_registry_image_consistency_check` finds a PDK the image ships but the
     registry omits (the condition that produced #389 and went unreported for
     several releases), AND the reverse — a registry entry whose assets are not
     in the image. A one-directional check would have stayed green on the
     reverse case.

  2. The `ihp-sg13cmos5l` entry itself. `tapcell_master` must be explicitly
     null and `tap_geom_layers` must be present: WITHOUT the geometry keys the
     tapless-cell latch-up screen has nothing to measure and reports a
     FALSE-POSITIVE PERC FAIL. That was diagnosed and fixed once on the sibling
     PDK and did not transfer, because this PDK had no entry at all.

The consistency-check tests drive the image through injected enumerators, so
they run WITHOUT docker and assert the CHECKER'S LOGIC. A separate test runs
the real docker path when — and only when — the pinned image is present, and
skips (never silently passes) when it is not.

chip-AGNOSTIC: the logic tests use fixture PDK names; only the registry-content
tests name the PDK they are about, which is the artefact under test.
"""
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import pdk_registry_image_consistency_check as C  # noqa: E402

REAL_REGISTRY = PROGRAMS / "pdk_registry.json"
PDK_UNDER_TEST = "ihp-sg13cmos5l"


def _write_registry(tmp_path, entries):
    f = tmp_path / "pdk_registry.json"
    f.write_text(json.dumps({"schema_version": 1, "pdks": entries}))
    return f


@pytest.fixture
def fake_image(monkeypatch):
    """Drive the checker from an in-memory image listing."""
    state = {"pdks": [], "dirs": set()}

    def _dirs(image, pdk_root, timeout=180):
        return sorted(state["pdks"]), ""

    def _isdir(image, path, timeout=120):
        return path in state["dirs"]

    monkeypatch.setattr(C, "_image_pdk_dirs", _dirs)
    monkeypatch.setattr(C, "_image_path_is_dir", _isdir)
    return state


# ---------------------------------------------------------------------------
# Direction A — shipped but unregistered (the #389 precondition).
# ---------------------------------------------------------------------------

def test_reports_shipped_but_unregistered(tmp_path, fake_image):
    fake_image["pdks"] = ["alpha-pdk", "beta-pdk"]
    fake_image["dirs"] = {"/foss/pdks/alpha-pdk", "/foss/pdks/beta-pdk"}
    reg = _write_registry(tmp_path, [
        {"name": "alpha-pdk", "container_path": "/foss/pdks/alpha-pdk"}])
    rep = C.check(reg, "fake:image")
    assert rep["verdict"] == "INCONSISTENT"
    assert rep["shipped_but_unregistered"] == ["beta-pdk"]
    assert rep["registered_but_absent"] == []


# ---------------------------------------------------------------------------
# Direction B — registered but absent. Without this the check would be
# one-directional and a stale entry would stay green.
# ---------------------------------------------------------------------------

def test_reports_registered_but_absent(tmp_path, fake_image):
    fake_image["pdks"] = ["alpha-pdk"]
    fake_image["dirs"] = {"/foss/pdks/alpha-pdk"}
    reg = _write_registry(tmp_path, [
        {"name": "alpha-pdk", "container_path": "/foss/pdks/alpha-pdk"},
        {"name": "ghost-pdk", "container_path": "/foss/pdks/ghost-pdk"}])
    rep = C.check(reg, "fake:image")
    assert rep["verdict"] == "INCONSISTENT"
    assert rep["registered_but_absent"] == ["ghost-pdk"]
    assert rep["shipped_but_unregistered"] == []


def test_clean_registry_is_consistent(tmp_path, fake_image):
    fake_image["pdks"] = ["alpha-pdk"]
    fake_image["dirs"] = {"/foss/pdks/alpha-pdk"}
    reg = _write_registry(tmp_path, [
        {"name": "alpha-pdk", "container_path": "/foss/pdks/alpha-pdk"}])
    rep = C.check(reg, "fake:image")
    assert rep["verdict"] == "CONSISTENT"


def test_placeholder_entry_is_exempt_structurally(tmp_path, fake_image):
    """An entry with no container_path describes auto-detect heuristics, not a
    shipped asset tree. It must be exempt by the ABSENCE OF THE FIELD, so the
    exemption needs no name allow-list to maintain."""
    fake_image["pdks"] = ["alpha-pdk"]
    fake_image["dirs"] = {"/foss/pdks/alpha-pdk"}
    reg = _write_registry(tmp_path, [
        {"name": "alpha-pdk", "container_path": "/foss/pdks/alpha-pdk"},
        {"name": "some_placeholder_entry"}])
    rep = C.check(reg, "fake:image")
    assert rep["verdict"] == "CONSISTENT"
    assert rep["placeholder_entries_exempt"] == ["some_placeholder_entry"]


def test_uninspectable_image_is_indeterminate_not_pass(tmp_path, monkeypatch):
    """An image that cannot be read must NOT read as CONSISTENT. A check that
    reports success when it verified nothing is worse than no check."""
    monkeypatch.setattr(C, "_image_pdk_dirs",
                        lambda i, r, timeout=180: (None, "image absent"))
    reg = _write_registry(tmp_path, [
        {"name": "alpha-pdk", "container_path": "/foss/pdks/alpha-pdk"}])
    rep = C.check(reg, "fake:image")
    assert rep["verdict"] == "INDETERMINATE"
    assert "shipped_but_unregistered" not in rep


def test_pdk_detection_is_structural_not_a_name_allow_list(monkeypatch):
    """The shell probe must select on BOTH marker dirs. A looser test (any
    subdirectory) fires on the PDK-manager cache dir and on stray files, and a
    check that fires on non-defects gets ignored."""
    captured = {}

    def _fake_run(cmd, capture_output, text, timeout):
        captured["script"] = cmd[-1]

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""
        return _R()

    monkeypatch.setattr(C.subprocess, "run", _fake_run)
    C._image_pdk_dirs("fake:image", "/foss/pdks")
    for marker in C.PDK_MARKER_DIRS:
        assert f'"$d/{marker}"' in captured["script"]
    assert " -a " in captured["script"], "markers must be ANDed, not ORed"


# ---------------------------------------------------------------------------
# The registry entry this issue added.
# ---------------------------------------------------------------------------

def _entry(name):
    reg = json.loads(REAL_REGISTRY.read_text())
    for e in reg["pdks"]:
        if e.get("name") == name:
            return e
    return None


def test_pdk_under_test_is_registered():
    """The shipped-but-unregistered condition itself. Fails on any tree where
    the entry was never added."""
    assert _entry(PDK_UNDER_TEST) is not None, (
        f"{PDK_UNDER_TEST} ships in the EDA image but has no registry entry")


def test_entry_declares_tapcell_master_explicitly_null():
    """This PDK ships no tap master (its own librelane config says so). The key
    must be PRESENT and null: absent would let a default leak in, and a
    non-null value would name a cell that does not exist in this library."""
    e = _entry(PDK_UNDER_TEST)
    assert "tapcell_master" in e
    assert e["tapcell_master"] is None


def test_entry_declares_tap_geom_layers():
    """Missing geometry keys are the known cause of a FALSE-POSITIVE PERC
    latch-up FAIL on a tapless PDK — the screen has nothing to measure."""
    e = _entry(PDK_UNDER_TEST)
    tg = e.get("tap_geom_layers")
    assert isinstance(tg, dict), "tap_geom_layers missing"
    for key in ("nwell", "pplus", "poly", "activ"):
        assert key in tg, f"tap_geom_layers lacks {key!r}"
        assert "/" in str(tg[key]), f"{key} must be a layer/datatype pair"
    assert tg.get("implicit_implant"), "implicit_implant must be stated"


def test_entry_does_not_declare_an_implant_layer_the_library_never_draws():
    """The implicit implant must NOT also be declared as an explicit layer.

    MEASURED on this PDK's own std-cell GDS: the N+ layer 7/0 is absent from
    the file entirely (activ 475 / gatpoly 453 / psd 172 / nwell 86 shapes are
    present). N+ is implied as (activ - pplus). An entry that declares BOTH
    implicit_implant=nplus AND an explicit nplus layer aims the latch-up screen
    at geometry that is never drawn — reintroducing the false-positive PERC
    FAIL these keys exist to remove. An independently-derived draft of this
    entry did exactly that, which is why it is asserted rather than assumed."""
    tg = _entry(PDK_UNDER_TEST)["tap_geom_layers"]
    implicit = tg.get("implicit_implant")
    assert implicit, "implicit_implant must be stated"
    assert implicit not in tg, (
        f"{implicit!r} is declared as the IMPLICIT implant but also appears as "
        f"an explicit layer key ({implicit}={tg.get(implicit)!r}) — the "
        f"library does not draw it")


def test_entry_declares_its_own_assets_not_a_siblings():
    """Every declared asset must live under this PDK's own container_path. A
    copied sibling entry would point at the sibling's tree — the exact
    wrong-PDK failure this issue is about."""
    e = _entry(PDK_UNDER_TEST)
    root = e["container_path"]
    assert root.endswith(PDK_UNDER_TEST)
    for key in ("liberty_glob", "tech_lef_glob", "cell_lef_glob",
                "cell_gds_glob", "drc_deck", "lvs_deck", "lefdef_layermap"):
        val = e.get(key)
        assert val, f"{key} not declared"
        assert not val.startswith("/"), f"{key} must be relative to the root"
        # the sibling's library stem must not appear in this entry's paths
        assert "sg13g2" not in val, (
            f"{key}={val!r} names the SIBLING library — copied, not derived")


def test_entry_does_not_declare_a_pdn_layer_absent_from_its_stack():
    """This PDK's stack is M1-M4-TM1 — it has no TopMetal2. A strap plan copied
    from the sibling would name a layer that does not exist here."""
    e = _entry(PDK_UNDER_TEST)
    straps = e.get("pdn_straps")
    if straps is None:
        return                     # auto-derived from the tech LEF: correct
    layers = {s.get("layer") for s in straps.get("stripes", [])}
    for pair in straps.get("connects", []):
        layers.update(pair)
    assert "TopMetal2" not in layers, (
        "TopMetal2 is not in this PDK's metal stack")


def test_real_image_registry_consistency():
    """The live both-directions sweep against the pinned image.

    SKIPS (never silently passes) when the image is not present locally, so an
    absent image cannot be mistaken for a clean result."""
    image = C._resolve_image(None)
    if not image:
        pytest.skip("no EDA image resolvable")
    names, err = C._image_pdk_dirs(image, C.DEFAULT_PDK_ROOT)
    if names is None:
        pytest.skip(f"pinned image not inspectable here: {err}")
    rep = C.check(REAL_REGISTRY, image)
    assert rep["verdict"] == "CONSISTENT", (
        f"registry/image drift: "
        f"shipped_but_unregistered={rep['shipped_but_unregistered']}, "
        f"registered_but_absent={rep['registered_but_absent']}")
