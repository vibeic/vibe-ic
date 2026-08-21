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
        # a PDN that attaches zero PG pins is exactly the case that shipped
        # this defect, so it has to be measured and reported, never skipped.
        tcl = mod._build_pg_reconnect_tcl()
        assert "PG_NET_OWNERSHIP_AUDIT" in tcl
        assert "getSigType" in tcl and "getITerms" in tcl

    def test_the_marker_names_the_question_the_predicate_asks(self):
        # THE FIX. The predicate is `[$iterm getNet] eq "NULL"` — a net POINTER
        # test. The marker used to be called PG_CONNECT_AUDIT and its field
        # `unconnected=`, and the PnR step rendered that as "N/N PG terminals
        # connected (0 orphaned)". A pointer is not a conductor: a terminal can
        # be owned by a supply net that carries no metal over the port at all,
        # and this predicate counts it as fine. The name must not assert what
        # the predicate never tested.
        tcl = mod._build_pg_reconnect_tcl()
        assert "no_net=" in tcl
        assert "unconnected=" not in tcl
        assert "PG_CONNECT_AUDIT" not in tcl
        # and the emitter has to SAY so, next to the predicate, so the next
        # reader of this Tcl cannot repeat the misread.
        assert "NET OWNERSHIP" in tcl
        assert "THIS IS NOT A CONDUCTOR TEST" in tcl

    def test_nonfatal_marker_is_renamed_with_it(self):
        # Two spellings of the same audit in one log is how a parser silently
        # reads the wrong one.
        tcl = mod._build_pg_reconnect_tcl()
        assert "PG_NET_OWNERSHIP_AUDIT_NONFATAL" in tcl
        assert "PG_CONNECT_AUDIT_NONFATAL" not in tcl

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
        assert (tcl.index("PG_NET_OWNERSHIP_AUDIT")
                < tcl.index("write_def /out/routed.def"))

    def test_default_is_empty_so_the_arg_is_explicit(self):
        # A caller that forgets to pass the block gets a byte-identical legacy
        # template rather than a half-wired one — the Python gate then reports
        # BLOCKED (unmeasured) rather than a silent pass.
        assert "PG_NET_OWNERSHIP_AUDIT" not in _pnr_tcl()


class TestParsePgNetOwnershipAudit:
    def test_parses_the_audit_line(self):
        assert mod._parse_pg_net_ownership_audit(
            "noise\nPG_NET_OWNERSHIP_AUDIT: total=32246 no_net=20576 "
            "masters=FILL1,DECAP4\ntail") == (32246, 20576, "FILL1,DECAP4")

    def test_parses_a_clean_audit(self):
        assert mod._parse_pg_net_ownership_audit(
            "PG_NET_OWNERSHIP_AUDIT: total=32246 no_net=0 masters=") \
            == (32246, 0, "")

    def test_takes_the_last_audit_when_several(self):
        # An incremental / resumed run can emit more than one; the final state
        # of the design is the one that ships.
        assert mod._parse_pg_net_ownership_audit(
            "PG_NET_OWNERSHIP_AUDIT: total=10 no_net=7 masters=A\n"
            "PG_NET_OWNERSHIP_AUDIT: total=10 no_net=0 masters=") \
            == (10, 0, "")

    def test_absent_audit_is_none_not_zero(self):
        # The whole point: "not measured" must be distinguishable from "clean".
        assert mod._parse_pg_net_ownership_audit("no audit here") is None
        assert mod._parse_pg_net_ownership_audit("") is None

    def test_nonfatal_marker_alone_is_not_an_audit(self):
        assert mod._parse_pg_net_ownership_audit(
            "PG_NET_OWNERSHIP_AUDIT_NONFATAL: bad command") is None
        assert mod._parse_pg_net_ownership_audit(
            "PG_CONNECT_AUDIT_NONFATAL: bad command") is None

    # ── the rename must not brick a resumed run ─────────────────────────────
    # A resume replays the cached openroad.log an OLDER emitter wrote. If the
    # legacy spelling stopped parsing, the gate would return None and report
    # BLOCKED/unmeasured on a run whose evidence is right there in the file.

    def test_legacy_spelling_still_parses(self):
        assert mod._parse_pg_net_ownership_audit(
            "PG_CONNECT_AUDIT: total=32246 unconnected=20576 "
            "masters=FILL1,DECAP4") == (32246, 20576, "FILL1,DECAP4")
        assert mod._parse_pg_net_ownership_audit(
            "PG_CONNECT_AUDIT: total=600 unconnected=0 masters=") \
            == (600, 0, "")

    def test_mixed_spellings_still_take_the_last(self):
        # A resumed run can carry the legacy line from the cached log and the
        # new one from the re-run. Last wins, regardless of spelling.
        assert mod._parse_pg_net_ownership_audit(
            "PG_CONNECT_AUDIT: total=10 unconnected=7 masters=A\n"
            "PG_NET_OWNERSHIP_AUDIT: total=10 no_net=0 masters=") == (10, 0, "")
        assert mod._parse_pg_net_ownership_audit(
            "PG_NET_OWNERSHIP_AUDIT: total=10 no_net=0 masters=\n"
            "PG_CONNECT_AUDIT: total=10 unconnected=3 masters=B") \
            == (10, 3, "B")

    def test_the_old_name_is_gone_from_the_module(self):
        # One name for one measurement. A leftover alias is how the overclaim
        # comes back.
        assert not hasattr(mod, "_parse_pg_connect_audit")


