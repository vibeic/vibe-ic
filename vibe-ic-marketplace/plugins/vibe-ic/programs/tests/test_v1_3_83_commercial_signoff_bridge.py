"""v1.3.83 — commercial-PDK sign-off bridge regressions (commercial_pdk_v1382/v1383fix
close-loop):

1. streamout must force macro_resolution_mode=2 (commercial LEFs ship no
   FOREIGN, so macro_layout_files was silently ignored -> GDS held ZERO
   std-cell FEOL -> vacuous FEOL PASSes + phantom min-area on pin rects).
2. bridge/signoff_config.json drives the std-cell exclusion marker + dummy
   fill; discovery lands them on PdkConfig.
3. step_lvs: calibre-binary-absent must FALL THROUGH to the open-source
   Magic+netgen route when the bridge ships the tech (STRONG DOCTRINE — no
   commercial-EDA-tool excuse), not dead-end ENV_UNAVAILABLE.
4. dashboard web daemon retries ports and records the actually-bound URL
   (a stale daemon on 8787 used to silently serve the PREVIOUS run).
"""
import json
import os
import socket
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as p3
import _watchdog

#: A LOOK INTERVAL and two LOOK COUNTS — never a runtime bound. Nothing here
#: decides "too slow"; the only thing that ends a wait is the subject making no
#: forward progress at all.
_LOOK_S = 0.1
_STALL_LOOKS = 300
_MAX_LOOKS = 200_000


#: CLK_TCK once — `/proc` reports thread CPU in clock ticks.
_TICK = float(os.sysconf("SC_CLK_TCK") or 100)


def _server_cpu_s():
    """CPU seconds burned by every thread of this process EXCEPT this one.

    THE WAITER CANNOT BE ITS OWN PROGRESS SIGNAL. The first version of this used
    `sum(os.times()[:2])` — whole-process CPU — and that is wrong in the one
    direction that matters: the retry loop asking "is the server done yet?" also
    burns CPU, so the counter advances on the WAITER's account and a completely
    wedged server keeps looking busy. The stall could then never fire and the
    wait would run to its iteration cap — a hang introduced while removing a
    false verdict. MEASURED: the falsification probe for this shape did not
    terminate until the signal was narrowed to the lines below.

    Excluding the calling thread leaves exactly the server's own work —
    `serve_forever` plus the per-request thread `ThreadingHTTPServer` spawns.
    Returns None when nothing is readable, which `ProgressMeter` carries forward
    rather than mistaking for a reset."""
    me = str(threading.get_native_id())
    total = 0.0
    seen = False
    try:
        tids = os.listdir("/proc/self/task")
    except OSError:
        return None
    for tid in tids:
        if tid == me:
            continue
        try:
            with open(f"/proc/self/task/{tid}/stat", "rb") as fh:
                fields = fh.read().rsplit(b")", 1)[1].split()
            total += (int(fields[11]) + int(fields[12])) / _TICK
            seen = True
        except (OSError, IndexError, ValueError):
            continue
    return total if seen else None


def _fetch(url):
    """GET `url` and return the response. NO wall-clock bound, and no retry.

    RUNG 2 (structural assertion). Rung 1 for an HTTP wait would mean demoting
    the socket timeout to a LOOK INTERVAL and retrying while the server still
    makes progress. MEASURED, on a 6 s handler under a 0.5 s look: the retry
    never obtains a response at all. Each attempt abandons the request in flight
    and the next starts from scratch, so an answer slower than one look is never
    collected, and the wait ends — via the stall detector, after 11 looks —
    reporting that the server never answered a request it was in fact serving.
    That is the SAME false verdict the 5 s bound produced, relocated rather than
    removed, and it lands in exactly the case the bound was wrong about: a
    handler slower than the guess.

    The progress signal is not what fails. The identical rung-1 shape DOES stop
    correctly on a wedge wherever the waiter never touches the subject, which is
    why the file and bind polls in this campaign keep rung 1. It is the RETRY
    that is unavailable for an HTTP wait, not the watchdog.

    So the bound is gone and nothing replaces it with another clock. What is
    asserted is the thing meant: the server ANSWERED, and with what. One
    blocking GET against that same 6 s handler returns 200 in 6.0 s. A genuinely
    wedged server now blocks, and the outer progress-supervised session ends it
    — the only layer that can tell a wedge from a slow host."""
    return urllib.request.urlopen(url)


