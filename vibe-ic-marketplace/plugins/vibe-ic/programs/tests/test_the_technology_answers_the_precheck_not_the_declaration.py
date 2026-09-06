#!/usr/bin/env python3
"""Two precheck rungs that must be DERIVED from the process, never declared.

vibe-ic#2058 FP-10, and the owner's ForbiddenLayers ruling of 2026-09-06.

THE MEASUREMENT BOTH START FROM. spm x gf180mcuD, image label 0.3.46, lane
czspmfp, through the front door — `reports/phase3/general_precheck.json`:

    General.SealRing          FAIL              (`seal_ring_required: true`)
    General.ForbiddenLayers   NOT_DETERMINED    "the layout draws on 32
        layer/datatype pair(s), and `forbidden_layers` was not declared, so no
        layer can be called forbidden"

and, one consumer away, `die_finishing_gen` treating the SAME
`seal_ring_required: false` as a DECIDED not-applicable and writing its SKIPPED
marker. One declaration, two consumers, opposite meanings, and no value of it
able to produce a PASS on either rung.

THE RULE. A not-applicable is legitimate only when it is a fact about the
PROCESS — this technology has no seal-ring facility, this technology's layer
table defines these pairs and no others. A DECLARED not-applicable is refused.

MEASURED TWO-ARM, the real spm die, `--pdk gf180mcu`, only the program
differing (probe/spm_BASE.json vs probe/spm_HEAD.json):

    KLayout.ReadLayout   PASS -> PASS      General.SealRing        FAIL -> FAIL
    General.DatabaseUnit PASS -> PASS      Checker.KLayoutDensity  FAIL -> FAIL
    KLayout.CheckTopLevel PASS -> PASS     Checker.KLayoutZeroArea PASS -> PASS
    KLayout.CheckSize    PASS -> PASS      Checker.KLayoutAntenna  PASS -> PASS
    Checker.MagicDRC     FAIL -> FAIL      Checker.KLayoutDRC      FAIL -> FAIL
    General.ForbiddenLayers   NOT_DETERMINED -> FAIL

Every other rung byte-identical. gf180mcuD HAS a seal-ring generator, so its
seal row does NOT reach NOT_APPLICABLE and spm keeps its FAIL. Its layer table
has 118 pairs and spm draws on 32, three of which — 100/0, 901/0, 902/0 — the
technology does not define. Those three are written by our OWN flow
(`def_gds_port_power_restore`: TEXT_LAYER (100,0), RAIL_MARKER 901/902), which
is the finding, not an argument against the rung.

THE FIXTURES BELOW ARE SYNTHETIC TECHNOLOGIES, not synthetic answers. Each is a
real directory laid out the way a KLayout-integrated PDK is, reached through
`$PDK_ROOT/<name>` — the resolver's own last door — so what is being tested is
the derivation and not a monkeypatched return value.
"""
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import general_precheck as GP                      # noqa: E402
import _pdk_layer_authority as AUTH                # noqa: E402
import _tapeout_declaration as TD                  # noqa: E402
from test_general_precheck import (                # noqa: E402
    write_gds, _rect, _project, _step, _NEVER_RAN)

#: The layer/datatype the shared die fixture draws its boundary on.
MAPPED = (67, 20)
#: In NEITHER the synthetic technology's table NOR this flow's own marker
#: declaration — deliberately not 100/901/902, which ARE ours (see
#: `test_a_flow_marker_layer_is_disclosed_and_not_failed`).
UNMAPPED = (777, 3)
#: One the flow itself writes: `def_gds_port_power_restore.RAIL_MARKER["VSS"]`.
FLOW_MARKER = (902, 0)


def _lyp(pairs) -> str:
    """A KLayout layer-properties document — the real XML shape, minimal."""
    body = "".join(
        f" <properties>\n  <name/>\n  <source>{l}/{d}@1</source>\n"
        f" </properties>\n" for (l, d) in pairs)
    return f'<?xml version="1.0" encoding="utf-8"?>\n<layer-properties>\n{body}</layer-properties>\n'


