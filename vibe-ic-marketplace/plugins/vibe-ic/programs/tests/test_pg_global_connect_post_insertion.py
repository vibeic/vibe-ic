"""PG global-connect re-apply + audit gate.

`global_connect` is a ONE-SHOT: OpenROAD walks the instances that exist at the
moment it runs and attaches every PG terminal matching a registered
`add_global_connection` rule. The Phase-3 flow called it exactly once, inside
the PDN block, which runs BEFORE global placement. Every instance created
after that point kept BOTH PG terminals on no net:

  * buffer_ports / repair_design / repair_timing buffers
  * clock_tree_synthesis clock buffers
  * Design-for-ECO spare cells
  * repair_antennas diodes
  * the decap/fill physical-only cells, inserted dead last (after
    detailed_route)

Those cells still occupy sites and still draw their own supply-rail metal into
the layout. With no owning net the router has no reason to keep signal wires
min-space clear of that metal, so the streamed layout carries metal-1 spacing
violations that neither the router's own DRC (0 violations) nor the cell
library's DRC (0 violations) can see.

MEASURED on two designs / two PDKs, so the defect is the flow's ordering and
not any one PDK:

  * commercial 180nm, 16123 instances: 5835 PG-connected (exactly the
    floorplan.def instance count), 10288 instances / 20576 PG terminals on no
    net, 9602 of them decap/fill. Foundry deck: 1118 metal-1 spacing
    violations, 72% signal-to-supply.
  * open IHP sg13g2, 1813 instances: 352 PG-connected, 1461 instances / 2922
    PG terminals on no net, 1359 of them decap/fill.

These tests pin BOTH halves of the repair:
  (1) the emitted Tcl re-applies global_connect after the LAST
      instance-creating step and re-routes, and audits unconditionally;
  (2) the Python gate turns the audit into a verdict — and in particular
      never reports a design whose supply connectivity was not measured, or
      whose PG terminals are orphaned, as a pass.
"""
import importlib

mod = importlib.import_module("phase3_one_shot_runner")


def _pnr_tcl(**over):
    """Render the full pnr.tcl template with every block empty except the ones
    under test, so an ordering assertion cannot be satisfied by unrelated Tcl."""
    kw = dict(
        tech_lef_c="/x/tech.lef", cell_lef_c="/x/cell.lef",
        macro_lefs_tcl="", liberty_c="/x/c.lib", macro_libs_tcl="",
        netlist_c="/x/d.v", top="d", sdc_c="/x/d.sdc", dont_use_block="",
        metal_prefix="met", die_w=100, die_h=100, core_pad=10,
        core_w=90, core_h=90, site="unit", out_dir_c="/out",
        tapcell_block="", pdn_block="", util=0.3,
        spare_protection_tcl="", spare_postfix_tcl="",
        clk_buf="BUF", clk_buf_root="BUF", routing_constraint_tcl="",
        pg_cleanup_block="", spef_repair_block="",
        antenna_repair_block="", filler_block="")
    kw.update(over)
    return mod._build_pnr_tcl_text(**kw)


