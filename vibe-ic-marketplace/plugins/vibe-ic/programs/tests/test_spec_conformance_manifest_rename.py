"""spec_conformance_check must CONSUME the declared interface rename.

`phase2/stage1/rtl/SOURCE_MANIFEST.json -> renamed_interfaces` is the flow's
documented way (catalog-glue-author/SKILL.md, ORGANIC #711) for a design to say
"this L9 illustrative interface is delivered under these RTL names". It had a
parser (`l9_rtl_pin_consistency_check._manifest_renamed_groups`) and NO consumer
in the 44-step flow, so an author who declared a rename as instructed still got
port-missing + port-extra ERRORs from this gate.

The rename is an ACCEPTED DECLARATION, never a suppression: these tests pin both
halves — the declared rename reconciles, and every malformed / dishonest
declaration still ERRORs, as does any UNDECLARED mismatch.
"""
import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parents[1] / "spec_conformance_check.py"

SPEC = {
    "top_module": "dut",
    "ports": [
        {"name": "i_clk",      "direction": "input",  "width": 1},
        {"name": "o_mem_addr", "direction": "output", "width": 10},
        {"name": "o_mem_data", "direction": "output", "width": 8},
    ],
}

RTL_RENAMED = """
module dut(
   input  wire       i_clk,
   output wire [9:0] o_mem_waddr,
   output wire [9:0] o_mem_raddr,
   output wire [7:0] o_mem_wdata);
   assign o_mem_waddr = 10'd0;
   assign o_mem_raddr = 10'd0;
   assign o_mem_wdata = 8'd0;
endmodule
"""