def test_pdkconfig_has_signoff_bridge_fields():
    pdk = p3.PdkConfig(name="x", liberty="l", tech_lef="t", cell_lef="c",
                       cell_gds=None, site="s", drc_deck=None)
    assert pdk.stdcell_marker_layer is None
    assert pdk.bridge_magicrc is None
    assert pdk.bridge_netgen_setup is None
    assert pdk.dummy_fill is None


def _mk_custom_pdk(tmp_path: Path) -> Path:
    pdk = tmp_path / "input" / "pdk"
    (pdk / "lef").mkdir(parents=True)
    (pdk / "lef" / "cells.lef").write_text("SITE unit\nMACRO X\n")
    (pdk / "liberty").mkdir()
    (pdk / "liberty" / "cells.lib").write_text("library(x){}\n")
    (pdk / "gds" / "nested_dir").mkdir(parents=True)
    (pdk / "gds" / "nested_dir" / "cells.gds").write_bytes(b"\x00" * 64)
    bridge = pdk / "bridge"
    (bridge / "magic").mkdir(parents=True)
    (bridge / "magic" / "foo.magicrc").write_text("# rc\n")
    (bridge / "netgen").mkdir()
    (bridge / "netgen" / "foo_setup.tcl").write_text("# setup\n")
    (bridge / "signoff_config.json").write_text(json.dumps({
        "stdcell_exclusion_marker_layer": "65/0",
        "dummy_fill": {"layers": [
            {"name": "MET1", "gds": "9/0", "min_density": 0.30,
             "tile_um": 1.4, "pitch_um": 1.9, "margin_um": 0.65}]},
        "same_net_heal": {"layers": [
            {"name": "MET1", "gds": "9/0", "max_bridge_um": 0.22}]},
    }))
    return tmp_path


def test_discovery_reads_signoff_bridge_config(tmp_path):
    project = _mk_custom_pdk(tmp_path)
    pdk = p3._detect_pdk(project, override=None)
    assert pdk.name.startswith("custom:")
    assert pdk.stdcell_marker_layer == "65/0"
    assert pdk.dummy_fill and pdk.dummy_fill["layers"][0]["gds"] == "9/0"
    assert pdk.bridge_magicrc and pdk.bridge_magicrc.endswith("foo.magicrc")
    assert pdk.bridge_netgen_setup and pdk.bridge_netgen_setup.endswith(
        "foo_setup.tcl")
    assert pdk.same_net_heal and pdk.same_net_heal["layers"][0][
        "max_bridge_um"] == 0.22
    # nested cell GDS still discovered (rglob)
    assert pdk.cell_gds and pdk.cell_gds.endswith("cells.gds")


def test_same_net_heal_script_is_config_gated_morphological_close():
    # The heal MUST be a per-layer morphological CLOSE (grow d then shrink d)
    # bridging gaps <= 2d = max_bridge_um. With max_bridge_um < the layer
    # min-space, this can only merge SAME-NET shapes (different nets are
    # >= min-space) — never shorts two nets nor masks a different-net
    # violation. Regression-pin the close form + the half-gap arithmetic.
    src = p3._GDS_SAME_NET_HEAL_PY
    assert "max_bridge_um" in src
    assert "/ 2.0 / dbu" in src              # d = max_bridge_um / 2
    assert "reg.size(d)" in src              # grow
    assert "reg.size(-d)" in src             # shrink -> CLOSE
    assert "SAME_NET_HEAL_DONE" in src


def test_same_net_heal_noop_without_config(tmp_path):
    pdk = p3.PdkConfig(name="custom:pdk", liberty="l", tech_lef="t",
                       cell_lef="c", cell_gds=None, site="s", drc_deck=None)
    gds = tmp_path / "x.gds"
    gds.write_bytes(b"\x00")
    ok, note = p3._klayout_same_net_heal(tmp_path, "x", pdk, "nonexistent", gds)
    assert not ok and "config" in note


_TECH_LEF = (
    "LAYER MET1\n  TYPE ROUTING ;\n  WIDTH 0.23 ;\n  SPACING 0.23 ;\n"
    "  SPACING 0.6 RANGE 10.001 100000 ;\n  MINWIDTH 0.23 ;\nEND MET1\n"
    "LAYER MET2\n  TYPE ROUTING ;\n  SPACING 0.28 ;\nEND MET2\n")


def test_read_layer_min_space_picks_default_not_range(tmp_path):
    tl = tmp_path / "tech.lef"
    tl.write_text(_TECH_LEF)
    # the DEFAULT SPACING (0.23), never the wide-metal RANGE variant (0.6)
    assert p3._read_layer_min_space_um(str(tl), "MET1") == 0.23
    assert p3._read_layer_min_space_um(str(tl), "MET2") == 0.28
    assert p3._read_layer_min_space_um(str(tl), "MET9") is None


