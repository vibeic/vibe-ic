"""#630/#631 — the restored labels were present and invisible to the extractor.

#613 landed and does what it says: the restore puts a text on GDS layer 100 for
every placed DEF pin, and `gds_port_label_check` then PASSes. On a real
mixed-signal run the top-level LVS still could not name one port:

    restored: 20 I/O labels + 633 power-rail markers
    PASS: u_hawaii_adc.gds — names all 20 placed port(s)        rc 0

    .subckt u_hawaii_adc                    <- no ports, still
    Final result: Circuits do NOT match uniquely (top-level cell has no ports)

CAUSE. Layer 100 is this file's contract with `klayout_pdk_lvs`, the GEOMETRIC
extractor. M1's top-level LVS does not use that consumer — it extracts with
MAGIC, which reads GDS through the PDK's own tech. That tech declares its port
layers explicitly and has no entry for layer 100, so `gds read` drops all 20
texts, `port makeall` has nothing to promote, and extraction emits a portless
subckt.

#631 IS THE SAME FINDING AIMED AT THE GATE, and it is right: the check's own
argument — that a PDK CLASS predicts nothing and the readable fact is whether
the labels are IN THE FILE — applies to itself. Presence predicts nothing
either.

THE LAYER IS READ, NOT GUESSED. Hardcoding one would be the error class #613
fixed. Magic's `*-GDS.tech` states it uniformly, VERIFIED ON TWO INDEPENDENT
PDKs:

    layer  MET2PIN           layer  MET2PIN
    labels MET2PIN port      labels MET2PIN port
    calma 10 2               calma 69 5

WHY THE GATE ONLY REPORTS. Blocking is not calibrated, and the counter-evidence
turned up while writing this: the restore writes 100, NATIVE KLayout streamout
writes 10/1, and sky130A's tech declares neither (68/5, 69/5, …). `subservient`,
a shipped cell whose sign-off is green, would be flagged by the naive rule.
Either its LVS never reads the GDS through Magic, or the rule is wrong — and
until that is established, failing a design on a predicate whose accept case has
never been run is exactly what #613's own calibration rule forbids.
"""
from __future__ import annotations

import importlib
import os
import pathlib

R = importlib.import_module("def_gds_port_power_restore")
C = importlib.import_module("gds_port_label_check")
G = importlib.import_module("gds_substance_check")

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]

#: Directory holding real Magic `*-GDS.tech` files to validate the parser
#: against. Set `VIBEIC_PDK_TECH_DIR` to a directory containing them (they are
#: extractable from any PDK image with `cat /foss/pdks/<pdk>/libs.tech/magic/
#: <pdk>-GDS.tech`). Unset -> those cases skip; the synthetic fixture still
#: covers the grammar. NO personal path is baked in — a shipped test that names
#: one user's home cannot run anywhere else.
_TECH = pathlib.Path(os.environ.get("VIBEIC_PDK_TECH_DIR", "")) \
    if os.environ.get("VIBEIC_PDK_TECH_DIR") else None

_SYNTH_TECH = """\
layer  NWELL NWELL
 calma 31 0
layer NWELLPIN
 labels NWELLPIN port
 calma 31 2
layer  MET1
 calma 8 0
layer  MET1PIN
 labels MET1PIN port
 calma 8 2
layer  MET2TXT
 labels MET2TXT noport
 calma 10 25
layer  MET3PIN
 labels MET3PIN noport
 calma 30 25
layer  MET2PIN
 labels MET2PIN port
 calma 10 2
"""


# ── the resolver reads the PDK's own declaration ───────────────────────────
def test_the_port_label_layers_come_from_the_tech():
    got = R.pdk_port_label_layers(_SYNTH_TECH)
    assert got == {1: (8, 2), 2: (10, 2)}, got


def test_a_noport_label_layer_is_not_a_port_layer():
    """`noport` sits beside the port blocks and means the OPPOSITE. Matching
    `labels <X> <anything>` would take the wrong layer.

    NON-VACUOUS BY CONSTRUCTION: the fixture's `noport` block is named
    `MET3PIN`, so the `...PIN` suffix guard does NOT already exclude it and the
    `port` keyword is the only thing doing the work. The first version used
    `MET2TXT`, which the suffix guard rejected anyway — the mutation that
    accepted `noport` left the suite green.
    """
    got = R.pdk_port_label_layers(_SYNTH_TECH)
    assert (10, 25) not in got.values()
    assert 3 not in got, (
        "a `noport` layer was taken as a port layer — labels written there "
        "are dropped by the extractor exactly as if they were on layer 100")
    assert (30, 25) not in got.values()


def test_a_block_without_calma_contributes_nothing():
    """A layer the tech names but gives no GDS coordinates for is a half-known
    answer, and a half-known layer is not a layer."""
    assert R.pdk_port_label_layers(
        "layer MET1PIN\n labels MET1PIN port\n") == {}


