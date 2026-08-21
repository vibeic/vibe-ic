"""vibe-ic#789 — a sign-off DRC verdict must never be computed on a GDS that
was streamed with legacy (compact) LEF/DEF layer numbering.

THE DEFECT
----------
All of the streamout-layermap guards were keyed on ``pdk.calibre_drc`` — i.e.
on *the sign-off deck being a commercial Calibre deck*. That is a VENDOR test
standing in for a physical one, and the physics is vendor-free:

  GDSII stores no layer NAMES. A shape carries only an integer layer/datatype
  pair. Every DRC deck that reads a GDS therefore binds its rules to layer
  NUMBERS — KLayout DSL ``input(19, 0)`` / ``polygons(1, 0)``, SVRF
  ``LAYER MAP <gds> DATATYPE <dt> <id>``.

So a PDK whose sign-off deck is a KLayout ``.lydrc`` has ``calibre_drc=None``,
slipped every guard, and streamed on the LEF/DEF reader's own compact numbering
— silently, with a PASS on the ``gds`` step and a DRC number afterwards that is
neither a pass nor a violation count.

Measured in the shipped image (``ghcr.io/vibeic/vibeic-eda:0.2.63``):
  * ``/foss/pdks/asap7/libs.tech/klayout/drc/asap7.lydrc`` exists and selects
    every layer BY NUMBER (``input(7,0)`` GATE, ``input(19,0)`` M1,
    ``input(20,0)`` M2, ``input(30,0)`` M3 …), while NO ``asap7*.map`` exists
    anywhere under ``/foss/pdks`` and ``pdk_registry.json`` configures none.
    ``LEFDEF_MAP`` resolved to ``""`` → silent legacy numbering.
  * Streaming a DEF that routes M1/M2/M3 through the REAL streamout script
    with the REAL asap7 LEFs and ``LEFDEF_MAP=""`` (klayout in that image)
    lands the geometry on GDS ``1/0 12/0 14/0 16/0``. The PDK's own
    ``asap7.lyt`` declares M1/M2/M3 = ``19/0 20/0 30/0``, and NOTHING was
    written there. The deck still runs, still reads real numbers, and reads
    every routed shape as some other layer's purpose — ``14/0`` is not even
    in the deck's input set. That verdict is neither a pass nor a count.
  * ``/foss/pdks/nangate45/libs.tech/klayout/drc/FreePDK45.lydrc`` likewise
    (``polygons(1, 0)`` …); its DRC on a legacy-numbered GDS reported
    7,911,144 phantom IMPLANT/VT/CONTACT items.
  * ``sky130A.map`` and ``gf180mcu.map`` DO ship → those PDKs are unaffected.

THE FIX
-------
``_signoff_drc_deck(calibre_drc, klayout_drc)`` — no new discovery, it reads
the SAME two fields ``step_drc`` dispatches on — and the guards ask "is there a
deck", never "is the deck Calibre".

COMPOSITION WITH #785
---------------------
#785 closes the *configured-but-absent* map (a path is set, the file is not
there) inside the streamout script. This closes the *nothing configured at all*
map for a deck-present PDK, at the step level, before the script runs. The two
are disjoint by construction and both are proven here.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _pdk(**kw):
    base = dict(name="t", liberty="l", tech_lef="t.lef", cell_lef="c.lef",
                cell_gds="c.gds", site="s", drc_deck=None, metal_prefix="met")
    base.update(kw)
    return R.PdkConfig(**base)


def _run_step_gds(tmp_path, monkeypatch, pdk):
    """Drive the REAL ``step_gds`` far enough to reach (or pass) the streamout
    layermap pre-flight gate. Magic streamout and docker are stubbed out so the
    gate is the only thing that can decide the verdict; everything after it
    fails for want of a tool, which is exactly how we tell "gated" from
    "not gated"."""
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "top.def").write_text("DESIGN top ;\nEND DESIGN\n")
    monkeypatch.setattr(R._pl, "pnr_dir", lambda _p: pnr)
    monkeypatch.setattr(R, "_magic_def_to_gds",
                        lambda *a, **k: (False, "no magic"))
    monkeypatch.setattr(R, "_docker_exec", lambda *a, **k: (1, "", "no tool"))
    return R.step_gds(tmp_path, "top", pdk, "container")


_MAP_REASON = "streamout layer map missing"


# ---------------------------------------------------------------------------
# THE REGRESSION. Fails before the fix (a KLayout-deck PDK with no map was
# waved through), passes after.
# ---------------------------------------------------------------------------
def test_klayout_deck_without_map_now_fails(tmp_path, monkeypatch):
    res = _run_step_gds(tmp_path, monkeypatch,
                        _pdk(calibre_drc=None,
                             drc_deck="/pdk/libs.tech/klayout/drc/x.lydrc",
                             lefdef_layermap=None))
    assert res.status == "FAIL"
    assert _MAP_REASON in res.detail
    # the message must name the deck that will actually run, so the operator
    # can go and look at it
    assert "x.lydrc" in res.detail
    assert res.extras.get("signoff_drc_deck") == \
        "/pdk/libs.tech/klayout/drc/x.lydrc"


def test_klayout_deck_with_map_is_untouched(tmp_path, monkeypatch):
    """The map is what makes the verdict meaningful; having one is the whole
    point. A KLayout-deck PDK that ships its map must NOT be newly gated."""
    res = _run_step_gds(tmp_path, monkeypatch,
                        _pdk(calibre_drc=None,
                             drc_deck="/pdk/libs.tech/klayout/drc/x.lydrc",
                             lefdef_layermap="/pdk/libs.tech/klayout/tech/x.map"))
    assert _MAP_REASON not in res.detail


def test_no_deck_at_all_is_untouched(tmp_path, monkeypatch):
    """A project with NO sign-off deck runs no DRC, so there is no verdict for
    the numbering to corrupt. It must stay ungated — failing it would be
    inventing a requirement out of nothing."""
    res = _run_step_gds(tmp_path, monkeypatch,
                        _pdk(calibre_drc=None, drc_deck=None,
                             lefdef_layermap=None))
    assert _MAP_REASON not in res.detail


def test_configured_but_absent_map_is_NOT_this_gate(tmp_path, monkeypatch):
    """COMPOSITION BOUNDARY WITH #785 — pinned so the two fixes cannot drift
    into each other.

    This gate is keyed on ``lefdef_layermap`` being UNSET. A map that IS set
    but whose file is missing (nangate45's ``FreePDK45.map``, which no image
    ships) is a DIFFERENT state: the config is complete, the asset is not.
    It must NOT be caught here — it is caught inside the streamout script by
    #785's ``CONFIGURED_BUT_ABSENT`` exit(7), which is the only place that can
    see the container-side filesystem. Failing it here as well would make the
    two guards report the same run under two different diagnoses.

    Between them the two are exhaustive over "the map is not usable":
    unset -> here, set-but-absent -> #785, set-and-present -> streamout runs."""
    res = _run_step_gds(tmp_path, monkeypatch,
                        _pdk(calibre_drc=None,
                             drc_deck="/pdk/libs.tech/klayout/drc/x.lydrc",
                             lefdef_layermap="/pdk/does/not/exist.map"))
    assert _MAP_REASON not in res.detail


