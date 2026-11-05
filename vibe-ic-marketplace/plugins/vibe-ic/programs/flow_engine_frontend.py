#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


def phase_main(argv=None, *, scope="all"):
    """Parse the public interface shared by all phase entries."""
    parser = argparse.ArgumentParser(description="Run the Router-selected step table.")
    parser.add_argument("project", type=Path)
    parser.add_argument("--route", choices=("ic", "ip"))
    parser.add_argument("--delivery-target", choices=("rtl", "ip_soft", "ip_model", "ip_hardmacro", "shippable_gds", "foundry_handoff"))
    parser.add_argument("--entry-step")
    parser.add_argument("--exit-step")
    parser.add_argument("--rtl-input", choices=("structured", "original"), default="structured")
    parser.add_argument("--pdk", default="auto")
    parser.add_argument("--ic-name", default="UNNAMED_CHIP")
    parser.add_argument("--mode", choices=("auto", "docs", "prompt"), default="docs")
    parser.add_argument("--execution-mode", choices=("default",), default="default")
    parser.add_argument("--skip-phase2", action="store_true")
    parser.add_argument("--skip-phase3", action="store_true")
    parser.add_argument("--skip-phase1", action="store_true")
    parser.add_argument("--skip-analog", action="store_true")
    parser.add_argument("--skip-hardware", action="store_true")
    parser.add_argument("--no-dashboard", action="store_true")
    parser.add_argument("--top-name", default="chip_top")
    parser.add_argument("--container")
    parser.add_argument("--from", dest="from_name")
    parser.add_argument("--to", dest="to_name")
    args = parser.parse_args(argv)
    args.scope = scope
    try:
        return run_public(args)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


def phase1_main(argv=None):
    return phase_main(argv, scope="phase1")


def document_owner(project, route):
    """Extract design documents through the existing document owner."""
    import phase1_one_shot_runner as owner
    project = Path(project).resolve()
    forwarded = ["--pdk", route["pdk"]] if route.get("pdk") else []
    started = time.monotonic()
    code = owner._run_docs_mode(project, route.get("ic_name", "UNNAMED_CHIP"), forwarded)
    status = {0: "PASS", 1: "FAIL"}.get(code, "NOT_MEASURED")
    report = {"project": str(project), "phase": 1, "mode": "docs",
              "verdict": status, "duration_s": time.monotonic() - started,
              "delegated_to": "phase1_doc_one_shot_runner", "delegated_rc": code,
              "steps": [{"name": owner.D1_STEP_NAME, "status": status, "exit_code": code}],
              "expert_review": "PENDING"}
    output = project / "reports/orchestrator/phase1_one_shot.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    return code


def rtl_owner(project, route):
    """Run authoring and lint owners without re-entering the public runner."""
    from types import SimpleNamespace
    import design_one_shot_runner as owner
    project = Path(project).resolve()
    first, last = str(route["entry_step"]), str(route["verify_through"])
    contract = route.get("input_contract", "structured")
    owner._pl.select_rtl_input(project, contract, first, "1" if last == "1" else "2")
    top = route.get("top_name", "chip_top")
    if contract == "original":
        top = owner._phase1_declared_module_name(owner._gather_phase1_plain_spec_text(project).text) or top
    ic_class, evidence = owner.detect_ic_class(project)
    plan = []
    staged = owner.step_reused_ip_consume(project, top)
    if staged is not None:
        plan.append(staged)
    if first in {"1", "D09", "rtl_authoring"}:
        plan.append(owner.step_rtl_gen(project, ic_class))
        plan.append(owner.step_reused_ip_consume(project, top))
        plan.append(owner.step_leaf_typo_aliases(project))
        plan.append(owner.step_reset_clock_variant_aliases(project, top))
    if last not in {"1", "D09", "rtl_authoring"}:
        plan.append(native_lint(project, top))
    args = SimpleNamespace(entry_step=first, exit_step=last)
    return finish_frontend(project, [row for row in plan if row is not None], args, ic_class, evidence)


def owner_main(project, route, kind):
    return document_owner(project, route) if kind == "phase1" else rtl_owner(project, route)


