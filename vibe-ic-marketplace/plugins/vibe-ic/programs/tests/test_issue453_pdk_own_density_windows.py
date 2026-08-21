#!/usr/bin/env python3
"""The metal-density gate must judge a run by ITS PDK's own stated window.

Two defects, one root. The gate accepts per-layer windows and honestly discloses
that its built-in [0.30, 0.70] is a generic stand-in — and nothing ever supplied
one. `signoff_ladder_run` passed a literal `{}`, and no caller in the tree passed
`--windows`, so every run on every process was judged by the generic default
while the foundry's real numbers sat unread in the PDK tree. MEASURED against one
open PDK's own sign-off script, the generic window is wider on BOTH sides than
what that PDK enforces, so a design its foundry would reject could clear us.

The second defect is the mirror of the one the producer/consumer parity file
covers: one layer was being MEASURED and then dropped by the consumer's
layer-name filter, so its density reached the report with no verdict on it.

Order matters and is asserted here as behaviour, not as a comment: judging that
layer against the generic 30% floor when its PDK states 35% would have been a
new wrong answer replacing a missing one.

What these tests pin:
  1. every PDK's stated windows are the numbers MEASURED out of that PDK's own
     files, including the top-layer exception one of them makes;
  2. a PDK that states only one bound gets that bound honoured and the other
     bound labelled generic — separately, so the verdict cannot read as fully
     foundry-judged;
  3. a PDK that states NOTHING is recorded as stating nothing, and an UNKNOWN
     PDK is never judged by some other PDK's numbers;
  4. the ladder actually supplies them, resolving the PDK from the artifact
     first and the environment second;
  5. the previously-dropped layer is judged, against its PDK's window.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import metal_layer_density_check as MLD  # noqa: E402
import pdk_metal_density_windows as PMDW  # noqa: E402
import signoff_ladder_run as SLR  # noqa: E402

# The registry keys, kept out of the gate sources. These are data keys, and the
# numbers beside them below are the ones measured out of each PDK's own files.
_OPEN_A = "sky130A"        # states both bounds, with a top-layer exception
_OPEN_B = "gf180mcuD"      # states a minimum and NO maximum
_OPEN_C = "ihp-sg13g2"     # states both bounds, looser on its top layers
_OPEN_D = "asap7"          # states a window for ONE layer of its stack
_OPEN_E = "nangate45"      # states nothing at all


def _report(tmp_path: Path, layers: dict, **extra) -> Path:
    p = tmp_path / "metal_density.json"
    p.write_text(json.dumps({"layers": layers, **extra}))
    return p


def _project(tmp_path: Path, layers: dict, **extra) -> Path:
    d = tmp_path / "proj" / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "metal_density.json").write_text(json.dumps({"layers": layers, **extra}))
    return tmp_path / "proj"


# ── 1. the measured numbers ──────────────────────────────────────────────────

def test_the_windows_are_the_numbers_measured_from_each_pdk():
    """Pinned as data because they are FACTS about those PDKs, not choices. Each
    was read out of that PDK's own density source (and, for three of the five,
    corroborated against a second, independent source in the same tree)."""
    a, _ = PMDW.windows_for_pdk(_OPEN_A)
    assert a["met1"] == a["met2"] == a["met3"] == a["met4"] == (0.35, 0.60)
    assert a["li1"] == (0.35, 0.60), (
        "the local-interconnect layer is regulated identically to the first "
        "routing layers by this PDK — that is the fact this issue turned on")
    assert a["met5"] == (0.45, 0.76), (
        "the top routing layer is the EXCEPTION: a different window from the "
        "rest of the stack. Assuming the stack is uniform would judge it wrong "
        "at both ends")

    c, _ = PMDW.windows_for_pdk(_OPEN_C)
    assert all(c[f"metal{n}"] == (0.35, 0.60) for n in range(1, 6))
    assert c["topmetal1"] == c["topmetal2"] == (0.25, 0.70)

    d, _ = PMDW.windows_for_pdk(_OPEN_D)
    assert d == {"m5": (0.15, 0.90)}, (
        "this PDK states a window for exactly one layer of its stack; the rest "
        "must stay absent so the disclosed generic default covers them")


def test_a_pdk_that_states_only_a_minimum_gets_a_half_window():
    b, prov = PMDW.windows_for_pdk(_OPEN_B)
    assert all(b[f"metal{n}"] == (0.30, None) for n in range(1, 6))
    assert prov["status"] == "stated"
    assert set(prov["bounds_unstated"]) >= {f"metal{n}" for n in range(1, 6)}


def test_a_pdk_that_states_nothing_says_so_rather_than_looking_unread():
    e, prov = PMDW.windows_for_pdk(_OPEN_E)
    assert e == {}
    assert prov["status"] == "states-none", (
        "'read it, it states no rule' and 'nobody looked' both produce an empty "
        "table; the status is what tells them apart")
    assert "measured_from" in prov


def test_an_unknown_pdk_is_never_judged_by_another_pdks_numbers():
    for name in ("no-such-pdk", "", "custom_auto_detect"):
        w, prov = PMDW.windows_for_pdk(name)
        assert w == {}
        assert prov["status"] == "unknown-pdk"


# ── 2. half-stated windows are resolved and disclosed BOUND BY BOUND ─────────

def test_a_stated_minimum_beside_a_generic_maximum_is_labelled_as_both(tmp_path):
    """The dishonest simplification would be one `window_source` for the pair.
    A reader would then see a foundry name over a number we invented."""
    w, _ = PMDW.windows_for_pdk(_OPEN_B)
    res = MLD.check(_report(tmp_path, {"metal1": 0.45}), w, 0.30, 0.70)
    src = res["per_layer"]["metal1"]["window_source"]
    assert "min=supplied" in src and "max=generic-default" in src, src
    assert "generic" in res["window_note"] and "metal1" in res["window_note"]


def test_the_generic_note_still_fires_when_only_one_bound_is_generic(tmp_path):
    """The half-and-half layer is the one most likely to be misread as fully
    foundry-judged, so it is exactly the one the disclosure must not skip. A
    whole-string equality test on `window_source` would have dropped it."""
    w, _ = PMDW.windows_for_pdk(_OPEN_B)
    res = MLD.check(_report(tmp_path, {"metal1": 0.45}), w, 0.30, 0.70)
    assert res["verdict"] == "PASS"
    assert res.get("window_note"), "a generic bound decided this PASS, unsaid"


def test_a_fully_stated_window_is_not_mislabelled_generic(tmp_path):
    w, _ = PMDW.windows_for_pdk(_OPEN_A)
    res = MLD.check(_report(tmp_path, {"met1": 0.40}), w, 0.30, 0.70)
    assert res["per_layer"]["met1"]["window_source"] == "supplied"
    assert res.get("window_note") is None


def test_a_null_bound_with_no_default_is_UNCHECKED_not_a_pass(tmp_path):
    """§4.05: no rule on one side and nothing to fall back on is not a pass."""
    res = MLD.check(_report(tmp_path, {"metal1": 0.45}),
                    {"metal1": (0.30, None)}, None, None)
    assert res["verdict"] == "FAIL"
    assert res["per_layer"]["metal1"]["status"] == "UNCHECKED"


# ── 3. the verdicts that CHANGE (this is the point of the fix) ───────────────

@pytest.mark.parametrize("pdk,layer,density", [
    (_OPEN_A, "met1", 0.32),   # under the PDK floor, over the generic floor
    (_OPEN_A, "met1", 0.65),   # over the PDK ceiling, under the generic ceiling
    (_OPEN_C, "metal1", 0.32),
    (_OPEN_C, "metal1", 0.65),
])
def test_generic_window_passes_designs_the_pdk_rejects(pdk, layer, density,
                                                       tmp_path):
    """The false PASS this fix removes, measured at both ends of the window."""
    rpt = _report(tmp_path, {layer: density})
    assert MLD.check(rpt, {}, 0.30, 0.70)["verdict"] == "PASS"
    w, _ = PMDW.windows_for_pdk(pdk)
    assert MLD.check(rpt, w, 0.30, 0.70)["verdict"] == "FAIL"


@pytest.mark.parametrize("pdk,layer,density", [
    (_OPEN_A, "met5", 0.73),      # top layer: this PDK allows more than we did
    (_OPEN_C, "topmetal1", 0.27),  # top layers: this PDK allows less than we did
    (_OPEN_D, "m5", 0.85),
])
def test_generic_window_also_fails_designs_the_pdk_accepts(pdk, layer, density,
                                                           tmp_path):
    """The correction runs BOTH ways. A tighter-everywhere change would be easy
    to defend and would be wrong: three of these layers are legal at densities
    the generic window rejects, and calling them violations is also a false
    verdict."""
    rpt = _report(tmp_path, {layer: density})
    assert MLD.check(rpt, {}, 0.30, 0.70)["verdict"] == "FAIL"
    w, _ = PMDW.windows_for_pdk(pdk)
    assert MLD.check(rpt, w, 0.30, 0.70)["verdict"] == "PASS"


# ── 4. the ladder actually supplies them ────────────────────────────────────

def test_the_ladder_no_longer_passes_an_empty_window_map(tmp_path, monkeypatch):
    """The whole defect in one assertion: same artifact, same gate, and the
    verdict changes purely because the ladder now looks the windows up."""
    monkeypatch.delenv("PDK_VARIANT", raising=False)
    monkeypatch.delenv("PDK", raising=False)
    proj = _project(tmp_path, {"met1": 0.32}, pdk=_OPEN_A)
    t = SLR.check_tier_metal_density(proj)
    assert t.verdict == "FAIL"
    assert t.details["per_layer"]["met1"]["window"] == [0.35, 0.60]


def test_the_artifact_declares_its_own_pdk_and_that_wins_over_the_shell(
        tmp_path, monkeypatch):
    """A stored report read from a differently-configured shell must not be
    rejudged against whatever PDK that shell points at."""
    monkeypatch.setenv("PDK_VARIANT", _OPEN_C)
    proj = _project(tmp_path, {"met1": 0.32}, pdk=_OPEN_A)
    t = SLR.check_tier_metal_density(proj)
    assert t.details["per_layer"]["met1"]["window"] == [0.35, 0.60]
    assert _OPEN_A in t.notes and _OPEN_C not in t.notes


def test_the_environment_is_the_fallback_for_a_report_that_declares_nothing(
        tmp_path, monkeypatch):
    monkeypatch.setenv("PDK_VARIANT", _OPEN_A)
    proj = _project(tmp_path, {"met1": 0.32})
    t = SLR.check_tier_metal_density(proj)
    assert t.details["per_layer"]["met1"]["window"] == [0.35, 0.60]


def test_an_undeclarable_run_degrades_to_the_generic_default_and_says_so(
        tmp_path, monkeypatch):
    """Archived reports predate the declaration. They must keep working, keep
    their old verdict, and SAY that a generic window produced it."""
    monkeypatch.delenv("PDK_VARIANT", raising=False)
    monkeypatch.delenv("PDK", raising=False)
    proj = _project(tmp_path, {"met1": 0.32})
    t = SLR.check_tier_metal_density(proj)
    assert t.verdict == "PASS"
    assert t.details["per_layer"]["met1"]["window"] == [0.30, 0.70]
    assert "generic" in t.notes


def test_the_tier_names_whose_numbers_judged_it_even_on_a_pass(tmp_path,
                                                              monkeypatch):
    """A PASS under a foundry window and a PASS under our stand-in are different
    claims; a reader who cannot tell them apart cannot weigh the tier."""
    monkeypatch.delenv("PDK_VARIANT", raising=False)
    monkeypatch.delenv("PDK", raising=False)
    proj = _project(tmp_path, {"met1": 0.40}, pdk=_OPEN_A)
    t = SLR.check_tier_metal_density(proj)
    assert t.verdict == "PASS"
    assert _OPEN_A in t.notes and "own stated" in t.notes


def test_a_half_stated_pdk_has_its_unstated_bound_called_out_in_the_tier(
        tmp_path, monkeypatch):
    monkeypatch.delenv("PDK_VARIANT", raising=False)
    monkeypatch.delenv("PDK", raising=False)
    proj = _project(tmp_path, {"metal1": 0.45}, pdk=_OPEN_B)
    t = SLR.check_tier_metal_density(proj)
    assert t.verdict == "PASS"
    assert "states no bound" in t.notes and "metal1" in t.notes


# ── 5. the dropped layer, judged — and judged against the RIGHT number ───────

def test_the_local_interconnect_layer_is_now_judged(tmp_path, monkeypatch):
    """It was measured and discarded: a number in the report that no verdict
    ever touched."""
    monkeypatch.delenv("PDK_VARIANT", raising=False)
    monkeypatch.delenv("PDK", raising=False)
    proj = _project(tmp_path, {"li1": 0.22, "met1": 0.40}, pdk=_OPEN_A)
    t = SLR.check_tier_metal_density(proj)
    assert "li1" in t.details["per_layer"]
    assert t.details["per_layer"]["li1"]["status"] == "FAIL"
    assert t.verdict == "FAIL"


def test_the_order_of_the_two_fixes_is_load_bearing(tmp_path):
    """Judging the newly-visible layer against the generic 30% floor would have
    replaced a missing verdict with a wrong one. This density is legal under the
    generic window and a violation under the window its PDK actually states —
    doing the layer first and the windows later would have shipped the PASS."""
    rpt = _report(tmp_path, {"li1": 0.32})
    assert MLD.check(rpt, {}, 0.30, 0.70)["verdict"] == "PASS"
    w, _ = PMDW.windows_for_pdk(_OPEN_A)
    assert MLD.check(rpt, w, 0.30, 0.70)["verdict"] == "FAIL"


def test_every_place_that_recognises_a_layer_name_recognises_the_same_names():
    """Three separate restatements of the layer-name shape used to live in this
    gate (the filter, the .rpt scraper, the flat-key matcher) plus a fourth in
    the producer. The scraper and the flat-key matcher had ALREADY fallen behind
    the filter — neither knew the `cap*metal` spelling the filter accepts."""
    for name in ("met1", "metal1", "m1", "topmetal1", "capmetal1", "li1"):
        assert MLD._METAL_RE.match(name), name
        assert MLD._FLAT_KEY_RE.match(f"{name}_density"), name
        assert MLD._RPT_LINE_RE.search(f"{name} density = 42.0%"), name


def test_the_flat_key_and_rpt_paths_reach_the_same_verdict(tmp_path):
    """Same measurement, three report shapes, one answer. A layer recognised on
    one path and dropped on another is the same class of bug as the one this
    issue is about, one layer down."""
    w, _ = PMDW.windows_for_pdk(_OPEN_A)
    nested = _report(tmp_path, {"li1": 0.22})
    flat = tmp_path / "flat.json"
    flat.write_text(json.dumps({"li1_density": 0.22}))
    rpt = tmp_path / "scraped.rpt"
    rpt.write_text("li1 density = 22.0%\n")
    verdicts = {p.name: MLD.check(p, w, 0.30, 0.70) for p in (nested, flat, rpt)}
    for name, res in verdicts.items():
        assert res["verdict"] == "FAIL", name
        assert res["per_layer"]["li1"]["density"] == pytest.approx(0.22), name


# ── the artifact has to carry the PDK, or none of the above fires ───────────

class _FakeRegion:
    def __init__(self, area):
        self._a = area

    # vibe-ic#990 — the recipe now measures a SET of (layer, datatype) specs
    # per metal layer, so it starts from an empty region and joins one region
    # per spec. Both are real KLayout API (`Region()` is the documented empty
    # constructor, `Region#+` is join); this fake grew the two calls the recipe
    # makes rather than the recipe being bent around the fake.
    #
    # Adding AREAS is faithful here only because this fake hands every layer
    # the same constant and models no geometry at all — there is nothing to
    # overlap. The recipe's real correctness on overlapping shapes is measured
    # against a genuine GDSII stream in
    # `test_issue990_density_counts_the_dummy_fill_datatype`, whose stand-in
    # computes an exact union.
    def __add__(self, other):
        return _FakeRegion(self._a + other._a)

    def merge(self):
        pass

    def area(self):
        return self._a


class _FakeBox:
    def width(self):
        return 1000

    def height(self):
        return 1000


class _FakeCell:
    def bbox(self):
        return _FakeBox()

    def begin_shapes_rec(self, li):
        return li


class _FakeLayout:
    dbu = 1.0

    def read(self, path):
        pass

    def top_cell(self):
        return _FakeCell()

    def find_layer(self, gl, gd):
        return gl * 1000 + gd


class _FakePya:
    Layout = _FakeLayout

    @staticmethod
    def Region(handle=None):
        # Each selected layer covers a tenth of the die, so a well-formed run
        # produces a plausible density and a dropped layer is visibly absent.
        # `Region()` with no handle is the empty region the recipe accumulates
        # into (vibe-ic#990) and must contribute nothing.
        return _FakeRegion(0.0 if handle is None else 100000.0)


def _run_recipe(tmp_path, layermap_text, pdk):
    """EXECUTE the emitted measurement script against a stub layout backend.

    Asserting on the recipe as a STRING would pass on a script that cannot run;
    this runs the real selection loop and the real report assembly, so what is
    checked is the artifact the gate will actually read."""
    import phase3_one_shot_runner as R
    mp = tmp_path / "pdk.map"
    mp.write_text(layermap_text)
    out = tmp_path / "metal_density.json"
    g = {"gds": str(tmp_path / "x.gds"), "map": str(mp), "out": str(out),
         "pdk": pdk, "__name__": "__recipe__"}
    saved = sys.modules.get("pya")
    sys.modules["pya"] = _FakePya  # type: ignore[assignment]
    try:
        exec(compile(R._metal_density_recipe(), "recipe", "exec"), g)
    finally:
        if saved is None:
            sys.modules.pop("pya", None)
        else:
            sys.modules["pya"] = saved
    return json.loads(out.read_text())


_MAP = ("li1   NET,SPNET,VIA  67 20\n"
        "met1  NET,SPNET,PIN  68 20\n"
        "mcon  VIA,LEFPIN     67 44\n")


def test_the_measurement_declares_the_pdk_it_was_taken_under(tmp_path):
    """Without this field a stored report has to be told from outside which
    process produced it, and every one of the window lookups above then depends
    on whatever shell happens to read it."""
    doc = _run_recipe(tmp_path, _MAP, _OPEN_A)
    assert doc.get("pdk") == _OPEN_A, (
        "the artifact must record its own PDK — the consumer resolves the "
        "window from it first, precisely so a re-read cannot rejudge it")


def test_the_runner_passes_the_pdk_into_the_measurement(tmp_path):
    """The declaration is only as good as the wiring that fills it. Pinned at
    source level because filling it for real needs the container; the executable
    half of this pair is the test above."""
    import inspect

    import phase3_one_shot_runner as R
    src = inspect.getsource(R._emit_metal_density_report)
    assert "-rd pdk=" in src, (
        "the recipe reads a `pdk` variable that nothing sets — it would record "
        "an empty PDK on every run")


def test_the_measurement_collects_the_layer_the_gate_judges(tmp_path):
    """Producer/consumer parity, executed rather than pattern-matched: every
    layer in the emitted artifact is one the gate will judge, and the layer this
    issue was about is present."""
    doc = _run_recipe(tmp_path, _MAP, _OPEN_A)
    assert set(doc["layers"]) == {"li1", "met1"}, doc["layers"]
    for name in doc["layers"]:
        assert MLD._METAL_RE.match(name), f"measured {name!r} is never judged"


# ── the gate's own prose stays shape-based ───────────────────────────────────

def test_no_pdk_or_design_literal_in_the_gate_sources():
    """The per-PDK numbers are DATA and live in the registry. The gate and the
    resolver must stay shape-based: the moment a PDK name appears in a branch,
    the next PDK needs a code change instead of a data row."""
    banned = ("sky130", "gf180", "ihp-sg13", "nangate", "asap7", "ibex",
              "spm", "subservient", "sha256")
    for prog in ("metal_layer_density_check.py", "pdk_metal_density_windows.py"):
        src = (_PROGRAMS / prog).read_text()
        for tok in banned:
            assert tok not in src, f"{tok!r} leaked into {prog}"


def test_the_registry_documents_where_every_number_came_from():
    """A foundry number with no provenance cannot be checked by the next reader,
    and this table is exactly the kind that rots silently."""
    reg = json.loads((_PROGRAMS / "pdk_registry.json").read_text())
    seen = 0
    for entry in reg["pdks"]:
        block = entry.get("metal_density_windows")
        if block is None:
            continue
        seen += 1
        assert block.get("_measured_from"), entry["name"]
        assert isinstance(block.get("layers"), dict), entry["name"]
    assert seen == 5, f"expected every open PDK to be measured, got {seen}"


def test_registry_windows_are_ordered_and_in_range():
    reg = json.loads((_PROGRAMS / "pdk_registry.json").read_text())
    for entry in reg["pdks"]:
        block = entry.get("metal_density_windows") or {}
        for layer, (lo, hi) in (block.get("layers") or {}).items():
            where = f"{entry['name']}/{layer}"
            for b in (lo, hi):
                assert b is None or 0.0 <= b <= 1.0, where
            if lo is not None and hi is not None:
                assert lo < hi, f"{where}: window is empty or inverted"


def test_the_docstring_does_not_still_claim_nothing_supplies_windows():
    """The tier's own prose said the report's windows win "else the generic
    default" — true when written, and a lie the moment the PDK table was wired
    in. Stale prose next to corrected code is how the next reader is misled."""
    src = (_PROGRAMS / "signoff_ladder_run.py").read_text()
    i = src.index("def check_tier_metal_density")
    doc = src[i:i + 2000].lower()
    # The claim that has to be there: the tier says whose windows it supplies.
    assert "stated per-layer window" in doc
    # And the code has to match it — the empty map is what made the old prose
    # true-but-useless, and re-introducing it would leave this docstring lying.
    body = src[i:src.index("def _metal_density_attribution")]
    assert "mld.check(rpt, {}," not in body