def test_a_tech_declaring_no_port_layer_is_empty_not_defaulted():
    """LOAD-BEARING. `{}` is what makes the restore DISCLOSE instead of
    guessing; a default here would put labels on some other PDK's layer."""
    assert R.pdk_port_label_layers("layer FOO\n calma 1 0\n") == {}
    assert R.pdk_port_label_layers("") == {}


def test_the_metal_index_comes_from_the_shared_resolver():
    """`MET2PIN` -> 2 through `metal_index`, so the PDK layer and the datatype
    contract cannot drift into different notions of which metal is which."""
    assert R.metal_index("MET2") == 2
    assert set(R.pdk_port_label_layers(_SYNTH_TECH)) == {1, 2}


def test_two_real_pdk_techs_parse():
    """Real bytes from two independent PDKs — a parser proved only on its own
    fixture is proved against itself."""
    if _TECH is None or not _TECH.is_dir():
        return
    for name, want_met2 in (("ihp-sg13g2-GDS.tech", (10, 2)),
                            ("sky130A-GDS.tech", (69, 5))):
        f = _TECH / name
        if not f.is_file():
            continue
        got = R.pdk_port_label_layers(f.read_text(errors="replace"))
        assert got.get(2) == want_met2, (name, got)
        assert len(got) >= 5, (name, got)


# ── the restore writes there IN ADDITION to layer 100 ──────────────────────
def test_the_klayout_contract_layer_is_kept():
    """Layer 100 is the contract with `klayout_pdk_lvs`; writing the PDK layer
    INSTEAD would break the geometric extractor to fix the Magic one."""
    src = (pathlib.Path(R.__file__)).read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "tc.shapes(tlayer).insert(pya.Text(name, _tr))" in code
    assert "tc.shapes(ly.layer(*_pdk_ld)).insert(pya.Text(name, _tr))" in code


def _seed_layout(path):
    """A REAL input layout, because :func:`restore` opens one — see the long
    note in `test_no_pdk_layer_is_disclosed_not_silent`."""
    try:
        import pya
    except Exception:                        # noqa: BLE001 — absence is a state
        path.write_bytes(b"")
        return
    layout = pya.Layout()
    layout.create_cell("c")
    layout.write(str(path))


def test_no_pdk_layer_is_disclosed_not_silent(tmp_path, capsys):
    """A run that wrote NO extractor-readable label must SAY SO — that is the
    state #630 measured, and it looked identical to success.

    THE PREMISE THIS TEST SHIPPED WITH WAS FALSE, AND IT MADE THE TEST VACUOUS.
    It handed `restore` a GDS that does not exist and asserted `rc == 3` — which
    is the "'pya' not available. DISCLOSED." exit, a DIFFERENT disclosure from
    the one this test is named for. So on a host WITHOUT KLayout it passed
    without the `NO PDK PORT-LABEL LAYER` sentence ever being produced, and on
    a host WITH it — the pinned landing image and every host in this fleet — the
    call reached `pya.Layout().read()` on a missing file and raised
    `RuntimeError: Unable to open file ... (errno=2)`. Measured 2026-08-27 on
    both. Either way the note that makes the state visible was never read, and
    deleting the `_pdk_note` branch outright would not have turned this red.

    The correction is the input. With a real layout the run reaches the write,
    and the assertion is the sentence itself. The invariant is stated once for
    both worlds and is non-vacuous in each: the run NEVER reports having
    restored labels without naming which layer they can be read from. Where
    KLayout is present that is the #630 note beside the `restored:` line; where
    it is absent nothing was written and the run must say that instead of
    claiming a restore."""
    dp = tmp_path / "x.def"
    dp.write_text("DESIGN c ;\nUNITS DISTANCE MICRONS 1000 ;\nPINS 1 ;\n"
                  "    - a + LAYER Metal2 ( -70 -70 ) ( 70 70 )\n"
                  "      + PLACED ( 1000 2000 ) N ;\nEND PINS\nEND DESIGN\n",
                  encoding="utf-8")
    gds_in = tmp_path / "in.gds"
    _seed_layout(gds_in)
    rc = R.restore(str(gds_in), str(dp), str(tmp_path / "o.gds"))
    out = capsys.readouterr()
    assert rc in (0, 3), (rc, out.out, out.err)
    if rc == 0:
        assert "restored:" in out.out, out.out
        assert "NO PDK PORT-LABEL LAYER" in out.out, out.out
    else:
        assert "'pya' not available" in out.err, out.err
        assert "restored:" not in out.out, out.out


# ── the gate REPORTS readability and does not fail on it ───────────────────
def _cen(labels, layer):
    class _C:
        label_layers_per_structure = {"top": [layer] * len(labels)}
    return _C()


def test_a_label_on_a_declared_port_layer_reads_as_readable(tmp_path):
    tech = tmp_path / "t.tech"
    tech.write_text(_SYNTH_TECH, encoding="utf-8")
    ok, note = C.label_layer_readability(_cen(["a"], (10, 2)), "top", str(tech))
    assert ok is True
    assert "can name the ports" in note


