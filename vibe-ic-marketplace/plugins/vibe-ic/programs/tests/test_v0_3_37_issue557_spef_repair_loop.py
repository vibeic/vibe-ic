"""ORGANIC #557 / #581 — post-route SPEF EXTRACTION (measure-only) +
SPEF-true Step-23.

Pre-fix (#557): after detailed_route there was no SPEF STA → WNS -15.87
at sign-off while in-flow estimate said -1.09.

#581 round-3 evolution: the post-route block was originally a REPAIR loop
(extract → repair_timing → reroute), but every RSZ repair-move
(repair_design r2, then repair_timing -setup r3) SEGFAULTS (Signal 11) on
a post-detailed-route SPEF-annotated design, killing the whole openroad
process so GDS was never written. The block is now MEASURE-ONLY: OpenRCX
extract → write_spef → SPEF_MEASURE_COMPLETE, with NO repair_timing /
repair_design / reroute. The SPEF feeds #527's SPEF-true Step-23 STA;
residual post-route timing goes via the pre-route #561 ECO path.
"""
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402
import sdc_constraints as sdc  # noqa: E402


# ── (b) _post_route_spef_repair_tcl — TCL content checks ────────────────────

def test_spef_repair_tcl_contains_measure_complete_marker(tmp_path):
    """#581 r3 — the success marker is SPEF_MEASURE_COMPLETE (extract-only)."""
    tcl = R._post_route_spef_repair_tcl("/out", "/tech.lef")
    (tmp_path / "spef_repair.tcl").write_text(tcl)
    result = subprocess.run(
        ["python3", "-c",
         f"txt=open(r'{tmp_path}/spef_repair.tcl').read();"
         "assert 'SPEF_MEASURE_COMPLETE' in txt,'marker missing'"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0


def test_spef_repair_tcl_contains_extract_parasitics(tmp_path):
    tcl = R._post_route_spef_repair_tcl("/out", "/tech.lef")
    (tmp_path / "spef_repair.tcl").write_text(tcl)
    result = subprocess.run(
        ["python3", "-c",
         f"txt=open(r'{tmp_path}/spef_repair.tcl').read();"
         "assert 'extract_parasitics' in txt,'extract missing'"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0


def test_spef_repair_tcl_is_measure_only_no_repair(tmp_path):
    """#581 r3 / #147 — with the DEFAULT (fork_repair_capable=False, i.e. stock
    or pre-rebake OpenROAD) the post-route block calls NO repair_timing /
    repair_design and does NO reroute: the STOCK RSZ repair-move family
    segfaults on a post-detailed-route SPEF-annotated design (catch cannot
    contain a segfault → openroad dies → GDS never written). Timing repair is
    pre-route only. This is the probe-negative fallback — byte-for-byte the
    same BEHAVIOUR as before #147."""
    tcl = R._post_route_spef_repair_tcl("/out", "/tech.lef")
    # COMMAND lines only — the doctrine comment names the banned commands.
    cmds = "\n".join(ln for ln in tcl.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "repair_timing" not in cmds
    assert "repair_design" not in cmds
    # no reroute either (the segfault is in the repair that PRECEDED it,
    # but reroute on the already-converged route is also pointless here)
    assert "detailed_route" not in cmds
    assert "global_route" not in cmds


# ── #147 — fork real-SPEF setup-repair ESTIMATE (probe-gated, END-of-flow) ────
def test_postroute_repair_estimate_block_recipe():
    """#147 — the fork-capable ESTIMATE block runs the real setup repair:
    read_spef → `estimate_parasitics -detailed_routing` (flag lives HERE) →
    `repair_design` → `repair_timing -setup` (NO flag), each NONFATAL-guarded,
    worst-slack before/after, to a SEPARATE sta_spef_repaired.rpt."""
    tcl = R._postroute_repair_estimate_tcl("/the_out", fork_repair_capable=True)
    cmds = "\n".join(ln for ln in tcl.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "read_spef /the_out/post_route_repair.spef" in cmds
    assert "estimate_parasitics -detailed_routing" in cmds
    assert "repair_design" in cmds
    assert "repair_timing -setup" in cmds
    assert "SPEF_REPAIR_APPLIED_ON_ESTIMATE" in cmds
    # improved slack goes to a SEPARATE report, NEVER the authoritative sta.rpt.
    assert "sta_spef_repaired.rpt" in cmds
    # the flag is on estimate_parasitics, NOT repair_timing — a `repair_timing
    # -setup -detailed_routing` throws STA-0562 and the NONFATAL catch would
    # silently swallow it (no repair). Guard that regression:
    assert "repair_timing -setup -detailed_routing" not in cmds
    assert "catch {estimate_parasitics -detailed_routing}" in cmds
    # do NOT insert global_route -start_incremental (EST-0104).
    assert "global_route -start_incremental" not in cmds


def test_postroute_repair_estimate_empty_on_stock():
    # stock upstream OpenROAD (probe False) → NO block at all, so it can never
    # reach a repair command it would segfault on.
    assert R._postroute_repair_estimate_tcl("/o", fork_repair_capable=False) == ""


def test_spef_extract_block_is_measure_only_never_modifies_design():
    # The extraction block (runs BEFORE write_def) must NEVER carry a repair
    # move — that would ship unrouted ECO cells into the DEF/GDS/netlist.
    cmds = "\n".join(ln for ln in R._post_route_spef_repair_tcl(
        "/out", "/tech.lef").splitlines() if not ln.lstrip().startswith("#"))
    assert "SPEF_MEASURE_COMPLETE" in cmds
    for banned in ("repair_timing", "repair_design", "estimate_parasitics "
                   "-detailed_routing", "detailed_route", "global_route"):
        assert banned not in cmds


def test_pnr_tcl_repair_estimate_runs_after_shipped_artifacts():
    # ORDER GUARANTEE: the estimate block appears AFTER routed.def / <top>.def /
    # <top>_pnr.v / sta.rpt are written, so it can only measure — never corrupt
    # the shipped design.
    kw = dict(
        tech_lef_c="/t.lef", cell_lef_c="/c.lef", macro_lefs_tcl="",
        liberty_c="/l.lib", macro_libs_tcl="", netlist_c="/n.v", top="foo",
        sdc_c="/s.sdc", dont_use_block="", metal_prefix="met",
        die_w=100, die_h=100, core_pad=10, core_w=80, core_h=80, site="unit",
        out_dir_c="/out", tapcell_block="", pdn_block="", util=0.45,
        spare_protection_tcl="", spare_postfix_tcl="", clk_buf="", clk_buf_root="",
        routing_constraint_tcl="", pg_cleanup_block="",
        spef_repair_block="# extract\n", antenna_repair_block="", filler_block="",
        spef_repair_estimate_block="SPEF_REPAIR_ESTIMATE_MARKER\n")
    tcl = R._build_pnr_tcl_text(**kw)
    assert "SPEF_REPAIR_ESTIMATE_MARKER" in tcl
    assert (tcl.index("write_def /out/routed.def")
            < tcl.index("write_verilog /out/foo_pnr.v")
            < tcl.index("report_checks > /out/sta.rpt")
            < tcl.index("SPEF_REPAIR_ESTIMATE_MARKER")
            < tcl.index("\nexit"))


def test_openroad_postroute_repair_probe(monkeypatch):
    """The #147 capability probe: env opt-in OR a DIFFERENTIAL flag probe →
    capable; stock / error → fail-safe False. Cached per container.

    v1.4.x CONTRACT CHANGE (deliberate — this test previously pinned a wording
    gate). The probe used to SCRAPE `help estimate_parasitics` for the
    `-detailed_routing` token, so a help-TEXT reformat silently disabled our own
    fork's post-route SPEF repair. It now TRIES the flag and compares the result
    against a deliberately-invalid CONTROL flag in the same session: if the tool
    treats them the same the flag is unknown; if differently, the arg parser
    accepted it. The control calibrates the probe at run time, so no phrasing of
    either rejection is consulted. The flag is on estimate_parasitics, NOT
    repair_timing/repair_design (probing those can never discriminate)."""
    R._POSTROUTE_REPAIR_CAP_CACHE.clear()

    # (a) explicit env opt-in → capable.
    def _env_on(container, cmd, timeout=1800):
        if "VIBEIC_OPENROAD_POSTROUTE_SPEF_REPAIR" in cmd:
            return 0, "1", ""
        return 0, "", ""
    monkeypatch.setattr(R, "_docker_exec_raw", _env_on)
    assert R._openroad_supports_postroute_spef_repair("c-env") is True

    # (b) no env, but the fork flag is advertised on estimate_parasitics help.
    R._POSTROUTE_REPAIR_CAP_CACHE.clear()

    def _fork_probe(container, cmd, timeout=1800):
        if "VIBEIC_OPENROAD_POSTROUTE_SPEF_REPAIR" in cmd:
            return 0, "", ""
        # exactly what the fork build prints (captured live): the real flag gets
        # PAST arg parsing and fails later; the bogus control is rejected AT it.
        return 0, ("VIBEIC_PROBE_REAL: Error: no network has been linked.\n"
                   "VIBEIC_PROBE_CTRL: STA-0562\n"), ""
    monkeypatch.setattr(R, "_docker_exec_raw", _fork_probe)
    assert R._openroad_supports_postroute_spef_repair("c-fork") is True

    # (b2) the SAME conclusion under totally different phrasings — the property
    # a help-text scrape could never satisfy.
    R._POSTROUTE_REPAIR_CAP_CACHE.clear()

    def _fork_reworded(container, cmd, timeout=1800):
        if "VIBEIC_OPENROAD_POSTROUTE_SPEF_REPAIR" in cmd:
            return 0, "", ""
        return 0, ("VIBEIC_PROBE_REAL: no design loaded; nothing to estimate\n"
                   "VIBEIC_PROBE_CTRL: ERR-9999 unrecognised option\n"), ""
    monkeypatch.setattr(R, "_docker_exec_raw", _fork_reworded)
    assert R._openroad_supports_postroute_spef_repair("c-fork2") is True

    # (c) stock help (no -detailed_routing) → fail-safe False (guarded skip).
    R._POSTROUTE_REPAIR_CAP_CACHE.clear()

    def _stock_probe(container, cmd, timeout=1800):
        if "VIBEIC_OPENROAD_POSTROUTE_SPEF_REPAIR" in cmd:
            return 0, "", ""
        # stock: the real flag is rejected EXACTLY like the bogus control
        # (captured live by probing a flag that genuinely does not exist).
        return 0, ("VIBEIC_PROBE_REAL: STA-0562\n"
                   "VIBEIC_PROBE_CTRL: STA-0562\n"), ""
    monkeypatch.setattr(R, "_docker_exec_raw", _stock_probe)
    assert R._openroad_supports_postroute_spef_repair("c-stock") is False

    # (c2) a probe that produced no markers at all → fail-safe False.
    R._POSTROUTE_REPAIR_CAP_CACHE.clear()

    def _garbled(container, cmd, timeout=1800):
        if "VIBEIC_OPENROAD_POSTROUTE_SPEF_REPAIR" in cmd:
            return 0, "", ""
        return 0, "openroad: command not found\n", ""
    monkeypatch.setattr(R, "_docker_exec_raw", _garbled)
    assert R._openroad_supports_postroute_spef_repair("c-garbled") is False

    # (d) docker/openroad error → fail-safe False (never speculatively enables).
    R._POSTROUTE_REPAIR_CAP_CACHE.clear()

    def _boom(container, cmd, timeout=1800):
        raise OSError("docker unreachable")
    monkeypatch.setattr(R, "_docker_exec_raw", _boom)
    assert R._openroad_supports_postroute_spef_repair("c-err") is False


def test_spef_repair_tcl_contains_skip_path(tmp_path):
    """No captable → SPEF_REPAIR_SKIP emitted (not a hard failure)."""
    tcl = R._post_route_spef_repair_tcl("/out", "/tech.lef")
    (tmp_path / "spef_repair.tcl").write_text(tcl)
    result = subprocess.run(
        ["python3", "-c",
         f"txt=open(r'{tmp_path}/spef_repair.tcl').read();"
         "assert 'SPEF_REPAIR_SKIP' in txt,'skip marker missing'"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0


def test_spef_repair_tcl_write_spef_to_outdir(tmp_path):
    tcl = R._post_route_spef_repair_tcl("/the_out", "/tech.lef")
    (tmp_path / "spef_repair.tcl").write_text(tcl)
    result = subprocess.run(
        ["python3", "-c",
         f"txt=open(r'{tmp_path}/spef_repair.tcl').read();"
         "assert '/the_out/post_route_repair.spef' in txt,'spef path missing'"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0


# ── (c) Step-23 SPEF-based verdict ───────────────────────────────────────────

def test_spef_sta_prerequisites_missing_returns_false_with_notes(tmp_path):
    """_emit_spef_sta returns False and appends a note when prerequisites
    (SPEF, pnr netlist, SDC) are absent — Step-23 falls back to estimate."""
    notes = []
    ok = R._emit_spef_sta(
        project=tmp_path,
        top="chip_top",
        pdk=None,          # not reached — prereq check exits early
        container="",
        spef_path=tmp_path / "missing.spef",
        rpt_out=tmp_path / "sta_spef.rpt",
        notes=notes,
    )
    assert ok is False
    assert any("SPEF-based STA prerequisites missing" in n for n in notes)


def test_spef_repair_tcl_captable_discovery_uses_libs_ref_anchor(tmp_path):
    """Captable discovery must use the /libs.ref/ anchor from the tech-LEF
    path (chip-AGNOSTIC: no PDK-name literal in the Python code)."""
    tcl = R._post_route_spef_repair_tcl("/out", "/pdk/libs.ref/sky130A/tech.lef")
    assert "/libs.ref/" in tcl
    assert "rules.openrcx" in tcl
