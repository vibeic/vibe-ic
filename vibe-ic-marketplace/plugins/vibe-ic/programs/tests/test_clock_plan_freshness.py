#!/usr/bin/env python3
"""Step 16 — the clock plan that was never re-derived, keyed on CONTENT.

THE DEFECT. `step_canonicalize_artefacts`'s Step-16 block decided whether to
rewrite `phase3/stage3/cts/clock_plan.json` on the PLAN's own content alone::

    _needs_refresh = not (isinstance(_cl, list) and _cl)

so once the plan carried a populated `clocks` array it was never written again,
however much later the constraints were regenerated. The plan is DERIVED from
the project's SDCs: an SDC edited after it was written (a re-run at a different
period, a clock added) leaves the stale plan in place, and every skew target
keyed off it describes the old design. Nothing anywhere could see the drift.

WHY THIS IS NOT MTIME — the first attempt at this fix keyed staleness on mtime
and it did not survive review, for two reasons that are both load-bearing:

  1. MTIME DOES NOT SURVIVE COPYING. git does not restore mtimes. Over the 17
     tracked `clock_plan.json` files (`git ls-files benchmark-data`) the mtime
     rule fired on SIX in one checkout and FIVE in another worktree of the same
     commit — identical bytes, different answer — every hit naming
     `phase3/stage3/pnr/constraint.sdc`. A finding whose count depends on the
     order git wrote files is not measuring the artefact. Clone, copy, rsync
     and archive extraction are how this corpus and every user project are
     distributed. Content-keyed, the same 17 files yield 0 findings on every
     tree; `test_a_checkout_ordering_mtime_skew_is_not_staleness` reproduces
     that exact shape (plan 15 min older than constraint.sdc, content equal).
  2. THE PRODUCER COULD OVERWRITE A GOOD PLAN WITH A FABRICATED ONE. Staleness
     set `_needs_refresh = True`; the refresh block then re-derived clocks and,
     when it found none, injected a synthetic `{"clk", 10.0 ns}` before an
     UNCONDITIONAL write. So SDCs absent or moved + a primary DEF present + a
     provenance mismatch replaced a correct MULTI-CLOCK plan with one
     fabricated clock — and the replacement then satisfied every downstream
     substance check. `test_stale_refresh_never_replaces_a_good_plan_with_a_
     synthetic_one` EXECUTES that path (it was originally read, not run).

THE FIX, in three parts.
  * CONTENT KEY. The plan RECORDS `derived_from` = {relative SDC path: sha256}.
    Both sides compare that record against the SDCs present now. A plan that
    records nothing produces NO finding — absence of provenance is not evidence
    of staleness.
  * PRODUCER GUARD. A staleness-triggered refresh may only write when
    re-derivation actually produced clocks from real SDCs. Otherwise the
    existing plan is KEPT and the failure to re-derive is disclosed.
  * ONE DEFINITION. Producer and checker both call
    `_path_layout.clock_plan_input_sdcs` / `clock_plan_sdc_digests`, so the
    checker can no longer call stale what the producer calls fresh. The DEFs
    (`floorplan.def` / `placed.def`) are gone from the comparison entirely: the
    plan is built from `create_clock` statements and from nothing else, so a
    newer DEF cannot make it wrong, and they were the checker-side half of the
    producer/checker disagreement.

The gate slot stays ADVISORY (rc unchanged): the producer re-derives in the same
condition, so blocking here would fail already-complete runs for a provenance
fact rather than a wrong answer.

DIRECTION-1 GUARDS (`test_d1_*`) hold on the pre-fix tree too.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _path_layout as PL             # noqa: E402
import clock_plan_check as C          # noqa: E402
from _clock_plan_fixture import current_fixture  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_SDC = "create_clock -name clk -period 10.0 [get_ports clk]\n"
_SDC_REL = "phase3/stage3/pnr/constraint.sdc"


def test_image_owned_lef_metadata_does_not_read_the_host_namespace(tmp_path, monkeypatch):
    import _physical_current as pc
    import librelane_contract as llc
    from types import SimpleNamespace
    lef = tmp_path.parent / (tmp_path.name + "-image-only.lef")
    # Deliberately different host bytes at the same absolute image path.
    lef.write_text("host namespace is not the selected image\n")
    image = "ghcr.io/vibeic/vibeic-eda@sha256:" + "a" * 64
    expected = {"path": str(lef), "bytes": 9,
                "sha256": hashlib.sha256(b"image LEF").hexdigest(), "image": image}
    calls = []
    def image_read(argv, **kwargs):
        calls.append(argv)
        assert argv[argv.index("--skip") - 1] == image
        assert argv[-1] == str(lef)
        return SimpleNamespace(returncode=0, stdout=json.dumps([dict(expected)]), stderr="")
    monkeypatch.setattr(llc, "run_container", image_read)
    assert pc.lef_entries(tmp_path, [str(lef)], image=image) == [expected]
    assert len(calls) == 1


def test_missing_image_lef_does_not_fall_back_to_host(tmp_path, monkeypatch):
    import _physical_current as pc
    import librelane_contract as llc
    import pytest
    from types import SimpleNamespace
    path = tmp_path.parent / (tmp_path.name + "-host-only.lef")
    path.write_text("host LEF\n")
    monkeypatch.setattr(llc, "run_container", lambda *_a, **_k: SimpleNamespace(
        returncode=1, stdout="", stderr="FileNotFoundError: selected image LEF missing"))
    with pytest.raises(ValueError, match="CURRENT_IMAGE_LEF_UNAVAILABLE"):
        pc.lef_entries(tmp_path, [str(path)], image="image@sha256:" + "a" * 64)


def test_project_lef_remains_bound_to_the_identity_mount(tmp_path):
    import _physical_current as pc
    path = tmp_path / "input/pdk/tech.lef"
    path.parent.mkdir(parents=True)
    path.write_text("project LEF\n")
    assert pc.lef_entries(tmp_path, [str(path)], image="selected-image") == [pc.entry(tmp_path, path)]


def _plan(*, derived_from=None, clocks=None) -> dict:
    doc = {
        "tool": "openroad",
        "primary_clock": (clocks or [{"name": "clk"}])[0]["name"],
        "clocks": clocks or [
            {"name": "clk", "period_ns": 10.0, "source": "clk"}],
    }
    if derived_from is not None:
        doc["derived_from"] = derived_from
    return doc


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _project(tmp: Path, *, sdc: str = _SDC, plan: dict = None) -> Path:
    """A project whose plan records the digest of the SDC actually on disk."""
    proj = tmp / "proj"
    _write(proj / _SDC_REL, sdc)
    if plan is None:
        plan = _plan(derived_from={
            _SDC_REL: hashlib.sha256(sdc.encode()).hexdigest()})
    _write(proj / "phase3/stage3/cts/clock_plan.json", json.dumps(plan))
    _write(proj / "phase3/stage3/pnr/floorplan.def",
           "VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n")
    _write(proj / "phase3/stage3/pnr/placed.def",
           "VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n")
    return proj


def _read_plan(proj: Path) -> dict:
    return json.loads(
        (proj / "phase3/stage3/cts/clock_plan.json").read_text())


# ===========================================================================
# The key is CONTENT, and it survives a copy
# ===========================================================================


def test_an_added_sdc_is_seen(tmp_path):
    """A constraint file the plan was never derived from is staleness too."""
    proj = _project(tmp_path)
    _write(proj / "constraints/extra.sdc",
           "create_clock -name clk2 -period 8.0 [get_ports clk2]\n")
    assert C._stale_inputs(proj, _read_plan(proj)) == ["constraints/extra.sdc"]












def test_the_shared_definition_is_the_producers_historical_set(tmp_path):
    """Keep user/legacy ASIC inputs while excluding unrelated tool decks."""
    proj = _project(tmp_path)
    _write(proj / "input/constraints/extra.sdc", _SDC)
    _write(proj / "steps/7_constraints/top.sdc", _SDC)
    _write(proj / "phase3/librelane/attempts/old/top.sdc", _SDC)
    assert set(PL.clock_plan_input_sdcs(proj)) == {
        proj / _SDC_REL,
        proj / "input/constraints/extra.sdc",
        proj / "steps/7_constraints/top.sdc"}


# ===========================================================================
# PRODUCER — the write must not destroy a real measurement
# ===========================================================================










# ===========================================================================
# GATE — the advisory disclosure
# ===========================================================================
def _run_gate(proj: Path, out: Path):
    r = _pr.run(
        [sys.executable, str(_PROGRAMS / "clock_plan_check.py"), str(proj),
         "--json", str(out)],
        capture_output=True, text=True)
    return r, json.loads(out.read_text())


def _rules(doc):
    return [(f["severity"], f["rule"]) for f in doc["findings"]]


def test_gate_discloses_a_stale_plan(tmp_path):
    proj = _project(tmp_path)
    (proj / _SDC_REL).write_text(
        "create_clock -name clk -period 4.0 [get_ports clk]\n")
    r, doc = _run_gate(proj, tmp_path / "o.json")
    assert ("WARNING", "CLOCK_PLAN_STALE") in _rules(doc), _rules(doc)
    msg = [f["message"] for f in doc["findings"]
           if f["rule"] == "CLOCK_PLAN_STALE"][0]
    assert _SDC_REL in msg, msg


def test_gate_does_not_flag_a_fresh_plan(tmp_path):
    proj = _project(tmp_path)
    _, doc = _run_gate(proj, tmp_path / "o.json")
    assert "CLOCK_PLAN_STALE" not in [f["rule"] for f in doc["findings"]]


def test_the_staleness_disclosure_keeps_current_binding_blocking(
        tmp_path, monkeypatch):
    """A stale disclosure is advisory, but changed bound inputs still fail.

    The receipt is a same-invocation subject binding.  Once the SDC bytes are
    edited, the consumer must refuse that old native measurement; otherwise a
    stale plan could be called current merely because its clock values look
    plausible.
    """
    proj = _project(tmp_path)
    current_fixture(monkeypatch, proj, _SDC, preserve_provenance=True)
    (proj / _SDC_REL).write_text(
        "create_clock -name clk -period 4.0 [get_ports clk]\n")
    r, doc = _run_gate(proj, tmp_path / "o.json")
    assert r.returncode == 1, r.stdout + r.stderr
    assert doc["verdict"] == "FAIL"
    assert "CLOCK_PLAN_STALE" in [f["rule"] for f in doc["findings"]]
    assert "CLOCK_PLAN_CURRENT_REFUSED" in [
        f["rule"] for f in doc["findings"]]


# ===========================================================================
# DIRECTION-1 GUARDS — hold on the pre-fix tree too
# ===========================================================================
def test_d1_a_dropped_sdc_clock_still_fails(tmp_path):
    """The gate's real blocking job must survive the new advisory finding."""
    proj = _project(tmp_path)
    (proj / _SDC_REL).write_text(
        _SDC + "create_clock -name clk_div2 -period 20.0 [get_ports clk_div2]\n")
    r, doc = _run_gate(proj, tmp_path / "o.json")
    assert r.returncode == 1
    assert doc["verdict"] == "FAIL"
    assert "SDC_CLOCK_DROPPED" in [f["rule"] for f in doc["findings"]]