def test_same_net_heal_REFUSES_unsafe_max_bridge(tmp_path, monkeypatch):
    # §4.05 SAFETY-BY-CONSTRUCTION: a max_bridge_um >= the layer min-space would
    # let the close merge DIFFERENT-net shapes (short / mask a violation). The
    # program must REFUSE such a layer, never silently apply it — even though
    # klayout is (pretended) present and the GDS exists.
    tl = tmp_path / "tech.lef"
    tl.write_text(_TECH_LEF)
    gds = tmp_path / "x.gds"
    gds.write_bytes(b"\x00")
    monkeypatch.setattr(p3, "_tool_in_path", lambda c, t: True)
    # a confirmed PDN so we isolate the MIN-SPACE guard (the PDN precondition
    # is exercised separately in test_same_net_heal_refuses_when_pdn_unconfirmed)
    _pnr = p3._pl.pnr_dir(tmp_path)
    _pnr.mkdir(parents=True, exist_ok=True)
    (_pnr / "openroad.log").write_text(
        "[INFO PDN-0001] Inserting grid: grid\n"
        "PDN_INSERTED_ADAPTIVE: MET1 follow-pins net=VDD/VSS width=0.8\n")
    # 0.30 >= MET1 min-space 0.23 -> unsafe -> refused, heal does NOT run
    pdk = p3.PdkConfig(name="custom:pdk", liberty="l", tech_lef=str(tl),
                       cell_lef="c", cell_gds=None, site="s", drc_deck=None,
                       same_net_heal={"layers": [
                           {"name": "MET1", "gds": "9/0",
                            "max_bridge_um": 0.30}]})
    ok, note = p3._klayout_same_net_heal(tmp_path, "x", pdk, "vibeic-eda", gds)
    assert not ok
    assert "min-space" in note and "MET1" in note

    # 0.22 < 0.23 -> safe -> the guard admits it (it then proceeds to the
    # container run, which is where a real klayout would execute).
    p3._pl.pnr_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    pdk.same_net_heal = {"layers": [
        {"name": "MET1", "gds": "9/0", "max_bridge_um": 0.22}]}
    # stub the container exec so no real docker is needed; assert the guard
    # let a SAFE layer through to the exec path.
    calls = {}

    def _fake_exec(container, cmd, marker=None, **_kw):
        calls["cmd"] = cmd
        return 1, "", "no-docker"      # fail the exec -> NONFATAL note
    monkeypatch.setattr(p3, "_docker_exec", _fake_exec)
    ok2, note2 = p3._klayout_same_net_heal(tmp_path, "x", pdk, "vibeic-eda", gds)
    assert "HEAL_SPEC" in calls.get("cmd", ""), "safe layer must reach the exec"
    assert '"max_bridge_um": 0.22' in calls["cmd"]


def test_pnr_pdn_status_reads_marker(tmp_path):
    pnr = p3._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True, exist_ok=True)
    log = pnr / "openroad.log"
    log.write_text("[INFO PDN-0001] grid\nPDN_INSERTED_ADAPTIVE: MET1 fp\n")
    assert p3._pnr_pdn_status(tmp_path) == (True, "PDN_INSERTED_ADAPTIVE")
    log.write_text("PDN_INSERTED: met1 follow-pins + met4/met5 stripes\n")
    assert p3._pnr_pdn_status(tmp_path) == (True, "PDN_INSERTED")
    # NONFATAL wins even if a later attempt printed a success marker (conservative)
    log.write_text("PDN_NONFATAL: pdngen threw\nPDN_INSERTED: retry\n")
    assert p3._pnr_pdn_status(tmp_path)[0] is False
    log.write_text("PDN_SKIPPED: no PDK config\n")
    assert p3._pnr_pdn_status(tmp_path) == (False, "PDN_SKIPPED")
    log.write_text("[INFO] routing complete\n")
    assert p3._pnr_pdn_status(tmp_path) == (False, "no PDN insertion marker")