def _technology(root: Path, name: str, *, pairs, sealring: bool) -> Path:
    """A PDK volume: a KLayout tech dir, a layer table, maybe a generator."""
    vol = root / name
    tech = vol / "libs.tech" / "klayout" / "tech"
    tech.mkdir(parents=True, exist_ok=True)
    if pairs is not None:
        (tech / f"{name}.lyp").write_text(_lyp(pairs))
    if sealring:
        scripts = tech / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "sealring.py").write_text("# a seal-ring generator\n")
    return vol


def _die(path: Path, layers=((67, 20),)) -> Path:
    return write_gds(path, {"chip_top": {
        "boundaries": [(l, d, _rect(0, 0, 100_000, 80_000)) for (l, d) in layers]}})


@pytest.fixture
def pdkroot(tmp_path, monkeypatch):
    root = tmp_path / "pdks"
    root.mkdir()
    monkeypatch.setenv("PDK_ROOT", str(root))
    return root


# --------------------------------------------------------------------------- #
# FP-10 — the seal-ring tier
# --------------------------------------------------------------------------- #
def test_a_technology_with_no_seal_ring_facility_reaches_not_applicable(
        tmp_path, pdkroot):
    _technology(pdkroot, "notech", pairs=[MAPPED], sealring=False)
    proj = _project(tmp_path, _die, {"deliverable": "DIE",
                                     "top_cell": "chip_top",
                                     "seal_ring_required": False})
    ev = _step(GP.evaluate(proj, runner=_NEVER_RAN, pdk="notech"),
               "General.SealRing")
    assert ev.verdict == GP.NOT_APPLICABLE, ev.evidence
    assert "no seal-ring generator" in ev.evidence
    assert ev.measured["technology_seal_ring_facility"] is False
    # THE DERIVATION IS CHECKABLE, not asserted: the report names the path it
    # looked for and did not find.
    assert any(p.endswith("scripts/sealring.py")
               for p in ev.measured["seal_ring_facility_tried"])


def test_not_applicable_does_not_block_the_precheck_verdict(tmp_path, pdkroot):
    """The row the ruling asks the precheck to PASS over."""
    _technology(pdkroot, "notech", pairs=[MAPPED], sealring=False)
    proj = _project(tmp_path, _die, {"deliverable": "DIE",
                                     "top_cell": "chip_top",
                                     "seal_ring_required": False})
    rep = GP.evaluate(proj, runner=_NEVER_RAN, pdk="notech")
    assert "General.SealRing" in rep.not_applicable_steps
    assert "General.SealRing" not in rep.failed_steps
    assert "General.SealRing" not in rep.undetermined_steps
    # …and it is NAMED in the aggregate rather than silently absent.
    assert rep.steps_with_evidence >= 1


def test_a_declared_false_is_refused_where_the_facility_EXISTS(tmp_path,
                                                               pdkroot):
    """THE LOAD-BEARING NEGATIVE. Same declaration, same layout, same code —
    only the technology differs. This is the arm spm is on."""
    _technology(pdkroot, "hastech", pairs=[MAPPED], sealring=True)
    proj = _project(tmp_path, _die, {"deliverable": "DIE",
                                     "top_cell": "chip_top",
                                     "seal_ring_required": False})
    ev = _step(GP.evaluate(proj, runner=_NEVER_RAN, pdk="hastech"),
               "General.SealRing")
    assert ev.verdict == GP.NOT_DETERMINED, ev.evidence
    assert "HAS the facility" in ev.evidence
    assert "declared not-applicable is refused" in ev.evidence


def test_an_unresolvable_technology_is_not_applicable_to_nothing(tmp_path,
                                                                 pdkroot):
    """`False` is a measurement; `None` is not. A name with no volume behind it
    must not become 'this process has no seal ring'."""
    proj = _project(tmp_path, _die, {"deliverable": "DIE",
                                     "top_cell": "chip_top",
                                     "seal_ring_required": False})
    ev = _step(GP.evaluate(proj, runner=_NEVER_RAN, pdk="nosuchtech"),
               "General.SealRing")
    assert ev.verdict == GP.NOT_DETERMINED, ev.evidence
    assert ev.measured["technology_seal_ring_facility"] is None
    assert "could not be asked" in ev.evidence