def _project(tmp_path, rtl_src, manifest):
    """Lay out the paths the gate resolves: <proj>/phase2/stage1/rtl."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dut.v").write_text(rtl_src)
    if manifest is not None:
        (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest))
    spec = tmp_path / "L9.json"
    spec.write_text(json.dumps(SPEC))
    return rtl, spec


def _run(tmp_path, rtl_src, manifest, positional=False):
    rtl, spec = _project(tmp_path, rtl_src, manifest)
    out = tmp_path / "f.json"
    # `positional` exercises the OTHER arg shape: the verdict must not depend on
    # HOW the RTL was handed to the gate.
    rtl_args = [str(rtl)] if positional else ["--rtl-dir", str(rtl)]
    rc = subprocess.run(
        [sys.executable, str(PROG)] + rtl_args +
        ["--spec", str(spec), "--json", str(out)],
        capture_output=True, text=True).returncode
    findings = json.loads(out.read_text()) if out.is_file() else []
    rules = {f["rule"] for f in findings if f["severity"] == "ERROR"}
    return rc, rules, findings


_GOOD = {"reused_ip": True, "renamed_interfaces": [
    {"l9": ["o_mem_addr"], "rtl": ["o_mem_waddr", "o_mem_raddr"]},
    {"l9": ["o_mem_data"], "rtl": ["o_mem_wdata"]}]}


def test_declared_rename_is_accepted(tmp_path):
    """THE FIX: a 1->N rename with matching direction+width reconciles."""
    rc, rules, findings = _run(tmp_path, RTL_RENAMED, _GOOD)
    assert rc == 0, f"declared rename must reconcile; got ERRORs {rules}"
    assert not rules
    assert any(f["rule"] == "port-renamed-by-manifest" for f in findings)


def test_without_the_manifest_the_same_rtl_still_errors(tmp_path):
    """NEGATIVE CONTROL: no declaration ⇒ the exact-name comparison stands."""
    rc, rules, _ = _run(tmp_path, RTL_RENAMED, None)
    assert rc != 0
    assert "port-missing" in rules and "port-extra" in rules


def test_reused_ip_false_is_not_a_declaration(tmp_path):
    """The keystone flag gates the whole relaxation (fail-closed)."""
    mf = dict(_GOOD, reused_ip=False)
    rc, rules, _ = _run(tmp_path, RTL_RENAMED, mf)
    assert rc != 0
    assert "port-missing" in rules and "port-extra" in rules


def test_undeclared_missing_port_still_errors(tmp_path):
    """A port dropped WITHOUT declaring it is still a hard ERROR."""
    rtl = RTL_RENAMED.replace(
        "   output wire [7:0] o_mem_wdata);", "   output wire [7:0] o_unrelated);"
    ).replace("   assign o_mem_wdata = 8'd0;", "   assign o_unrelated = 8'd0;")
    mf = {"reused_ip": True, "renamed_interfaces": [
        {"l9": ["o_mem_addr"], "rtl": ["o_mem_waddr", "o_mem_raddr"]}]}
    rc, rules, _ = _run(tmp_path, rtl, mf)
    assert rc != 0
    assert "port-missing" in rules, rules


def test_rename_from_a_port_the_spec_lacks_errors(tmp_path):
    mf = {"reused_ip": True, "renamed_interfaces": [
        {"l9": ["o_not_in_spec"], "rtl": ["o_mem_waddr"]}]}
    rc, rules, _ = _run(tmp_path, RTL_RENAMED, mf)
    assert rc != 0
    assert "port-rename-undeclared-spec-port" in rules, rules


def test_rename_to_a_port_the_rtl_lacks_errors(tmp_path):
    mf = {"reused_ip": True, "renamed_interfaces": [
        {"l9": ["o_mem_addr"], "rtl": ["o_absent"]}]}
    rc, rules, _ = _run(tmp_path, RTL_RENAMED, mf)
    assert rc != 0
    assert "port-rename-missing-rtl-port" in rules, rules


def test_rename_may_not_change_width(tmp_path):
    """o_mem_addr is 10 bits; o_mem_wdata is 8 — a rename cannot re-shape it."""
    mf = {"reused_ip": True, "renamed_interfaces": [
        {"l9": ["o_mem_addr"], "rtl": ["o_mem_wdata"]}]}
    rc, rules, _ = _run(tmp_path, RTL_RENAMED, mf)
    assert rc != 0
    assert "port-rename-width-mismatch" in rules, rules


def test_rename_may_not_change_direction(tmp_path):
    rtl = RTL_RENAMED.replace("   output wire [7:0] o_mem_wdata);",
                              "   input  wire [7:0] i_mem_rdata);").replace(
        "   assign o_mem_wdata = 8'd0;", "   wire _u = &{1'b0, i_mem_rdata};")
    mf = {"reused_ip": True, "renamed_interfaces": [
        {"l9": ["o_mem_data"], "rtl": ["i_mem_rdata"]}]}
    rc, rules, _ = _run(tmp_path, rtl, mf)
    assert rc != 0
    assert "port-rename-direction-mismatch" in rules, rules


def test_verdict_does_not_depend_on_the_arg_shape(tmp_path):
    """The manifest is found from the RESOLVED FILES, not from `--rtl-dir`.

    Keying the project-root derivation on the arg shape made the identical tree
    with the identical declaration return PASS via `--rtl-dir` and FAIL when the
    same directory was passed positionally — a silent, invocation-shaped
    difference in a conformance verdict.
    """
    rc_flag, rules_flag, _ = _run(tmp_path / "a", RTL_RENAMED, _GOOD)
    rc_pos, rules_pos, _ = _run(tmp_path / "b", RTL_RENAMED, _GOOD,
                                positional=True)
    assert rc_flag == rc_pos == 0, (rc_flag, rc_pos, rules_flag, rules_pos)
    assert rules_flag == rules_pos == set()


def test_undeclared_drop_still_errors_under_both_arg_shapes(tmp_path):
    """The refusal must be invocation-shape independent too."""
    rtl = RTL_RENAMED.replace(
        "   output wire [7:0] o_mem_wdata);", "   output wire [7:0] o_unrelated);"
    ).replace("   assign o_mem_wdata = 8'd0;", "   assign o_unrelated = 8'd0;")
    mf = {"reused_ip": True, "renamed_interfaces": [
        {"l9": ["o_mem_addr"], "rtl": ["o_mem_waddr", "o_mem_raddr"]}]}
    rc_flag, rules_flag, _ = _run(tmp_path / "a", rtl, mf)
    rc_pos, rules_pos, _ = _run(tmp_path / "b", rtl, mf, positional=True)
    assert rc_flag != 0 and rc_pos != 0
    assert "port-missing" in rules_flag and "port-missing" in rules_pos


_LOGICAL_SCOPE_CASES = [
    "raw-rtl-dir", "raw-positional-directory", "raw-positional-file",
    "toolports-good", "toolports-wrong-width", "toolports-wrong-clock",
    "toolports-missing-selected-port", "toolports-missing-top",
    "raw-missing-rename", "raw-wrong-spec-width", "raw-wrong-spec-clock",
    "raw-forged-declaration", "implementation-none", "implementation-good",
    "raw-directory-pivot", "raw-phase2-ancestor-pivot", "raw-stage1-ancestor-pivot",
]


def _run_selected_source_scope(tmp_path, case):
    """Real CLI on neutral current selected inputs; tool JSON is metadata only."""
    import os
    import hashlib
    from test_d2_renamed_reused_ip_ports_take_their_documents_side import _phase1_selected_scope_project
    project = _phase1_selected_scope_project(tmp_path, "absent")
    spec = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    source = project / "phase2/stage1/rtl"
    if case in {"raw-directory-pivot", "raw-phase2-ancestor-pivot", "raw-stage1-ancestor-pivot"}:
        role_files = [spec, project / "plugin_output/declaration.json",
                      source / "SOURCE_MANIFEST.json", source / "core.v"]
        role_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in role_files}
        pivot = (source if case == "raw-directory-pivot" else
                 project / "phase2" if case == "raw-phase2-ancestor-pivot" else
                 project / "phase2/stage1")
        target = project / ("outside-" + pivot.name)
        pivot.rename(target)
        pivot.symlink_to(target, target_is_directory=True)
        assert {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in role_files} == role_before
    if case.startswith("implementation-"):
        source = project / "phase2/stage2/synth"
    if case == "raw-missing-rename":
        (project / "phase2/stage1/rtl/SOURCE_MANIFEST.json").write_text(
            json.dumps({"reused_ip": True, "renamed_interfaces": []}))
    elif case in {"raw-wrong-spec-width", "raw-wrong-spec-clock"}:
        content = json.loads(spec.read_text())
        for key in ("ports", "top_ports", "top_module_pins"):
            for port in content[key]:
                if port["name"] == ("clk" if case.endswith("clock") else "o_memory_wdata"):
                    port["width"] = 4
        spec.write_text(json.dumps(content))
    elif case == "raw-forged-declaration":
        (project / "plugin_output/declaration.json").write_text(
            json.dumps({"top_module": "unselected_top", "memory_interface_protocol": "split_read_write"}))
    args = ["--rtl-dir", str(source)]
    if case == "raw-positional-directory":
        args = [str(source)]
    elif case == "raw-positional-file":
        args = [str(source / "core.v")]
    if case.startswith("toolports-") or case == "implementation-good":
        # Author-controlled elaboration input shape, never an EDA measurement.
        ports = {name: {"direction": "input" if name in {"clk", "rst"} else "output",
                        "bits": list(range(width))}
                 for name, width in [("clk", 1), ("rst", 1), ("o_status", 1),
                                     ("o_memory_wdata", 2), ("o_memory_waddr", 1),
                                     ("o_memory_wen", 1)]}
        if case == "toolports-wrong-width":
            ports["o_memory_wdata"]["bits"] = [1, 2, 3]
        elif case == "toolports-wrong-clock":
            ports["clk"]["bits"] = [1, 2]
        elif case == "toolports-missing-selected-port":
            del ports["o_memory_wdata"]
        metadata = project / "controlled-tool-ports.json"
        metadata.write_text(json.dumps({"modules": {
            "absent_top" if case == "toolports-missing-top" else "core": {"ports": ports}}}))
        args += ["--tool-ports", str(metadata)]
    before = {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in project.rglob("*") if p.is_file()}
    subject = Path(os.environ.get("VIBEIC_CONFORMANCE_SUBJECT", PROG.parent))
    report = tmp_path / "scope-findings.json"
    cli = subprocess.run([sys.executable, str(subject / "spec_conformance_check.py"),
                          "--spec", str(spec), "--top", "core", *args,
                          "--json", str(report)], capture_output=True, text=True)
    findings = json.loads(report.read_text()) if report.is_file() else []
    (tmp_path / "scope-consumer.receipt.json").write_text(json.dumps({
        "case": case, "argv": cli.args, "natural_rc": cli.returncode,
        "stdout": cli.stdout, "stderr": cli.stderr, "findings": findings,
        "source_input_hashes": before,
    }, indent=2) + "\n")
    after = {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in project.rglob("*") if p.is_file()}
    assert after == before
    return cli, findings


import pytest


@pytest.mark.parametrize("case", _LOGICAL_SCOPE_CASES)
def test_selected_raw_scope_is_independent_of_future_synthesis(tmp_path, case):
    cli, findings = _run_selected_source_scope(tmp_path, case)
    accepted = cli.returncode == 0
    positive = case in {"raw-rtl-dir", "raw-positional-directory", "raw-positional-file", "toolports-good"}
    if positive:
        assert accepted is True, cli.stdout + cli.stderr
        assert [f for f in findings if f["severity"] == "ERROR"] == []
    elif case == "toolports-missing-top":
        assert cli.returncode == 2
        assert "NOT_MEASURED" in cli.stderr
    else:
        assert cli.returncode == 1, cli.stdout + cli.stderr
        assert any(f["severity"] == "ERROR" for f in findings)
        if case.startswith("implementation-") or case.endswith("pivot"):
            assert any(f["rule"] == "selected-interface-binding-invalid"
                       and "LL_SYNTH_HANDOFF_INVALID" in f["message"] for f in findings)
        else:
            assert all("LL_SYNTH_HANDOFF_INVALID" not in f["message"] for f in findings)
            expected_rule = {
                "toolports-wrong-width": "port-rename-width-mismatch",
                "toolports-wrong-clock": "port-width-mismatch",
                "toolports-missing-selected-port": "port-rename-missing-rtl-port",
                "raw-missing-rename": "port-missing",
                "raw-wrong-spec-width": "port-width-mismatch",
                "raw-wrong-spec-clock": "port-width-mismatch",
                "raw-forged-declaration": "selected-interface-binding-invalid",
            }[case]
            assert any(f["rule"] == expected_rule for f in findings)