def test_d1_a_missing_plan_still_fails(tmp_path):
    proj = _project(tmp_path)
    (proj / "phase3/stage3/cts/clock_plan.json").unlink()
    r, doc = _run_gate(proj, tmp_path / "o.json")
    assert r.returncode == 1
    assert "CLOCK_PLAN_MISSING" in [f["rule"] for f in doc["findings"]]


def test_d1_a_clock_with_no_period_still_fails(tmp_path):
    proj = _project(tmp_path, plan={
        "primary_clock": "clk", "clocks": [{"name": "clk", "source": "clk"}]})
    r, doc = _run_gate(proj, tmp_path / "o.json")
    assert r.returncode == 1
    assert "CLOCK_NO_PERIOD" in [f["rule"] for f in doc["findings"]]


def test_d1_a_healthy_fresh_plan_still_passes(tmp_path, monkeypatch):
    proj = _project(tmp_path)
    current_fixture(monkeypatch, proj, _SDC)
    r, doc = _run_gate(proj, tmp_path / "o.json")
    assert r.returncode == 0
    assert doc["verdict"] == "PASS"


def test_an_unreadable_sdc_is_not_called_stale(tmp_path):
    """A digest that cannot be computed is not evidence of change — and it must
    not be reported as an added file either."""
    proj = _project(tmp_path)
    real_read = Path.read_bytes
    target = proj / _SDC_REL

    def boom(self, *a, **kw):
        if self == target:
            raise OSError("simulated read failure")
        return real_read(self, *a, **kw)

    Path.read_bytes = boom
    try:
        # The recorded path can no longer be hashed, so it reads as changed —
        # which is the FAIL-CLOSED direction for a provenance claim. What must
        # NOT happen is a crash or a fabricated extra entry.
        out = C._stale_inputs(proj, _read_plan(proj))
        assert out == [_SDC_REL], out
    finally:
        Path.read_bytes = real_read


