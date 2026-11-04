"""T91 (mig-rtlver) step 3: the CDC/RDC rules read a Yosys JSON netlist.

Review row 3 keeps the rules (no CDC engine exists; Verilator 5.053 rejects
`--cdc`) and moves their input from regex over RTL text onto the netlist
LibreLane's `Yosys.JsonHeader` writes, where a flop's clock, its reset and
whether a name is a PORT are structural facts.

Every netlist below is REAL yosys output, not hand-written JSON: vibeic-eda
0.3.77 (yosys 0.69+ 4d572059c), the Yosys.JsonHeader passes
(`hierarchy -check -top T -nokeep_prints -nokeep_asserts; rename -top T;
proc; flatten; opt_clean -purge; json`), run on the `.v` beside each `.json`
in `tests/fixtures/cdc_netlist/` and on the calibration structures in
`calibration/cdc_netlist_*.v`.

Each test drives the shipped CLI, so on a tree without the netlist front end
it answers wrongly (argparse refuses `--netlist`, or the switch is ignored and
the regex arm answers) rather than raising inside the test.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROG = Path(__file__).resolve().parents[1]
FIX = PROG / "tests" / "fixtures" / "cdc_netlist"
CAL = PROG / "calibration"
sys.path.insert(0, str(PROG))


def _captured_tool(netlist):
    """Only the native tool execution is substituted, with its captured JSON.

    The production build still enumerates/hashes inputs, validates native
    output and publishes the real binding. This is source-contract evidence,
    not a claim that Yosys ran in this pytest session.
    """
    def run(argv, **kwargs):
        assert argv[0] == "yosys", "only the native Yosys seam is substituted"
        target = Path(argv[-1].rsplit("json -o ", 1)[1])
        target.write_bytes(Path(netlist).read_bytes())
        return subprocess.CompletedProcess(argv, 0, "", "")
    return run


def _produce(project, netlist):
    import _cdc_netlist as cn
    from _specrtl_common import rtl_source_files
    with patch.object(cn.shutil, "which", return_value="/captured/yosys"), \
            patch.object(cn.subprocess, "run", side_effect=_captured_tool(netlist)):
        return cn.build(project, rtl_source_files(project), cn.load(netlist).top)


def _run(gate: str, *args: str) -> tuple[int, dict]:
    out = Path(args[0]) / f"{gate}.json"
    cp = subprocess.run([sys.executable, str(PROG / f"{gate}.py"), *args,
                         "--json", str(out)], capture_output=True, text=True)
    doc = json.loads(out.read_text()) if out.is_file() else {}
    return cp.returncode, doc


def _project(tmp: Path, name: str, rtl: Path, mode: str | None,
             netlist: Path | None) -> Path:
    pj = tmp / name
    (pj / "phase2/stage1/rtl").mkdir(parents=True)
    shutil.copy(rtl, pj / "phase2/stage1/rtl" / rtl.name)
    if mode:
        (pj / "phase3").mkdir()
        (pj / "phase3/librelane_switch.json").write_text(
            json.dumps({"steps": {"3": mode}}))
    if netlist is not None:
        _produce(pj, netlist)
    return pj


def _rules(doc: dict) -> list[str]:
    return sorted({f["rule"] for f in doc.get("findings", [])
                   if f.get("severity") == "ERROR"})


def test_the_netlist_sees_a_crossing_the_regex_arm_misses(tmp_path):
    """A clk_a flop captured by a clk_b flop INSIDE a submodule.

    The regex arm excludes whatever is handed to a submodule (it cannot see
    inside); the flattened netlist can, and the capture is one flop deep.
    """
    pj = _project(tmp_path, "via_sub", FIX / "cdc_via_submodule.v", None, None)
    rc, doc = _run("clock_domain_reg_crossing_check", str(pj),
                   "--front-end", "regex")
    assert (rc, _rules(doc)) == (0, [])      # the regex arm's known blind spot
    rc, doc = _run("clock_domain_reg_crossing_check", str(pj),
                   "--netlist", str(_produce(pj, FIX / "cdc_via_submodule.json")))
    assert (rc, _rules(doc)) == (1, ["CDC_REG_NO_SYNC"])
    assert doc["summary"]["netlist_clock_domains"] == ["clk_a", "clk_b"]


def test_dual_mode_names_the_disagreement(tmp_path):
    pj = _project(tmp_path, "via_sub", FIX / "cdc_via_submodule.v", "dual",
                  FIX / "cdc_via_submodule.json")
    rc, doc = _run("clock_domain_reg_crossing_check", str(pj))
    cmp = doc["summary"]["front_end_comparison"]
    assert rc == 1
    assert (cmp["regex_verdict"], cmp["netlist_verdict"], cmp["agree"]) == \
        ("PASS", "FAIL", False)
    assert cmp["netlist_blocking_rules"] == ["CDC_REG_NO_SYNC"]


def test_a_synchronised_multi_clock_design_passes_on_the_netlist(tmp_path):
    pj = _project(tmp_path, "mc", FIX / "multi_clock_sync.v", "librelane",
                  FIX / "multi_clock_sync.json")
    rc, doc = _run("clock_domain_reg_crossing_check", str(pj))
    assert (rc, _rules(doc)) == (0, [])
    assert doc["summary"]["front_end"] == "netlist"
    assert doc["summary"]["multi_clock_modules_examined"] == 1


def test_a_suffix_named_internal_wire_is_not_a_port_on_the_netlist(tmp_path):
    """#2063 (fix 3341a0d32), kept as a regression on the netlist front end.

    `b_raw` survives `opt_clean -purge` in the logic-driven fixture (it is in
    the netlist's netnames) and is not in its ports; in the alias fixture it
    is purged altogether. Neither may be read as an async input.
    """
    for name in ("internal_raw_logic", "internal_raw_alias"):
        doc = json.loads((FIX / f"{name}.json").read_text())["modules"][name]
        assert "b_raw" not in doc["ports"]
        pj = _project(tmp_path, name, FIX / f"{name}.v", "librelane",
                      FIX / f"{name}.json")
        rc, rep = _run("cdc_async_input_check", str(pj))
        assert (rc, _rules(rep), rep["summary"]["front_end"]) == (0, [], "netlist")
    names = json.loads((FIX / "internal_raw_logic.json").read_text())
    assert "b_raw" in names["modules"]["internal_raw_logic"]["netnames"]


def test_a_real_async_port_named_raw_still_needs_a_synchroniser(tmp_path):
    """The negative control of #2063: port-ness tightens the premise only."""
    for src, js, want in (("cdc_netlist_async_raw_unsync.v", "cdc_netlist_async_positive.json",
                           (1, ["ASYNC_INPUT_NO_SYNC"])),
                          ("cdc_netlist_async_raw_sync.v", "cdc_netlist_async_negative.json",
                           (0, []))):
        pj = _project(tmp_path, js, CAL / src, None, CAL / js)
        rc, doc = _run("cdc_async_input_check", str(pj), "--front-end", "netlist")
        assert (rc, _rules(doc), doc["summary"]["front_end"]) == (*want, "netlist")


def test_reset_cycle_on_the_netlist(tmp_path):
    for js, src, want in (("cdc_netlist_reset_positive.json", "cdc_netlist_reset_circular.v",
                          (1, ["CIRCULAR_RESET_DEPENDENCY"])),
                         ("cdc_netlist_reset_negative.json", "cdc_netlist_reset_sync_ok.v", (0, []))):
        pj = _project(tmp_path, js, CAL / src, None, CAL / js)
        rc, doc = _run("reset_dependency_check", str(pj), "--netlist",
                       str(pj / "reports/phase2/cdc/netlist.json"))
        assert (rc, _rules(doc)) == want


@pytest.mark.parametrize("case,n,edge_count,cyclic_sccs,scc_count", [
    ("ring17", 17, 17, 1, 1),
    ("ring4", 4, 4, 1, 1),
    ("dense5", 5, 20, 1, 1),
    ("selfloop", 1, 1, 1, 1),
    ("disjoint_scc", 4, 4, 2, 2),
    ("broken_ring17", 17, 16, 0, 17),
    ("dag5", 5, 4, 0, 5),
], ids=lambda value: str(value))
def test_native_reset_graph_cycles(tmp_path, case, n, edge_count, cyclic_sccs, scc_count):
    """Issue #3334: fresh native ARST graphs, through the ordinary CLI.

    Requires native Yosys (or the normal build image resolver). No captured
    JSON or graph substitute supplies the verdict. Preserve raw receipts in
    pytest's basetemp for the identical base/candidate/reverse controls.
    """
    import hashlib
    import os
    import _cdc_netlist as cn

    rtl_dir = tmp_path / "phase2/stage1/rtl"
    rtl_dir.mkdir(parents=True)
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": "neutral_reset_top"}))
    text = [f"module neutral_reset_top(input wire clk, ext_rst, "
            f"input wire [{n-1}:0] data_i, output reg [{n-1}:0] q);"]
    for i in range(n):
        if case == "dense5":
            deps = [j for j in range(n) if j != i]
        elif case == "selfloop":
            deps = [i]
        elif case == "disjoint_scc":
            deps = [i ^ 1]
        elif case in ("dag5", "broken_ring17"):
            deps = [i + 1] if i + 1 < n else []
        else:
            deps = [(i + 1) % n]
        rhs = "ext_rst" + "".join(f" | q[{j}]" for j in deps)
        text += [f"wire rst_{i} = {rhs};",
                 f"always @(posedge clk or posedge rst_{i}) "
                 f"if (rst_{i}) q[{i}] <= 1'b0; else q[{i}] <= data_i[{i}];"]
    rtl = rtl_dir / "neutral_reset_top.v"
    rtl.write_text("\n".join(text + ["endmodule"]) + "\n")
    native = cn.build(tmp_path, [rtl], "neutral_reset_top")
    nl = cn.load(native, "neutral_reset_top")
    binding = cn.require_binding(tmp_path, native, nl)
    assert len(nl.flops) == n
    assert all(f.arst is not None and f.srst is None for f in nl.flops)

    # Read-only independent inventory using the existing uncached cone API.
    resets = {nl.root(f.arst) for f in nl.flops}
    reset_of = {f.name: nl.root(f.arst) for f in nl.flops}
    q_of = nl.flop_of_q()
    edges = {r: set() for r in resets}
    for r in resets:
        for bit in nl.cone([r])[0]:
            edges[reset_of[q_of[bit].name]].add(r)
    assert (len(edges), sum(map(len, edges.values()))) == (n, edge_count)
    inventory = {"case": case, "graph": {str(k): sorted(v) for k, v in edges.items()},
                 "rtl_sha256": hashlib.sha256(rtl.read_bytes()).hexdigest(),
                 "netlist_sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
                 "input_fingerprint": binding["input"]["fingerprint"],
                 "producer_pid": os.getpid(),
                 "true_arst_flops": n, "srst_flops": 0}
    (tmp_path / "native_inventory.json").write_text(json.dumps(inventory, indent=2))
    reports = []
    for seed in ("1", "7"):
        output = tmp_path / f"ordinary.{seed}.json"
        argv = [sys.executable, "-B", str(PROG / "reset_dependency_check.py"),
                str(tmp_path), "--front-end", "netlist", "--json", str(output)]
        child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, env={**os.environ, "PYTHONHASHSEED": seed})
        stdout, stderr = child.communicate()
        (tmp_path / f"ordinary.{seed}.stdout").write_text(stdout)
        (tmp_path / f"ordinary.{seed}.stderr").write_text(stderr)
        report = json.loads(output.read_text())
        (tmp_path / f"ordinary.{seed}.receipt.json").write_text(json.dumps(
            {"argv": argv, "pid": child.pid, "rc": child.returncode,
             "hash_seed": seed, "passed": report["passed"],
             "violations": report["summary"]["violations"]}, indent=2))
        reports.append((child.returncode, report))
    expected_rc = int(cyclic_sccs != 0)
    for rc, report in reports:
        # The first assertion observes the existing wrong VALUE for ring17.
        assert rc == expected_rc, report
        assert report["passed"] == (expected_rc == 0)
        assert report["verdict"] == ("FAIL" if expected_rc else "PASS")
        assert _rules(report) == (["CIRCULAR_RESET_DEPENDENCY"] if expected_rc else [])
        assert report["summary"]["violations"] == len(report["findings"]) == cyclic_sccs
        assert all(f["severity"] == "ERROR" for f in report["findings"])
        info = report["summary"]["reset_dependency_analysis"]
        assert info["reporting_policy"] == "one_witness_per_cyclic_scc"
        assert info["cycle_detection_complete"] is True
        assert info["all_cycles_enumerated"] is False
        assert (info["reset_nodes"], info["reset_edges"]) == (n, edge_count)
        assert (info["scc_count"], info["cyclic_scc_count"], info["witness_count"]) == (
            scc_count, cyclic_sccs, cyclic_sccs)
        assert info["scc_nodes_visited"] == 2 * n
        assert info["scc_edges_examined"] == 2 * edge_count
        assert info["witness_edges_examined"] <= edge_count
    assert reports[0] == reports[1]
    rows = cn.reset_dependency_findings(nl)
    assert [r["message"] for r in rows] == [f["message"] for f in reports[0][1]["findings"]]
    for row in rows:
        cycle = row["evidence"]["cycle_bits"]
        assert len(set(cycle)) == len(cycle) > 0
        assert all(b in edges[a] for a, b in zip(cycle, cycle[1:] + cycle[:1]))
        assert row["evidence"]["cycle"] == [cn._LookupSnapshot(nl).bit_label(b) for b in cycle]
    # Reordering the same native cells must not change the ordered witnesses.
    nl.flops.reverse()
    assert cn.reset_dependency_findings(nl) == rows


