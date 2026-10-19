#!/usr/bin/env python3
"""formal_structural_check — the structural answers, through its OWN entry points.

Step 5 reaches this program through `formal_property_run`; these arms drive it
directly (`check()` and the CLI `main()`), both ways, on generic RTL:

  sync reset, posedge                 -> clock_edge / reset_port / reset_sync PASS
  async reset declared "synchronous"  -> reset_sync REFUTED
  negedge flop declared posedge       -> clock_edge REFUTED
  a reset port that reaches no flop   -> reset_port not PASS

Needs yosys on PATH (the vibeic-eda image, as CI and falsref run it); without
it the arms are NOT_VERIFIED by name, and VIBEIC_REQUIRE_EDA_VERIFICATION=1
turns that back into a failure. chip-AGNOSTIC.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import formal_structural_check as fsc  # noqa: E402
from not_verified_tier import skip_not_verified  # noqa: E402

SYNC = """module m(input clk, input rst, input [3:0] d, output reg [3:0] q);
  always @(posedge clk) if (rst) q <= 4'd0; else q <= d;
endmodule
"""
ASYNC = """module m(input clk, input rst, input [3:0] d, output reg [3:0] q);
  always @(posedge clk or posedge rst) if (rst) q <= 4'd0; else q <= d;
endmodule
"""
NEG = SYNC.replace("posedge clk", "negedge clk")
DEAD_RST = """module m(input clk, input rst, input [3:0] d, output reg [3:0] q);
  always @(posedge clk) q <= d;