def test_no_pdk_named_at_all_is_unchanged(tmp_path):
    """The pre-change behaviour, preserved by name: with nothing to derive
    from, a declared false is still refused and still says why."""
    proj = _project(tmp_path, _die, {"deliverable": "DIE",
                                     "top_cell": "chip_top",
                                     "seal_ring_required": False})
    ev = _step(GP.evaluate(proj, runner=_NEVER_RAN), "General.SealRing")
    assert ev.verdict == GP.NOT_DETERMINED
    assert "Declared-away is not the same as checked-and-clean" in ev.evidence


# --------------------------------------------------------------------------- #
# ForbiddenLayers — the complement of the technology's own layer table
# --------------------------------------------------------------------------- #
def test_a_gds_whose_layers_are_all_mapped_passes(tmp_path, pdkroot):
    _technology(pdkroot, "maptech", pairs=[MAPPED, (1, 0)], sealring=False)
    proj = _project(tmp_path, _die, {"deliverable": "DIE",
                                     "top_cell": "chip_top"})
    ev = _step(GP.evaluate(proj, runner=_NEVER_RAN, pdk="maptech"),
               "General.ForbiddenLayers")
    assert ev.verdict == GP.PASS, ev.evidence
    # THE AUTHORITY IS NAMED. A pass that does not say what it was judged
    # against is the state this rung was in before.
    assert ev.measured["layer_authority"].endswith("maptech.lyp")
    assert ev.measured["allowed_pairs"] == 2
    assert ev.measured["unmapped_layers"] == []


def test_one_unmapped_layer_fails_and_the_layer_is_named(tmp_path, pdkroot):
    """THE MUTATION THE RULING ASKS FOR: a synthetic GDS with one unmapped
    layer must FAIL. Identical to the passing fixture but for one added
    boundary."""
    _technology(pdkroot, "maptech", pairs=[MAPPED, (1, 0)], sealring=False)
    proj = _project(tmp_path,
                    lambda p: _die(p, layers=(MAPPED, UNMAPPED)),
                    {"deliverable": "DIE", "top_cell": "chip_top"})
    ev = _step(GP.evaluate(proj, runner=_NEVER_RAN, pdk="maptech"),
               "General.ForbiddenLayers")
    assert ev.verdict == GP.FAIL, ev.evidence
    assert f"{UNMAPPED[0]}/{UNMAPPED[1]}" in ev.evidence
    assert ev.measured["unmapped_layers"] == [f"{UNMAPPED[0]}/{UNMAPPED[1]}"]


def test_a_technology_with_no_readable_table_is_not_determined(tmp_path,
                                                               pdkroot):
    """NOT an empty allowed set. A table nobody could read must not make every
    layer in every GDS forbidden at once."""
    _technology(pdkroot, "blindtech", pairs=None, sealring=False)
    proj = _project(tmp_path, _die, {"deliverable": "DIE",
                                     "top_cell": "chip_top"})
    ev = _step(GP.evaluate(proj, runner=_NEVER_RAN, pdk="blindtech"),
               "General.ForbiddenLayers")
    assert ev.verdict == GP.NOT_DETERMINED, ev.evidence
    assert "allowed set is unknown" in ev.evidence
    assert ev.measured["allowed_pairs"] is None


def test_a_declared_prohibition_still_refuses_with_no_table(tmp_path, pdkroot):
    """The derivation replaces the declaration as the source of what is
    ALLOWED. It does not cancel a prohibition somebody wrote down — losing that
    refusal because a volume was unreachable would be a check weakened by an
    absence."""
    _technology(pdkroot, "blindtech", pairs=None, sealring=False)
    proj = _project(tmp_path, _die,
                    {"deliverable": "DIE", "top_cell": "chip_top",
                     "forbidden_layers": [f"{MAPPED[0]}/{MAPPED[1]}"]})
    ev = _step(GP.evaluate(proj, runner=_NEVER_RAN, pdk="blindtech"),
               "General.ForbiddenLayers")
    assert ev.verdict == GP.FAIL, ev.evidence
    assert f"{MAPPED[0]}/{MAPPED[1]}" in ev.evidence