def test_calibre_deck_without_map_still_fails(tmp_path, monkeypatch):
    """The pre-existing commercial case is a strict subset of the new one and
    must keep behaving identically."""
    res = _run_step_gds(tmp_path, monkeypatch,
                        _pdk(calibre_drc="/pdk/calibre/KF_DRC.rule",
                             drc_deck=None, lefdef_layermap=None))
    assert res.status == "FAIL"
    assert _MAP_REASON in res.detail
    assert "KF_DRC.rule" in res.detail


# ---------------------------------------------------------------------------
# The predicate itself: deck-PRESENCE, never vendor. Driven with a table so no
# single PDK, vendor or deck filename is load-bearing.
# ---------------------------------------------------------------------------
def test_predicate_is_presence_not_vendor(tmp_path, monkeypatch):
    table = [
        # (calibre_drc, klayout_drc, map, expect_gated)
        (None, None, None, False),                     # deckless  -> open
        (None, None, "/m.map", False),                 # deckless  -> open
        ("/d.rule", None, None, True),                 # SVRF deck -> gated
        (None, "/d.lydrc", None, True),                # DSL  deck -> gated
        (None, "/d.drc", None, True),                  # DSL  deck -> gated
        ("/d.rule", "/d.lydrc", None, True),           # both      -> gated
        ("/d.rule", None, "/m.map", False),            # mapped    -> open
        (None, "/d.lydrc", "/m.map", False),           # mapped    -> open
    ]
    for cal, kl, mp, gated in table:
        res = _run_step_gds(tmp_path, monkeypatch,
                            _pdk(calibre_drc=cal, drc_deck=kl,
                                 lefdef_layermap=mp))
        assert (_MAP_REASON in res.detail) is gated, (cal, kl, mp)