@pytest.mark.parametrize("case", ["missing", "bad_binding", "unsupported", "vacuous"])
def test_reset_native_refusal_boundaries(tmp_path, case):
    """Reuse the existing reset calibration RTL and ordinary refusal owner."""
    import _cdc_netlist as cn

    if case != "vacuous":
        rtl = tmp_path / "phase2/stage1/rtl" / (
            "unsupported path.sv" if case == "unsupported" else "reset_circular.v")
        rtl.parent.mkdir(parents=True)
        rtl.write_bytes((CAL / "cdc_netlist_reset_circular.v").read_bytes())
        if case == "bad_binding":
            native = cn.build(tmp_path, [rtl], "reset_circular")
            cn.require_binding(tmp_path, native, cn.load(native))
            manifest = tmp_path / cn.NETLIST_MANIFEST_REL
            doc = json.loads(manifest.read_text())
            doc["producer"]["exit_code"] = 1
            manifest.write_text(json.dumps(doc))
        elif case == "unsupported":
            with pytest.raises(cn.Refusal, match="CDC_NETLIST_UNSUPPORTED_PATH") as exc:
                cn.build(tmp_path, [rtl], "reset_circular")
            (tmp_path / "producer_refusal.json").write_text(json.dumps(
                {"code": exc.value.code, "message": str(exc.value)}))
            assert not (tmp_path / cn.NETLIST_MANIFEST_REL).exists()
    output = tmp_path / "ordinary.json"
    argv = [sys.executable, "-B", str(PROG / "reset_dependency_check.py"),
            str(tmp_path), "--front-end", "netlist", "--json", str(output)]
    child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = child.communicate()
    (tmp_path / "ordinary.stdout").write_text(stdout)
    (tmp_path / "ordinary.stderr").write_text(stderr)
    (tmp_path / "ordinary.receipt.json").write_text(json.dumps(
        {"argv": argv, "pid": child.pid, "rc": child.returncode}, indent=2))
    report = json.loads(output.read_text())
    expected = {"missing": (1, ["NETLIST_MISSING"]),
                "bad_binding": (1, ["CDC_NETLIST_UNBOUND"]),
                "unsupported": (1, ["NETLIST_MISSING"]), "vacuous": (2, [])}[case]
    assert (child.returncode, _rules(report)) == expected, report
    assert report["verdict"] == ("VACUOUS_PASS" if case == "vacuous" else "FAIL")
    assert report["summary"]["netlist_read"] is False
    assert "reset_dependency_analysis" not in report["summary"]