def native_lint(project, top_name=None):
    """Run installed lint tools with the existing diagnostic and hygiene rules."""
    import design_one_shot_runner as owner
    from _rtl_include_hub import silicon_rtl_selection
    import verilator_lint_gate as lint
    project = Path(project).resolve()
    output = project / "reports/phase2/lint"
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    files = list(silicon_rtl_selection(owner._pl.rtl_dir(project)))
    metrics, outputs, runs = {}, [], []
    status, detail, code = "NOT_MEASURED", "No RTL input for native lint.", None
    top = owner._v661_resolve_dut_module(project, top_name or "", None) if files else None
    if files and top:
        support = [p for p in owner._pl.rtl_dir(project).rglob("*")
                   if p.is_file() and p.suffix.lower() in (".v", ".sv", ".vh", ".svh", ".h")]
        commands = [
            ("verilator", ["verilator", "--lint-only", "--timing", "--Wall", "-Wno-fatal",
                           "--top-module", top,
                           *["-I" + str(p) for p in sorted({p.parent for p in support})],
                           *map(str, files)], output / "native-verilator.log"),
            ("rtl_hygiene", [sys.executable, str(Path(__file__).with_name("rtl_hygiene_lint.py")),
                             *map(str, files), "--top", top, "--severity", "ERROR",
                             "--json", str(output / "rtl_hygiene.json")], output / "native-hygiene.log"),
            ("rom_init", [sys.executable, str(Path(__file__).with_name("rom_init_lint.py")),
                          *map(str, files), "--json", str(output / "rom_init_lint.json")],
                         output / "native-rom-init.log"),
        ]
        for name, command, log in commands:
            if shutil.which(command[0]) is None:
                runs.append({"name": name, "ran": False, "exit_code": None,
                             "status": "NOT_MEASURED", "tool_seconds": 0.0})
                continue
            beginning = time.monotonic()
            result = subprocess.run(command, cwd=project, capture_output=True, text=True, check=False)
            text = result.stdout + result.stderr
            log.write_text(text)
            outputs.append(str(log))
            runs.append({"name": name, "ran": True, "exit_code": result.returncode,
                         "status": "PASS" if result.returncode == 0 else "FAIL",
                         "tool_seconds": time.monotonic() - beginning if name == "verilator" else 0.0,
                         "program_seconds": time.monotonic() - beginning if name != "verilator" else 0.0})
            if name == "verilator":
                code = result.returncode
                parsed = lint.parse_transcript(text, calibrate=False)
                diagnostics = parsed["diagnostics"]
                metrics.update({
                    "design__lint_error__count": parsed["exiting_errors"] if parsed["exiting_errors"] is not None
                        else sum(item["severity"] == "ERROR" for item in diagnostics),
                    "design__lint_warning__count": sum(item["severity"] == "WARNING" for item in diagnostics),
                    "design__inferred_latch__count": sum(item["code"] == "LATCH" for item in diagnostics),
                    "design__lint_timing_construct__count": sum(item["code"] == "NEEDTIMINGOPT" for item in diagnostics),
                    "blocking_lint_diagnostics": len(lint.blocking(diagnostics, map(str, support))),
                })
                if metrics["blocking_lint_diagnostics"]:
                    runs[-1]["status"] = "FAIL"
            else:
                findings_path = output / ("rtl_hygiene.json" if name == "rtl_hygiene" else "rom_init_lint.json")
                if findings_path.is_file():
                    outputs.append(str(findings_path))
                    findings = json.loads(findings_path.read_text())
                    if name == "rtl_hygiene":
                        metrics["blocking_hygiene_findings"] = sum(
                            item.get("block_eligible", True) and item["severity"] in ("ERROR", "WARN")
                            for item in findings)
                        if metrics["blocking_hygiene_findings"]:
                            runs[-1]["status"] = "FAIL"
                else:
                    runs[-1]["status"] = "NOT_MEASURED"
        status = ("FAIL" if any(item["status"] == "FAIL" for item in runs) else
                  "NOT_MEASURED" if any(item["status"] == "NOT_MEASURED" for item in runs) else "PASS")
        detail = "Installed Verilator, existing hygiene rules and ROM initialization checker."
    elif files:
        detail = "Native lint cannot resolve the selected RTL top."
    report_path = output / "native_lint.json"
    report = {"status": status, "metrics": metrics, "tools": runs,
              "detail": detail, "top": top, "files": list(map(str, files))}
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return owner.StepResult("rtl_validate", status, time.monotonic() - started, detail,
        [*outputs, str(report_path)], extras={"exit_code": code, "native_lint": str(report_path),
            "metrics": metrics, "tool_seconds": sum(item["tool_seconds"] for item in runs),
            "native_steps": runs, "input_contract": owner._pl.rtl_input(project)},
        reason_class="input_absent" if not files else "inconclusive" if status == "NOT_MEASURED" else "")


