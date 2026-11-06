"""Run produced full-stack HDL scenarios through the existing Icarus helper."""
import json


def execute(project, directory, tool):
    import full_stack_functional_tb as native
    from flow_native_adapters import Commands, inputs, simulation_sources, testbenches
    from verilator_coverage_measure import _tb_top_module

    commands = Commands(directory)
    try:
        files, top = inputs(project, tool)
    except FileNotFoundError as exc:
        return commands.result(detail=str(exc))
    root = project / "phase2/stage1/sim_full_stack"
    benches = [path for path in testbenches(project, tool)
               if path.suffix in {".v", ".sv"} and (tool.get("testbenches") or path.is_relative_to(root))]
    if not benches:
        return commands.result(detail="No produced full-stack HDL scenario testbenches.")
    files, includes = simulation_sources(project, files, top, benches)

    def dispatch(argv, run_dir, container, name, timeout):
        process = commands.run(argv, cwd=run_dir)
        if process is None:
            raise FileNotFoundError(name)
        return process.returncode, process.stdout + process.stderr

    cases, steps = [], []
    for index, bench in enumerate(benches):
        try:
            case = native._run_case(_tb_top_module(bench), bench, files, directory / str(index),
                                    dispatch, None, project, include_dirs=tuple(includes))
            code = case.get("run_rc", case.get("build_rc"))
            status = "FAIL" if code or case["state"] == native.FAILED else "PASS" if case["state"] == native.PASSED else "NOT_MEASURED"
            steps.append({"name": bench.name, "ran": True,
                          "exit_code": code, "status": status})
            cases.append({"testbench": str(bench), **case})
        except FileNotFoundError as exc:
            steps.append({"name": str(exc), "ran": False, "exit_code": None, "status": "NOT_MEASURED"})
    metrics = {}
    if len(cases) == len(benches) and all(case["state"] in native.EXECUTED_STATES for case in cases):
        metrics["blocking_system_scenario_failures"] = sum(case["state"] == native.FAILED for case in cases)
        counts = [case.get("checks") or {} for case in cases]
        if all("errors" in count or {"total", "passed"} <= count.keys() for count in counts):
            metrics["boot_workload_protocol_errors"] = sum(count["errors"] if "errors" in count
                else count["total"] - count["passed"] for count in counts)
    report = directory / "system_scenarios.json"
    report.write_text(json.dumps(cases, indent=2) + "\n")
    result = commands.result(metrics, [report], "Native results of the supplied full-stack HDL scenarios only.")
    result["native_steps"] = steps
    return result
