"""metal_fill_emit — the ENGINE SCRIPT itself must reach the KLayout runner,
not just the GDS/config/output it operates on.

MEASURED (spm x gf180mcuD/sky130A/ihp-sg13g2, 2026-08-07): `_density_metal_fill`
resolves its engine via `find_engine("metal_fill", "metal_fill.py")` — the copy
vendored INSIDE the plugin's own installation directory
(`~/.claude/plugins/cache/.../vibe-ic/<version>/programs/metal_fill/metal_fill.py`).
`phase3_one_shot_runner._container_mounts` never bind-mounts the plugin
installation path into the EDA container; only the project directory is
mounted, because that is the one thing every step actually needs. So on every
default run `ContainerRunner.covers(engine)` is False — the container genuinely
cannot see that host path — and the emitter DISCLOSED_SKIPped:

    "engine path is not reachable by the KLayout runner
     (container: <name>:klayout): /home/.../plugins/cache/.../metal_fill.py"

`cfg_path` already had this exact problem and already had the fix, one function
above: when the ORIGINAL config path is not covered, a fresh copy is
materialised under the report directory (which IS covered, because the flow's
own output has to land there). `metal_fill.py` is a single self-contained
KLayout batch script — env-var driven, no sibling imports at runtime (see its
own module docstring) — so the identical materialise-and-retarget move applies
to `engine` with no semantic cost.

Verified end-to-end against a real gf180mcuD run's actual streamed GDS: before
this fix, `metal_fill_emit` DISCLOSED_SKIPped on every one of the three PDKs
this session ran, so the shipped GDS carried metal2-5 density as low as
0.86%-4.04% and the real `gf180mcu.drc` sign-off deck reported 6 violations
(M1.4-M5.4, all coverage rules). Re-run through the fixed emitter and the SAME
real deck: every layer clears the 30% foundry floor and
``DRC RESULT: SUCCESS (0 violations)``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import metal_fill_emit as mfe  # noqa: E402
import _klayout_launch as kl   # noqa: E402


_ENGINE_BODY = "# fake KLayout batch script body, distinguishable by this line\n"


class _FakeContainerRunner(kl.KLayoutRunner):
    """Mimics `ContainerRunner`'s CONTRACT exactly: covers() is True only
    under one root (standing in for the container's real bind mount), and
    run() records the engine path it was actually asked to invoke — that
    record is what proves materialisation happened, not just that the run
    didn't crash."""

    kind = "container"
    detail = "fake:klayout"

    def __init__(self, mounted_root: Path):
        self._root = mounted_root
        self.invoked_with: Path | None = None

    def covers(self, host_path) -> bool:
        p = str(host_path)
        r = str(self._root)
        return p == r or p.startswith(r + "/")

    def run(self, script, env, *, path_keys=(), timeout=1800):
        self.invoked_with = Path(script)
        # A minimal, valid report: `run()` treats "no report file" as FAIL
        # regardless of rc, so the fake still has to write one.
        Path(env["FILL_REPORT"]).write_text(json.dumps({
            "verdict": "PASS",
            "layers": [{"name": "metal1", "target": 0.35,
                       "density_after": 0.40, "worst_window_after": 0.40,
                       "reached": True, "over_max": False}],
        }))
        return 0, "ok", ""


def _project(tmp_path: Path):
    """(project, config_path). `phase3/stage3/pnr/*.gds` is auto-discovered
    via `_GDS_GLOBS`; the config is NOT (`_CFG_GLOBS` looks under `signoff/`
    or `input/pdk/bridge/` — the real caller, `_density_metal_fill`, always
    passes `--config` explicitly at the path used here), so every test below
    passes `config_path` through rather than relying on auto-discovery."""
    proj = tmp_path / "proj"
    pnr = proj / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "chip_top.gds").write_bytes(b"\x00" * 16)  # content is opaque here
    cfg_path = pnr / "metal_fill_density_cfg.json"
    cfg_path.write_text(json.dumps(
        {"layers": [{"name": "metal1", "target": 0.35}]}))
    return proj, cfg_path