def finish_frontend(project, plan, args, ic_class, evidence):
    statuses = {row.status for row in plan}
    status = ("FAIL" if "FAIL" in statuses else "NOT_MEASURED" if "NOT_MEASURED" in statuses
              else "PASS_WITH_WAIVERS" if "PASS_WITH_WAIVERS" in statuses else "PASS")
    summary = {"project": str(project), "ic_class": ic_class,
               "ic_class_evidence": evidence, "steps": [asdict(row) for row in plan],
               "verdict": status, "expert_review": "PENDING",
               "declared_window": {"entry_step": args.entry_step, "exit_step": args.exit_step}}
    path = Path(project) / "reports/orchestrator/phase2_one_shot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Owner tools {status}: {path}", flush=True)
    return 0 if status in ("PASS", "PASS_WITH_WAIVERS") else 1 if status == "FAIL" else 2


class OwnerSession:
    """One selected owner invocation shared by all its native result readers."""

    def __init__(self, project, route, force=False, table=None):
        self.project, self.route = Path(project).resolve(), route
        self.table = table
        self.force = force
        self.executed = False
        self.phase1_executed = False
        self.log = None
        self.reused_rtl = []
        self.reused_authoring = {}

    def table_steps(self):
        if self.table is None:
            self.table = json.loads((Path(__file__).parents[1] / "flow/steps.json").read_text())
        return self.table["steps"]

    def bounded_owner_rows(self):
        rows = self.table_steps()
        def addresses(row):
            legacy = row.get("legacy_id", {})
            return {row.get("name"), legacy.get("registry"), *legacy.get("native", [])}
        closed = set(self.route.get("verify_closed_steps", []))
        if closed:
            selected = [row for row in rows if closed.intersection(addresses(row))]
        else:
            first = next(i for i, row in enumerate(rows) if str(self.route["entry_step"]) in addresses(row))
            last = next(i for i, row in enumerate(rows) if str(self.route["verify_through"]) in addresses(row))
            selected = rows[first:last + 1]
        return [row for row in selected if row["tool"].get("function") == "step_rtl_gen"
                or "Verilator.Lint" in row["tool"].get("steps", [])]

    def _command(self, kind, route=None):
        code = ("import json,sys; from pathlib import Path; "
                "sys.path.insert(0, sys.argv[1]); "
                "from flow_engine_frontend import owner_main; "
                "raise SystemExit(owner_main(Path(sys.argv[2]), json.loads(sys.argv[3]), sys.argv[4]))")
        return [sys.executable, "-c", code, str(Path(__file__).parent),
                str(self.project), json.dumps(route or self.route), kind]

    def result(self, directory, kind, *, rerun=False):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        rerun = rerun or self.force
        name = "phase1_one_shot.json" if kind == "phase1" else "phase2_one_shot.json"
        path = self.project / "reports/orchestrator" / name
        bounded = self.route["delivery_target"] == "rtl"
        if bounded and kind == "phase1":
            source = directory / "router_selection.json"
            source.write_text(json.dumps(self.route, indent=2) + "\n")
            return {"ran": True, "exit_code": 0, "metrics": {}, "reports": [str(source)],
                    "tool_seconds": 0.0, "native_steps": [{"name": "router_selection", "ran": True,
                        "exit_code": 0, "status": "PASS", "reused": True,
                        "source": "task_nature_route.route_decision_receipt supplied output"}],
                    "detail": "C7 reuse of the unchanged Router selection for bounded requirements; no physical document extraction."}
        command = None
        if kind == "phase1" and not self.phase1_executed and (rerun or not path.is_file()):
            command = self._command("phase1")
            self.phase1_executed = True
        elif kind != "phase1" and not self.executed and (bounded or rerun or not path.is_file()):
            if bounded:
                owner_rows = self.bounded_owner_rows()
                from _rtl_include_hub import silicon_rtl_selection
                produced = list(silicon_rtl_selection(self.project / "phase2/stage1/rtl"))
                if produced:
                    self.reused_rtl = produced
                    self.reused_authoring = json.loads(path.read_text()) if path.is_file() else {}
                    owner_rows = [row for row in owner_rows if row["tool"].get("function") != "step_rtl_gen"]
                first = owner_rows[0]["legacy_id"]["native"][0] if owner_rows else None
                last = owner_rows[-1]["legacy_id"]["native"][0] if owner_rows else None
            else:
                author = next(row for row in self.table_steps() if row["tool"].get("function") == "step_rtl_gen")
                first = last = author["legacy_id"]["native"][0]
            command = self._command("rtl", {**self.route, "entry_step": first, "verify_through": last}) if first is not None else None
            self.executed = True
        if command is not None:
            path.unlink(missing_ok=True)
            if kind != "phase1":
                (self.project / "reports/phase2/lint/native_lint.json").unlink(missing_ok=True)
            self.log = directory / "owner.log"
            with tempfile.TemporaryFile() as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                    cwd=directory, check=False)
                log.seek(0)
                with self.log.open("wb") as destination:
                    shutil.copyfileobj(log, destination)
        report = json.loads(path.read_text()) if path.is_file() else {}
        rows = report.get("steps", [])
        if kind == "phase1":
            own = rows
        elif kind in ("rtl", "rtl_gen"):
            author_rows = self.reused_authoring.get("steps", []) if self.reused_rtl else rows
            own = [row for row in author_rows if row["name"] == "rtl_gen"]
        elif kind == "rtl_validate":
            own = [row for row in rows if row["name"] in ("rtl_validate", "rtl_lint_tool", "determinism_gates")]
        else:
            own = [row for row in rows if row["name"] == kind]
        lint_path = self.project / "reports/phase2/lint/native_lint.json"
        measured = json.loads(lint_path.read_text()) if kind == "rtl_validate" and lint_path.is_file() else {}
        metrics = {key: value for row in own for key, value in row.get("extras", {}).get("metrics", {}).items()}
        metrics.update(measured.get("metrics", {}))
        tools = measured.get("tools", [])
        native = [{"name": row["name"], "ran": row["status"] in ("PASS", "FAIL"),
                   "exit_code": row.get("extras", {}).get("exit_code"), "status": row["status"]}
                  for row in own if row["status"] != "NOT_APPLICABLE"]
        authoring = kind in ("rtl", "rtl_gen")
        if authoring:
            from _rtl_include_hub import silicon_rtl_selection
            produced = list(silicon_rtl_selection(self.project / "phase2/stage1/rtl"))
            native = ([] if self.reused_rtl else
                      [row for row in native if row["status"] not in ("WAIVED", "PASS_WITH_WAIVERS")])
            native.append({"name": "rtl_output", "ran": True, "exit_code": 0 if produced else 1,
                           "status": "PASS" if produced else "FAIL",
                           "detail": ("C7 reused existing canonical RTL; its authoring owner was not rerun."
                                      if self.reused_rtl else "Owner produced RTL.") if produced else "The owner produced no RTL.",
                           **({"reused": True, "source": list(map(str, self.reused_rtl))} if self.reused_rtl else {})})
        metrics.update({row["name"]: row["status"] for row in own})
        sources = [path, *([lint_path] if measured else [])]
        if authoring and self.reused_rtl:
            sources.extend(self.reused_rtl)
            if self.reused_authoring:
                source = directory / "reused_authoring.json"
                source.write_text(json.dumps(self.reused_authoring, indent=2) + "\n")
                sources.append(source)
        for row in own:
            for output in row.get("output_files", []):
                source = Path(output)
                sources.append(source if source.is_absolute() else self.project / source)
        if self.log:
            sources.append(self.log)
        reports = []
        for source in dict.fromkeys(sources):
            if source.is_file():
                destination = directory / source.name
                if source != destination:
                    shutil.copyfile(source, destination)
                reports.append(str(destination))
        return {"ran": bool(own) or authoring, "exit_code": None, "metrics": metrics,
                "reports": reports, "tool_seconds": sum(item["tool_seconds"] for item in tools),
                "native_steps": [*native, *tools],
                "detail": ("C7 reused canonical RTL and retained its original author report; native lint uses the current RTL."
                           if self.reused_rtl else "Existing owner report; native verdicts remain in its steps.")}