def test_a_selected_netlist_front_end_never_falls_back_to_regex(tmp_path):
    """Switch says netlist, no netlist on disk: a blocking refusal, not PASS."""
    for gate in ("cdc_async_input_check", "clock_domain_reg_crossing_check",
                 "reset_dependency_check"):
        pj = _project(tmp_path, gate, FIX / "multi_clock_sync.v", "librelane", None)
        rc, doc = _run(gate, str(pj))
        assert (rc, _rules(doc)) == (1, ["NETLIST_MISSING"]), gate


def test_no_switch_takes_the_netlist_default(tmp_path):
    """R-0929-TOOL-DEFAULT (owner, 2026-09-29): the tool is the default. This
    was `test_no_switch_keeps_the_regex_default` -- with no switch the regex
    arm decided and passed the submodule crossing it cannot see (0, []). The
    netlist front end is now the production default for step 3
    (librelane_contract.PRODUCTION_DEFAULTS), so the same project with its
    netlist and no switch finds the crossing; naming step 3 `direct` still
    selects the regex arm, which is kept (HARVEST-then-delete amendment)."""
    pj = _project(tmp_path, "plain", FIX / "cdc_via_submodule.v", None,
                  FIX / "cdc_via_submodule.json")
    rc, doc = _run("clock_domain_reg_crossing_check", str(pj))
    assert (rc, _rules(doc)) == (1, ["CDC_REG_NO_SYNC"])
    assert doc["summary"]["front_end"] == "netlist"
    pj = _project(tmp_path, "direct", FIX / "cdc_via_submodule.v", "direct",
                  FIX / "cdc_via_submodule.json")
    rc, doc = _run("clock_domain_reg_crossing_check", str(pj))
    assert (rc, _rules(doc)) == (0, [])
    assert "front_end" not in doc["summary"]


