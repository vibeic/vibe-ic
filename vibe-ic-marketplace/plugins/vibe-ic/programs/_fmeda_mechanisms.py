"""Run native codeword-boundary diagnostic injection from engineering inputs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

MANIFEST = "phase2/stage1/fmeda_mechanisms.json"
NATIVE_DIR = "reports/phase2/safety/mechanisms"
_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")


class Refusal(ValueError):
    pass


class NotMeasured(Refusal):
    pass


def load_json(path: Path):
    return json.loads(path.read_text())


def path_in(project: Path, name: str) -> Path:
    path = Path(name)
    if not path.is_absolute():
        path = project / path
    if not path.is_file():
        raise NotMeasured(f"missing source: {path}")
    return path



def _name(value):
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise Refusal(f"unsupported HDL identifier: {value!r}")
    return value


def _embedded(row):
    return "stimulus" in row


def _validate_stimulus(row):
    """A typed reference encoding, never a claim inferred from RTL/prose."""
    stimulus = row["stimulus"]
    k, n = row["data_width"], row["code_width"]
    bits, check = stimulus["data_bits"], stimulus["check_bit"]
    if (row["kind"] != "parity" or stimulus["encoding"] not in ("even_parity", "odd_parity") or
            n != k + 1 or not isinstance(bits, list) or len(bits) != k or
            any(type(bit) is not int for bit in bits) or type(check) is not int or
            sorted([*bits, check]) != list(range(n))):
        raise Refusal("unsupported parity stimulus or incomplete/duplicate codeword bits")
    checker = row["checker"]
    if checker["corrected_output"] is not None:
        raise Refusal("embedded parity stimulus measures detection only, not correction")
    constants = checker["constant_inputs"]
    if not isinstance(constants, dict):
        raise Refusal("expected typed constant input bindings")
    for name, value in constants.items():
        _name(name)
        width, number = value["width"], value["value"]
        if (name in (checker["input"], checker["detect"]) or
                type(width) is not int or not 1 <= width <= 4096 or
                type(number) is not int or not 0 <= number < (1 << width)):
            raise Refusal("invalid constant input width/value or conflicting role")


def declaration(project: Path):
    from _specrtl_common import rtl_source_files
    from p0_tool_frontend_check import _top

    project = project.resolve()
    doc = load_json(path_in(project, MANIFEST))
    doc["top_module"] = _name(doc.get("top_module") or _top(project))
    files = doc.get("rtl_files") or [str(path.relative_to(project)) for path in
        rtl_source_files(project, exts=("*.v", "*.sv", "*.vh", "*.svh"))]
    doc["rtl_files"] = [{"path": row if isinstance(row, str) else row["path"]} for row in files]
    if not doc["rtl_files"] or not doc.get("mechanisms"):
        raise NotMeasured("RTL sources or engineering mechanism wiring are missing")
    for row in doc["rtl_files"]:
        path_in(project, row["path"])
    for row in doc["mechanisms"]:
        if row["kind"] not in ("ecc", "parity", "lockstep"):
            raise Refusal("unsupported diagnostic mechanism kind")
        for width in (row["data_width"], row["code_width"]):
            if type(width) is not int or width <= 0:
                raise Refusal("non-positive diagnostic port width")
        if _embedded(row):
            _validate_stimulus(row)
    return doc



def _read_order(project: Path, doc: dict):
    from testbench_gen import package_first_order
    files = [project / r["path"] for r in doc["rtl_files"]
             if Path(r["path"]).suffix in (".v", ".sv")]
    return [str(p.relative_to(project)) for p in package_first_order(files)]


def native_script(project: Path, doc: dict) -> str:
    order = _read_order(project, doc)
    paths = [str(project / p) for p in order]
    dirs = sorted({str((project / r["path"]).parent) for r in doc["rtl_files"]})
    if any(not re.fullmatch(r"[A-Za-z0-9_/.-]+", p) for p in paths + dirs):
        raise Refusal("unsupported native command path escaping")
    top = doc["top_module"]
    return ("read_slang --keep-hierarchy --single-unit --top " + top + " " +
            " ".join("-I " + d for d in dirs) + " " + " ".join(paths) +
            f"; hierarchy -check -top {top}; proc; write_json " +
            str(project / NATIVE_DIR / "hierarchy.json"))


def elaborate(project: Path, doc: dict) -> dict:
    root = project / NATIVE_DIR
    root.mkdir(parents=True, exist_ok=True)
    out, log = root / "hierarchy.json", root / "hierarchy.log"
    out.unlink(missing_ok=True)
    argv = ["yosys", "-Q", "-T", "-p", native_script(project, doc)]
    if not shutil.which("yosys"):
        import fmeda_fault_injection_coverage as fi
        import _docker_memory as memory
        try:
            image = fi._local_docker_image()
        except RuntimeError:
            image = None
        if not image:
            raise NotMeasured("native Yosys unavailable and no local tool image")
        argv = ["docker", "run", "--rm", "--network", "none", "--cpus", "8",
                *memory.docker_memory_flags(), "-u", f"{os.getuid()}:{os.getgid()}",
                "-v", f"{project}:{project}", "--entrypoint", "yosys", image, *argv[1:]]
    try:
        result = subprocess.run(argv, cwd=project, capture_output=True, text=True)
    except OSError as exc:
        raise NotMeasured(f"native hierarchy unavailable: {exc}") from exc
    log.write_text(result.stdout + result.stderr)
    if result.returncode:
        raise Refusal(f"native hierarchy failed rc={result.returncode}; {log}")
    if not out.is_file():
        raise NotMeasured(f"native Yosys left no hierarchy report; {log}")
    validate_hierarchy(doc, load_json(out), project)
    return {"exit_code": result.returncode, "reports": [str(out), str(log)]}



def _parameterized_declarations(project: Path, doc: dict):
    """Source syntax only excludes unsupported specialization; never proves it.

    Slang's lowered JSON erases effective parameter values. The standalone FI
    builder instantiates a declaration with defaults, so even equal port widths
    cannot establish equivalence to an overridden reachable instance. Until an
    effective-parameter ABI exists, parameterized mechanism subtrees refuse.
    Macro/directive tokens in the selected declaration also refuse: their
    expansion can introduce a body parameter invisible to raw module regions.
    Unrelated parameterized modules remain outside this selected boundary.
    """
    from module_port_audit import lexical_mask, module_regions
    definitions = {}
    for row in doc["rtl_files"]:
        source = path_in(project, row["path"]).read_text()
        issues = []
        mask = lexical_mask(source, attributes=True)
        for name, start, body, end in module_regions(source, issues):
            if name in definitions:
                raise Refusal("ambiguous source module declaration: " + name)
            definitions[name] = ("#" in mask[start:body] or
                                 bool(re.search(r"\bparameter\b", mask[body:end])) or
                                 bool(re.search(r"`[A-Za-z_]", mask[start:end])))
        if issues:
            raise Refusal("unsupported module declaration discovery: " + "; ".join(issues))
    return definitions


def validate_hierarchy(doc: dict, native: dict, project: Path):
    from _cdc_netlist import FLOP_TYPES
    declarations = _parameterized_declarations(project, doc)
    modules = native.get("modules", {})
    top = doc["top_module"]
    if top not in modules or not modules[top].get("attributes", {}).get("top"):
        raise Refusal("native selected top is absent")
    for row in doc["mechanisms"]:
        k, n = row["data_width"], row["code_width"]
        for role in (("checker",) if _embedded(row) else ("encoder", "checker")):
            part = row[role]
            module_type = top
            for segment in part["instance"].split(".")[1:]:
                cell = modules.get(module_type, {}).get("cells", {}).get(segment)
                if not isinstance(cell, dict) or cell.get("type") not in modules:
                    raise Refusal(f"unreachable native instance: {part['instance']}")
                module_type = cell["type"]
            # Native slang keep-hierarchy uses declaration$full.instance.path;
            # ordinary Yosys modules retain the declaration name. Other shapes
            # are unsupported, never inferred from a prefix/regex success.
            if module_type not in (part["module"], part["module"] + "$" + part["instance"]):
                raise Refusal(f"native module differs at {part['instance']}: {module_type}")
            module = modules[module_type]
            if module.get("attributes", {}).get("blackbox"):
                raise Refusal("black-box mechanism cannot establish implementation closure")
            pending, seen = [module_type], set()
            while pending:
                name = pending.pop()
                if name in seen:
                    continue
                seen.add(name)
                body = modules[name]
                declaration_name = name.split("$", 1)[0]
                if declaration_name not in declarations:
                    raise Refusal("unsupported native/source module identity: " + name)
                if declarations[declaration_name]:
                    raise Refusal("unsupported parameterized mechanism instance or macro-expanded declaration: " + name)
                if body.get("memories") or body.get("processes"):
                    raise Refusal("stateful/unlowered mechanism is outside combinational contract")
                for cell in body.get("cells", {}).values():
                    typ = cell.get("type", "")
                    if (typ in FLOP_TYPES or typ.startswith(("$dlatch", "$mem", "$_DFF", "$_SDFF", "$_DLATCH")) or
                            typ in ("$ff", "$sr")):
                        raise Refusal("stateful mechanism is outside combinational contract")
                    if typ in modules:
                        if modules[typ].get("attributes", {}).get("blackbox"):
                            raise Refusal("black-box mechanism dependency")
                        pending.append(typ)
            expected = {part["input"]: ("input", k if role == "encoder" else n)}
            if role == "encoder":
                expected[part["output"]] = ("output", n)
            else:
                expected[part["detect"]] = ("output", 1)
                if part["corrected_output"]:
                    expected[part["corrected_output"]] = ("output", k)
            actual = {name: (p.get("direction"), len(p.get("bits", [])))
                      for name, p in module.get("ports", {}).items()}
            if _embedded(row):
                expected.update({name: ("input", value["width"])
                                 for name, value in part["constant_inputs"].items()})
                actual_inputs = {name: value for name, value in actual.items() if value[0] == "input"}
                expected_inputs = {name: value for name, value in expected.items() if value[0] == "input"}
                # Other DUT outputs are not correction evidence. All inputs
                # must be bound; the detector must be the actual one-bit output.
                valid = (actual_inputs == expected_inputs and
                         actual.get(part["detect"]) == ("output", 1) and
                         all(direction in ("input", "output") for direction, _ in actual.values()))
            else:
                valid = actual == expected
            if not valid:
                raise Refusal(f"native ports/widths differ at {part['instance']}: {actual} != {expected}")


def census(stdout: str, spec, max_vectors: int):
    import fmeda_fault_injection_coverage as fi

    golden = fi._GOLDEN_RE.findall(stdout)
    faults = fi._FAULT_RE.findall(stdout)
    if not golden or not faults:
        raise NotMeasured("native simulator left no baseline or injection counts")
    if any(line.startswith(("GOLDEN", "FAULT")) and not
           (fi._GOLDEN_RE.fullmatch(line) or fi._FAULT_RE.fullmatch(line))
           for line in stdout.splitlines()):
        raise Refusal("native simulation reported unknown measurement values")
    correction = spec.dec_out is not None
    matches = [g[2] for g in golden] + [f[2] for f in faults]
    if any(match not in (("0", "1") if correction else ("NA",)) for match in matches):
        raise Refusal("native correction result disagrees with the mechanism's correction mode")
    results = fi.parse_injection_results(stdout, correction=correction)
    rows = [{"id": row.fault_id, "detect": row.detect, "match": row.match,
             "covered": row.covered} for row in results.injections]
    baseline = [{"data": int(data), "detect": detect == "1",
                 "match": None if match == "NA" else match == "1",
                 "code_known": known == "1" if known else None}
                for data, detect, match, known in golden]
    return results, baseline, rows



def spec_for(row: dict, rtl_files: list):
    import fmeda_fault_injection_coverage as fi
    enc, chk = row.get("encoder", {}), row["checker"]
    return fi.MechanismSpec(row["kind"], enc.get("module"), enc.get("input", ""), enc.get("output", ""),
                            chk["module"], chk["input"], chk["corrected_output"], chk["detect"],
                            row["data_width"], row["code_width"], rtl_files,
                            source="project_engineering_declaration",
                            stimulus=row.get("stimulus"),
                            checker_constants=chk.get("constant_inputs", {}))


def measure(project: Path, args):
    import fmeda_fault_injection_coverage as fi

    doc = declaration(project)
    native = elaborate(project, doc)
    order = _read_order(project, doc)
    floor = fi.asil_floor(args.asil, args.min_dc)
    reports = []
    for index, row in enumerate(doc["mechanisms"]):
        spec = spec_for(row, order)
        tb_rel = f"phase2/stage2/safety/{index}/fmeda_fi_tb.v"
        tb = project / tb_rel
        tb.parent.mkdir(parents=True, exist_ok=True)
        tb.write_text(fi.build_ecc_injection_tb(spec, args.max_vectors,
                                               detection_only=spec.dec_out is None))
        code, stdout, stderr = fi.run_injection_iverilog(project, order, tb_rel)
        log_rel = f"{NATIVE_DIR}/{index}.log"
        (project / log_rel).write_text(stdout + "\n" + stderr)
        if code == 127:
            raise NotMeasured(f"native injection tool unavailable; {log_rel}")
        if code:
            raise Refusal(f"native injection failed rc={code}; {log_rel}")
        results, baseline, faults = census(stdout, spec, args.max_vectors)
        report = fi.build_report(spec, results, args.asil, floor)
        report.update(id=row.get("id", str(index)), baseline=baseline, fault_list=faults,
            fault_list_truncated=False, max_vectors=args.max_vectors,
            correction_applicable=spec.dec_out is not None,
            raw_evidence={"path": log_rel, "injection_exit_code": code},
            detection_criterion=("detect_flag_asserted OR corrected_output_matches"
                                 if spec.dec_out else "detect_flag_asserted"))
        reports.append(report)
    passed = all(report["ge_floor"] for report in reports)
    return (0 if passed else 1), {"program": "fmeda_fault_injection_coverage",
        "applicable": True, "measured": True, "asil": args.asil, "dc_floor_pct": floor,
        "campaign": {"max_vectors": args.max_vectors,
                     "fault_model": "single-bit flip at the declared codeword boundary"},
        "native_hierarchy": native, "mechanisms": reports,
        "verdict": "PASS" if passed else "FAIL", "ge_floor": passed,
        "reason": "Native baseline and per-mechanism ASIL/DC results",
        "scope": "Codeword-boundary simulation; whole required-fault population and latency are unmeasured."}



def consume(project: Path | None, report: dict, asil, min_dc):
    import fmeda_fault_injection_coverage as fi

    asil = (asil if asil is not None else "D").strip().upper()
    if asil not in fi.ASIL_DC_FLOOR:
        return {"gate": "fmeda_coverage_check", "passed": False, "verdict": "FAIL",
                "reason": f"Unknown ASIL: {asil}"}
    floor = fi.asil_floor(asil, min_dc)
    rows = report.get("mechanisms") or [report]
    measured = report.get("measured", True) and all(
        row.get("detected_faults") is not None and row.get("injected_faults", 0) > 0
        for row in rows)
    if not measured:
        verdict = "FAIL" if report.get("verdict") == "FAIL" else "NOT_MEASURED"
        return {"gate": "fmeda_coverage_check", "passed": False, "verdict": verdict,
                "reason": report.get("reason", "No native diagnostic coverage measurement")}
    results = []
    for index, row in enumerate(rows):
        dc = fi.compute_dc(row["detected_faults"], row["injected_faults"])
        passed, reason = fi.dc_verdict(dc, floor)
        valid = row.get("baseline_valid", False)
        results.append({"id": row.get("id", str(index)), "passed": valid and passed,
            "injected_faults": row["injected_faults"], "detected_faults": row["detected_faults"],
            "recomputed_dc_pct": round(dc, 4), "baseline_valid": valid,
            "reason": reason if valid else "invalid native fault-free baseline"})
    passed = all(row["passed"] for row in results)
    output = {"gate": "fmeda_coverage_check", "passed": passed,
              "asil": asil, "dc_floor_pct": floor, "verdict": "PASS" if passed else "FAIL",
              "mechanisms": results, "reason": "Native measurements against the requested ASIL/DC floor"}
    if len(results) == 1:
        output.update({key: results[0][key] for key in ("injected_faults", "detected_faults",
                       "recomputed_dc_pct", "baseline_valid")})
    return output