def run_owner(project, route, directory, kind, *, rerun=False):
    return OwnerSession(project, route).result(directory, kind, rerun=rerun)


def native_diagnostics(process, argv, project, require_phase2=True):
    name = "phase2_one_shot.json" if require_phase2 else "phase1_one_shot.json"
    path = Path(project) / "reports/orchestrator" / name
    if not path.is_file():
        return {"status": "NOT_MEASURED", "reason": "The native owner produced no report.",
                "argv": argv, "rc": process.rc}
    report = json.loads(path.read_text())
    if not report.get("steps"):
        return {"status": "NOT_MEASURED", "reason": "The native owner reported no tool results.",
                "argv": argv, "rc": process.rc}
    return {"status": "REPORTS_AVAILABLE", "fresh_reports": [name],
            "argv": argv, "rc": process.rc, "native_verdict": report["verdict"]}


def run_public(args):
    """Forward the public entry's selected Router window to the native engine."""
    import flow_engine
    project = args.project.resolve()
    if args.entry_step is not None or args.exit_step is not None:
        if args.entry_step is None or args.exit_step is None:
            raise ValueError("The native entry requires both Router window bounds.")
        route = {"entry_step": args.entry_step, "verify_through": args.exit_step,
                 "input_contract": args.rtl_input,
                 "delivery_target": args.delivery_target or
                    ("ip_hardmacro" if args.route == "ip" else "shippable_gds")}
        if args.rtl_input == "original" and "verify_closed_steps" not in route:
            import route_decision
            dag = route_decision.canonical_dag(input_contract="original")
            joined = route_decision.dependency_closed_join(
                (str(args.entry_step), str(args.exit_step)), dag=dag)
            route["verify_closed_steps"] = joined["closed_steps"]
    else:
        import task_nature_route as router
        text = flow_engine.design_text(project)
        proposal = router.route_task(text)
        target = args.delivery_target
        if target is None and args.route:
            target = "ip_hardmacro" if args.route == "ip" else "shippable_gds"
        if target is None:
            requirements = router.prompt_delivery_requirements(text)
            resolved = router.resolve_prompt_delivery_target(requirements, None)
            if not resolved["ok"]:
                raise ValueError(resolved["reason"])
            target = resolved["target"]
        route = router.route_decision_receipt(
            text, nature=proposal["entry_nature"], delivery_target=target)
    if getattr(args, "pdk", "auto") != "auto":
        route = {**route, "pdk": args.pdk}
    for name, default in (("ic_name", "UNNAMED_CHIP"), ("top_name", "chip_top")):
        if getattr(args, name, default) != default:
            route[name] = getattr(args, name)
    engine_options = {"pdk": args.pdk} if getattr(args, "pdk", "auto") != "auto" else {}
    scope = getattr(args, "scope", "all")
    if (scope == "all" and not any(getattr(args, flag, False)
            for flag in ("skip_phase1", "skip_phase2", "skip_phase3"))):
        options = {"route": route, **engine_options}
        for name in ("from_name", "to_name"):
            if getattr(args, name, None):
                options[name] = getattr(args, name)
        summary = flow_engine.run(project, **options)
        return 1 if summary.get("fail") else 2 if summary.get("not_measured") else 0
    table = flow_engine.read_json(flow_engine.TABLE)
    selected = flow_engine.select_steps(table, route,
        flow_engine.design_features(project, route, table), None, None)
    positions = {row["name"]: i for i, row in enumerate(table["steps"])}
    lower, upper = 0, len(table["steps"]) - 1
    scope = getattr(args, "scope", "all")
    if scope == "phase1":
        upper = positions["requirements_and_delivery_route"]
    if scope in {"phase2", "phase23"} or getattr(args, "skip_phase1", False):
        lower = positions["rtl_authoring"]
    if scope == "phase2" or getattr(args, "skip_phase3", False):
        upper = positions["netlist_handoff"]
    if scope == "phase3" or getattr(args, "skip_phase2", False):
        lower = positions["die_floorplan_and_macros"]
    requested = [row for row in selected if lower <= positions[row["name"]] <= upper]
    if not requested:
        raise ValueError("The selected phase does not intersect the Router window")
    first = getattr(args, "from_name", None) or (requested[0]["name"] if lower else None)
    last = getattr(args, "to_name", None) or (requested[-1]["name"] if upper < len(table["steps"]) - 1 else None)
    options = {"route": route, **engine_options}
    if first:
        options["from_name"] = first
    if last:
        options["to_name"] = last
    summary = flow_engine.run(project, **options)
    return 1 if summary.get("fail") else 2 if summary.get("not_measured") else 0


if __name__ == "__main__":
    sys.exit(phase1_main())
