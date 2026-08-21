"""Regression: the streamout layermap conformance check must treat the design's
hard-macro / IP GDS layers as legitimate library geometry, not ORPHAN_LAYER.

Root shape: a vendor hard-macro GDS is MERGED into the streamed GDS and brings
its own layers; those layers are usually absent from the std-cell library GDS,
so before this fix they were false-flagged ORPHAN_LAYER on ANY design that
integrates a hard macro. Chip/PDK-AGNOSTIC by construction: every fixture layer
here is a synthetic generic number (68/20 design, 200/0 macro) — no vendor / SKU
/ design literal appears.
"""
import importlib
from pathlib import Path

m = importlib.import_module("gds_streamout_layermap_check")


def _patch_layers(monkeypatch, mapping):
    """Make scan_gds_layers return a controlled layer-set per file path
    (avoids crafting real GDS binaries; the parser itself is tested elsewhere)."""
    monkeypatch.setattr(
        m, "scan_gds_layers",
        lambda p, *a, **k: set(mapping.get(Path(p), set())))


def _files(tmp_path, names):
    out = {}
    for n in names:
        f = tmp_path / n
        f.write_bytes(b"\x00")   # just needs .is_file() True
        out[n] = f
    return out


def test_macro_gds_layer_is_not_orphan(monkeypatch, tmp_path):
    f = _files(tmp_path, ["design.gds", "lib.gds", "macro.gds"])
    _patch_layers(monkeypatch, {
        f["design.gds"]: {(68, 20), (200, 0)},   # design draws a macro layer
        f["lib.gds"]:    {(68, 20)},              # std-cell library only
        f["macro.gds"]:  {(200, 0)},              # the macro's own layer
    })
    # WITHOUT the macro GDS: 200/0 is a (false) orphan.
    fnd, _ = m.audit(f["design.gds"], None, f["lib.gds"], None,
                     require_layermap=False)
    assert any(x.category == "ORPHAN_LAYER" for x in fnd)

    # WITH the macro GDS: 200/0 is recognised, zero orphans.
    fnd2, st2 = m.audit(f["design.gds"], None, f["lib.gds"], None,
                        require_layermap=False, macro_gds=[f["macro.gds"]])
    assert not any(x.category == "ORPHAN_LAYER" for x in fnd2)
    assert "200/0" in st2.macro_layers


def test_genuinely_unmapped_layer_still_flagged(monkeypatch, tmp_path):
    # A layer in NEITHER lib nor macro nor map must STILL be an orphan — the
    # fix must not weaken the gate into a rubber stamp.
    f = _files(tmp_path, ["design.gds", "lib.gds", "macro.gds"])
    _patch_layers(monkeypatch, {
        f["design.gds"]: {(68, 20), (200, 0), (999, 7)},
        f["lib.gds"]:    {(68, 20)},
        f["macro.gds"]:  {(200, 0)},
    })
    fnd, st = m.audit(f["design.gds"], None, f["lib.gds"], None,
                      require_layermap=False, macro_gds=[f["macro.gds"]])
    orph = [x for x in fnd if x.category == "ORPHAN_LAYER"]
    assert orph and "999/7" in orph[0].details
    assert "200/0" not in orph[0].details   # macro layer cleared


def test_no_macro_gds_is_byte_identical_behaviour(monkeypatch, tmp_path):
    # macro_gds=None (default) must behave exactly as before the fix.
    f = _files(tmp_path, ["design.gds", "lib.gds"])
    _patch_layers(monkeypatch, {
        f["design.gds"]: {(68, 20)},
        f["lib.gds"]:    {(68, 20)},
    })
    fnd, st = m.audit(f["design.gds"], None, f["lib.gds"], None,
                      require_layermap=False)
    assert not any(x.category == "ORPHAN_LAYER" for x in fnd)
    assert st.macro_layers == []


def test_cli_macro_gds_flag_wires_through(monkeypatch, tmp_path):
    f = _files(tmp_path, ["design.gds", "lib.gds", "macro.gds"])
    _patch_layers(monkeypatch, {
        f["design.gds"]: {(68, 20), (200, 0)},
        f["lib.gds"]:    {(68, 20)},
        f["macro.gds"]:  {(200, 0)},
    })
    rc = m.main(["--gds", str(f["design.gds"]),
                 "--lib-gds", str(f["lib.gds"]),
                 "--macro-gds", str(f["macro.gds"]),
                 "--allow-missing-layermap"])
    assert rc == 0   # 200/0 allowed via --macro-gds → no ERROR → exit 0


def test_unscannable_macro_gds_warns_not_swallows(monkeypatch, tmp_path):
    # A declared macro GDS that fails to scan must (a) NOT skip the whole
    # check, (b) surface a WARNING, (c) contribute zero layers (fail-safe).
    f = _files(tmp_path, ["design.gds", "lib.gds", "macro.gds"])
    def boom(p, *a, **k):
        p = Path(p)
        if p == f["macro.gds"]:
            raise ValueError("corrupt macro record")   # non-(OSError/struct)
        return {f["design.gds"]: {(68, 20), (200, 0)},
                f["lib.gds"]: {(68, 20)}}.get(p, set())
    monkeypatch.setattr(m, "scan_gds_layers", boom)
    fnd, st = m.audit(f["design.gds"], None, f["lib.gds"], None,
                      require_layermap=False, macro_gds=[f["macro.gds"]])
    assert any(x.category == "MACRO_GDS_UNSCANNED" for x in fnd)      # WARN
    assert any(x.category == "ORPHAN_LAYER" for x in fnd)             # gate ran
    assert st.macro_layers == []                                     # fail-safe