def test_engine_outside_the_mount_is_materialised_into_the_covered_report_dir(
        tmp_path, monkeypatch):
    proj, cfg_path = _project(tmp_path)
    # The plugin's own install tree — a sibling of `proj`, i.e. genuinely
    # OUTSIDE whatever the fake runner covers. This is the exact shape of
    # `find_engine`'s vendored-copy branch on a real host.
    plugin_install = tmp_path / "plugin_install" / "metal_fill"
    plugin_install.mkdir(parents=True)
    real_engine = plugin_install / "metal_fill.py"
    real_engine.write_text(_ENGINE_BODY)

    fake_runner = _FakeContainerRunner(mounted_root=proj)
    monkeypatch.setattr(mfe._kl, "find_engine", lambda *a, **k: real_engine)
    monkeypatch.setattr(mfe._kl, "find_runner", lambda *a, **k: fake_runner)

    res = mfe.run(proj, gds=None, config=str(cfg_path), out=None, in_place=True,
                  cell="chip_top", report=None)

    assert res.get("verdict") != "DISCLOSED_SKIP", res
    assert fake_runner.invoked_with is not None, \
        "the fake runner was never called — the skip fired before run()"
    # THE ASSERTION THAT MATTERS: what actually got invoked is NOT the
    # original (uncovered) engine path, and IS covered by the fake mount.
    assert fake_runner.invoked_with != real_engine
    assert fake_runner.covers(fake_runner.invoked_with)
    assert fake_runner.invoked_with.read_text() == _ENGINE_BODY, \
        "the materialised copy must be byte-identical to the vendored engine"
    # And it lives under the project's report directory, not somewhere new.
    assert str(fake_runner.invoked_with).startswith(
        str(proj / "reports" / "phase3"))


def test_engine_already_covered_is_used_verbatim_no_copy_made(
        tmp_path, monkeypatch):
    """The reverse case: a HostRunner (or a container that DOES mount the
    plugin tree) needs no materialisation at all — this must stay a no-op."""
    proj, cfg_path = _project(tmp_path)
    engine_dir = proj / "vendored_engine"
    engine_dir.mkdir()
    real_engine = engine_dir / "metal_fill.py"
    real_engine.write_text(_ENGINE_BODY)

    fake_runner = _FakeContainerRunner(mounted_root=proj)  # covers ALL of proj
    monkeypatch.setattr(mfe._kl, "find_engine", lambda *a, **k: real_engine)
    monkeypatch.setattr(mfe._kl, "find_runner", lambda *a, **k: fake_runner)

    res = mfe.run(proj, gds=None, config=str(cfg_path), out=None, in_place=True,
                  cell="chip_top", report=None)

    assert res.get("verdict") != "DISCLOSED_SKIP", res
    assert fake_runner.invoked_with == real_engine, (
        "an already-reachable engine must be run in place, not copied — "
        f"got {fake_runner.invoked_with}")


def test_gds_outside_the_mount_still_skips_materialisation_is_engine_only(
        tmp_path, monkeypatch):
    """The fix must NOT widen into 'copy anything uncovered'. A GDS the caller
    pointed outside the project is a real configuration problem — silently
    copying a multi-MB layout would hide it, not fix it."""
    proj, cfg_path = _project(tmp_path)
    outside_gds = tmp_path / "elsewhere" / "chip_top.gds"
    outside_gds.parent.mkdir(parents=True)
    outside_gds.write_bytes(b"\x00" * 16)

    plugin_install = tmp_path / "plugin_install" / "metal_fill"
    plugin_install.mkdir(parents=True)
    real_engine = plugin_install / "metal_fill.py"
    real_engine.write_text(_ENGINE_BODY)

    fake_runner = _FakeContainerRunner(mounted_root=proj)
    monkeypatch.setattr(mfe._kl, "find_engine", lambda *a, **k: real_engine)
    monkeypatch.setattr(mfe._kl, "find_runner", lambda *a, **k: fake_runner)

    res = mfe.run(proj, gds=str(outside_gds), config=str(cfg_path), out=None,
                  in_place=True, cell="chip_top", report=None)

    assert res.get("verdict") == "DISCLOSED_SKIP"
    assert "GDS" in res.get("reason", "")
    assert fake_runner.invoked_with is None, \
        "run() must not have been reached — GDS is unreachable, unfixably"