def test_the_front_end_runs_the_json_header_passes():
    """The netlist is the one Yosys.JsonHeader writes, pass for pass."""
    import importlib
    sys.path.insert(0, str(PROG))
    cn = importlib.import_module("_cdc_netlist")
    script = cn.yosys_script([Path("/d/a.v")], "top", Path("/d/o.json"))
    assert script.split("; ")[1:] == [
        "hierarchy -check -top top -nokeep_prints -nokeep_asserts",
        "rename -top top", "proc", "flatten", "opt_clean -purge",
        "json -o /d/o.json"]


def test_the_runner_writes_the_netlist_manifest_for_a_multi_clock_design(tmp_path, monkeypatch):
    """Step-3 call site: librelane mode reads domains from CLK pins.

    Only the native subprocess is substituted: it writes captured Yosys JSON
    where Yosys would write it; the production build and binding run.
    """
    sys.path.insert(0, str(PROG))
    import design_one_shot_runner as runner
    import _cdc_netlist as cn

    monkeypatch.setattr(cn.shutil, "which", lambda _tool: "/captured/yosys")
    monkeypatch.setattr(cn.subprocess, "run", _captured_tool(FIX / "multi_clock_sync.json"))
    pj = _project(tmp_path, "mc", FIX / "multi_clock_sync.v", "librelane", None)
    runner.step_emit_phase2_manifests(pj, [], "multi_clock_sync")
    rec = json.loads((pj / "reports/phase2/cdc/netlist_front_end.json").read_text())
    crossing = json.loads((pj / "reports/phase2/cdc/crossing.json").read_text())
    assert (rec["verdict"], rec["clock_domains"], rec["multi_clock_agrees"]) == \
        ("PASS", ["clk_a", "clk_b"], True)
    assert (crossing["verdict"], crossing["front_end"]) == ("SKIPPED-CONDITION", "netlist")
    assert crossing["clocks_found"] == ["clk_a", "clk_b"]


