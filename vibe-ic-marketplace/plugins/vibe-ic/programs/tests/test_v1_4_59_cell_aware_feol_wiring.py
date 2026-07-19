"""v1.4.59 — svrfdrc --cell-aware-feol wiring (opt-in FEOL over-fire exemption).

The plugin passes `--cell-aware-feol=<cfg>` to the native svrfdrc buddy ONLY when
(a) the container's binary advertises the flag (`svrfdrc --help` mentions it,
image >= 0.2.19) AND (b) the design ships the inputs (a `cell_aware_feol`
sign-off-config block + a per-master library GDS + the placed {top}.def). When
either is absent the flag is omitted and the DRC report is BYTE-IDENTICAL to the
stock run (the exemption is provably-never-false-clean and off by default).

These tests mock the container probe (no docker) and prove:
  - the --cell-aware-feol probe returns True/False by --help and CACHES;
  - the cfg-builder GATE returns None (byte-identical) when the config block, the
    library GDS, or the placed DEF is absent — so a design that ships nothing is
    never touched.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


def _mk_pdk(**over):
    kw = dict(name="t", liberty="x", tech_lef="x", cell_lef="x",
              cell_gds=None, site="x", drc_deck=None, calibre_drc="/deck.rule")
    kw.update(over)
    return R.PdkConfig(**kw)


# ── probe caching ─────────────────────────────────────────────────────────────
def test_caf_probe_true_and_cached(monkeypatch):
    R._SVRFDRC_CAF_CACHE.clear()
    calls = {"n": 0}

    def fake_exec(container, cmd, **kw):
        calls["n"] += 1
        return 0, "  --cell-aware-feol=cfg  OPT-IN ...\n  --threads=n\n", ""

    monkeypatch.setattr(R, "_docker_exec", fake_exec)
    assert R._svrfdrc_supports_cell_aware_feol("c", "svrfdrc") is True
    assert R._svrfdrc_supports_cell_aware_feol("c", "svrfdrc") is True
    assert calls["n"] == 1                       # cached, one probe


def test_caf_probe_false_on_old_image(monkeypatch):
    R._SVRFDRC_CAF_CACHE.clear()
    monkeypatch.setattr(
        R, "_docker_exec",
        lambda container, cmd, **kw: (0, "  --cell=name\n  --threads=n\n", ""))
    assert R._svrfdrc_supports_cell_aware_feol("old", "svrfdrc") is False


def test_caf_probe_false_on_exec_error(monkeypatch):
    R._SVRFDRC_CAF_CACHE.clear()

    def boom(container, cmd, **kw):
        raise RuntimeError("docker down")

    monkeypatch.setattr(R, "_docker_exec", boom)
    assert R._svrfdrc_supports_cell_aware_feol("x", "svrfdrc") is False


# ── cfg-builder gate: absent inputs -> None (byte-identical stock DRC) ─────────
def test_build_cfg_none_when_config_absent(tmp_path):
    pdk = _mk_pdk(cell_aware_feol=None, cell_gds="/lib.gds")
    assert R._build_cell_aware_feol_cfg(
        tmp_path, "top", pdk, "c", "svrfdrc", "/deck.rule") is None


def test_build_cfg_none_when_cell_gds_absent(tmp_path):
    pdk = _mk_pdk(cell_aware_feol={"feol_gds": ["2/0"], "feol_rules": ["NW.S"]},
                  cell_gds=None)
    assert R._build_cell_aware_feol_cfg(
        tmp_path, "top", pdk, "c", "svrfdrc", "/deck.rule") is None


def test_build_cfg_none_when_placed_def_missing(tmp_path):
    # config + cell_gds present but no <top>.def in pnr_dir -> gate not met
    pdk = _mk_pdk(cell_aware_feol={"feol_gds": ["2/0"], "feol_rules": ["NW.S"]},
                  cell_gds="/lib.gds")
    assert R._build_cell_aware_feol_cfg(
        tmp_path, "top", pdk, "c", "svrfdrc", "/deck.rule") is None
