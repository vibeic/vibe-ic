"""#601's flatten is conditional on what the deck in hand actually does.

`_klayout_merge_layers` flattened every KLayout stream-out before its per-layer
merge, because a deck that does NOT merge across a cell-instance boundary reads
two abutting same-layer polygons as a zero-spacing edge pair. That is a property
of the DECK AND THE TOOL, and it is measurable.

MEASURED on spm x gf180mcuD (v1.22.10, klayout 0.30.9, image sha256:89a8fd72…),
with the PDK's own deck in its default deep mode: two 0.115 um rects (the
layer's min width is 0.23 um, read from the PDK's own tech LEF) abutting across
a cell-instance boundary — the hierarchical arm reports 6 violations and the
flattened+merged arm reports 6, so the boundary cost nothing and the deck had
already merged it. Probe runtime 23.5 s.

What the flatten costs on a die, same DEF, same deck: GDS 1,136,500,018 B flat
vs 81,021,436 B hierarchical, sign-off DRC 2554 s / 26 GB vs 318 s / 2.9 GB,
plus 1.75 h of `magic lef write` on the flat stream in `digital_hardmacro_gen`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402

_MAP = """Via1    VIA               35 0
Metal1  NET,SPNET,PIN,VIA 34 0
NAME    Metal1/LABEL      34 10
Metal2  NET,SPNET,PIN,VIA 36 0
"""
_TLEF = """LAYER Metal1
  TYPE ROUTING ;
  WIDTH 0.23 ;
END Metal1
LAYER Metal2
  TYPE ROUTING ;
  WIDTH 0.28 ;
END Metal2
"""


class _Pdk:
    name = "somepdk"
    metal_prefix = "Metal"
    drc_deck = "/foss/pdks/somepdk/deck.drc"
    calibre_drc = None
    lefdef_layermap = "/foss/pdks/somepdk/tech.map"
    tech_lef = "/foss/pdks/somepdk/tech.lef"


def _wire(monkeypatch, tmp_path, hier, flat, *, deck=_Pdk.drc_deck,
          texts=None):
    """Wire the probe's three container calls to counted fixtures."""
    texts = texts or {_Pdk.lefdef_layermap: _MAP, _Pdk.tech_lef: _TLEF}
    monkeypatch.setattr(R, "_read_pdk_text", lambda p, c=None: texts.get(str(p)))
    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: True)
    monkeypatch.setattr(R, "_to_container_path", lambda p, c: p)
    calls = []

    def fake_exec(container, cmd, timeout=1800, **kw):
        calls.append(cmd)
        if "merge_probe.py" in cmd:
            d = Path(cmd.split("PROBE_DIR=", 1)[1].split()[0])
            (d / "probe_hier.gds").write_bytes(b"h")
            (d / "probe_flat.gds").write_bytes(b"f")
            return 0, "MERGE_PROBE_WRITTEN", ""
        arm = "hier" if "probe_hier.gds" in cmd else "flat"
        rdb = Path(cmd.split("-rd report=", 1)[1].split()[0])
        n = hier if arm == "hier" else flat
        rdb.write_text("<report>" + "<item></item>" * n + "</report>")
        return 0, "", ""
    monkeypatch.setattr(R, "_docker_exec", fake_exec)
    R._MERGE_PROBE_CACHE.clear()
    pdk = _Pdk()
    pdk.drc_deck = deck
    return pdk, calls


def test_the_probe_reads_the_layer_and_width_from_the_pdks_own_files(tmp_path, monkeypatch):
    pdk, _ = _wire(monkeypatch, tmp_path, 0, 0)
    name, pair, width, why = R._probe_routing_layer(pdk, "c")
    assert (name, pair, width, why) == ("Metal1", (34, 0), 0.23, "")


def test_equal_arms_mean_the_deck_merges_and_the_flatten_is_skipped(tmp_path, monkeypatch):
    pdk, calls = _wire(monkeypatch, tmp_path, 6, 6)
    rec = R._deck_merges_across_hierarchy(tmp_path, pdk, "c")
    assert rec["answer"] is True, rec
    assert rec["violations"] == {"hier": 6, "flat": 6}
    assert "already merges across the hierarchy" in rec["reason"]
    assert any("probe_hier.gds" in c for c in calls)
    assert any("probe_flat.gds" in c for c in calls)


def test_more_violations_without_the_merge_keeps_the_flatten(tmp_path, monkeypatch):
    """#601's own case: the boundary costs violations, so the flatten stays."""
    pdk, _ = _wire(monkeypatch, tmp_path, 9, 6)
    rec = R._deck_merges_across_hierarchy(tmp_path, pdk, "c")
    assert rec["answer"] is False, rec
    assert "needs the flatten" in rec["reason"]


def test_fewer_violations_without_the_merge_decides_nothing(tmp_path, monkeypatch):
    pdk, _ = _wire(monkeypatch, tmp_path, 3, 6)
    rec = R._deck_merges_across_hierarchy(tmp_path, pdk, "c")
    assert rec["answer"] is None and "can classify" in rec["reason"]


def test_an_unreadable_input_decides_nothing_and_the_flatten_happens(tmp_path, monkeypatch):
    # no layer map
    pdk, _ = _wire(monkeypatch, tmp_path, 6, 6, texts={_Pdk.tech_lef: _TLEF})
    assert R._deck_merges_across_hierarchy(tmp_path, pdk, "c")["answer"] is None
    # no width in the tech LEF
    pdk, _ = _wire(monkeypatch, tmp_path, 6, 6,
                   texts={_Pdk.lefdef_layermap: _MAP, _Pdk.tech_lef: "LAYER x\nEND x\n"})
    assert R._deck_merges_across_hierarchy(tmp_path, pdk, "c")["answer"] is None
    # no KLayout DSL deck at all
    pdk, _ = _wire(monkeypatch, tmp_path, 6, 6, deck="")
    rec = R._deck_merges_across_hierarchy(tmp_path, pdk, "c")
    assert rec["answer"] is None and "no sign-off DRC deck" in rec["reason"]


def test_the_probe_is_asked_once_per_deck(tmp_path, monkeypatch):
    pdk, calls = _wire(monkeypatch, tmp_path, 6, 6)
    first = R._deck_merges_across_hierarchy(tmp_path, pdk, "c")
    n = len(calls)
    again = R._deck_merges_across_hierarchy(tmp_path, pdk, "c")
    assert again == first and len(calls) == n


def test_the_merge_script_only_flattens_when_it_is_told_to():
    script = R._GDS_LAYER_MERGE_PY
    assert 'os.environ.get("KEEP_HIERARCHY") == "1"' in script
    assert "if not _keep_hier:" in script
    assert "GDS_LAYER_MERGE_HIERARCHY" in script
    # the per-layer merge itself is unconditional
    assert "reg.merge()" in script


def test_the_caller_passes_the_flag_only_on_a_measured_yes():
    import inspect
    body = inspect.getsource(R._klayout_merge_layers)
    assert "_deck_merges_across_hierarchy(project, pdk, container)" in body
    assert '_merge_probe.get("answer") is True' in body
    assert "KEEP_HIERARCHY=1 " in body
    assert "signoff_merge_probe.json" in body