def _role_project(tmp_path, case='sticky', *, header=False, intent_rel='input/docs/control.md'):
    import design_one_shot_runner as runner
    project = tmp_path / case
    rtl = project / 'phase2/stage1/rtl/neutral.sv'
    rtl.parent.mkdir(parents=True)
    bodies = {
        'sticky': "else if(event_i || q) q<=1'b1;",
        'data': 'else q<=event_i | q;',
        'ready': "else if(ready_i) q<=1'b0; else if(event_i && !q) q<=1'b1;",
        'init': "else if(event_i) q<=1'b1;",
        'sync': "else if(q) q<=1'b0; else q<=event_i;",
        'mixed': "else if(event_i || q) q<=1'b1;",
    }
    extra_ports = ',output reg a,b' if case == 'mixed' else ''
    extra = ("always @(posedge clk or negedge b) if(!b) a<=0; else a<=event_i;\n"
             "always @(posedge clk or negedge a) if(!a) b<=0; else b<=event_i;\n") if case == 'mixed' else ''
    body = ("always @(posedge clk or negedge rst_n) if(!rst_n) q<=1'b0; "
            + bodies[case] + '\n' + extra)
    if header:
        (rtl.parent / 'state_body.svh').write_text(body)
        body = '`include "state_body.svh"\n'
    rtl.write_text('module neutral(input wire clk,rst_n,event_i,ready_i,output reg q'
                   + extra_ports + ');\n' + body + 'endmodule\n')
    l9 = project / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
    l9.parent.mkdir(parents=True)
    l9.write_text(json.dumps({'top_module': 'neutral'}))
    switch = project / 'phase3/librelane_switch.json'
    switch.parent.mkdir(parents=True)
    switch.write_text(json.dumps({'steps': {'3': 'librelane'}}))
    docs = project / 'input/docs'
    docs.mkdir(parents=True)
    role = 'synchronous reset' if case == 'sync' else 'functional update'
    intent_path = project / intent_rel
    intent_path.parent.mkdir(parents=True, exist_ok=True)
    prefix = 'control_intent: ' if intent_path.suffix == '.yaml' else ''
    intent_path.write_text(prefix + f'State q uses its constant data branch as a {role}.\n')
    # This is the runner's normal producer, not a mocked native build helper.
    result = runner.step_emit_phase2_manifests(project, [], 'neutral')
    assert result.status == 'PASS'
    return project, rtl