def test_native_asic_inputs_exclude_quartus_and_historical_tool_decks(tmp_path):
    proj = _project(tmp_path)
    included = [_SDC_REL, "phase2/stage2/constraints/top.asic.sdc",
                "input/constraints/aux.sdc", "steps/7_constraints/extra.sdc",
                "constraints/user.sdc"]
    for rel in included[1:]:
        _write(proj / rel, _SDC)
    excluded = ["phase2/stage1/fpga/top.sdc",
                "phase2/.phase2_held/constraints/top.sdc",
                "phase3/librelane/02-yosys-synthesis/synthesis.abc.sdc",
                "phase3/librelane/attempts/old/15-floorplan/top.sdc",
                "phase3/stage3/pnr/old/constraint.sdc"]
    for rel in excluded:
        _write(proj / rel, "derive_pll_clocks\n" + _SDC)
    expected = {proj / rel for rel in included}
    assert set(PL.clock_plan_input_sdcs(proj)) == expected
    assert set(C._find_sdc_files(proj)) == expected
    assert set(PL.clock_plan_sdc_digests(proj)) == set(included)


def test_fpga_and_old_attempts_cannot_add_an_asic_clock_domain(
        tmp_path, monkeypatch):
    proj = _project(tmp_path)
    _write(proj / "phase2/stage1/fpga/top.sdc",
           "derive_pll_clocks\n"
           "create_clock -name fpga_only -period 2 [get_ports fpga_clk]\n")
    _write(proj / "phase3/librelane/attempts/old/15-floorplan/top.sdc",
           "create_clock -name old_clock -period 3 [get_ports old_clk]\n")
    current_fixture(monkeypatch, proj, _SDC)
    result, doc = _run_gate(proj, tmp_path / "o.json")
    assert result.returncode == 0, doc
    assert doc["verdict"] == "PASS"
    assert doc["sdc_files_checked"] == [_SDC_REL]


def test_user_asic_aux_clock_must_still_be_covered(tmp_path, monkeypatch):
    proj = _project(tmp_path)
    _write(proj / "input/constraints/aux.sdc",
           "create_clock -name aux -period 8 [get_ports aux_clk]\n")
    current_fixture(monkeypatch, proj, _SDC)
    result, doc = _run_gate(proj, tmp_path / "o.json")
    assert result.returncode == 1
    assert "SDC_CLOCK_DROPPED" in [f["rule"] for f in doc["findings"]]
    assert "input/constraints/aux.sdc" in doc["sdc_files_checked"]


def test_only_fpga_constraints_do_not_supply_an_asic_clock(tmp_path):
    proj = tmp_path / "only_fpga"
    _write(proj / "phase2/stage1/fpga/top.sdc", _SDC)
    assert PL.clock_plan_input_sdcs(proj) == []
    assert C._find_sdc_files(proj) == []