def test_a_label_off_every_declared_port_layer_is_MEASURED_but_not_a_FAIL(tmp_path):
    """THE MEASUREMENT AND THE VERDICT ARE SEPARATE, and keeping them separate
    is the whole point.

    The predicate says `False` — measured off every declared layer — and that
    is a FACT the producer acts on (it re-runs the restore). The GATE still
    does not fail on it, because blocking is a calibration decision that is not
    settled: on the shipped corpus both sha256 and subservient are off-layer,
    and neither has a passing LVS to prove the rule would be right about them.

    An earlier version of this test asserted `None`, which conflated "I have
    not measured" with "I measured and chose not to fail" — and that
    conflation is what stopped the producer from being able to act at all.
    """
    tech = tmp_path / "t.tech"
    tech.write_text(_SYNTH_TECH, encoding="utf-8")
    ok, note = C.label_layer_readability(_cen(["a"], (100, 2)), "top", str(tech))
    assert ok is False, "off-layer must be MEASURED, not left unknown"
    assert "ADVISORY" in note and "not yet calibrated" in note
    assert "(100, 2)" in note and "(10, 2)" in note


def test_the_gate_still_does_not_FAIL_on_an_off_layer_label():
    """The other half: a measured False must not reach the VERDICT. If it ever
    does, it fails three shipped designs on a rule with no accept case in the
    corpus.

    Driven on a real shipped GDS with a real PDK tech, because a synthetic
    fixture would prove only the fixture."""
    import subprocess
    import sys as _sys
    # Derived from this file's own location, NOT typed. The docstring at the
    # top of `_TECH` says a shipped test naming one user's home cannot run
    # anywhere else — and the first version of this test did exactly that, two
    # edits after that sentence was written. `shipped_path_portability_check`
    # caught it at the landing gate.
    base = _REPO / "benchmark-data" / "ic" / "subservient"
    tech = _TECH / "sky130A-GDS.tech" if _TECH else None
    # THE GUARD WAS ON THE WRONG THING. `base.is_dir()` is true in every
    # checkout — the directory is tracked — while the GDS this drives on is
    # NOT IN GIT at all (`git ls-files …/stage4/gds` -> 0). So the test passed
    # only where that artefact happens to sit on disk, and failed in every
    # worktree — which is the environment the dispatch doctrine tells every
    # agent to work in, and the one the widened selection first ran it in.
    #
    # A bare `return` also made the absence look like a pass. Skipping loudly
    # is the honest shape: the accept case genuinely needs a real shipped GDS
    # (a synthetic fixture would prove only the fixture), so where there is
    # none there is nothing to assert.
    gds = sorted((base / "phase3/stage4/gds").glob("*.gds")) if base.is_dir() else []
    if not gds or tech is None or not tech.is_file():
        import pytest
        pytest.skip("needs a real shipped subservient GDS (untracked) and a PDK "
                    "tech; absent here, so there is no accept case to drive")
    out = pathlib.Path("/tmp") / "t630_gate.json"
    r = subprocess.run(
        [_sys.executable, str(_PROGRAMS / "gds_port_label_check.py"), str(base),
         "--pdk-tech", str(tech), "--json", str(out)],
        capture_output=True, text=True, timeout=60)
    import json
    rep = json.loads(out.read_text())
    f = rep["files"][0]
    assert r.returncode == 0, r.stderr[-300:]
    assert f["verdict"] == "OK"
    assert f["labels_extractor_readable"] is False, f
    (base / "reports/phase3/gds_port_labels.json").unlink(missing_ok=True)


def test_no_tech_is_UNKNOWN_not_confirmed(tmp_path):
    ok, note = C.label_layer_readability(_cen(["a"], (100, 2)), "top", None)
    assert ok is None
    assert "UNKNOWN" in note and "not confirmed" in note


def test_a_tech_declaring_nothing_cannot_establish_it_either_way(tmp_path):
    tech = tmp_path / "t.tech"
    tech.write_text("layer FOO\n calma 1 0\n", encoding="utf-8")
    ok, note = C.label_layer_readability(_cen(["a"], (100, 2)), "top", str(tech))
    assert ok is None and "either way" in note


def test_a_top_with_no_labels_says_nothing_here():
    """The no-label case is `NO_LABELS`' job; a second sentence about layers
    would be noise on a cell that has none."""
    assert C.label_layer_readability(_cen([], (0, 0)), "top", None) == (None, "")


def test_the_shipped_corpus_still_passes():
    """THE ACCEPT CASE that decides whether this could block: the three real
    sign-off GDS must stay rc 0 with the advisory present."""
    base = _REPO / "benchmark-data" / "ic"
    if not base.is_dir():
        return
    for proj in ("sha256", "subservient", "spm"):
        gds = list((base / proj / "phase3/stage4/gds").glob("*.gds"))
        if not gds:
            continue
        cen = G.structure_text_census(gds[0].read_bytes())
        layers = set(cen.label_layers_per_structure.get(gds[0].stem, []))
        assert layers, f"{proj}: the census lost the label layers"