def _official_role_answer(project, role='functional_update', expected_write_rc=0, *,
                          source_rel='phase2/stage1/rtl/neutral.sv', source_line=2,
                          intent_rel='input/docs/control.md'):
    import ai_signed_judgement as expert
    command = [sys.executable, str(PROG / 'ai_signed_judgement.py'), str(project), '--step', '3']
    request_run = subprocess.run(command, capture_output=True, text=True)
    assert request_run.returncode == 0, request_run.stdout + request_run.stderr
    request = json.loads(request_run.stdout)
    rtl = project / source_rel
    source = {'file': source_rel, 'line': source_line,
              'quote': rtl.read_text().splitlines()[source_line - 1]}
    intent_path = project / intent_rel
    intent = ([{'file': intent_rel, 'line': 1,
                'quote': intent_path.read_text().splitlines()[0]}]
              if intent_path.is_file() else [])
    answer = {key: request[key] for key in ('evidence_sha256', 'netlist_sha256')}
    answer['reset_roles'] = [{'candidate': row, 'role': role, 'source_context': [source],
                             'intent': intent, 'rationale': (f"State {row['state']} Q {row['q']} "
                             f"uses selector {row['selector']} at the cited constant-arm branch; "
                             + ('the cited input cannot establish its architectural role.'
                                if role == 'unresolved' else
                                'the cited input describes the intended state update.'))}
                            for row in request['candidates']]
    answer_path = project.parent / (project.name + '-authored-answer.json')
    answer_path.write_text(json.dumps(answer))
    written = subprocess.run(command + ['--answer', str(answer_path), '--signed-by',
                                        'neutral-expert', '--judgement', 'Reviewed cited control intent.'],
                             capture_output=True, text=True)
    assert written.returncode == expected_write_rc, written.stdout + written.stderr
    return expert, request, answer_path