endmodule
"""
CLAIMS = [{"rule": "clock_edge", "signal": "clk", "value": "posedge"},
          {"rule": "reset_port", "signal": "rst", "value": ""},
          {"rule": "reset_sync", "signal": "rst", "value": "synchronous"}]


def _yosys():
    if shutil.which("yosys") is None:
        skip_not_verified(
            "yosys not on PATH, so no structural claim can be checked here",
            "tools/ci/run_suite_in_eda_image.sh -- programs/tests/test_formal_structural_check.py")


def _check(tmp: Path, rtl: str) -> dict:
    _yosys()
    f = tmp / "m.v"
    f.write_text(rtl)
    rec = fsc.check([f], "m", CLAIMS, tmp)
    return {c["rule"]: c["verdict"] for c in rec["claims"]} | {"_": rec["verdict"]}


def test_a_sync_posedge_design_passes_every_structural_claim(tmp_path):
    v = _check(tmp_path, SYNC)
    assert v == {"clock_edge": fsc.PASS, "reset_port": fsc.PASS,
                 "reset_sync": fsc.PASS, "_": fsc.PASS}, v


def test_an_async_reset_refutes_synchronous(tmp_path):
    v = _check(tmp_path, ASYNC)
    assert v["reset_sync"] == fsc.REFUTED and v["_"] == fsc.REFUTED, v


def test_a_negedge_flop_refutes_posedge(tmp_path):
    v = _check(tmp_path, NEG)
    assert v["clock_edge"] == fsc.REFUTED, v


def test_a_reset_that_reaches_no_flop_is_not_a_reset_port(tmp_path):
    v = _check(tmp_path, DEAD_RST)
    assert v["reset_port"] != fsc.PASS and v["_"] != fsc.PASS, v


def test_the_cli_both_ways(tmp_path, capsys):
    _yosys()
    for rtl, rc in ((SYNC, 0), (ASYNC, 1)):
        d = tmp_path / str(rc)
        d.mkdir()
        (d / "m.v").write_text(rtl)
        out = d / "rec.json"
        got = fsc.main(["--rtl", str(d / "m.v"), "--top", "m",
                        "--claim", "reset_sync:rst:synchronous",
                        "--work-dir", str(d), "--json", str(out)])
        capsys.readouterr()
        assert got == rc
        assert json.loads(out.read_text())["verdict"] == (fsc.PASS if rc == 0 else fsc.REFUTED)


def test_timeout_retains_completed_query_progress_and_marks_truncation_unknown(tmp_path, monkeypatch):
    """Software control: a timeout transcript is evidence, never a complete mapping."""
    transcript = (b"VIBEIC_TRANSITION_QUERY domain\n"
                  b"SAT solving finished - model found:\n"
                  b"VIBEIC_TRANSITION_COMPLETE domain\n"
                  b"VIBEIC_TRANSITION_QUERY 0_zero1\n"
                  b"SAT proof finished - no model found: SUCCESS!\n"
                  b"VIBEIC_TRANSITION_COMPLETE 0_zero1\n"
                  b"VIBEIC_TRANSITION_QUERY 0_one1\npartial body\n")

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(["yosys"], 120, output=transcript, stderr=b"timed out\n")

    monkeypatch.setattr(fsc._pr, "run", timeout)
    rc, stdout, stderr, native = fsc._native_query_run(["yosys"])
    info, _ = fsc._cofactor_payload_support(
        {"modules": {"transition_pair": {"ports": {}}}}, [], tmp_path / "cofactor")
    progress = fsc._transition_query_progress(stdout + stderr,
                                              ["domain", "0_zero1", "0_one1", "0_high"])
    assert rc == 124 and native["termination"] == "TIMEOUT", native
    assert "0_zero1" in stdout and stderr == "timed out\n"
    assert info["native_run"]["termination"] == "TIMEOUT", info
    assert (tmp_path / "cofactor" / "cofactor_support.stdout").read_bytes().startswith(
        b"VIBEIC_TRANSITION_QUERY domain")
    assert (tmp_path / "cofactor" / "cofactor_support.stderr").read_bytes() == b"timed out\n"
    assert progress["completed"] == 2 and progress["started"] == 3, progress
    assert progress["by_identity"]["0_zero1"] == {"status": "COMPLETED", "result": "PROVED"}
    assert progress["by_identity"]["0_one1"]["status"] == "UNKNOWN", progress
    assert progress["by_identity"]["0_high"]["status"] == "NOT_STARTED", progress


def test_missing_native_tool_is_not_reported_as_timeout(monkeypatch):
    def missing(*_args, **_kwargs):
        raise FileNotFoundError("yosys")

    monkeypatch.setattr(fsc._pr, "run", missing)
    rc, stdout, stderr, native = fsc._native_query_run(["yosys"])
    assert (rc, stdout, stderr) == (127, "", "")
    assert native["termination"] == "TOOL_UNAVAILABLE" and "yosys" in native["error"]


# Paired next-state controls use free, shared current Q/data in native Yosys.
import pytest  # noqa: E402

_CONTROL_CASES = {
    "direct": ("if(rst) q<=0; else q<=d;", fsc.PASS, "RESET_FORCE", True),
    "inverted": ("if(!rst) q<=0; else q<=d;", fsc.REFUTED, "RESET_FORCE", True),
    "boolean-d": ("q<=d & {W{!rst}};", fsc.PASS, "RESET_FORCE", True),
    "enable-only": ("if(rst) q<=d;", fsc.NOT_DISCHARGED, "RETENTION_CONTROL", None),
    "reset-first": ("if(rst) q<=0; else if(en) q<=d;", fsc.PASS, "RESET_FORCE", True),
    "enable-first": ("if(en) begin if(rst) q<=0; else q<=d; end", fsc.PASS, "RESET_FORCE", False),
    "local-or": ("if(rst|clear) q<=0; else q<=d;", fsc.PASS, "RESET_FORCE", True),
    "local-and": ("if(rst&clear) q<=0; else q<=d;", fsc.PASS, "RESET_FORCE", False),
    "local-only": ("if(clear) q<=0; else q<=d;", fsc.NOT_DISCHARGED, "LOCAL_CLEAR", None),
    "ordinary-data": ("q<={W{rst}};", fsc.NOT_DISCHARGED, "DATA_VALUE", None),
    "literal-x": ("if(rst) q<={W{1'bx}}; else q<=d;", fsc.NOT_DISCHARGED, "UNSUPPORTED", None),
    "mixed-unclosed": ("begin if(rst) q[0]<=0; else q[0]<=d[0]; q[1]<=rst ? d[1]^clear : d[1]; end",
                       fsc.NOT_DISCHARGED, "UNRESOLVED_DATA_DEPENDENCE", None),
}


def _control_rtl(body, width=2, edge="posedge clk"):
    return ("module m #(parameter W=" + str(width) + ")"
        "(input clk,rst,en,clear,input [W-1:0] d,output reg [W-1:0] q);\n"
        "always @(" + edge + ") " + body + "\nendmodule\n")


@pytest.mark.parametrize("case", _CONTROL_CASES)
def test_complete_reset_mapping_normal_cli_preserves_force_priority_and_unknowns(tmp_path, case):
    _yosys()
    body, expected, role, total = _CONTROL_CASES[case]
    rtl = tmp_path/"m.v"
    rtl.write_text(_control_rtl(body))
    out = tmp_path/"mapping.json"
    rc = fsc.main(["--rtl",str(rtl),"--top","m","--claim",
        "reset_polarity:rst:active_high","--work-dir",str(tmp_path),"--json",str(out)])
    rec = json.loads(out.read_text())
    assert rec["verdict"] == expected and rc == (0 if expected == fsc.PASS else 1), rec
    mapping = rec["claims"][0].get("reset_control_mapping") or {}
    assert mapping.get("shared_current_q_and_data") is True, rec
    assert mapping.get("paired_domain_reachable") is True, rec
    progress = mapping["query_progress"]
    assert progress["planned"] == mapping["query_count"] + 1, mapping
    assert progress["completed"] == progress["planned"] and not progress["unknown"], mapping
    assert mapping["native_run"]["termination"] == "COMPLETED", mapping
    assert len(mapping.get("raw_identities") or []) == 2, mapping
    assert all(len(r["current_q"]) == 1 for r in mapping["raw_identities"]), mapping
    assert role in {r["classification"] for r in mapping["rows"]}, mapping
    if total is not None:
        forced = [r for r in mapping["rows"] if r["classification"] == "RESET_FORCE"]
        assert forced and all(r["total_force"] is total for r in forced), mapping
        if case == "enable-first":
            # No assumption holds enable active: the blocked reset domain is
            # reachable, and the actual native total-force query is refuted.
            assert all(r["native_queries"]["zero1"] == "REFUTED" for r in forced), mapping
        if case == "reset-first":
            assert all(r["native_queries"]["zero1"] == "PROVED" for r in forced), mapping
    if case in {"literal-x", "mixed-unclosed"}:
        assert mapping["unresolved"] and not mapping["complete"], mapping
    if case == "mixed-unclosed":
        residual = next(r for r in mapping["rows"] if r["classification"] == "UNRESOLVED_DATA_DEPENDENCE")
        relation = residual["native_relation"]
        assert relation["name"] == "DEFINED_NONFORCING_RESET_DEPENDENCE", relation
        assert relation["proof_basis"] == "native_paired_cofactor_queries", relation
        for arm, detail in enumerate(relation["arms"]):
            assert detail["reset_value"] == arm and detail["definedness"] == "NO_UNDEF", detail
            assert detail["roles"] == [r for r in residual["conditional_roles"] if r["reset_value"] == arm], detail
            assert all(residual["native_queries"][f"{role}_reachable{arm}"] == "PROVED"
                       for role in ("force_zero", "force_one")), residual
            assert all(residual["native_queries"][f"{proof}{arm}"] == "PROVED"
                       for proof in ("roles_disjoint", "roles_cover")), residual


@pytest.mark.parametrize("case", ["high-zero", "high-one", "low-zero", "free-enable",
    "partial-force", "other-clock", "other-edge", "residual-data"])
def test_post_reset_native_independence_requires_total_same_edge_premises(tmp_path, case):
    _yosys()
    low = case == "low-zero"
    value = int(case == "high-one")
    reset = "!rst" if low else "rst"
    if case == "partial-force":
        reset += " & clear"
    enable = "!gate" if value else "gate"
    if case == "free-enable":
        enable = "en"
    elif case == "residual-data":
        enable += " | en"
    target_edge = "posedge other_clk" if case == "other-clock" else "negedge clk" if case == "other-edge" else "posedge clk"
    rtl = tmp_path / "m.v"
    rtl.write_text("module m(input clk,other_clk,rst,en,clear,input [1:0] d,output reg gate,q);\n"
        f"always @(posedge clk) if ({reset}) gate <= 1'b{value}; else gate <= en;\n"
        f"always @({target_edge}) if ({enable}) q <= rst ? d[1] : d[0];\nendmodule\n")
    out = tmp_path / "mapping.json"
    claim = "active_low" if low else "active_high"
    rc = fsc.main(["--rtl", str(rtl), "--top", "m", "--claim", f"reset_polarity:rst:{claim}",
                   "--work-dir", str(tmp_path), "--json", str(out)])
    rec = json.loads(out.read_text())
    positive = case in {"high-zero", "high-one", "low-zero"}
    # A composed reset-prefix certificate does not close the unrestricted
    # structural polarity obligation, even on the positive evidence arms.
    assert rec["verdict"] == fsc.NOT_DISCHARGED and rc == 1, rec
    mapping = rec["claims"][0]["reset_control_mapping"]
    assert len(mapping["raw_identities"]) == 2, mapping
    progress = mapping["query_progress"]
    assert progress["completed"] == progress["planned"] and not progress["unknown"], mapping
    if positive:
        row = next(r for r in mapping["rows"] if r["classification"] == "UNRESOLVED_DATA_DEPENDENCE")
        # The normal CLI must distinguish a proved post-reset relation from
        # the pre-fix one-step-only diagnostic. Its blocking verdict stays.
        assert row["reason"] == ("POST_RESET_COFACTOR_INDEPENDENCE: reset-independent in the immediate poststate of an asserted reset edge; "
                                 "unrestricted first-edge force sense remains unresolved"), row
    certified = [r for r in mapping["rows"] if r.get("post_reset_certificate")]
    assert len(certified) == int(positive), mapping
    if positive:
        row = certified[0]
        # Its unconstrained relation is still unequal. The new certificate
        # reports a composed post-reset scope rather than rewriting that fact.
        assert row["native_queries"]["equal"] == "REFUTED", row
        cert = row["post_reset_certificate"]
        assert cert["active_reset_value"] == int(not low), cert
        assert cert["scope"] == "current state immediately follows an asserted reset edge on the same clock and edge", cert
        assert len(cert["premises"]) == 1 and cert["premises"][0]["value"] == value, cert
        assert cert["premises"][0]["q"] != row["q"], cert
        post = mapping["post_reset_independence"]
        assert post["native_exit_code"] == 0 and post["status"] == "COMPLETED", post
        assert post["query_progress"]["completed"] == post["query_progress"]["planned"], post
        assert post["query_progress"]["by_identity"][cert["domain_query"]]["result"] == "HAS_UNDEF", post
        assert post["query_progress"]["by_identity"][cert["equality_query"]]["result"] == "PROVED", post
    assert mapping["unresolved"] and not mapping["complete"], mapping


@pytest.mark.parametrize("case", ["inhibit-high", "inhibit-low", "enable-high", "opposite-force", "mixed-data", "vector-undef-kept"])
def test_raw_feedback_retention_has_the_same_force_boundary_as_enable(tmp_path, case):
    _yosys()
    low = case == "inhibit-low"
    reset = "!rst" if low else "rst"
    enable = "rst" if case in {"enable-high", "inhibit-low"} else "!rst"
    body = f"if ({reset}) q[0]<=0; else q[0]<=d[0]; if ({enable}) q[1]<=d[1];"
    if case == "opposite-force":
        body = "if(rst) q[0]<=0; else q[0]<=d[0]; if(!rst) q[1]<=0; else q[1]<=d[1];"
    elif case == "mixed-data":
        body = "if(rst) q[0]<=0; else q[0]<=d[0]; q[1]<=rst ? d[1]^clear : d[1];"
    rtl = tmp_path / "m.v"
    if case == "vector-undef-kept":
        # Preserve the conservative literal-X refusal when a wide raw mux
        # contains undef in another lane; retention cannot erase that refusal.
        rtl.write_text(_control_rtl("begin " + body + " q[2] <= en ? 1'bx : d[2]; end", width=3))
    else:
        # A separate independent undef flop keeps the actual raw proc model
        # without putting X in a wide mux shared with the retention bit.
        rtl.write_text("module m(input clk,rst,en,clear,input [2:0] d,output reg [1:0] q,output reg poison);\n"
            "always @(posedge clk) begin " + body + " end\n"
            "always @(posedge clk) poison <= en ? 1'bx : d[2];\nendmodule\n")
    out = tmp_path / "mapping.json"
    claim = "active_low" if low else "active_high"
    rc = fsc.main(["--rtl", str(rtl), "--top", "m", "--claim", f"reset_polarity:rst:{claim}",
                   "--work-dir", str(tmp_path), "--json", str(out)])
    rec = json.loads(out.read_text())
    expected = fsc.REFUTED if case == "opposite-force" else fsc.NOT_DISCHARGED if case in {"mixed-data", "vector-undef-kept"} else fsc.PASS
    assert rec["verdict"] == expected, rec
    assert rc == (0 if expected == fsc.PASS else 1), rec
    mapping = rec["claims"][0]["reset_control_mapping"]
    assert mapping["state_model"] == "raw_pre_cleanup_current_source", mapping
    assert len(mapping["raw_identities"]) == len(mapping["rows"]) == 3, mapping
    assert mapping["native_exit_code"] == 0, mapping
    progress = mapping["query_progress"]
    assert progress["completed"] == progress["planned"] and not progress["unknown"], progress
    if expected == fsc.PASS:
        row = next(r for r in mapping["rows"] if r["classification"] == "RETENTION_CONTROL")
        assert row["proof_basis"] == "native_full_domain_retention_cofactor", row
        a = row["native_queries"]
        assert {a["retain0"], a["retain1"]} == {"PROVED", "REFUTED"}, row
        assert all(a[f"{role}_reachable{arm}"] == "PROVED" for arm in (0, 1)
                   for role in ("force_zero", "force_one")), row


@pytest.mark.parametrize("width,value", [(1,1),(3,5)])
def test_native_reset_parameter_and_async_timing_controls(tmp_path, width, value):
    _yosys()
    rtl = tmp_path/"m.v"
    rtl.write_text(_control_rtl(f"if(!rst) q<={value}; else if(en) q<=d;",width,
                                "posedge clk or negedge rst"))
    claims = [{"rule":"reset_polarity","signal":"rst","value":"active_low"},
              {"rule":"reset_sync","signal":"rst","value":"synchronous"}]
    rec = fsc.check([rtl],"m",claims,tmp_path)
    assert rec["claims"][0]["verdict"] == fsc.PASS, rec
    assert rec["claims"][1]["verdict"] == fsc.REFUTED, rec
    mapping = rec["claims"][0].get("reset_control_mapping") or {}
    assert len(mapping.get("raw_identities") or []) == width, mapping
    assert all(r["polarity"] == "active_low" and r["timing"] == "asynchronous"
               for r in mapping["rows"]), mapping


def test_unknown_clock_is_explicit_not_full_polarity(tmp_path):
    _yosys()
    rtl = tmp_path/"m.v"
    rtl.write_text(_control_rtl("if(rst) q<=0; else q<=d;",edge="posedge (clk & en)"))
    rec = fsc.check([rtl],"m",[{"rule":"reset_polarity","signal":"rst","value":"active_high"}],tmp_path)
    assert rec["verdict"] == fsc.NOT_DISCHARGED, rec
    mapping = rec["claims"][0].get("reset_control_mapping") or {}
    assert mapping.get("unresolved") and all(r["classification"] == "UNSUPPORTED"
                                             for r in mapping["rows"]), mapping


# These are self-authored public circuits, not examples copied from a field IC.
# In particular, the Boolean masking controls leave every Q/data bit free.
_GUARDED_ROLE_CASES = {
    "and-not": ("q<=d & {W{!(rst&clear)}};", fsc.PASS, "RESET_FORCE"),
    "and-not-low": ("q<=d & {W{!(!rst&clear)}};", fsc.REFUTED, "RESET_FORCE"),
    "or-mask": ("q<=d | {W{rst&clear}};", fsc.PASS, "RESET_FORCE"),
    "nested-predicate": ("q<=d & {W{!((rst&clear)|(rst&en))}};", fsc.PASS, "RESET_FORCE"),
    "qualified-retain": ("q<=q & {W{!(rst&clear)}};", fsc.PASS, "RESET_FORCE"),
    "shared-q-data": ("if(rst) begin if(en) q<=0; end else if(en) q<=d;", fsc.PASS, "RESET_FORCE"),
    "data-mux": ("q<=rst ? d : {W{en}};", fsc.NOT_DISCHARGED, "UNRESOLVED_DATA_DEPENDENCE"),
    "lowered-data-mux": ("q<=({W{rst}}&d)|({W{!rst}}&{W{en}});", fsc.NOT_DISCHARGED, "UNRESOLVED_DATA_DEPENDENCE"),
    "data-xor": ("q<=d ^ {W{rst&clear}};", fsc.NOT_DISCHARGED, "UNRESOLVED_DATA_DEPENDENCE"),
    "mixed-sense": ("if(rst^clear) q<=0; else q<=d;", fsc.NOT_DISCHARGED, "UNRESOLVED_DATA_DEPENDENCE"),
    "impossible-control": ("if(rst & !rst & clear) q<=0; else q<=d;", fsc.NOT_DISCHARGED, "NO_DEPENDENCE"),
    "conditional-x": ("if(rst&clear) q<={W{1'bx}}; else q<=d;", fsc.NOT_DISCHARGED, "UNSUPPORTED"),
}


@pytest.mark.parametrize("case", _GUARDED_ROLE_CASES)
def test_guarded_boolean_roles_normal_cli_has_actual_feasible_domains(tmp_path, case):
    _yosys()
    body, expected, classification = _GUARDED_ROLE_CASES[case]
    rtl, output = tmp_path / "m.v", tmp_path / "mapping.json"
    rtl.write_text(_control_rtl(body))
    rc = fsc.main(["--rtl", str(rtl), "--top", "m", "--claim",
        "reset_polarity:rst:active_high", "--work-dir", str(tmp_path), "--json", str(output)])
    rec = json.loads(output.read_text())
    assert rec["verdict"] == expected and rc == (0 if expected == fsc.PASS else 1), rec
    mapping = rec["claims"][0]["reset_control_mapping"]
    assert mapping["shared_current_q_and_data"] and mapping["paired_domain_reachable"], mapping
    assert len(mapping["raw_identities"]) == 2, mapping
    assert all(len(r["current_q"]) == 1 for r in mapping["raw_identities"]), mapping
    assert classification in {r["classification"] for r in mapping["rows"]}, mapping
    if case != "conditional-x":
        for row in mapping["rows"]:
            roles = row["conditional_roles"]
            assert len(roles) == 8, row
            assert all(row["native_queries"][f"roles_cover{arm}"] == "PROVED" and
                       row["native_queries"][f"roles_disjoint{arm}"] == "PROVED"
                       for arm in (0, 1)), row
            assert all(r["domain_query"] in {"PROVED", "REFUTED"} for r in roles), row
            assert all(r["implication_query"] == "PROVED" for r in roles
                       if r["role"] != "DATA"), row
    if expected in {fsc.PASS, fsc.REFUTED}:
        assert mapping["complete"] and not mapping["unresolved"], mapping
        assert all(any(r["reachable"] and r["role"] in {"FORCE_ZERO", "FORCE_ONE"}
                       for r in row["conditional_roles"]) for row in mapping["rows"]), mapping
    if case in {"and-not", "or-mask", "nested-predicate", "qualified-retain", "shared-q-data"}:
        assert all(row["total_force"] is False for row in mapping["rows"]), mapping
    if case in {"data-mux", "lowered-data-mux", "data-xor", "impossible-control"}:
        assert not any(r["reachable"] and r["role"] in {"FORCE_ZERO", "FORCE_ONE"}
                       for row in mapping["rows"] for r in row["conditional_roles"]), mapping
    if case == "mixed-sense":
        assert all(row["native_queries"]["high"] == "REFUTED" and
                   row["native_queries"]["low"] == "REFUTED" for row in mapping["rows"]), mapping
    if case == "qualified-retain":
        assert mapping["state_model"] == "raw_pre_cleanup_current_source", mapping
        assert mapping["optimized_projection_explained"] is True, mapping
        assert len(mapping["rows"]) == len(mapping["raw_identities"]) == 2, mapping
        assert all(not p["optimized_q"] and p["optimized_constants"] == ["0"]
                   for p in mapping["optimized_identity_projection"]), mapping
        binding = mapping["source_binding"]
        assert binding["rtl_sha256"] == rec["rtl_sha256"], rec
        assert binding["raw_netlist_sha256"] and binding["optimized_netlist_sha256"], rec
        assert binding["scope"].endswith("not optimized-state coverage"), rec


def test_data_mux_value_cannot_be_promoted_to_outer_mask_control(tmp_path):
    """A native true implication under data=0 is not reset-role provenance."""
    _yosys()
    rtl, output = tmp_path / "m.v", tmp_path / "mapping.json"
    rtl.write_text("module m(input clk,rst,d,en,clear,output reg q);\n"
                   " always @(posedge clk) q <= (rst ? d : (d | en)) & clear;\nendmodule\n")
    rc = fsc.main(["--rtl", str(rtl), "--top", "m", "--claim",
        "reset_polarity:rst:active_high", "--work-dir", str(tmp_path), "--json", str(output)])
    rec = json.loads(output.read_text())
    assert rc == 1 and rec["verdict"] == fsc.NOT_DISCHARGED, rec
    mapping = rec["claims"][0]["reset_control_mapping"]
    assert len(mapping["raw_identities"]) == len(mapping["rows"]) == 1, mapping
    assert mapping["shared_current_q_and_data"] and mapping["paired_domain_reachable"], mapping
    assert mapping["unresolved"] and not mapping["complete"], mapping
    assert all(row["classification"] == "UNRESOLVED_DATA_DEPENDENCE" for row in mapping["rows"]), mapping
    assert not any(role["reachable"] and role["role"] in {"FORCE_ZERO", "FORCE_ONE"}
                   for row in mapping["rows"] for role in row["conditional_roles"]), mapping


@pytest.mark.parametrize("operator", ["and", "or"])
def test_guarded_logical_and_reduction_masks_use_native_vector_truth(tmp_path, operator):
    _yosys()
    logical, reduction = ("&&", "&") if operator == "and" else ("||", "|")
    predicate = "!(rst&&clear)" if operator == "and" else "(rst&&clear)"
    rtl, output = tmp_path / "m.v", tmp_path / "mapping.json"
    rtl.write_text("module m #(parameter W=3)(input clk,rst,clear,input[W-1:0] d,output reg[1:0] q);\n"
        f"always @(posedge clk) begin q[0]<=d {logical} {predicate}; "
        f"q[1]<={reduction}{{d,{predicate}}}; end\nendmodule\n")
    rc = fsc.main(["--rtl", str(rtl), "--top", "m", "--claim",
        "reset_polarity:rst:active_high", "--work-dir", str(tmp_path), "--json", str(output)])
    rec = json.loads(output.read_text())
    assert rc == 0 and rec["verdict"] == fsc.PASS, rec
    raw = json.loads((tmp_path / "formal_structural_netlist_raw.json").read_text())
    types = {cell["type"] for cell in raw["modules"]["m"]["cells"].values()}
    assert f"$logic_{operator}" in types and f"$reduce_{operator}" in types, types
    mapping = rec["claims"][0]["reset_control_mapping"]
    assert mapping["complete"] and not mapping["unresolved"], mapping
    assert mapping["shared_current_q_and_data"] and mapping["paired_domain_reachable"], mapping
    assert len(mapping["raw_identities"]) == 2, mapping
    assert all(len(r["current_q"]) == 1 for r in mapping["raw_identities"]), mapping
    wanted = "FORCE_ZERO" if operator == "and" else "FORCE_ONE"
    assert mapping["rows"] and all(r["classification"] == "RESET_FORCE" and
        r["polarity"] == "active_high" and r["total_force"] is False for r in mapping["rows"]), mapping
    for row in mapping["rows"]:
        assert any(r["reset_value"] == 1 and r["role"] == wanted and r["reachable"] and
                   r["implication_query"] == "PROVED" for r in row["conditional_roles"]), row
        assert row["native_queries"]["zero0"] == row["native_queries"]["one0"] == "REFUTED", row
        assert all(row["native_queries"][f"roles_cover{arm}"] == "PROVED" and
                   row["native_queries"][f"roles_disjoint{arm}"] == "PROVED" for arm in (0, 1)), row


def test_lowered_data_mux_cannot_select_shared_payload_for_force_guard(tmp_path):
    """The H1 source meaning survives AND/OR lowering, without a mux opcode."""
    _yosys()
    rtl, output = tmp_path / "m.v", tmp_path / "mapping.json"
    rtl.write_text("module m(input clk,rst,d,en,clear,output reg q);\n"
        " always @(posedge clk) q <= ((rst & d) | ((!rst) & (d | en))) & clear;\nendmodule\n")
    rc = fsc.main(["--rtl", str(rtl), "--top", "m", "--claim",
        "reset_polarity:rst:active_high", "--work-dir", str(tmp_path), "--json", str(output)])
    rec = json.loads(output.read_text())
    assert rc == 1 and rec["verdict"] == fsc.NOT_DISCHARGED, rec
    mapping = rec["claims"][0]["reset_control_mapping"]
    assert len(mapping["raw_identities"]) == len(mapping["rows"]) == 1, mapping
    assert mapping["unresolved"] and not mapping["complete"], mapping
    row = mapping["rows"][0]
    assert row["classification"] == "UNRESOLVED_DATA_DEPENDENCE", mapping
    assert not any(role["reachable"] and role["role"] in {"FORCE_ZERO", "FORCE_ONE"}
                   for role in row["conditional_roles"]), row
    assert row["payload_support"]["status"] == "NATIVE_NORMALIZED_COFACTOR_SUPPORT", row
    native = json.loads((tmp_path / "formal_structural_netlist.json").read_text())["modules"]["m"]
    assert native["ports"]["d"]["bits"][0] in row["payload_support"]["shared_payload_bits"], row
    assert mapping["payload_analysis"]["native_exit_code"] == 0, mapping


@pytest.mark.parametrize("case,body,width,forced_bits,force_role", [
    ("xor", "q <= d ^ (d & {W{rst & clear}});", 2, 2, "FORCE_ZERO"),
    ("xnor", "q <= ~(d ^ (d & {W{rst & clear}}));", 3, 3, "FORCE_ONE"),
    ("current-q", "q <= q ^ (q & {W{rst & clear}});", 2, 2, "FORCE_ZERO"),
    ("unsigned-mask", "q <= d ^ (d & (rst & clear));", 2, 1, "FORCE_ZERO"),
], ids=["xor", "xnor", "current-q", "unsigned-mask"])
def test_shared_payload_correlations_are_classified_without_selecting_data_values(
        tmp_path, case, body, width, forced_bits, force_role):
    _yosys()
    rtl = tmp_path / "m.v"
    rtl.write_text(_control_rtl(body, width))
    output = tmp_path / "mapping.json"
    rc = fsc.main(["--rtl", str(rtl), "--top", "m", "--claim",
        "reset_polarity:rst:active_high", "--work-dir", str(tmp_path), "--json", str(output)])
    rec = json.loads(output.read_text())
    actual_verdict = rec["verdict"]
    assert actual_verdict == fsc.PASS
    assert rc == 0
    mapping = rec["claims"][0]["reset_control_mapping"]
    assert mapping["complete"] and not mapping["unresolved"], mapping
    assert mapping["shared_current_q_and_data"] and mapping["paired_domain_reachable"], mapping
    assert len(mapping["raw_identities"]) == len(mapping["rows"]) == width, mapping
    forced = [row for row in mapping["rows"] if row["classification"] == "RESET_FORCE"]
    assert len(forced) == forced_bits, mapping
    assert all(row["polarity"] == "active_high" and not row["total_force"] for row in forced), mapping
    for row in forced:
        assert any(role["reset_value"] == 1 and role["role"] == force_role and
                   role["reachable"] and role["implication_query"] == "PROVED"
                   for role in row["conditional_roles"]), row
        assert row["native_queries"]["undef0"] == row["native_queries"]["undef1"] == "NO_UNDEF", row
        assert any("cofactored_shared_payload_bit" in p for p in row["role_provenance"]), row
    if case == "current-q":
        assert all(any(role["reset_value"] == 0 and role["role"] == "RETAIN" and
                       role["reachable"] and role["implication_query"] == "PROVED"
                       for role in row["conditional_roles"]) for row in forced), mapping
    if case == "unsigned-mask":
        assert sum(row["classification"] == "NO_DEPENDENCE" for row in mapping["rows"]) == 1, mapping
    wrong = fsc.check([rtl], "m", [{"rule": "reset_polarity", "signal": "rst", "value": "active_low"}],
                      tmp_path / "wrong-sense")
    assert wrong["verdict"] == fsc.REFUTED, wrong


def test_correlated_role_candidates_preserve_data_and_undef_refusals(tmp_path):
    _yosys()
    for name, body in [
        ("data-switch", "q <= rst ? d : ~d;"),
        ("opposite-forced-values", "q <= d ^ ((rst ? d : ~d) & {W{clear}});"),
        ("literal-x", "q <= d ^ ((d ^ {W{1'bx}}) & {W{rst & clear}});"),
    ]:
        work = tmp_path / name
        work.mkdir()
        rtl = work / "m.v"
        rtl.write_text(_control_rtl(body))
        rec = fsc.check([rtl], "m", [{"rule": "reset_polarity", "signal": "rst", "value": "active_high"}], work)
        assert rec["verdict"] == fsc.NOT_DISCHARGED, rec
        mapping = rec["claims"][0]["reset_control_mapping"]
        assert len(mapping["raw_identities"]) == 2 and mapping["unresolved"], mapping


@pytest.mark.parametrize("payload", ["d", "{q,d[1:0]}"], ids=["free-data", "current-q"])
def test_masked_parity_reduction_normal_cli_matches_factored_reset_roles(tmp_path, payload):
    _yosys()
    observations = []
    for name, expression in [
        ("masked", f"^({payload} & {{W{{!(rst&clear)}}}})"),
        ("factored", f"(^{payload}) & !(rst&clear)"),
    ]:
        work = tmp_path / name
        work.mkdir()
        rtl, output = work / "m.v", work / "mapping.json"
        rtl.write_text("module m #(parameter W=3)(input clk,rst,clear,input[W-1:0] d,output reg q);\n"
                       f"always @(posedge clk) q <= {expression};\nendmodule\n")
        rc = fsc.main(["--rtl", str(rtl), "--top", "m", "--claim",
            "reset_polarity:rst:active_high", "--work-dir", str(work), "--json", str(output)])
        rec = json.loads(output.read_text())
        observations.append((name, rc, rec["verdict"]))
    assert observations == [("masked", 0, fsc.PASS), ("factored", 0, fsc.PASS)]
    for name, _, _ in observations:
        work = tmp_path / name
        mapping = json.loads((work / "mapping.json").read_text())["claims"][0]["reset_control_mapping"]
        assert mapping["complete"] and not mapping["unresolved"], mapping
        assert mapping["shared_current_q_and_data"] and mapping["paired_domain_reachable"], mapping
        assert len(mapping["raw_identities"]) == len(mapping["rows"]) == 1, mapping
        assert mapping["native_exit_code"] == mapping["payload_analysis"]["native_exit_code"] == 0, mapping
        progress = mapping["query_progress"]
        assert progress["completed"] == progress["planned"] and not progress["unknown"], mapping
        row = mapping["rows"][0]
        assert row["classification"] == "RESET_FORCE" and row["polarity"] == "active_high", row
        assert row["total_force"] is False, row
        assert any(role["reset_value"] == 1 and role["role"] == "FORCE_ZERO" and
                   role["reachable"] and role["implication_query"] == "PROVED"
                   for role in row["conditional_roles"]), row
        assert all(row["native_queries"][f"roles_{proof}{arm}"] == "PROVED"
                   for arm in (0, 1) for proof in ("cover", "disjoint")), row
        assert row["native_queries"]["undef0"] == row["native_queries"]["undef1"] == "NO_UNDEF", row
        if name == "masked":
            assert any(p["kind"] == "$reduce_xor" for p in row["role_provenance"]), row
        wrong = fsc.check([work / "m.v"], "m", [
            {"rule": "reset_polarity", "signal": "rst", "value": "active_low"}], work / "wrong-sense")
        assert wrong["verdict"] == fsc.REFUTED, wrong
        print("PARITY_RESET_OBSERVATION " + json.dumps({"form": name, "payload": payload,
            "verdict": "PASS", "wrong_sense": wrong["verdict"], "mapping": mapping}, sort_keys=True))


def test_parity_reduction_preserves_ordinary_data_current_q_and_undef_refusals(tmp_path):
    _yosys()
    for name, expression in [
        ("ordinary-data", "^(d ^ {W{rst&clear}})"),
        ("current-q-data", "^({q,d[0],rst&clear})"),
        ("literal-x", "^({d[1:0],1'bx} & {W{!(rst&clear)}})"),
    ]:
        work = tmp_path / name
        work.mkdir()
        rtl, output = work / "m.v", work / "mapping.json"
        rtl.write_text("module m #(parameter W=3)(input clk,rst,clear,input[W-1:0] d,output reg q);\n"
                       f"always @(posedge clk) q <= {expression};\nendmodule\n")
        rc = fsc.main(["--rtl", str(rtl), "--top", "m", "--claim",
            "reset_polarity:rst:active_high", "--work-dir", str(work), "--json", str(output)])
        rec = json.loads(output.read_text())
        assert rc == 1 and rec["verdict"] == fsc.NOT_DISCHARGED, rec
        mapping = rec["claims"][0]["reset_control_mapping"]
        assert len(mapping["raw_identities"]) == 1 and mapping["unresolved"] and not mapping["complete"], mapping
        assert mapping["native_exit_code"] == 0, mapping
        assert not any(role["reachable"] and role["role"] in {"FORCE_ZERO", "FORCE_ONE"}
                       for row in mapping["rows"] for role in row["conditional_roles"]), mapping
        print("PARITY_REFUSAL_OBSERVATION " + json.dumps({"case": name, "rc": rc,
            "verdict": rec["verdict"], "mapping": mapping}, sort_keys=True))


def test_derived_shared_payload_normal_cli_matches_factored_reset_roles(tmp_path):
    """The same derived parity must not change a reset role or its wrong sense."""
    _yosys()
    observations = []
    for name, expression in [
        ("derived", "p ^ (p & (rst & clear))"),
        ("factored", "p & !(rst & clear)"),
    ]:
        for sense in ("active_high", "active_low"):
            work = tmp_path / name / sense
            work.mkdir(parents=True)
            rtl, output = work / "m.v", work / "mapping.json"
            rtl.write_text("module m #(parameter W=3)(input clk,rst,clear,input[W-1:0] d,output reg q);\n"
                           "wire p=^d;\n"
                           f"always @(posedge clk) q <= {expression};\nendmodule\n")
            rc = fsc.main(["--rtl", str(rtl), "--top", "m", "--claim",
                f"reset_polarity:rst:{sense}", "--work-dir", str(work), "--json", str(output)])
            rec = json.loads(output.read_text())
            observations.append((name, sense, rc, rec["verdict"]))
    assert observations == [
        ("derived", "active_high", 0, fsc.PASS),
        ("derived", "active_low", 1, fsc.REFUTED),
        ("factored", "active_high", 0, fsc.PASS),
        ("factored", "active_low", 1, fsc.REFUTED),
    ], observations
    for name in ("derived", "factored"):
        work = tmp_path / name / "active_high"
        mapping = json.loads((work / "mapping.json").read_text())["claims"][0]["reset_control_mapping"]
        assert mapping["complete"] and not mapping["unresolved"], mapping
        assert mapping["shared_current_q_and_data"] and mapping["paired_domain_reachable"], mapping
        assert len(mapping["raw_identities"]) == len(mapping["rows"]) == 1, mapping
        assert mapping["native_exit_code"] == mapping["payload_analysis"]["native_exit_code"] == 0, mapping
        progress = mapping["query_progress"]
        assert progress["completed"] == progress["planned"] and not progress["unknown"], mapping
        row = mapping["rows"][0]
        assert row["classification"] == "RESET_FORCE" and row["polarity"] == "active_high", row
        assert row["total_force"] is False, row
        assert any(role["reset_value"] == 1 and role["role"] == "FORCE_ZERO" and
                   role["reachable"] and role["implication_query"] == "PROVED"
                   for role in row["conditional_roles"]), row
        assert all(row["native_queries"][f"roles_{proof}{arm}"] == "PROVED"
                   for arm in (0, 1) for proof in ("cover", "disjoint")), row
        assert row["native_queries"]["undef0"] == row["native_queries"]["undef1"] == "NO_UNDEF", row
        if name == "derived":
            assert any("cofactored_shared_payload_bit" in p for p in row["role_provenance"]), row


@pytest.mark.parametrize("payload", ["d", "{q,d[1:0]}"], ids=["free-data", "current-q"])
def test_masked_xnor_reduction_normal_cli_matches_factored_reset_roles(tmp_path, payload):
    """XNOR complements parity once; shared data and wrong sense stay real."""
    _yosys()
    observations = []
    for name, expression in [
        ("masked", f"~^({payload} & {{W{{!(rst&clear)}}}})"),
        ("factored", f"(~^{payload}) | (rst&clear)"),
    ]:
        for sense in ("active_high", "active_low"):
            work = tmp_path / name / sense
            work.mkdir(parents=True)
            rtl, output = work / "m.v", work / "mapping.json"
            rtl.write_text("module m #(parameter W=3)(input clk,rst,clear,input[W-1:0] d,output reg q);\n"
                           f"always @(posedge clk) q <= {expression};\nendmodule\n")
            rc = fsc.main(["--rtl", str(rtl), "--top", "m", "--claim",
                f"reset_polarity:rst:{sense}", "--work-dir", str(work), "--json", str(output)])
            rec = json.loads(output.read_text())
            observations.append((name, sense, rc, rec["verdict"]))
    assert observations == [
        ("masked", "active_high", 0, fsc.PASS),
        ("masked", "active_low", 1, fsc.REFUTED),
        ("factored", "active_high", 0, fsc.PASS),
        ("factored", "active_low", 1, fsc.REFUTED),
    ], observations
    for name in ("masked", "factored"):
        work = tmp_path / name / "active_high"
        mapping = json.loads((work / "mapping.json").read_text())["claims"][0]["reset_control_mapping"]
        assert mapping["complete"] and not mapping["unresolved"], mapping
        assert mapping["shared_current_q_and_data"] and mapping["paired_domain_reachable"], mapping
        assert len(mapping["raw_identities"]) == len(mapping["rows"]) == 1, mapping
        assert mapping["native_exit_code"] == mapping["payload_analysis"]["native_exit_code"] == 0, mapping
        progress = mapping["query_progress"]
        assert progress["completed"] == progress["planned"] and not progress["unknown"], mapping
        row = mapping["rows"][0]
        assert row["classification"] == "RESET_FORCE" and row["polarity"] == "active_high", row
        assert row["total_force"] is False, row
        assert any(role["reset_value"] == 1 and role["role"] == "FORCE_ONE" and
                   role["reachable"] and role["implication_query"] == "PROVED"
                   for role in row["conditional_roles"]), row
        assert all(row["native_queries"][f"roles_{proof}{arm}"] == "PROVED"
                   for arm in (0, 1) for proof in ("cover", "disjoint")), row
        assert row["native_queries"]["undef0"] == row["native_queries"]["undef1"] == "NO_UNDEF", row
        if name == "masked":
            raw = json.loads((work / "formal_structural_netlist_raw.json").read_text())
            assert "$reduce_xnor" in {cell["type"] for cell in raw["modules"]["m"]["cells"].values()}, raw
            assert any(p["kind"] == "$reduce_xnor" for p in row["role_provenance"]), row
        print("XNOR_RESET_OBSERVATION " + json.dumps({"form": name, "payload": payload,
            "verdict": "PASS", "wrong_sense": "REFUTED", "mapping": mapping}, sort_keys=True))


def test_xnor_reduction_preserves_ordinary_data_current_q_and_undef_refusals(tmp_path):
    _yosys()
    for name, expression in [
        ("ordinary-data", "~^(d ^ {W{rst&clear}})"),
        ("current-q-data", "~^({q,d[0],rst&clear})"),
        ("literal-x", "~^({d[1:0],1'bx} & {W{!(rst&clear)}})"),
    ]:
        work = tmp_path / name
        work.mkdir()
        rtl, output = work / "m.v", work / "mapping.json"
        rtl.write_text("module m #(parameter W=3)(input clk,rst,clear,input[W-1:0] d,output reg q);\n"
                       f"always @(posedge clk) q <= {expression};\nendmodule\n")
        rc = fsc.main(["--rtl", str(rtl), "--top", "m", "--claim",
            "reset_polarity:rst:active_high", "--work-dir", str(work), "--json", str(output)])
        rec = json.loads(output.read_text())
        assert rc == 1 and rec["verdict"] == fsc.NOT_DISCHARGED, rec
        mapping = rec["claims"][0]["reset_control_mapping"]
        assert len(mapping["raw_identities"]) == 1 and mapping["unresolved"] and not mapping["complete"], mapping
        assert mapping["native_exit_code"] == 0, mapping
        assert not any(role["reachable"] and role["role"] in {"FORCE_ZERO", "FORCE_ONE"}
                       for row in mapping["rows"] for role in row["conditional_roles"]), mapping
        print("XNOR_REFUSAL_OBSERVATION " + json.dumps({"case": name, "rc": rc,
            "verdict": rec["verdict"], "mapping": mapping}, sort_keys=True))


@pytest.mark.parametrize("body, expected", [
    ("if(rst) q<=0; else q<=(d+en)-(clear);", fsc.PASS),
    ("if(!rst) q<=0; else q<=(d+en)-(clear);", fsc.REFUTED),
    ("if(rst) q<=0; else q<=d[en +: 2];", fsc.NOT_DISCHARGED),
    pytest.param("if(rst) q<=0; else q<=d*{en,clear};", fsc.PASS, id="multiply-force-high"),
    pytest.param("if(!rst) q<=0; else q<=d*{en,clear};", fsc.REFUTED, id="multiply-wrong-force"),
    pytest.param("if(rst) q<=d*(en ? 2'bxx : 2'b11); else q<=d;", fsc.NOT_DISCHARGED, id="multiply-undef"),
])
def test_arithmetic_and_undefined_shift_use_exact_cones_without_new_credit(tmp_path, body, expected):
    _yosys()
    rtl=tmp_path/"m.v"
    rtl.write_text(_control_rtl(body))
    rec=fsc.check([rtl], "m", [{"rule":"reset_polarity", "signal":"rst", "value":"active_high"}], tmp_path)
    mapping=rec["claims"][0]["reset_control_mapping"]
    assert mapping["native_row_cone"]["reason"] == "single-driver-total-boolean-dag", mapping["native_row_cone"]
    assert mapping["native_row_cone"]["eligible"] is True, mapping["native_row_cone"]
    assert rec["verdict"] == expected, rec
    progress=mapping["query_progress"]
    assert progress["completed"] == progress["planned"] and not progress["unknown"], progress
    assert len(mapping["raw_identities"]) == 2


def test_native_container_queries_use_identity_supervision_not_client_timeout(monkeypatch):
    import _container_exec as ce
    calls=[]
    def supervised(container, command, **kwargs):
        calls.append((container,command,kwargs))
        return subprocess.CompletedProcess([], ce.STALLED_RC, "partial query\n", "owned job reaped")
    monkeypatch.setattr(ce,"run_in_container_supervised",supervised)
    monkeypatch.setattr(ce,"local_exec_mode",lambda _tag: False)
    rc,out,err,meta=fsc._native_query_run(["docker","exec"], container="test-container", command="yosys -s model.ys")
    assert calls == [("test-container","yosys -s model.ys",{"ceiling_s":120})]
    assert rc == ce.STALLED_RC and out == "partial query\n" and err == "owned job reaped"
    assert meta["termination"] == "STALLED" and meta["supervision"] == "container_identity_and_progress"


@pytest.mark.parametrize("body", [
    "if(rst) q<=0; else q<=(d+en)-clear;",
    "if(!rst) q<=0; else q<=(d+en)-clear;",
    "if(rst) q<=0; else q<=d[en +: 2];",
    pytest.param("if(rst) q<=0; else q<=d*{en,clear};", id="multiply-force-high"),
    pytest.param("if(!rst) q<=0; else q<=d*{en,clear};", id="multiply-wrong-force"),
    pytest.param("if(rst) q<=d*(en ? 2'bxx : 2'b11); else q<=d;", id="multiply-undef"),
])
def test_native_cone_and_whole_model_answers_match_every_identity_and_arm(tmp_path, monkeypatch, body):
    _yosys()
    rtl=tmp_path/"m.v"
    rtl.write_text(_control_rtl(body))
    claim=[{"rule":"reset_polarity", "signal":"rst", "value":"active_high"}]
    cone=fsc.check([rtl],"m",claim,tmp_path/"cone")
    monkeypatch.setattr(fsc,"_reset_row_cone_eligibility",lambda model: {"eligible":False,"reason":"whole-model control"})
    whole=fsc.check([rtl],"m",claim,tmp_path/"whole")
    left=cone["claims"][0]["reset_control_mapping"]
    right=whole["claims"][0]["reset_control_mapping"]
    assert cone["verdict"] == whole["verdict"]
    assert left["raw_identities"] == right["raw_identities"]
    assert left["query_progress"]["planned"] == right["query_progress"]["planned"]
    for arm in (left,right):
        assert arm["query_progress"]["completed"] == arm["query_progress"]["planned"]
    def answers(mapping):
        return [(r["cell"],r["bit_index"],r["classification"],r["native_queries"]) for r in mapping["rows"]]
    assert answers(left) == answers(right)


def test_native_host_progress_finishes_past_recorded_batch_budget(tmp_path):
    """Real progressing Python child, not a simulator or mocked supervisor."""
    import time
    program = ("import time\n"
               "start=time.monotonic()\n"
               "for tick in range(12):\n"
               " print('NATIVE_PROGRESS', tick, time.monotonic()-start, flush=True)\n"
               " time.sleep(0.02)\n"
               "print('NATIVE_BATCH_COMPLETED', flush=True)\n")
    argv = [sys.executable, '-u', '-c', program]
    budget = 0.05
    start = time.monotonic()
    rc, stdout, stderr, native = fsc._native_query_run(argv, timeout=budget)
    elapsed = time.monotonic() - start
    observation = {'scope': 'Process/progress ownership software fixture only; no EDA',
                   'argv': argv, 'recorded_budget_seconds': budget, 'elapsed_seconds': elapsed,
                   'rc': rc, 'stdout': stdout, 'stderr': stderr, 'native': native}
    (tmp_path / 'HOST_PROGRESS_OBSERVATION.json').write_text(json.dumps(observation, indent=2))
    assert (rc, native['termination'], 'NATIVE_BATCH_COMPLETED' in stdout) == (0, 'COMPLETED', True), observation
    ticks = [line.split() for line in stdout.splitlines() if line.startswith('NATIVE_PROGRESS ')]
    assert len(ticks) == 12 and float(ticks[-1][2]) > budget, observation
    assert elapsed > budget, observation


def test_native_cofactor_keeps_named_container_on_the_existing_local_route(tmp_path):
    """Actual in-image Yosys/normal cofactor owner; no Docker exec/mock tool."""
    import _container_exec as ce
    _yosys()
    assert ce.local_exec_mode('formal_structural_check'), 'this control requires the pinned no-Docker image route'
    model = {'modules': {'transition_pair': {
        'attributes': {'top': 1}, 'cells': {},
        'ports': {'input_7': {'direction': 'input', 'bits': [2]},
                  'q0_n0': {'direction': 'output', 'bits': [2]},
                  'q0_n1': {'direction': 'output', 'bits': [2]}},
        'netnames': {}}}}
    rows = [{'q': 9, 'query_ports': {'n0': 'q0_n0', 'n1': 'q0_n1'}}]
    info, payloads = fsc._cofactor_payload_support(model, rows, tmp_path,
                                                 container='normal-runner-default')
    observation = {'scope': 'Real native cofactor normalization with a container label on the existing local route',
                   'native': info, 'payloads': {str(k): sorted(v) for k, v in payloads.items()}}
    (tmp_path / 'LOCAL_ROUTE_OBSERVATION.json').write_text(json.dumps(observation, indent=2))
    observed = (info['native_exit_code'], info['status'])
    assert observed == (0, 'NATIVE_NORMALIZED_COFACTOR_SUPPORT'), observed
    assert payloads == {9: {7}}, observation
    assert info['native_run']['supervision'] == 'host_process_and_progress', observation


@pytest.mark.parametrize("reset_branch,normal_branch,declared,expected", [
    ("1'b0", "en ? 1'bx : q", "active_high", fsc.PASS),
    ("1'b0", "en ? 1'bx : q", "active_low", fsc.REFUTED),
    ("1'b1", "en ? 1'bx : q", "active_high", fsc.PASS),
    ("1'bx", "d", "active_high", fsc.NOT_DISCHARGED),
    ("en ? 1'b0 : q", "1'bx", "active_high", fsc.NOT_DISCHARGED),
])
def test_raw_undef_requires_defined_total_reset_arm(tmp_path, reset_branch, normal_branch, declared, expected):
    _yosys()
    rtl = tmp_path / "m.v"
    rtl.write_text("module m(input clk,rst,en,d,output reg q);\n"
                   "always @(posedge clk) if(rst) q <= " + reset_branch +
                   "; else q <= " + normal_branch + ";\nendmodule\n")
    rec = fsc.check([rtl], "m", [{"rule": "reset_polarity", "signal": "rst", "value": declared}], tmp_path)
    assert rec["verdict"] == expected, rec
    mapping = rec["claims"][0]["reset_control_mapping"]
    assert len(mapping["raw_identities"]) == 1
    if expected in {fsc.PASS, fsc.REFUTED}:
        row = mapping["rows"][0]
        assert row["classification"] == "RESET_FORCE"
        proof = row["raw_reset_domain_proof"]
        assert row["polarity"] == "active_high" and proof["force_value"] == int(reset_branch[-1])
        assert proof["queries"]["undef1"] == "NO_UNDEF"
        assert proof["queries"]["undef0"] == "HAS_UNDEF"
        assert "literal-X/undef" in row["unsupported"]
        assert mapping["query_progress"]["completed"] == mapping["query_progress"]["planned"]
    else:
        assert mapping["unresolved"] and not mapping["complete"]


def test_raw_undef_defined_force_honors_active_low_reset(tmp_path):
    _yosys()
    rtl = tmp_path / "m.v"
    rtl.write_text("module m(input clk,rst,en,output reg q);\n"
                   "always @(posedge clk) if(!rst) q<=1'b1; else if(en) q<=1'bx;\n"
                   "endmodule\n")
    rec = fsc.check([rtl], "m", [{"rule": "reset_polarity", "signal": "rst", "value": "active_low"}], tmp_path)
    assert rec["verdict"] == fsc.PASS, rec
    mapping = rec["claims"][0]["reset_control_mapping"]
    assert len(mapping["raw_identities"]) == 1
    row = mapping["rows"][0]
    proof = row["raw_reset_domain_proof"]
    assert row["polarity"] == "active_low" and proof["force_value"] == 1
    assert proof["queries"]["undef0"] == "NO_UNDEF" and proof["queries"]["undef1"] == "HAS_UNDEF"


def test_raw_pmux_unreachable_default_undef_does_not_replace_reset_proof(tmp_path):
    _yosys()
    rtl = tmp_path / "m.v"
    rtl.write_text("module m(input clk,rst,en,d,output reg q);\n"
                   "always @(posedge clk) if(rst) q<=0; else case(en)\n"
                   "1'b0:q<=q; 1'b1:q<=d; default:q<=1'bx; endcase\nendmodule\n")
    rec = fsc.check([rtl], "m", [{"rule": "reset_polarity", "signal": "rst",
                                "value": "active_high"}], tmp_path)
    assert rec["verdict"] == fsc.PASS, rec
    mapping = rec["claims"][0]["reset_control_mapping"]
    assert len(mapping["raw_identities"]) == len(mapping["rows"]) == 1
    assert mapping["state_model"] == "raw_pre_cleanup_current_source"
    assert mapping["raw_identities"][0]["literal_undef_in_transition"]
    row = mapping["rows"][0]
    assert row["classification"] == "RESET_FORCE"
    assert "literal-X/undef" in row["unsupported"]
    proof = row["raw_reset_domain_proof"]
    assert proof["status"] == "CERTIFIED"
    assert proof["active_reset_value"] == 1 and proof["force_value"] == 0
    assert proof["queries"]["undef0"] == proof["queries"]["undef1"] == "NO_UNDEF"
    assert proof["queries"]["zero0"] == proof["queries"]["one0"] == "REFUTED"
    assert proof["queries"]["zero1"] == "PROVED"
    progress = mapping["query_progress"]
    assert progress["planned"] == progress["started"] == progress["completed"] == 30
    assert mapping["native_row_cone"]["eligible"] is False


def test_raw_arithmetic_constant_force_cannot_be_reclassified_as_retention(tmp_path):
    _yosys()
    source = Path(__file__).parent / "fixtures/formal_reset/retention_algebraic_opposite_force.v"
    rtl = tmp_path / "m.v"
    rtl.write_bytes(source.read_bytes())
    out = tmp_path / "mapping.json"
    rc = fsc.main(["--rtl", str(rtl), "--top", "m", "--claim", "reset_polarity:rst:active_high",
                   "--work-dir", str(tmp_path), "--json", str(out)])
    rec = json.loads(out.read_text())
    assert rec["verdict"] == fsc.REFUTED, rec
    assert rc == 1, rec
    mapping = rec["claims"][0]["reset_control_mapping"]
    assert mapping["state_model"] == "raw_pre_cleanup_current_source", mapping
    assert len(mapping["raw_identities"]) == len(mapping["rows"]) == 3, mapping
    low = next(row for row in mapping["rows"] if row.get("polarity") == "active_low")
    assert low["classification"] == "RESET_FORCE" and low["total_force"], low
    assert low["native_queries"]["zero0"] == "PROVED", low
    assert low["native_queries"]["retain1"] == "PROVED", low
    assert low["native_queries"]["retain0"] == "REFUTED", low
    progress = mapping["query_progress"]
    assert progress["completed"] == progress["planned"] and not progress["unknown"], progress


_PRIORITY_LOAD_CASES = {
    'activate-priority-load': ('if(load & rst) q<=d; else if(shift) q<={q[0],q[1]};', 'active_high', fsc.PASS),
    'suppress-priority-load': ('if(load & !rst) q<=d; else if(shift) q<={q[0],q[1]};', 'active_high', fsc.PASS),
    'suppress-priority-load-low': ('if(load & rst) q<=d; else if(shift) q<={q[0],q[1]};', 'active_low', fsc.PASS),
    'enable-before-priority-load': ('if((load & !rst)|shift) q<=(load & !rst) ? d : {q[0],q[1]};', 'active_high', fsc.PASS),
    'inverse-select-priority-load': ('if(!(!(load & !rst))) q<=d; else if(shift) q<={q[0],q[1]};', 'active_high', fsc.PASS),
    'mixed-payload-kept': ('q<=rst ? d^{2{clear}} : d;', 'active_high', fsc.NOT_DISCHARGED),
    'nested-mixed-payload-kept': ('if(shift) q<=rst ? d^{2{clear}} : d;', 'active_high', fsc.NOT_DISCHARGED),
    'target-q-load-kept': ('if(load & !rst) q<=q+d; else if(shift) q<=d;', 'active_high', fsc.NOT_DISCHARGED),
    'reset-data-bypass-kept': ('if(load & !rst) q<=d^{2{rst}}; else if(shift) q<={q[0],q[1]};', 'active_high', fsc.NOT_DISCHARGED),
    'undef-load-kept': ("if(load & !rst) q<=2'bxx; else if(shift) q<={q[0],q[1]};", 'active_high', fsc.NOT_DISCHARGED),
    'wrong-force-kept': ('if(load & !rst) q<=d; else if(shift) q<={q[0],q[1]};', 'active_low_wrong', fsc.REFUTED),
}


@pytest.mark.parametrize('case', _PRIORITY_LOAD_CASES)
def test_priority_load_retention_normal_cli_keeps_unrestricted_q_and_data(tmp_path, case):
    _yosys()
    body, polarity, expected = _PRIORITY_LOAD_CASES[case]
    active = '!rst' if polarity == 'active_low' else 'rst'
    declared = 'active_low' if polarity.startswith('active_low') else 'active_high'
    source = ('module m(input clk,rst,load,shift,clear,input [1:0] d,'
              'output reg boot,output reg [1:0] q);\n'
              f'always @(posedge clk) if({active}) boot<=0; else boot<=d[0];\n'
              'always @(posedge clk) '+body+'\nendmodule\n')
    rtl = tmp_path/'m.v'
    rtl.write_text(source)
    output = tmp_path/'mapping.json'
    rc = fsc.main(['--rtl', str(rtl), '--top', 'm', '--claim',
                  'reset_polarity:rst:'+declared, '--work-dir', str(tmp_path), '--json', str(output)])
    rec = json.loads(output.read_text())
    assert rec['verdict'] == expected, rec
    assert rc == (0 if expected == fsc.PASS else 1), rec
    mapping = rec['claims'][0]['reset_control_mapping']
    assert len(mapping['raw_identities']) == 3, mapping
    assert mapping['query_progress']['completed'] == mapping['query_progress']['planned'], mapping
    if expected == fsc.PASS:
        rows = [r for r in mapping['rows'] if r.get('proof_basis') == 'native_priority_load_retention']
        assert len(rows) == 2, mapping
        assert all(r['classification'] == 'RETENTION_CONTROL' for r in rows), rows
        component = mapping['priority_load_retention']
        assert component['native_exit_code'] == 0, component
        assert component['query_progress']['completed'] == component['query_progress']['planned'], component
        for row in rows:
            cert = row['priority_load_certificate']
            assert cert['scope'] == 'unrestricted one-step shared current Q and data', cert
            assert cert['complete_reset_fanin_cut'] and cert['target_q_absent_from_load_support'], cert
            assert cert['directional_control'] == 'PROVED' and cert['discriminating_retention'] == 'REFUTED', cert
            assert cert['post_reset_state_restriction'] is False, cert
    elif expected == fsc.NOT_DISCHARGED:
        assert not any(r.get('priority_load_certificate') for r in mapping['rows']), mapping