class TestPgOverclaimIsGoneFromTheGate:
    """The literal that actually rendered as "3336 of 3337 connected".

    `_build_pg_reconnect_tcl` emits the number; this is where the runner turned
    it into a sentence. Every published record carries that sentence verbatim,
    which is how a net-pointer count became quotable as supply connectivity.
    """

    # The assertions below must see CODE, not prose: this module's comments
    # quote the old wording on purpose, to record what was wrong. A naive
    # substring search over the source would find those quotes and pass — the
    # test would then be unable to fail for the reason it exists.
    @staticmethod
    def _code_only():
        import inspect
        import io
        import tokenize
        src = inspect.getsource(mod)
        out = []
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                continue
            if tok.type == tokenize.STRING and tok.line.lstrip().startswith(
                    ('"""', "'''", 'r"""')):
                continue          # module/function docstring
            out.append(tok.string)
        return "\n".join(out)

    def test_the_helper_can_actually_fail(self):
        # NEGATIVE CONTROL for the helper itself: pick a phrase that exists
        # ONLY inside a comment. If the stripper were a no-op, `_code_only()`
        # would still contain it and every assertion below would be vacuous.
        import inspect
        assert "(0 orphaned)" in inspect.getsource(mod)   # quoted in a comment
        assert "(0 orphaned)" not in self._code_only()    # gone from the code

    def test_the_helper_keeps_the_code_it_is_asked_about(self):
        # The opposite failure: a stripper that ate everything would also make
        # every "still present" assertion vacuous.
        code = self._code_only()
        assert "_parse_pg_net_ownership_audit" in code
        assert "PG_NET_OWNERSHIP_AUDIT" in code

    def test_pass_path_no_longer_says_connected(self):
        code = self._code_only()
        assert "(0 orphaned)" not in code
        assert "pg_connect:" not in code

    def test_pass_path_states_the_scope_inline(self):
        code = self._code_only()
        assert "pg_net_ownership:" in code
        assert "NOT a conductor test" in code

    def test_finding_names_state_the_question_asked(self):
        code = self._code_only()
        for gone in ("PG_TERMINALS_UNCONNECTED", "PG_CONNECT_UNMEASURED",
                     "PG_CONNECT_ZERO_TERMINALS", "pg_terminals_unconnected"):
            assert gone not in code, gone
        for present in ("PG_TERMINALS_ON_NO_NET", "PG_NET_OWNERSHIP_UNMEASURED",
                        "PG_NET_OWNERSHIP_ZERO_TERMINALS",
                        "pg_terminals_on_no_net"):
            assert present in code, present

    def test_extras_carry_machine_readable_scope(self):
        # A consumer reading only the JSON must not be able to re-derive the
        # overclaim from the numbers.
        code = self._code_only()
        assert "net_ownership_only" in code
        assert "pg_conductor_measured" in code