@pytest.mark.parametrize('case', ['sticky', 'data', 'ready', 'init', 'sync'])
def test_native_reset_role_normal_producer_writer_consumer(tmp_path, case):
    import hashlib
    import _cdc_netlist as native
    import design_one_shot_runner as runner
    project, rtl = _role_project(tmp_path, case)
    native_files = [project / rel for rel in (native.NETLIST_REL, native.NETLIST_LOG_REL,
                                             native.NETLIST_MANIFEST_REL)]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in native_files}
    rc, first = _run('reset_dependency_check', str(project), '--front-end', 'netlist')
    if case == 'data':
        assert rc == 0 and not _rules(first)
        return
    assert rc == 1 and _rules(first) == ['RESET_ROLE_UNRESOLVED'], first
    assert first['summary']['reset_dependency_analysis']['cycle_detection_complete'] is False
    expert, request, _answer = _official_role_answer(
        project, 'synchronous_reset' if case == 'sync' else 'functional_update')
    rc, final = _run('reset_dependency_check', str(project), '--front-end', 'netlist')
    assert (rc, _rules(final)) == ((1, ['CIRCULAR_RESET_DEPENDENCY']) if case == 'sync' else (0, [])), final
    assert expert.check(project, '3')[0]
    assert final['summary']['reset_dependency_analysis']['cycle_detection_complete'] is True
    assert expert._requested(project, '3')  # adoption cannot self-release review
    # A normal producer continuation must reuse the current bound native bytes.
    runner.step_emit_phase2_manifests(project, [], 'neutral')
    assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in native_files}
    assert expert.check(project, '3')[0]
    assert native.reset_role_candidates(native.load(project / native.NETLIST_REL)) == request['candidates']


@pytest.mark.parametrize('mutation', ['no_intent', 'source', 'duplicate', 'conflict', 'deleted'])
def test_native_reset_role_authority_refusals(tmp_path, mutation):
    project, rtl = _role_project(tmp_path)
    expert, request, answer_path = _official_role_answer(project)
    receipt_path = project / 'reports/audit/ai_judgements/3.json'
    receipt = json.loads(receipt_path.read_text())
    if mutation == 'source':
        rtl.write_text(rtl.read_text() + '// changed source\n')
    elif mutation == 'deleted':
        receipt_path.unlink()
    else:
        if mutation == 'no_intent':
            receipt['reset_roles'][0]['intent'] = []
        elif mutation == 'duplicate':
            receipt['reset_roles'].append(receipt['reset_roles'][0])
        elif mutation == 'conflict':
            (project / 'input/docs/control.md').write_text('State q uses a synchronous reset.\n')
        receipt_path.write_text(json.dumps(receipt))
    rc, report = _run('reset_dependency_check', str(project), '--front-end', 'netlist')
    assert rc == 1 and report['passed'] is False, report
    assert not expert.check(project, '3')[0]


@pytest.mark.parametrize('intent', ['sticky_english', 'sticky_chinese'])
def test_native_reset_role_reviewed_inference_needs_no_magic_words(tmp_path, intent):
    project, rtl = _role_project(tmp_path)
    words = {
        'sticky_english': 'An event sets the pending flag; it stays set until reset.\n',
        'sticky_chinese': '\u4e8b\u4ef6\u767c\u751f\u6642\u8a2d\u5b9a\u5f85\u8655\u7406\u65d7\u6a19\uff0c\u4e26\u4fdd\u6301\u5230\u91cd\u7f6e\u3002\n',
    }
    (project / 'input/docs/control.md').write_text(words[intent])
    expert, request, _answer = _official_role_answer(project)
    rc, report = _run('reset_dependency_check', str(project), '--front-end', 'netlist')
    assert rc == 0 and not _rules(report), report
    assert expert.check(project, '3')[0]