def test_same_net_heal_refuses_when_pdn_unconfirmed(tmp_path, monkeypatch):
    # BLOCKER 3 (§4.05): the net-unaware close is safe ONLY when the routed
    # geometry is different-net clean, which the router guarantees ONLY when the
    # follow-pin PDN connected the rails. The PDN step is NONFATAL, so if the PnR
    # transcript does not confirm the grid, a real different-net signal-to-rail
    # near-miss may exist; a close would bridge/mask it (false-clean). The heal
    # MUST refuse — even for a per-layer SAFE (max_bridge < min-space) config.
    tl = tmp_path / "tech.lef"
    tl.write_text(_TECH_LEF)
    gds = tmp_path / "x.gds"
    gds.write_bytes(b"\x00")
    monkeypatch.setattr(p3, "_tool_in_path", lambda c, t: True)
    pnr = p3._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True, exist_ok=True)
    pdk = p3.PdkConfig(name="custom:pdk", liberty="l", tech_lef=str(tl),
                       cell_lef="c", cell_gds=None, site="s", drc_deck=None,
                       same_net_heal={"layers": [
                           {"name": "MET1", "gds": "9/0",
                            "max_bridge_um": 0.22}]})
    calls = {}

    def _fake_exec(container, cmd, marker=None, **_kw):
        calls["cmd"] = cmd
        return 1, "", "no-docker"
    monkeypatch.setattr(p3, "_docker_exec", _fake_exec)

    # (a) PDN NONFATAL -> REFUSED; the close never reaches the exec path
    (pnr / "openroad.log").write_text("PDN_NONFATAL: pdngen failed\n")
    ok, note = p3._klayout_same_net_heal(tmp_path, "x", pdk, "vibeic-eda", gds)
    assert not ok and "REFUSED" in note and "PDN_NONFATAL" in note
    assert "cmd" not in calls, "heal must not run when PDN is unconfirmed"

    # (b) no PDN marker at all -> REFUSED
    (pnr / "openroad.log").write_text("[INFO] routing done\n")
    ok, note = p3._klayout_same_net_heal(tmp_path, "x", pdk, "vibeic-eda", gds)
    assert not ok and "REFUSED" in note
    assert "cmd" not in calls

    # (c) PDN confirmed inserted -> the guard admits the safe layer to the exec
    (pnr / "openroad.log").write_text(
        "PDN_INSERTED_ADAPTIVE: MET1 follow-pins net=VDD/VSS width=0.8\n")
    ok, note = p3._klayout_same_net_heal(tmp_path, "x", pdk, "vibeic-eda", gds)
    assert "HEAL_SPEC" in calls.get("cmd", ""), "confirmed PDN must reach exec"


def test_same_net_heal_forces_klayout_streamout_not_magic(tmp_path, monkeypatch):
    # BLOCKER 2: a heal-only PDK bridge config (no stdcell marker, no dummy_fill)
    # must NOT take the Magic streamout early-return — the heal is a KLayout
    # post-streamout process, so a successful Magic stream would silently drop
    # it and the OSS router's same-net near-misses would survive to sign-off DRC.
    pnr = p3._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "top.def").write_text("VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n")
    pdk = p3.PdkConfig(name="custom:pdk", liberty="l", tech_lef="t",
                       cell_lef="c", cell_gds=None, site="s", drc_deck=None,
                       same_net_heal={"layers": [
                           {"name": "MET1", "gds": "9/0",
                            "max_bridge_um": 0.22}]})
    called = {"magic": False, "heal": 0}

    def _no_magic(*a, **k):
        called["magic"] = True
        return True, "magic ran (should NOT happen for heal-only config)"
    monkeypatch.setattr(p3, "_magic_def_to_gds", _no_magic)

    def _fake_exec(container, cmd, marker=None, **_kw):
        (pnr / "top.gds").write_bytes(b"\x00")     # KLayout streamout wrote GDS
        return 0, "", ""
    monkeypatch.setattr(p3, "_docker_exec", _fake_exec)
    monkeypatch.setattr(p3, "_gds_grid_snap", lambda *a, **k: (True, "snap"))
    monkeypatch.setattr(p3, "_klayout_merge_layers", lambda *a, **k: (True, "merge"))

    def _fake_heal(*a, **k):
        called["heal"] += 1
        return True, "healed"
    monkeypatch.setattr(p3, "_klayout_same_net_heal", _fake_heal)

    res = p3.step_gds(tmp_path, "top", pdk, "vibeic-eda")
    assert not called["magic"], (
        "Magic streamout must be skipped when same_net_heal is configured")
    assert res.extras.get("streamout_engine") == "klayout"
    assert called["heal"] == 1, "the same-net heal must run on the KLayout path"