class TestPgReconnectTcl:
    def test_reapplies_global_connect(self):
        tcl = mod._build_pg_reconnect_tcl()
        assert "global_connect" in tcl

    def test_reroutes_after_reconnect(self):
        # Re-connecting alone only makes the DEF honest: the signal wires were
        # already laid against metal the router ignored, so they must be
        # re-routed now that the physical-only cells' rails are net-owned.
        tcl = mod._build_pg_reconnect_tcl()
        assert tcl.index("{global_connect}") < tcl.index("detailed_route")

    def test_reroute_is_optional(self):
        assert "detailed_route" not in mod._build_pg_reconnect_tcl(reroute=False)

    def test_audit_is_emitted_unconditionally(self):
        # The audit must NOT be inside the success branch of the re-connect:
        # a PDN that connects zero PG pins is exactly the case that shipped
        # this defect, so it has to be measured and reported, never skipped.
        tcl = mod._build_pg_reconnect_tcl()
        assert "PG_CONNECT_AUDIT" in tcl
        assert "getSigType" in tcl and "getITerms" in tcl

    def test_audit_counts_power_and_ground(self):
        tcl = mod._build_pg_reconnect_tcl()
        assert '"POWER"' in tcl and '"GROUND"' in tcl

    def test_lifts_and_restores_do_not_touch_around_the_connect(self):
        # OpenROAD's global_connect SKIPS a do-not-touch instance, so the
        # Design-for-ECO spare cells -- set_dont_touch the moment they are
        # placed -- kept floating supply pins even under a re-applied
        # global_connect. MEASURED on the commercial 180nm design: re-applying
        # global_connect alone took 20576 orphaned PG terminals to 234, and
        # those 234 were exactly the 117 spares x 2 pins. do-not-touch means
        # "do not resize or remove"; it must never mean "leave the power pin
        # unconnected".
        tcl = mod._build_pg_reconnect_tcl()
        lift = tcl.index("setDoNotTouch false")
        conn = tcl.index("{global_connect}")   # the invocation, not the prose
        restore = tcl.index("setDoNotTouch true")
        assert lift < conn < restore, "lift/connect/restore must be in order"

    def test_do_not_touch_is_restored_before_the_reroute(self):
        # The router must not be free to resize or drop a spare the flow has
        # promised downstream ECO it preserved.
        tcl = mod._build_pg_reconnect_tcl()
        assert tcl.index("setDoNotTouch true") < tcl.index("detailed_route")

    def test_reports_how_many_were_lifted(self):
        tcl = mod._build_pg_reconnect_tcl()
        assert "PG_DONTTOUCH_LIFTED" in tcl
        assert "PG_DONTTOUCH_RESTORED" in tcl

    def test_every_step_is_nonfatal_guarded(self):
        # A re-connect/re-route failure must not abort a run that has already
        # produced routing; the GATE is the audit, not an OpenROAD exception.
        tcl = mod._build_pg_reconnect_tcl()
        assert tcl.count("catch") >= 3

    def test_carries_no_pdk_or_design_literal(self):
        # Chip- and PDK-AGNOSTIC: the net names come from the rules the PDN
        # step already registered on the block, so none appear here.
        tcl = mod._build_pg_reconnect_tcl()
        for literal in ("sky130", "gf180", "sg13g2", "VPWR", "VGND",
                        "VPB", "VNB", "VDD", "VSS", "FILL", "DECAP"):
            assert literal not in tcl, literal


class TestPgReconnectWiredIntoPnrTcl:
    """The block is worthless unless it lands AFTER filler insertion and
    BEFORE the DEF is written."""

    def _tcl(self):
        return _pnr_tcl(filler_block="FILLER_MARKER\n",
                        pg_reconnect_block=mod._build_pg_reconnect_tcl())

    def test_runs_after_filler_insertion(self):
        tcl = self._tcl()
        assert tcl.index("FILLER_MARKER") < tcl.index("PG_RECONNECT_DONE")

    def test_runs_before_the_def_is_written(self):
        tcl = self._tcl()
        assert tcl.index("PG_CONNECT_AUDIT") < tcl.index("write_def /out/routed.def")

    def test_default_is_empty_so_the_arg_is_explicit(self):
        # A caller that forgets to pass the block gets a byte-identical legacy
        # template rather than a half-wired one — the Python gate then reports
        # BLOCKED (unmeasured) rather than a silent pass.
        assert "PG_CONNECT_AUDIT" not in _pnr_tcl()


class TestParsePgConnectAudit:
    def test_parses_the_audit_line(self):
        assert mod._parse_pg_connect_audit(
            "noise\nPG_CONNECT_AUDIT: total=32246 unconnected=20576 "
            "masters=FILL1,DECAP4\ntail") == (32246, 20576, "FILL1,DECAP4")

    def test_parses_a_clean_audit(self):
        assert mod._parse_pg_connect_audit(
            "PG_CONNECT_AUDIT: total=32246 unconnected=0 masters=") \
            == (32246, 0, "")

    def test_takes_the_last_audit_when_several(self):
        # An incremental / resumed run can emit more than one; the final state
        # of the design is the one that ships.
        assert mod._parse_pg_connect_audit(
            "PG_CONNECT_AUDIT: total=10 unconnected=7 masters=A\n"
            "PG_CONNECT_AUDIT: total=10 unconnected=0 masters=") \
            == (10, 0, "")

    def test_absent_audit_is_none_not_zero(self):
        # The whole point: "not measured" must be distinguishable from "clean".
        assert mod._parse_pg_connect_audit("no audit here") is None
        assert mod._parse_pg_connect_audit("") is None

    def test_nonfatal_marker_alone_is_not_an_audit(self):
        assert mod._parse_pg_connect_audit(
            "PG_CONNECT_AUDIT_NONFATAL: bad command") is None
