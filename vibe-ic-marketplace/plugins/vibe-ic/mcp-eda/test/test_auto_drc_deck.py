#!/usr/bin/env python3
"""Tests for src/lib/auto_drc_deck.py — the helper extracted out of the
inline `python3 -c "..."` form in eda_drc_klayout (v0.99.1 fix to the
shell-escape bug `sh: 66: Syntax error: "(" unexpected`).

The helper is GENERAL — works for any tech LEF + KLayout-style layermap.
No PDK-specific behavior."""
import subprocess
import sys
from pathlib import Path

HELPER = Path(__file__).resolve().parent.parent / "src" / "lib" / "auto_drc_deck.py"
assert HELPER.exists()


def _run(*args):
    return subprocess.run(
        [sys.executable, str(HELPER), *args],
        capture_output=True, text=True, check=False,
    )


def test_emits_rules_for_routing_layer(tmp_path):
    techlef = tmp_path / "tech.lef"
    techlef.write_text(
        "LAYER MET1\n  TYPE ROUTING ;\n  WIDTH 0.230 ;\n"
        "  SPACING 0.230 ;\nEND MET1\n"
    )
    layermap = tmp_path / "layer.map"
    layermap.write_text("MET1 NET 9 0\n")
    out = tmp_path / "deck.drc"
    r = _run(
        f"--techlef={techlef}",
        f"--gds={tmp_path}/dummy.gds",
        "--top=top",
        f"--rdb={tmp_path}/r.rdb",
        f"--layermap={layermap}",
        f"--out={out}",
    )
    assert r.returncode == 0, r.stderr
    assert "AUTO_DRC_GENERATED" in r.stdout
    assert "rules=2" in r.stdout  # width + space
    deck = out.read_text()
    assert "met1 = input(9, 0)" in deck
    assert "met1.width" in deck
    assert "met1.space" in deck


def test_spacing_and_width_use_euclidian_metric(tmp_path):
    """The auto-deck MUST measure with `euclidian`, never `projection`.

    `projection` compares only the facing projection of parallel edges, so it
    cannot see a corner-to-corner (45-degree) separation at all. Measured on
    KLayout 0.30.6, two shapes offset dx = dy = 0.15 um against a 0.23 um
    limit (true Euclidean separation 0.2121 um — a genuine violation):

        metric=euclidian   violations=2   <- correctly flagged
        metric=projection  violations=0   <- MISSED

    The auto-deck is the fallback for PDKs shipping NO foundry deck, so a
    weaker metric here yields a false clean bill of health with nothing
    downstream to catch it. Every foundry deck in the tree (FreePDK45,
    sky130hd, asap7, ihp-sg13g2) uses `euclidian`; so does KLayout by
    default. This is a sign-off-integrity guard — do not relax it."""
    techlef = tmp_path / "tech.lef"
    techlef.write_text(
        "LAYER MET1\n  TYPE ROUTING ;\n  WIDTH 0.230 ;\n"
        "  SPACING 0.230 ;\nEND MET1\n"
    )
    layermap = tmp_path / "layer.map"
    layermap.write_text("MET1 NET 9 0\n")
    out = tmp_path / "deck.drc"
    r = _run(
        f"--techlef={techlef}",
        f"--gds={tmp_path}/dummy.gds",
        "--top=top",
        f"--rdb={tmp_path}/r.rdb",
        f"--layermap={layermap}",
        f"--out={out}",
    )
    assert r.returncode == 0, r.stderr
    deck = out.read_text()
    assert "projection" not in deck, (
        "auto-deck emitted the `projection` metric, which is blind to "
        f"corner-to-corner spacing violations:\n{deck}"
    )
    assert "met1.width(0.2298.um, euclidian)" in deck, deck
    assert "met1.space(0.2298.um, euclidian)" in deck, deck


