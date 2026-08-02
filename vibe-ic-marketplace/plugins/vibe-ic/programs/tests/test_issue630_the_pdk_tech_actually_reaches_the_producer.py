"""#630/#631 — the producer could write readable labels; nothing asked it to.

v1.9.46 gave `def_gds_port_power_restore` a `--pdk-tech` argument and the ability
to write port labels on the layers a PDK DECLARES for them. It landed with the
runner never supplying the argument, so every production run kept writing labels
only on layer 100 — the layer the extractor drops. **The fix was inert.**

That is the wiring-leak class this repo keeps catching in review, shipped by the
gatekeeper. `checker_execution_wiring_audit` catches a checker nothing runs; it
does not catch an argument nothing passes.

MEASURED END TO END on a real design, in the image, with magic `gds read` +
`ext2spice`:

    as shipped (labels on 8/1)          (no `.subckt` line at all)
    restored WITH --pdk-tech            .subckt subservient i_clk i_rst
                                        i_sram_rdata[0] i_sram_rdata[1] …

and the producer's own line:

    restored: 31 I/O labels … (+31 on the PDK's own port-label layer(s)
    [(68, 5), (69, 5), (70, 5), (71, 5), (72, 5)] so a Magic extractor can
    read them)

That pair is also the ACCEPT CASE #631 was waiting for: a design whose labels
sit on a declared port layer, whose extractor then names its ports.

WHY THE PDK ROOT IS NOT A NEW DERIVATION: it is the same `libs.ref` split
`_synth_excluded_patterns` already uses, so the two cannot drift into different
notions of where the PDK is. The tech file is then LISTED in the container
rather than assumed — an absent one returns None and the caller DISCLOSES, which
is the difference between "no readable label layer" and a path that is not there.
"""
from __future__ import annotations

import importlib
import types

P = importlib.import_module("phase3_one_shot_runner")


def _pdk(liberty="/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/x.lib"):
    return types.SimpleNamespace(liberty=liberty, port_label_restore=None)


def _exec(monkeypatch, table):
    """Script `_docker_exec` by substring of the command."""
    seen = []

    def fake(container, cmd, **kw):
        seen.append(cmd)
        for frag, resp in table.items():
            if frag in cmd:
                return resp
        return 1, "", "unscripted"

    monkeypatch.setattr(P, "_docker_exec", fake)
    return seen


# ── the resolver reads the PDK, never guesses ──────────────────────────────
def test_the_tech_is_listed_under_the_pdk_root_from_the_liberty(monkeypatch):
    seen = _exec(monkeypatch, {
        "libs.tech/magic": (0, "/foss/pdks/sky130A/libs.tech/magic/"
                               "sky130A-GDS.tech\n", "")})
    got = P._resolve_magic_gds_tech(_pdk(), "c")
    assert got.endswith("sky130A-GDS.tech"), got
    assert any("/foss/pdks/sky130A/libs.tech/magic" in c for c in seen), seen


def test_a_liberty_outside_libs_ref_yields_None_not_a_guess(monkeypatch):
    """LOAD-BEARING. A PDK laid out differently must produce NO path rather
    than a constructed one that happens to look right."""
    _exec(monkeypatch, {})
    assert P._resolve_magic_gds_tech(_pdk("/opt/custom/x.lib"), "c") is None


def test_an_absent_tech_file_yields_None(monkeypatch):
    _exec(monkeypatch, {"libs.tech/magic": (0, "\n", "")})
    assert P._resolve_magic_gds_tech(_pdk(), "c") is None


def test_a_failed_listing_yields_None(monkeypatch):
    _exec(monkeypatch, {"libs.tech/magic": (2, "", "boom")})
    assert P._resolve_magic_gds_tech(_pdk(), "c") is None


def test_the_derivation_is_the_one_already_in_use():
    """The PDK root comes from the same `libs.ref` split the synth-exclusion
    resolver uses. Two derivations of "where is the PDK" drift; one does not."""
    src = (P.__file__ and open(P.__file__, encoding="utf-8").read()) or ""
    seg = src[src.index("def _resolve_magic_gds_tech"):]
    seg = seg[:seg.index("\ndef ", 10)]
    assert 'parts.index("libs.ref")' in seg