def test_streamout_uses_manual_substitution_not_macro_resolution():
    # v1.3.84 root-cause: KLayout's macro_resolution_mode=2 substitutes the
    # cell-GDS geometry BUT ALSO paints each macro's SIZE box on the first
    # tech-LEF layer (here LAYER NACT / GDS 1/0). 633 abutting cells tiled a
    # SOLID nact plane over the whole die -> __nact__ = the entire core ->
    # every nact-keyed FEOL rule flooded (commercial PDK spm: 19 phantom families,
    # PO.S.1.3 x3706 / implant x3279 / CT.OT.1.1 x2557 ...). No produce_*
    # option or macro_resolution_mode suppresses the box. The fix streams the
    # DEF as LEF abstracts and MANUALLY copies each std cell's real geometry
    # from the cell GDS -> real 28% sparse nact, dropping DRC 19 -> 8 families.
    src = p3._GDS_STREAMOUT_PY
    assert "macro_resolution_mode = 2" not in src, (
        "macro_resolution_mode=2 re-introduces the phantom full-die NACT box")
    assert "manual-substitut" in src
    assert "begin_shapes_rec" in src          # copies real cell geometry
    assert ".shapes(_li).clear()" in src      # clears the abstract first
    assert "STDCELL_MARKER_LAYER" in src


def test_dummy_fill_noop_without_config(tmp_path):
    pdk = p3.PdkConfig(name="custom:pdk", liberty="l", tech_lef="t",
                       cell_lef="c", cell_gds=None, site="s", drc_deck=None)
    gds = tmp_path / "x.gds"
    gds.write_bytes(b"\x00")
    ok, note = p3._klayout_dummy_fill(tmp_path, "x", pdk, "nonexistent", gds)
    assert not ok and "config" in note


def test_step_lvs_falls_through_to_oss_route_when_bridge_present(tmp_path, monkeypatch):
    pdk = p3.PdkConfig(name="custom:pdk", liberty="l", tech_lef="t",
                       cell_lef="c", cell_gds=None, site="s", drc_deck=None,
                       calibre_lvs="/deck/lvs.rule",
                       bridge_magicrc="/bridge/magic/x.magicrc",
                       bridge_netgen_setup="/bridge/netgen/x_setup.tcl")
    # no tool in the (nonexistent) container: calibre absent -> must NOT
    # dead-end on calibre; falls to the OSS route whose own probe then
    # reports the #443 missing-tool wording instead.
    monkeypatch.setattr(p3, "_tool_in_path", lambda c, t: False)
    res = p3.step_lvs(tmp_path, "x", pdk, "nonexistent")
    assert "install Calibre (commercial)" not in res.detail
    assert "#443" in res.detail or res.status != "ENV_UNAVAILABLE"


def test_step_lvs_env_unavailable_without_bridge(tmp_path, monkeypatch):
    pdk = p3.PdkConfig(name="custom:pdk", liberty="l", tech_lef="t",
                       cell_lef="c", cell_gds=None, site="s", drc_deck=None,
                       calibre_lvs="/deck/lvs.rule")
    monkeypatch.setattr(p3, "_tool_in_path", lambda c, t: False)
    res = p3.step_lvs(tmp_path, "x", pdk, "nonexistent")
    assert res.status == "ENV_UNAVAILABLE"
    assert "bridge" in res.detail


def test_dashboard_serve_retries_ports_and_records_url(tmp_path):
    import flow_dashboard_web as fdw
    (tmp_path / "reports").mkdir()
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    port = blocker.getsockname()[1]
    blocker.listen(1)
    t = threading.Thread(
        target=lambda: fdw.serve(str(tmp_path), port=port, host="127.0.0.1"),
        daemon=True)
    t.start()
    import time
    url_f = tmp_path / "reports" / "dashboard_web.url"
    # `for _ in range(50)` was a 5 s wall clock wearing a loop: when it ran out
    # the test said "daemon must record its actually-bound URL", which is a
    # statement about `fdw.serve`, on the evidence that this host was busy. The
    # server runs in a thread of THIS process, so this process's CPU advancing
    # is a true "it is still working" reading; only a completely flat one ends
    # the wait, and the socket timeout below is a LOOK INTERVAL, not a bound.
    guard = _watchdog.loop_guard(
        "signoff-dashboard-bind", max_iter=_MAX_LOOKS,
        stall_iters=_STALL_LOOKS, progress_fn=_server_cpu_s)
    for _ in guard:
        if url_f.is_file() or not t.is_alive():
            break
        time.sleep(_LOOK_S)
    assert url_f.is_file(), (
        "daemon must record its actually-bound URL "
        f"({guard.reason} after {guard.iterations} looks)")
    rec = url_f.read_text().strip()
    bound = int(rec.rsplit(":", 1)[-1])
    assert bound != port, "daemon must have hopped off the busy port"
    assert _fetch(rec).status == 200
    blocker.close()