def test_predicate_names_no_pdk_or_vendor():
    """PDK-AGNOSTIC by construction: the decision function reads only its two
    arguments. Its source may not contain a PDK/vendor/layer literal."""
    import inspect
    src = inspect.getsource(R._signoff_drc_deck)
    body = src.split('"""')[-1]          # exclude the explanatory docstring
    for literal in ("sky130", "gf180", "nangate", "asap7", "FreePDK",
                    "calibre_drc ==", "metal1", "li1", "ihp"):
        assert literal not in body, literal


# ---------------------------------------------------------------------------
# Corpus proof over the PDKs this runner actually ships, derived from the
# runner's OWN resolution (pdk_registry.json + the named branches) rather than
# from a hand-written expectation table.
# ---------------------------------------------------------------------------
def _resolve_named_pdk(monkeypatch, tmp_path, name):
    """Run the REAL ``_detect_pdk`` for a named PDK with only the
    container-dependent staging stubbed, so the deck/map wiring under test is
    the shipped wiring."""
    monkeypatch.setattr(R, "_discover_local_macros",
                        lambda *a, **k: ([], [], [], []))
    monkeypatch.setattr(R, "_stage_asap7_merged_liberty",
                        lambda project, container, reg: Path("/x/merged.lib"))
    monkeypatch.setattr(R, "_stage_normalized_techlef",
                        lambda project, container, reg: Path("/x/norm.tlef"))
    # "the asset the registry declares exists in the image" — the registry is
    # the authority for WHICH assets a PDK has, which is what we are auditing.
    monkeypatch.setattr(
        R, "_registry_glob_one",
        lambda container, root, pattern, *a, **k: (
            f"{root}/{pattern}" if pattern else None))
    monkeypatch.setattr(R, "_docker_exec_raw", lambda *a, **k: (0, "", ""))
    return R._detect_pdk(tmp_path, override=name)


def test_shipped_pdks_are_gated_iff_deck_without_map(tmp_path, monkeypatch):
    """For every PDK the runner can name, the gate must fire exactly when the
    resolved config has a sign-off deck and no streamout layermap. No PDK name
    appears in the assertion — the expectation is DERIVED from the resolved
    config, so the test cannot drift from the wiring."""
    names = R._known_pdk_names()
    assert names, "runner declared no resolvable PDK names"
    seen = {}
    for name in names:
        try:
            pdk = _resolve_named_pdk(monkeypatch, tmp_path / name, name)
        except SystemExit:
            continue          # placeholder entry with no assets (auto-detect)
        if pdk is None:
            continue
        deck = R._signoff_drc_deck(pdk.calibre_drc, pdk.drc_deck)
        expect_gated = bool(deck) and not pdk.lefdef_layermap
        res = _run_step_gds(tmp_path / name, monkeypatch, pdk)
        assert (_MAP_REASON in res.detail) is expect_gated, (
            f"{name}: deck={deck} map={pdk.lefdef_layermap} "
            f"detail={res.detail[:200]}")
        seen[name] = expect_gated
    # The corpus must actually EXERCISE both directions, or the loop above
    # proves nothing.
    assert any(seen.values()), f"no shipped PDK exercised the gate: {seen}"
    assert not all(seen.values()), f"every shipped PDK gated: {seen}"