@pytest.mark.parametrize('intent', ['insufficient', 'contradictory'])
def test_native_reset_role_expert_unresolved_remains_blocking(tmp_path, intent):
    project, rtl = _role_project(tmp_path)
    words = {
        'insufficient': 'The clock is 20 ns; state q exists.\n',
        'contradictory': ('The flag is only reset by the external reset.\n'
                          'The flag is synchronously reset by its own value.\n'),
    }
    (project / 'input/docs/control.md').write_text(words[intent])
    # The expert, rather than a language-specific keyword matcher, owns this
    # semantic refusal. The canonical writer preserves its unresolved answer.
    expert, request, _answer = _official_role_answer(project, role='unresolved')
    receipt = json.loads((project / 'reports/audit/ai_judgements/3.json').read_text())
    assert receipt['reset_roles'][0]['role'] == 'unresolved'
    rc, report = _run('reset_dependency_check', str(project), '--front-end', 'netlist')
    assert rc == 1 and _rules(report) == ['RESET_ROLE_UNRESOLVED'], report
    assert not expert.check(project, '3')[0]


def test_native_reset_cycle_survives_unknown_and_functional_role_adoption(tmp_path):
    project, rtl = _role_project(tmp_path, 'mixed')
    rc, first = _run('reset_dependency_check', str(project), '--front-end', 'netlist')
    assert rc == 1 and _rules(first) == ['CIRCULAR_RESET_DEPENDENCY', 'RESET_ROLE_UNRESOLVED']
    _official_role_answer(project)
    rc, final = _run('reset_dependency_check', str(project), '--front-end', 'netlist')
    assert rc == 1 and _rules(final) == ['CIRCULAR_RESET_DEPENDENCY']


def test_step3_authoring_preserves_existing_signed_subject_bytes(tmp_path):
    import ai_signed_judgement as expert
    import _ai_judgement_fixture as fixture
    project, rtl = _role_project(tmp_path)
    subjects = {
        'phase2/stage1/fallback_skill.md': 'spec-to-rtl',
        'reports/phase2/gates/professional_tb.json': '{"dut_kind":"expert_reference"}',
        'phase2/stage1/sim_professional/expert_reference_tb.py': 'expected = 1',
        'phase2/stage1/formal/formal_authoring_request.json': '{}',
        'phase2/stage1/formal/formal_expert_review.json': '{}',
    }
    for rel, value in subjects.items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    before = {sid: expert.evidence_sha256(project, sid) for sid in ('D1', '1', '4', '5')}
    (project / 'legacy_signed_subject_hashes.json').write_text(json.dumps(before, sort_keys=True))
    for sid in before:
        fixture.sign(project, sid)
        assert expert.check(project, sid)[0]
    _official_role_answer(project)
    assert before == {sid: expert.evidence_sha256(project, sid) for sid in before}
    assert all(expert.check(project, sid)[0] for sid in before)


@pytest.mark.parametrize('source_form', ['header', 'structured', 'legacy'])
def test_native_reset_role_existing_canonical_sources(tmp_path, source_form):
    intent_rel = {'header': 'input/docs/control.md',
                  'structured': 'input/phase1_structured.yaml',
                  'legacy': 'phase1/input_doc/control.txt'}[source_form]
    project, rtl = _role_project(tmp_path, header=source_form == 'header', intent_rel=intent_rel)
    source_rel = ('phase2/stage1/rtl/state_body.svh' if source_form == 'header'
                  else 'phase2/stage1/rtl/neutral.sv')
    expert, request, _answer = _official_role_answer(
        project, source_rel=source_rel, source_line=1 if source_form == 'header' else 2,
        intent_rel=intent_rel)
    assert intent_rel in request['intent_files']
    rc, report = _run('reset_dependency_check', str(project), '--front-end', 'netlist')
    assert rc == 0 and not _rules(report), report
    assert expert.check(project, '3')[0]


def test_native_reset_role_missing_original_input_remains_blocking(tmp_path):
    project, rtl = _role_project(tmp_path)
    (project / 'input/docs/control.md').unlink()
    expert, request, _answer = _official_role_answer(project, role='unresolved')
    assert request['intent_files'] == []
    rc, report = _run('reset_dependency_check', str(project), '--front-end', 'netlist')
    assert rc == 1 and _rules(report) == ['RESET_ROLE_UNRESOLVED'], report
    assert not expert.check(project, '3')[0]