def test_skips_layer_without_layermap_entry(tmp_path):
    """Layer in tech LEF but absent from layermap → no rule emitted (no
    false rule against an unknown GDS layer index)."""
    techlef = tmp_path / "tech.lef"
    techlef.write_text(
        "LAYER MET1\n  TYPE ROUTING ;\n  WIDTH 0.230 ;\n"
        "  SPACING 0.230 ;\nEND MET1\n"
    )
    layermap = tmp_path / "layer.map"
    layermap.write_text("# empty\n")
    out = tmp_path / "deck.drc"
    r = _run(
        f"--techlef={techlef}",
        f"--gds={tmp_path}/dummy.gds",
        "--top=top",
        f"--rdb={tmp_path}/r.rdb",
        f"--layermap={layermap}",
        f"--out={out}",
    )
    assert r.returncode == 0
    assert "rules=0" in r.stdout


def test_layermap_auto_discover(tmp_path):
    """When --layermap is empty, the helper searches the techlef's parent
    and grandparent directories. We verify the auto-discover branch fires
    for files matching `*layermap*` / `*layer_map*` / `*.layermap`."""
    techdir = tmp_path / "pdk" / "lef"
    techdir.mkdir(parents=True)
    techlef = techdir / "tech.lef"
    techlef.write_text(
        "LAYER MET1\n  TYPE ROUTING ;\n  WIDTH 0.5 ;\n"
        "  SPACING 0.4 ;\nEND MET1\n"
    )
    # Drop a layermap in the parent dir
    (tmp_path / "pdk" / "klayout.layermap").write_text("MET1 NET 7 0\n")
    out = tmp_path / "deck.drc"
    r = _run(
        f"--techlef={techlef}",
        f"--gds={tmp_path}/dummy.gds",
        "--top=top",
        f"--rdb={tmp_path}/r.rdb",
        "--layermap=",  # empty — triggers auto-discover
        f"--out={out}",
    )
    assert r.returncode == 0, r.stderr
    assert "LAYERMAP_AUTO_DETECTED=" in r.stdout
    assert "rules=2" in r.stdout


def test_handles_techlef_with_no_routing_layers(tmp_path):
    """Tech LEF with only OBS/MASTERSLICE layers (no ROUTING) → 0 rules,
    no crash."""
    techlef = tmp_path / "tech.lef"
    techlef.write_text(
        "LAYER OBS\n  TYPE MASTERSLICE ;\n  WIDTH 0.1 ;\nEND OBS\n"
    )
    layermap = tmp_path / "layer.map"
    layermap.write_text("OBS NET 1 0\n")
    out = tmp_path / "deck.drc"
    r = _run(
        f"--techlef={techlef}",
        f"--gds={tmp_path}/dummy.gds",
        "--top=top",
        f"--rdb={tmp_path}/r.rdb",
        f"--layermap={layermap}",
        f"--out={out}",
    )
    assert r.returncode == 0
    # MASTERSLICE is filtered out (only ROUTING / CUT considered)
    assert "rules=0" in r.stdout


def test_paths_with_special_chars(tmp_path):
    """Robustness: paths with spaces or parentheses don't break the helper.
    This is the failure class that broke v0.99.0 inline-python-c form."""
    weird_dir = tmp_path / "dir with spaces (and parens)"
    weird_dir.mkdir()
    techlef = weird_dir / "tech.lef"
    techlef.write_text(
        "LAYER MET1\n  TYPE ROUTING ;\n  WIDTH 1 ;\n"
        "  SPACING 1 ;\nEND MET1\n"
    )
    layermap = weird_dir / "layer.map"
    layermap.write_text("MET1 NET 9 0\n")
    out = weird_dir / "deck.drc"
    r = _run(
        f"--techlef={techlef}",
        f"--gds={weird_dir}/dummy.gds",
        "--top=top",
        f"--rdb={weird_dir}/r.rdb",
        f"--layermap={layermap}",
        f"--out={out}",
    )
    assert r.returncode == 0
    assert out.exists()