def test_a_declaration_can_add_a_prohibition_but_never_widen_what_is_allowed(
        tmp_path, pdkroot):
    """Both directions in one fixture: the technology maps the layer, and the
    declaration forbids it anyway -> FAIL; and an EMPTY declared list buys
    nothing for an unmapped layer -> still FAIL."""
    _technology(pdkroot, "maptech", pairs=[MAPPED, (1, 0)], sealring=False)
    stricter = _project(tmp_path / "a", _die,
                        {"deliverable": "DIE", "top_cell": "chip_top",
                         "forbidden_layers": [f"{MAPPED[0]}/{MAPPED[1]}"]})
    ev = _step(GP.evaluate(stricter, runner=_NEVER_RAN, pdk="maptech"),
               "General.ForbiddenLayers")
    assert ev.verdict == GP.FAIL and "declaration forbids" in ev.evidence

    laundered = _project(tmp_path / "b",
                         lambda p: _die(p, layers=(MAPPED, UNMAPPED)),
                         {"deliverable": "DIE", "top_cell": "chip_top",
                          "forbidden_layers": []})
    ev = _step(GP.evaluate(laundered, runner=_NEVER_RAN, pdk="maptech"),
               "General.ForbiddenLayers")
    assert ev.verdict == GP.FAIL, "an empty forbidden list bought a pass"


# --------------------------------------------------------------------------- #
# The resolver itself
# --------------------------------------------------------------------------- #
def test_a_prefix_resolves_only_when_it_is_unambiguous(tmp_path):
    """spm's own case: the run resolved `gf180mcu` and the volume is
    `gf180mcuD`. One candidate resolves; two are an ambiguity and refuse."""
    reg = tmp_path / "reg.json"
    (tmp_path / "volA").mkdir()
    (tmp_path / "volB").mkdir()
    reg.write_text(json.dumps({"pdks": [
        {"name": "procXA", "container_path": str(tmp_path / "volA")}]}))
    vol, how, _ = AUTH.resolve_volume("procX", registry_path=reg, environ={})
    assert vol == tmp_path / "volA", how

    reg.write_text(json.dumps({"pdks": [
        {"name": "procXA", "container_path": str(tmp_path / "volA")},
        {"name": "procXB", "container_path": str(tmp_path / "volB")}]}))
    vol, how, _ = AUTH.resolve_volume("procX", registry_path=reg, environ={})
    assert vol is None and "not derivable" in how


def test_the_layer_table_parser_reads_a_named_source(tmp_path):
    """`<source>LVS_RF 100/5@1</source>` — the shape a real table uses. A name
    carrying digits must not be read as a layer number."""
    pairs = AUTH.parse_layer_table(
        "<layer-properties>"
        "<properties><source>LVS_RF 100/5@1</source></properties>"
        "<properties><source>met1 34/0@1</source></properties>"
        "<properties><source>12/0@1</source></properties>"
        "<properties><source>*/*@1</source></properties>"
        "</layer-properties>")
    assert pairs == {(100, 5), (34, 0), (12, 0)}


# --------------------------------------------------------------------------- #
# Owner ruling 2026-09-06 — the flow's OWN marker layers are disclosed, not failed
# --------------------------------------------------------------------------- #
def test_the_flow_marker_set_is_derived_from_the_writer_never_typed():
    """It must come from `def_gds_port_power_restore`'s own constants. A typed
    copy here would be a second declaration of the same fact, free to drift the
    day someone moves the writer."""
    import def_gds_port_power_restore as W
    exact, base, why, tried = AUTH.flow_marker_layers()
    assert exact == {tuple(v) for v in W.RAIL_MARKER.values()}
    assert base == W.TEXT_LAYER[0]
    assert "def_gds_port_power_restore" in why
    # the datatype is DATA — the writer's own comment says it is the pin's
    # 1-based metal index — so the LAYER is what can be declared ahead of a run
    assert AUTH.is_flow_marker(base, 0, exact, base)
    assert AUTH.is_flow_marker(base, 4, exact, base)
    assert not AUTH.is_flow_marker(base + 1, 0, exact, base)


