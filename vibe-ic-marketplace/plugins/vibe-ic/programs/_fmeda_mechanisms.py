"""Validated project-local FMEDA engineering declarations and native evidence.

This finite combinational-port contract measures a codeword boundary model of
reachable implementation modules. It does not inject a physical DUT instance,
establish whole-chip safety, or replace the legacy mechanism classifier.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess

MANIFEST = "phase2/stage1/fmeda_mechanisms.json"
SCHEMA = "vibeic.fmeda-mechanisms.v1"
REPORT_SCHEMA = "vibeic.fmeda-measurements.v1"
NATIVE_DIR = "reports/phase2/safety/mechanisms"
_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")


class Refusal(ValueError):
    pass


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refusal(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path):
    try:
        return json.loads(path.read_text(), object_pairs_hook=_pairs)
    except (OSError, ValueError) as exc:
        raise Refusal(f"cannot read {path.name}: {exc}") from None


def path_in(project: Path, rel: str) -> Path:
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
        raise Refusal("expected a project-relative file path")
    if any(p in (".", "..") for p in rel.split("/")):
        raise Refusal(f"non-canonical path: {rel}")
    path = project / rel
    if any(p.is_symlink() for p in [path, *path.parents] if p != project.parent):
        raise Refusal(f"symlink is not a bound source: {rel}")
    if not path.resolve().is_relative_to(project.resolve()) or not path.is_file():
        raise Refusal(f"missing/escaped source: {rel}")
    return path


def _keys(value, required):
    if not isinstance(value, dict) or set(value) != set(required.split()):
        raise Refusal(f"expected exactly these keys: {required}")


def _name(value):
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise Refusal(f"unsupported HDL identifier: {value!r}")
    return value


def declaration(project: Path):
    """Validate author input against the existing current source/top readers."""
    from _specrtl_common import rtl_source_files, strip_comments
    from p0_tool_frontend_check import _top
    project = project.resolve()
    manifest = path_in(project, MANIFEST)
    doc = load_json(manifest)
    _keys(doc, "schema authority top_module rtl_files mechanisms")
    if (doc["schema"] != SCHEMA or
            doc["authority"] != "AUTHOR_ENGINEERING_DECLARATION"):
        raise Refusal("unsupported declaration schema/authority")
    top = _name(doc["top_module"])
    if not _top(project) or top != _top(project):
        raise Refusal("declared mechanism top differs from current L9 selected top")
    sources = rtl_source_files(project, exts=("*.v", "*.sv", "*.vh", "*.svh"))
    if not sources:
        raise Refusal("no current authored RTL")
    current = []
    for source in sources:
        rel = str(source.relative_to(project))
        source = path_in(project, rel)
        current.append({"path": rel, "sha256": digest(source)})
    supplied = doc["rtl_files"]
    if not isinstance(supplied, list) or not supplied:
        raise Refusal("empty RTL inventory")
    for row in supplied:
        _keys(row, "path sha256")
        path_in(project, row["path"])
        if not isinstance(row["sha256"], str) or not _SHA.fullmatch(row["sha256"]):
            raise Refusal("invalid source SHA256")
    if (len({r["path"] for r in supplied}) != len(supplied) or
            sorted(supplied, key=lambda r: r["path"]) != current):
        raise Refusal("declaration source inventory/hash differs from current authored RTL")
    # A quoted local include may only resolve to this same bound population.
    # Macro-selected/external includes are outside this finite contract.
    population = {p.resolve() for p in sources}
    dirs = sorted({p.parent for p in sources})
    for source in sources:
        for line in strip_comments(source.read_text()).splitlines():
            if re.match(r"\s*`include\b", line):
                match = re.fullmatch(r'\s*`include\s+"([^"\n]+)"\s*', line)
                if not match:
                    raise Refusal("unsupported macro/computed include")
                choices = [source.parent / match[1], *[d / match[1] for d in dirs]]
                selected = next((p for p in choices if p.exists()), None)
                if selected is None or selected.resolve() not in population:
                    raise Refusal("include is outside bound authored RTL inventory")
                path_in(project, str(selected.relative_to(project)))
    mechanisms = doc["mechanisms"]
    if not isinstance(mechanisms, list) or not mechanisms:
        raise Refusal("empty mechanism population")
    ids, sites = set(), set()
    for row in mechanisms:
        _keys(row, "id kind encoder checker data_width code_width")
        _name(row["id"])
        if row["id"] in ids or row["kind"] not in ("ecc", "parity", "lockstep"):
            raise Refusal("duplicate mechanism ID or unsupported kind")
        ids.add(row["id"])
        for width in (row["data_width"], row["code_width"]):
            if type(width) is not int or not 1 <= width <= 4096:
                raise Refusal("unsupported/non-positive port width")
        for key, keys in (("encoder", "module instance input output"),
                          ("checker", "module instance input detect corrected_output")):
            part = row[key]
            _keys(part, keys)
            for field in ("module", "input"):
                _name(part[field])
            if not isinstance(part["instance"], str):
                raise Refusal("missing instance path")
            parts = part["instance"].split(".")
            if len(parts) < 2 or parts[0] != top:
                raise Refusal("instance is outside current selected top")
            for p in parts:
                _name(p)
        _name(row["encoder"]["output"])
        _name(row["checker"]["detect"])
        if row["checker"]["corrected_output"] is not None:
            _name(row["checker"]["corrected_output"])
        site = (row["checker"]["instance"], row["checker"]["input"])
        if site in sites:
            raise Refusal("duplicate protected codeword boundary")
        sites.add(site)
    l9 = []
    for name in ("L9_INTEGRATION_SPEC.json", "L9_INTEGRATION.json"):
        rel = "phase1/generated_docs/" + name
        if (project / rel).exists():
            l9.append({"path": rel, "sha256": digest(path_in(project, rel))})
    binding = {"declaration_sha256": digest(manifest), "rtl_files": current,
               "l9_files": l9, "top_module": top}
    return doc, binding


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


def _memory_ceiling():
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))


def elaborate(project: Path, doc: dict) -> dict:
    """Native hierarchy only, bounded instrument; no flatten/mapping/ABC."""
    root = project / NATIVE_DIR
    root.mkdir(parents=True, exist_ok=True)
    out = root / "hierarchy.json"
    out.unlink(missing_ok=True)
    script = native_script(project, doc)
    argv = ["yosys", "-Q", "-T", "-p", script]
    host = bool(shutil.which("yosys"))
    if not host:
        import fmeda_fault_injection_coverage as fi
        import _docker_memory as memory
        image = fi._local_docker_image()
        if not image:
            raise Refusal("native Yosys unavailable; no local image (no pull/fallback)")
        argv = ["docker", "run", "--rm", "--network", "none", "--cpus", "1",
                *memory.docker_memory_flags({"VIBEIC_DOCKER_MEMORY": "2g"}),
                "-u", f"{os.getuid()}:{os.getgid()}", "-v", f"{project}:{project}",
                "--entrypoint", "yosys", image, *argv[1:]]
    try:
        result = subprocess.run(argv, cwd=project, capture_output=True, text=True,
                                timeout=30, preexec_fn=_memory_ceiling if host else None)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refusal(f"native hierarchy NOT_MEASURED: {exc}") from None
    log = root / "hierarchy.log"
    log.write_text(result.stdout + result.stderr)
    rec = {"argv": argv, "script": script, "exit_code": result.returncode,
           "read_order": _read_order(project, doc), "source_root": str(project),
           "hierarchy_sha256": digest(out) if out.is_file() else None,
           "log_sha256": digest(log), "memory_ceiling_bytes": 2 * 1024**3,
           "wall_limit_s": 30,
           "tool_identity": load_json(out).get("creator") if out.is_file() else None}
    (root / "execution.json").write_text(json.dumps(rec, indent=2) + "\n")
    if result.returncode or not out.is_file():
        raise Refusal(f"native hierarchy refused rc={result.returncode}; {NATIVE_DIR}/hierarchy.log")
    validate_hierarchy(doc, load_json(out), project)
    rec["execution_sha256"] = digest(root / "execution.json")
    return rec


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
        for role in ("encoder", "checker"):
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
            if actual != expected:
                raise Refusal(f"native ports/widths differ at {part['instance']}: {actual} != {expected}")


def require_native(project: Path, doc: dict, rec: dict):
    if not isinstance(rec, dict):
        raise Refusal("missing native hierarchy identity")
    root = project / NATIVE_DIR
    stored = load_json(path_in(project, NATIVE_DIR + "/execution.json"))
    if ({k: v for k, v in rec.items() if k != "execution_sha256"} != stored or
            rec.get("execution_sha256") != digest(root / "execution.json") or
            rec.get("exit_code") != 0):
        raise Refusal("native execution identity/return code differs")
    if (rec.get("source_root") != str(project) or
            rec.get("script") != native_script(project, doc) or
            rec.get("read_order") != _read_order(project, doc)):
        raise Refusal("native source/top/read-order identity differs")
    argv = rec.get("argv", [])
    if (not isinstance(argv, list) or argv[-4:] != ["-Q", "-T", "-p", rec["script"]] or
            not (argv[0] == "yosys" or
                 (argv[:2] == ["docker", "run"] and
                  any(argv[i:i+2] == ["--entrypoint", "yosys"] for i in range(len(argv)))))):
        raise Refusal("native invocation differs from the declared hierarchy producer")
    for name, key in (("hierarchy.json", "hierarchy_sha256"), ("hierarchy.log", "log_sha256")):
        if digest(path_in(project, NATIVE_DIR + "/" + name)) != rec.get(key):
            raise Refusal(f"native {name} changed")
    validate_hierarchy(doc, load_json(root / "hierarchy.json"), project)


def census(stdout: str, spec, max_vectors: int):
    """Strict complete baseline/bit census; NA is a type, not a match."""
    import fmeda_fault_injection_coverage as fi
    if type(max_vectors) is not int or not 1 <= max_vectors <= 4096:
        raise Refusal("invalid bounded stimulus count")
    correction = spec.dec_out is not None
    values = fi._stimulus_values(spec.data_width, max_vectors)
    golden = fi._GOLDEN_RE.findall(stdout)
    faults = fi._FAULT_RE.findall(stdout)
    expected = {f"d{d}_b{i}" for d in values for i in range(spec.code_width)}
    if (len(golden) != len(values) or {int(g[0]) for g in golden} != set(values) or
            len(faults) != len(expected) or {f[0] for f in faults} != expected):
        raise Refusal("incomplete/duplicate baseline or single-bit fault census")
    if any(line.startswith(("GOLDEN", "FAULT")) and not
           (fi._GOLDEN_RE.fullmatch(line) or fi._FAULT_RE.fullmatch(line))
           for line in stdout.splitlines()):
        raise Refusal("malformed/unknown measurement value")
    matches = [g[2] for g in golden] + [f[2] for f in faults]
    if any(m not in (("0", "1") if correction else ("NA",)) for m in matches):
        raise Refusal("measurement correction mode differs from declaration")
    results = fi.parse_injection_results(stdout, correction=correction)
    rows = [{"id": x.fault_id, "detect": x.detect, "match": x.match,
             "covered": x.covered} for x in results.injections]
    baseline = [{"data": int(d), "detect": det == "1",
                 "match": None if mat == "NA" else mat == "1",
                 "code_known": known == "1" if known else None}
                for d, det, mat, known in golden]
    return results, baseline, rows


def spec_for(row: dict, rtl_files: list):
    import fmeda_fault_injection_coverage as fi
    enc, chk = row["encoder"], row["checker"]
    return fi.MechanismSpec(row["kind"], enc["module"], enc["input"], enc["output"],
                            chk["module"], chk["input"], chk["corrected_output"], chk["detect"],
                            row["data_width"], row["code_width"], rtl_files,
                            source="project_engineering_declaration")


def measure(project: Path, args):
    import fmeda_fault_injection_coverage as fi
    if getattr(args, "enc_module", None) or getattr(args, "dec_module", None):
        raise Refusal("project declaration and explicit CLI wiring cannot select different authorities")
    doc, binding = declaration(project)
    native = elaborate(project, doc)
    if declaration(project)[1] != binding:
        raise Refusal("sources changed during native hierarchy production")
    order = _read_order(project, doc)
    floor = fi.asil_floor(args.asil, args.min_dc)
    reports = []
    for row in doc["mechanisms"]:
        spec = spec_for(row, order)
        tb_rel = "phase2/stage2/safety/" + row["id"] + "/fmeda_fi_tb.v"
        tb = project / tb_rel
        tb.parent.mkdir(parents=True, exist_ok=True)
        tb.write_text(fi.build_ecc_injection_tb(spec, args.max_vectors,
                                               detection_only=spec.dec_out is None))
        ec, stdout, stderr = fi.run_injection_iverilog(project, order, tb_rel,
                                                      timeout=args.timeout)
        log_rel = NATIVE_DIR + "/" + row["id"] + ".log"
        (project / log_rel).write_text(stdout + "\n" + stderr)
        if ec:
            raise Refusal(f"{row['id']} injection NOT_MEASURED rc={ec}; {log_rel}")
        results, baseline, faults = census(stdout, spec, args.max_vectors)
        rep = fi.build_report(spec, results, args.asil, floor)
        rep.update(id=row["id"], baseline=baseline, fault_list=faults,
                   fault_list_truncated=False, max_vectors=args.max_vectors,
                   correction_applicable=spec.dec_out is not None,
                   raw_evidence={"path": log_rel, "sha256": digest(project / log_rel),
                                 "injection_exit_code": ec},
                   detection_criterion=("detect_flag_asserted OR corrected_output_matches"
                                        if spec.dec_out else "detect_flag_asserted"))
        reports.append(rep)
    if declaration(project)[1] != binding:
        raise Refusal("sources changed during injection production")
    passed = all(r["ge_floor"] for r in reports)
    return (0 if passed else 1), {
        "schema": REPORT_SCHEMA, "applicable": True, "measured": True,
        "asil": args.asil, "dc_floor_pct": floor, "input_binding": binding,
        "campaign": {"max_vectors": args.max_vectors, "fault_model": "single-bit flip; every declared codeword bit per selected stimulus"},
        "native_hierarchy": native, "mechanisms": reports,
        "verdict": "PASS" if passed else "FAIL", "ge_floor": passed,
        "reason": "each declared mechanism independently satisfies baseline and ASIL floor"
                  if passed else "one or more declared mechanisms fails baseline/ASIL floor",
        "scope": "codeword-boundary model of current reachable modules; not physical-instance injection or whole-chip FMEDA"}


def consume(project: Path, report: dict, asil, min_dc):
    import fmeda_fault_injection_coverage as fi
    doc, binding = declaration(project)
    if report.get("schema") != REPORT_SCHEMA or report.get("input_binding") != binding:
        raise Refusal("missing/stale declared mechanism measurement")
    require_native(project, doc, report.get("native_hierarchy", {}))
    rows = report.get("mechanisms")
    if (not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows) or
            [r.get("id") for r in rows] != [r["id"] for r in doc["mechanisms"]]):
        raise Refusal("measurement mechanism census differs")
    recomputed = []
    for declaration_row, row in zip(doc["mechanisms"], rows):
        spec = spec_for(declaration_row, _read_order(project, doc))
        raw = row.get("raw_evidence", {})
        if not isinstance(raw, dict):
            raise Refusal("missing raw injection evidence")
        expected_log = NATIVE_DIR + "/" + declaration_row["id"] + ".log"
        if raw.get("path") != expected_log or raw.get("injection_exit_code") != 0:
            raise Refusal("missing successful raw injection evidence")
        log = path_in(project, expected_log)
        if raw.get("sha256") != digest(log):
            raise Refusal("raw injection transcript changed")
        max_vectors = report.get("campaign", {}).get("max_vectors")
        if row.get("max_vectors") != max_vectors:
            raise Refusal("mechanism stimulus count differs from campaign options")
        results, baseline, faults = census(log.read_text(), spec, max_vectors)
        expected_mechanism = fi.build_report(spec, results, report.get("asil", "D"), None)["mechanism"]
        if (row.get("fault_list") != faults or row.get("baseline") != baseline or
                row.get("mechanism") != expected_mechanism or
                row.get("injected_faults") != results.injected or
                row.get("detected_faults") != results.detected or
                row.get("baseline_valid") != results.golden_ok or
                row.get("correction_applicable") != (spec.dec_out is not None)):
            raise Refusal("written baseline/fault census/counts differ from native transcript")
        passed, why = fi.dc_verdict(results.dc_pct, fi.asil_floor(asil or report.get("asil", "D"), min_dc))
        recomputed.append({"id": declaration_row["id"], "passed": results.golden_ok and passed,
                           "injected_faults": results.injected, "detected_faults": results.detected,
                           "recomputed_dc_pct": results.dc_pct, "baseline_valid": results.golden_ok,
                           "reason": why if results.golden_ok else "invalid fault-free baseline"})
    passed = all(r["passed"] for r in recomputed)
    return {"gate": "fmeda_coverage_check", "passed": passed,
            "verdict": "PASS" if passed else "FAIL", "mechanisms": recomputed,
            "reason": "each mechanism independently recomputed from current native evidence"
                      if passed else "one or more mechanisms independently fails"}