# ── and it REACHES the producer, which is the half that was missing ────────
def _restore(monkeypatch, tech):
    """Drive `_klayout_restore_port_labels` and capture the producer argv."""
    calls = {}
    monkeypatch.setattr(P, "_resolve_magic_gds_tech", lambda *_a, **_k: tech)
    monkeypatch.setattr(P, "_tool_in_path", lambda *_a, **_k: True)
    monkeypatch.setattr(P, "_ship_program", lambda name, d: d / name)
    monkeypatch.setattr(P, "_to_container_path", lambda s, c: s)

    def fake_exec(container, cmd, **kw):
        calls["cmd"] = cmd
        return 0, "restored: 3 I/O labels + 0 power-rail markers ()", ""

    monkeypatch.setattr(P, "_docker_exec", fake_exec)
    return calls


def test_the_pdk_tech_reaches_the_producer_argv(monkeypatch, tmp_path):
    """THE DEFECT. Without this the producer's ability is unreachable and every
    run writes labels the extractor drops."""
    calls = _restore(monkeypatch, "/foss/pdks/sky130A/libs.tech/magic/x-GDS.tech")
    gds = tmp_path / "top.gds"
    gds.write_bytes(b"\x00\x06\x00\x02\x00\x07")
    dfp = tmp_path / "top.def"
    dfp.write_text("DESIGN top ;\n", encoding="utf-8")
    monkeypatch.setattr(P._pl, "pnr_dir", lambda _p: tmp_path)
    (tmp_path / "top.labeled.gds").write_bytes(b"\x00\x06\x00\x02\x00\x07")
    P._klayout_restore_port_labels(tmp_path, "top", _pdk(), "c", gds, dfp,
                                   force=True)
    assert "--pdk-tech /foss/pdks/sky130A/libs.tech/magic/x-GDS.tech" \
        in calls["cmd"], calls["cmd"]


def test_no_tech_means_NO_FLAG_rather_than_an_empty_one(monkeypatch, tmp_path):
    """`--pdk-tech ''` would make the producer try to read an empty path and
    report a read failure, which is a different and misleading fact."""
    calls = _restore(monkeypatch, None)
    gds = tmp_path / "top.gds"
    gds.write_bytes(b"\x00\x06\x00\x02\x00\x07")
    dfp = tmp_path / "top.def"
    dfp.write_text("DESIGN top ;\n", encoding="utf-8")
    monkeypatch.setattr(P._pl, "pnr_dir", lambda _p: tmp_path)
    (tmp_path / "top.labeled.gds").write_bytes(b"\x00\x06\x00\x02\x00\x07")
    P._klayout_restore_port_labels(tmp_path, "top", _pdk(), "c", gds, dfp,
                                   force=True)
    assert "--pdk-tech" not in calls["cmd"], calls["cmd"]


def test_the_note_says_which_case_it_was(monkeypatch, tmp_path):
    """A run whose labels are NOT extractor-readable must say so — otherwise it
    reads exactly like the run that fixed the problem."""
    for tech, want in (("/p/libs.tech/magic/a-GDS.tech", "PDK port-label layers"),
                       (None, "does not read")):
        _restore(monkeypatch, tech)
        gds = tmp_path / "top.gds"
        gds.write_bytes(b"\x00\x06\x00\x02\x00\x07")
        dfp = tmp_path / "top.def"
        dfp.write_text("DESIGN top ;\n", encoding="utf-8")
        monkeypatch.setattr(P._pl, "pnr_dir", lambda _p: tmp_path)
        (tmp_path / "top.labeled.gds").write_bytes(b"\x00\x06\x00\x02\x00\x07")
        ok, note = P._klayout_restore_port_labels(
            tmp_path, "top", _pdk(), "c", gds, dfp, force=True)
        assert ok, note
        assert want in note, (tech, note)