def test_a_flow_marker_layer_is_disclosed_and_not_failed(tmp_path, pdkroot):
    """spm's own case: 100/0, 901/0 and 902/0 are OURS. The rung must stop
    calling them unknown, and the INFO row must name them."""
    _technology(pdkroot, "maptech", pairs=[MAPPED, (1, 0)], sealring=False)
    proj = _project(tmp_path,
                    lambda p: _die(p, layers=(MAPPED, FLOW_MARKER, (100, 0))),
                    {"deliverable": "DIE", "top_cell": "chip_top"})
    rep = GP.evaluate(proj, runner=_NEVER_RAN, pdk="maptech")
    fl = _step(rep, "General.ForbiddenLayers")
    assert fl.verdict == GP.PASS, fl.evidence
    assert fl.measured["unmapped_layers"] == []
    assert set(fl.measured["flow_marker_layers"]) == {"902/0", "100/0"}

    info = _step(rep, "General.FlowMarkerLayers")
    assert info.verdict == GP.INFO, info.evidence
    assert set(info.measured["flow_marker_layers"]) == {"902/0", "100/0"}
    assert "must not carry them" in info.evidence
    assert "General.FlowMarkerLayers" in rep.info_steps
    assert "General.FlowMarkerLayers" not in rep.failed_steps
    assert "General.FlowMarkerLayers" not in rep.undetermined_steps


def test_THE_CONTROL_a_layer_in_neither_set_still_fails_naming_it(tmp_path,
                                                                  pdkroot):
    """The ruling's control. Forgiving OUR markers must not forgive anything
    else — a layer the technology does not define and the flow does not claim
    is a layer nobody can explain."""
    _technology(pdkroot, "maptech", pairs=[MAPPED, (1, 0)], sealring=False)
    proj = _project(tmp_path,
                    lambda p: _die(p, layers=(MAPPED, FLOW_MARKER, UNMAPPED)),
                    {"deliverable": "DIE", "top_cell": "chip_top"})
    fl = _step(GP.evaluate(proj, runner=_NEVER_RAN, pdk="maptech"),
               "General.ForbiddenLayers")
    assert fl.verdict == GP.FAIL, fl.evidence
    assert fl.measured["unmapped_layers"] == [f"{UNMAPPED[0]}/{UNMAPPED[1]}"]
    assert f"{UNMAPPED[0]}/{UNMAPPED[1]}" in fl.evidence
    # …and the flow marker beside it is still recognised as ours, not lumped in
    assert fl.measured["flow_marker_layers"] == [f"{FLOW_MARKER[0]}/{FLOW_MARKER[1]}"]


def test_THE_MUTATION_dropping_the_derived_declaration_re_reddens_our_markers(
        tmp_path, pdkroot, monkeypatch):
    """Break the derivation and spm's own markers must go red again — which is
    the state the ruling was issued about. A rung that stays green with the
    declaration gone is not reading it."""
    _technology(pdkroot, "maptech", pairs=[MAPPED, (1, 0)], sealring=False)
    proj = _project(tmp_path,
                    lambda p: _die(p, layers=(MAPPED, FLOW_MARKER, (100, 0))),
                    {"deliverable": "DIE", "top_cell": "chip_top"})
    monkeypatch.setattr(AUTH, "flow_marker_layers",
                        lambda: (set(), None, "MUTATION: not derived", []))
    rep = GP.evaluate(proj, runner=_NEVER_RAN, pdk="maptech")
    fl = _step(rep, "General.ForbiddenLayers")
    assert fl.verdict == GP.FAIL, "the derivation is not load-bearing"
    assert set(fl.measured["unmapped_layers"]) == {"100/0", "902/0"}
    # and the INFO rung refuses too — it must never answer "the flow writes
    # nothing", which would report our own markers as unknown in the rung above
    info = _step(rep, "General.FlowMarkerLayers")
    assert info.verdict == GP.NOT_DETERMINED, info.evidence
    assert "could not be derived" in info.evidence