class TestMacroPdnUnreachableWitness:
    """The one supply-REACH statement the flow already computes.

    `_macro_pdn_grid_plan` decides that a hard-macro supply port narrower than
    the smallest legal strap pitch cannot be crossed by any strap pattern, and
    prints MACRO_PDN_PORT_UNREACHABLE. Through v1.9.62 nothing read that line —
    `git grep` returned exactly one hit, the `puts` that emits it — while the
    same step reported "PG terminals connected".
    """

    def test_parses_the_ports(self):
        assert mod._parse_macro_pdn_unreachable(
            "noise\nMACRO_PDN_PORT_UNREACHABLE: m0/PWR port extent 0.4um "
            "across the strap is below the smallest legal pitch 1.2um\n"
            "MACRO_PDN_PORT_UNREACHABLE: m0/GND port extent 0.4um\n"
        ) == ["m0/PWR", "m0/GND"]

    def test_deduplicates_but_keeps_order(self):
        assert mod._parse_macro_pdn_unreachable(
            "MACRO_PDN_PORT_UNREACHABLE: b/PWR x\n"
            "MACRO_PDN_PORT_UNREACHABLE: a/PWR x\n"
            "MACRO_PDN_PORT_UNREACHABLE: b/PWR x\n") == ["b/PWR", "a/PWR"]

    def test_absent_marker_is_the_empty_list(self):
        # A design with no hard macros never emits it, and that is not a
        # finding — it is the normal state.
        assert mod._parse_macro_pdn_unreachable("") == []
        assert mod._parse_macro_pdn_unreachable("nothing here") == []

    def test_it_is_reported_not_blocking(self):
        # DELIBERATE, and not timidity: the flow cannot widen a macro port or
        # lower a PDK pitch floor, so there is no in-flow repair. A condition
        # with no repair must be reported with its reason, never turned into a
        # FAIL that no rerun can clear.
        import inspect
        src = inspect.getsource(mod)
        assert "REPORTED, NOT BLOCKING" in src
        assert '"macro_pdn_ports_unreachable"' in src
        # it must not have been wired into any verdict-bearing finding
        assert 'finding": "MACRO_PDN_PORT_UNREACHABLE' not in src


class TestPgNumberNamesItsDatabase:
    """A number describes the artifact it was measured on, or it says so.

    The PG audit runs two statements before `write_def routed.def`, so it
    describes the BASE route. `step_signoff_spef_repair` and
    `step_signoff_drv_wire_length_repair` then copy a LATER route over
    routed.def and <top>.def — and the repair Tcl clears and re-inserts the
    decap/fill physical-only cells, which are exactly the population the PG
    audit exists to catch.

    MEASURED on published run spm/v1.5.65_sky130A, which took the promotion
    branch: its transcript records total=2148; its shipped routed.def measures
    2136 PG instance terminals read back with the same LEF pair.
    """

    def test_the_disclosure_exists_and_names_the_mechanism(self):
        note = mod._PG_STALE_AFTER_PROMOTION
        assert note.startswith("PG_NET_OWNERSHIP_STALE_AFTER_PROMOTION:")
        assert "not re-audited" in note

    def test_both_promotion_paths_carry_it(self):
        import inspect
        for fn in (mod.step_signoff_spef_repair,
                   mod.step_signoff_drv_wire_length_repair):
            src = inspect.getsource(fn)
            assert "_PG_STALE_AFTER_PROMOTION" in src, fn.__name__
            assert "pg_net_ownership_stale" in src, fn.__name__
