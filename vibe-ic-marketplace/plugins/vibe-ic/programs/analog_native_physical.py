#!/usr/bin/env python3
"""Default analog A11--A16: call the existing native producers.

This module is an execution adapter, not a qualification system.  A missing
tool, deck or measurement is NOT_MEASURED; a native violation is FAIL.  The
caller must propagate both outcomes rather than admitting a completed flow.
A13 extracts only. A14 reuses that extraction without extracting again.

Optional settings are ordinary design inputs in options['config'][step_id],
with optional per-block entries in its 'blocks' map. No settings are needed
to invoke layout, native PV or PEX. Statistical sample count and reliability
decks/limits must come from the design, not this adapter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import uuid
from pathlib import Path
from typing import Callable

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write(path: Path, value: dict) -> None:
    from _atomic_artefact import write_json
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, value)


def _result(status: str, detail: str, outputs=(), **extra) -> dict:
    return {"status": status, "detail": detail,
            "outputs": [str(p) for p in outputs], **extra}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _paths(project: Path, name: str) -> tuple[Path, Path]:
    return (project / "phase3" / "analog" / name,
            project / "phase3" / "librelane" / "analog" / name / "native_analog")


def _settings(options: dict, step: str, name: str) -> dict:
    cfg = options.get("config") or {}
    selected = ((cfg.get("steps") or {}).get(step) or cfg.get(step, {})) if isinstance(cfg, dict) else {}
    selected = dict(selected) if isinstance(selected, dict) else {}
    blocks = selected.pop("blocks", {})
    if isinstance(blocks, dict) and isinstance(blocks.get(name), dict):
        selected.update(blocks[name])
    local = (cfg.get("blocks") or {}).get(name, {})
    if isinstance(local, dict):
        local_step = (local.get("steps") or {}).get(step, {})
        if isinstance(local_step, dict):
            selected.update(local_step)
    return selected


def _interrupted(rc) -> bool:
    return isinstance(rc, int) and (rc < 0 or rc in (130, 137, 143))


def _native_call(operation: str, step: str, project: Path, name: str,
                 options: dict, run: Callable, settings: dict, *, host=False) -> dict:
    _, work = _paths(project, name)
    report = work / f"{step}-{uuid.uuid4().hex}.json"
    argv = [operation, str(project), "--block", name, "--json", str(report),
            "--container", str(options.get("container") or ""),
            "--pdk", str(options.get("pdk") or ""),
            "--image", str(options.get("image") or ""),
            "--settings", json.dumps(settings)]
    execution = run("analog_native_physical.py", argv, outputs=[str(report)],
                    **({"host": True} if host else {}))
    doc = _read(report)
    if doc.get("status") not in ("PASS", "FAIL", "NOT_MEASURED", "NOT_APPLICABLE"):
        rc = execution.get("returncode")
        doc = _result("NOT_MEASURED" if rc in (2, 3, 69, 124, 127) or _interrupted(rc) else "FAIL",
                      f"{step}: producer returned {rc} without a terminal result")
    if execution.get("returncode") not in (0, None) and doc["status"] == "PASS":
        doc = _result("NOT_MEASURED" if _interrupted(execution.get("returncode")) else "FAIL",
                      f"{step}: native execution failed despite PASS report",
                      doc.get("outputs", []))
    # Keep the previous attempts; only a newly returned terminal result can
    # become the current producer record consumed by the following step.
    _write(work / f"{step}.json", doc)
    doc.setdefault("outputs", []).append(str(report))
    doc["executions"] = [execution]
    return doc


def run_step(step_id: str, project: Path, block: dict, options: dict,
             run: Callable) -> dict:
    """Execute one physical analog step through the caller's captured runner."""
    project = Path(project).resolve()
    name = block.get("name") or block.get("block")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", name):
        return _result("NOT_MEASURED", "analog block has no usable declared name")
    bdir, work = _paths(project, name)
    cfg = _settings(options, step_id, name)
    if step_id == "A11" and (bdir / "layout_inputs.json").is_file():
        try:
            layout_inputs = json.loads((bdir / "layout_inputs.json").read_bytes())
        except (OSError, ValueError) as exc:
            return _result("NOT_MEASURED", f"layout execution inputs unreadable: {exc}")
        if not isinstance(layout_inputs, dict):
            return _result("NOT_MEASURED", "layout execution inputs must be an object")
        cfg = {**layout_inputs, **cfg}
    if step_id == "A13" and (bdir / "extraction_inputs.json").is_file():
        try:
            extraction_inputs = json.loads((bdir / "extraction_inputs.json").read_bytes())
        except (OSError, ValueError) as exc:
            return _result("NOT_MEASURED", f"extraction execution inputs unreadable: {exc}")
        if not isinstance(extraction_inputs, dict):
            return _result("NOT_MEASURED", "extraction execution inputs must be an object")
        cfg = {**extraction_inputs, **cfg}
    if step_id == "A16":
        # Like nominal measurement studies, mission/report inputs may be
        # supplied beside the block without changing all upstream inputs.
        cfg = {**_read(bdir / "reliability_inputs.json"), **cfg}
        # The flow's existing design applicability owns which analyses are
        # required. Keep unknown flags conservative, and still evaluate any
        # supplied evidence even when its analysis was not requested.
        cfg["_features"] = dict(options.get("features") or {})
    if step_id == "A15" and options.get("post_mc_samples") is not None:
        samples = options["post_mc_samples"]
        if not isinstance(samples, int) or isinstance(samples, bool) or samples < 2:
            return _result("NOT_MEASURED", "post_mc_samples must be an integer >= 2")
        cfg["samples"] = samples
    if step_id == "A15" and options.get("workers") is not None:
        budget = options["workers"]
        selected_workers = cfg.get("workers", budget)
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in (budget, selected_workers)):
            return _result("NOT_MEASURED", "statistical workers and execution worker budget must be positive integers")
        cfg["workers"] = min(budget, selected_workers)
    if step_id == "A14":
        current = ((options.get("previous_results") or {}).get("A07") or {}).get(name)
        if isinstance(current, dict):
            # Transfer only the already-produced input state and transcript
            # pointers to the child, not a new pre-layout execution request.
            cfg["_pre_result"] = {key: current[key] for key in
                ("status", "metrics", "input_views", "native_inputs", "executions") if key in current}
    if step_id == "A11":
        report = work / f"A11-{uuid.uuid4().hex}.json"
        argv = [str(project), "--block", name,
                "--container", str(options.get("container") or ""),
                "--family", str(options.get("pdk") or ""), "--json", str(report)]
        for key in ("magicrc", "pdk_root", "gencell_tcl", "drc_tech", "magic_tech",
                    "tech_lef", "wire_width_um", "via_pad_half_um", "pg_via_cuts", "pg_wire_width_um"):
            if cfg.get(key) is not None:
                argv += ["--" + key.replace("_", "-"), str(cfg[key])]
        # Stage transports Magic/PDK calls to --container; the source-PDF
        # parser belongs to this host orchestration process.
        execution = run("analog_a5_layout_emit.py", argv,
                        outputs=[str(report), str(bdir / "layout.mag"),
                                 str(bdir / f"{name}.gds")], host=True)
        doc = _read(report)
        measured = (doc.get("blocks") or {}).get(name, {})
        rc = execution.get("returncode")
        state = measured.get("result", doc.get("result"))
        produced = all(p.is_file() and p.stat().st_size for p in
                       (bdir / "layout.mag", bdir / f"{name}.gds"))
        if rc == 0 and state == "OK" and produced:
            status = "PASS"
        elif state in ("ENV_UNAVAILABLE", "NO_BLOCKS") or rc in (69, 127):
            status = "NOT_MEASURED"
        else:
            status = "FAIL"
        return _result(status, measured.get("reason") or doc.get("reason") or
                       f"native layout: {state}, rc={rc}",
                       [report, bdir / "layout.mag", bdir / f"{name}.gds"],
                       metrics={"layout": measured}, executions=[execution])
    operations = {"A12": "pv", "A13": "extract", "A14": "resim",
                  "A15": "statistics", "A16": "reliability"}
    if step_id not in operations:
        return _result("NOT_APPLICABLE", f"{step_id} is not a physical analog step")
    # Reliability reads the source PDF here and keeps native analyses on the
    # explicit --container transport, like the other measured-input readers.
    return _native_call(operations[step_id], step_id, project, name, options, run, cfg,
                        **({"host": True} if step_id == "A16" else {}))


def _pv(project: Path, name: str, container: str, image: str, pdk: str,
        cfg: dict) -> dict:
    import analog_a6_native_pv as pv
    import analog_pdk_availability as availability

    bdir, _ = _paths(project, name)
    resolved = availability.resolve_pdk(pdk or None, project=str(project), container=container)
    if not resolved.get("available"):
        return _result("NOT_MEASURED", resolved.get("reason", "native PDK unavailable"))
    if not (bdir / f"{name}.gds").is_file():
        return _result("NOT_MEASURED", "A11 block GDS is absent")
    # Native producer performs the real DRC and LVS. Existing report counts,
    # including nonzero violations, remain authoritative.
    use_librelane = bool(image) and cfg.get("drc_engine", "librelane") == "librelane"
    native_inputs = dict(resolved)
    ll_record, ll_rc = {}, None
    if use_librelane:
        import analog_a6_librelane_drc as ll
        ll_rc = ll.run(project, name, image, container=container)
        ll_record = _read(bdir / "a6_librelane_drc.json")
        native_inputs.pop("drc_deck", None)  # DRC ran above; LVS is independent.
    record = pv.run_block_pv(project, name, native_inputs, container=container)
    if use_librelane:
        ll_status = ("PASS" if ll_rc == 0 and ll_record.get("result") == "CLEAN" else
                     "FAIL" if ll_record.get("result") == "BLOCKING" else "NOT_MEASURED")
        record["drc"] = {"executed": bool(ll_record.get("engines")),
                         "verdict": ll_status, "returncode": ll_rc, "native": ll_record}
    reports = [bdir / p for p in ("drc.report", "comp.json") if (bdir / p).is_file()]
    drc, lvs = record.get("drc") or {}, record.get("lvs") or {}
    failures = (drc.get("verdict") == "FAIL" or lvs.get("verdict") == "mismatch")
    if failures:
        return _result("FAIL", "native block DRC/LVS reported a violation", reports,
                       metrics=record)
    import analog_native_erc as erc
    erc_record = erc.run(project, name, container=container,
                         lvs_deck=erc.select_deck(project, resolved, pdk))
    record["erc"] = erc_record
    reports.extend(Path(p) for p in erc_record.get("outputs", []))
    if erc_record.get("status") == "FAIL":
        return _result("FAIL", "native analog well/tap ERC reported an electrical violation",
                       reports, metrics=record,
                       native_inputs=erc_record.get("native_inputs", {}))
    pv_pass = (drc.get("verdict") == "PASS" and lvs.get("verdict") == "match")
    complete = pv_pass and erc_record.get("status") == "PASS"
    return _result("PASS" if complete else "NOT_MEASURED",
                   "native block DRC/LVS and well/tap ERC passed" if complete else
                   erc_record.get("detail", "native physical verification remains incomplete"),
                   reports, metrics=record,
                   native_inputs=erc_record.get("native_inputs", {}))


def _extract(project: Path, name: str, container: str, image: str, pdk: str,
             cfg: dict) -> dict:
    import analog_a7_post_layout_emit as a7
    import analog_real_corner_sweep as ars
    import librelane_contract as lc
    import magic_extract_spice_emit as mx
    from _analog_producer_common import layout_netlist_identity

    bdir, work = _paths(project, name)
    net = bdir / f"{name}.sp"
    gds = bdir / f"{name}.gds"
    lay = bdir / "layout_provenance.json"
    if not all(p.is_file() for p in (net, gds, lay)):
        return _result("NOT_MEASURED", "PEX requires the current netlist, GDS and layout provenance")
    layout_record = _read(lay)
    identity, reason = layout_netlist_identity(layout_record, net.read_text())
    if identity != "MATCH":
        return _result("NOT_MEASURED", f"layout/netlist identity {identity}: {reason}")
    if layout_record.get("producer") != "analog_a5_layout_emit" or \
            layout_record.get("result") != "OK" or not layout_record.get("netlist_content_sha256"):
        return _result("NOT_MEASURED", "A11 successful content-bound layout record is absent")
    if not image:
        return _result("NOT_MEASURED", "LibreLane Magic.RCX image is unstated")
    mounts = []
    native_inputs = {}
    selection = cfg.get("magic_core")
    if selection is not None:
        if not isinstance(selection, dict):
            return _result("NOT_MEASURED", "Magic core selection must state path, sha256 and target")
        core = Path(str(selection.get("path", "")))
        if not core.is_absolute():
            core = project / core
        core = core.resolve()
        target = str(selection.get("target", ""))
        expected = selection.get("sha256")
        if (not core.is_file() or not isinstance(expected, str) or
                not re.fullmatch(r"[0-9a-f]{64}", expected) or _sha(core) != expected):
            return _result("NOT_MEASURED", "selected Magic core is absent or differs from its source hash")
        if not Path(target).is_absolute() or Path(target).name != "tclmagic.so" or ".." in Path(target).parts:
            return _result("NOT_MEASURED", "selected Magic core needs its explicit absolute installed target")
        if lc._provider_for_image(image) is not None or lc._provider_route(project):
            return _result("NOT_MEASURED", "LOCAL execution cannot emulate the selected Magic shared-library mount")
        # Ask the selected image's ordinary launcher for its actual runtime
        # prefix; an arbitrary existing .so path would not select its core.
        try:
            probe = lc.run_container(["docker", "run", *lc._dmem.docker_memory_flags(),
                "--rm", "--network", "none", "--entrypoint", "magic", image, "--prefix"],
                probe_deadline_s=lc.PROBE_DEADLINE_S)
            prefixes = [line.strip() for line in probe.stdout.splitlines() if line.strip().startswith("/")]
            if probe.returncode or len(prefixes) != 1 or Path(target) != Path(prefixes[0]) / "magic/tcl/tclmagic.so":
                return _result("NOT_MEASURED", "selected Magic target differs from the native launcher runtime")
        except lc.Refusal as exc:
            return _result("NOT_MEASURED", str(exc))
        native_inputs[str(core)] = {"path": str(core), "sha256": expected}
        receipt = selection.get("build_receipt")
        if receipt is not None:
            receipt = Path(str(receipt))
            if not receipt.is_absolute():
                receipt = project / receipt
            receipt = receipt.resolve()
            if not receipt.is_file():
                return _result("NOT_MEASURED", "selected Magic build receipt is absent")
            native_inputs[str(receipt)] = {"path": str(receipt), "sha256": _sha(receipt)}
        mounts.append((core, target))
    try:
        tech = a7.layout_tech(bdir)
    except ValueError as exc:
        return _result("NOT_MEASURED", str(exc))
    work.mkdir(parents=True, exist_ok=True)
    styles = cfg.get("styles")
    if styles is None:
        if tech.is_file():
            styles = a7.extraction_styles(tech)
        else:
            import shlex
            seen = set()
            def read_tech(path):
                if path in seen:
                    return ""
                seen.add(path)
                text = ars._docker(container, f"cat {shlex.quote(str(path))}")
                if text.returncode:
                    raise OSError(f"layout extraction technology unreadable: {path}: {text.stderr}")
                parts = []
                for line in text.stdout.splitlines():
                    include = a7._INCLUDE_RE.match(line)
                    if include:
                        child = path.parent / include[1]
                        parts.append(read_tech(child if child.suffix else child.with_suffix(".tech")))
                    else:
                        parts.append(line)
                return "\n".join(parts)
            flat = work / "magic_tech.flat"
            flat.write_text(read_tech(tech))
            styles = a7.extraction_styles(flat)
    if not styles or not isinstance(styles, list):
        return _result("NOT_MEASURED", "layout technology declares no parasitic extraction style")
    family, root = tech.parents[2].name, str(tech.parents[3])
    state = work / "pex_state_in.json"
    _write(state, {"gds": str(gds), "metrics": {}})
    corners = []
    for style in styles:
        slug = a7._style_slug(str(style))
        source = work / f"pex_{slug}.source.json"
        config = work / f"pex_{slug}.config.json"
        _write(source, {"meta": {"version": 2, "step": a7.RCX_STEP},
                        "DESIGN_NAME": name, "PDK": family,
                        "MAGIC_RCX_EXTRACT_STYLE": style})
        try:
            config = lc.resolve_step_config(project, image, source, config, pdk_root=root)
            folders = lc.run_chain(project, image, [(a7.RCX_STEP, config, state)],
                                   namespace=f"analog/{name}/a13_{slug}", pdk_root=root,
                                   **({"mounts": mounts} if mounts else {}))
        except lc.Refusal as exc:
            status = "NOT_MEASURED" if (lc.tool_stop_reason(exc.code) or
                exc.code in ("LL_IMAGE_INCAPABLE", "LL_CONFIG_RESOLVE_FAILED", "LL_MOUNTED_FILE_CHANGED")) else "FAIL"
            return _result(status, f"{exc.code}: {exc}", metrics={"corners": corners}, native_inputs=native_inputs)
        folder = folders[-1]
        extracted = Path(_read(folder / "state_out.json").get("spice_rcx") or "")
        if not extracted.is_file():
            return _result("FAIL", "Magic.RCX produced no extracted SPICE", metrics={"corners": corners})
        text = extracted.read_text(errors="replace")
        audit = mx.audit_extracted_netlist(text, spice_file=str(extracted))
        if not audit.passed:
            return _result("FAIL", "Magic.RCX output has no usable parasitics", [extracted],
                           metrics={"extraction_depth": audit.depth, "audit": audit.summary})
        # Reuse the same device-accounting consumer as the existing A7
        # producer; parasitics on an extraction of a different circuit do
        # not qualify this block's PEX.
        lay_doc = _read(lay)
        grid = float(lay_doc.get("lambda_per_um") or 0)
        tech_text = (work / "magic_tech.flat").read_text() if (work / "magic_tech.flat").is_file() else a7._tech_text(tech)
        inventory = a7.device_inventory(a7.device_instances(net.read_text(), name),
            a7.device_instances(text, name), a7.summed_device_models(tech_text),
            layout_grid_m=(1e-6 / grid if math.isfinite(grid) and grid > 0 else 0.0))
        if inventory["result"] != "MATCH":
            return _result("FAIL", "PEX device inventory differs from the source circuit",
                           [extracted], metrics={"device_inventory": inventory})
        corners.append({"style": style, "extracted_netlist": str(extracted),
                        "sha256": _sha(extracted), "step_dir": str(folder),
                        "depth": audit.depth, "parasitics": audit.summary,
                        "device_inventory": inventory})
        if any(not Path(view["path"]).is_file() or _sha(Path(view["path"])) != view["sha256"]
               for view in native_inputs.values()):
            return _result("NOT_MEASURED", "selected Magic source changed during extraction",
                           metrics={"corners": corners}, native_inputs=native_inputs)
    return _result("PASS", "native Magic.RCX extraction completed; no resimulation run",
                   [c["extracted_netlist"] for c in corners],
                   metrics={"corners": corners, "layout_sha256": _sha(gds),
                            "netlist_sha256": _sha(net), "magic_tech": str(tech),
                            **({"magic_core":dict(selection)} if selection is not None else {})},
                   **({"native_inputs":native_inputs} if native_inputs else {}))


def _current_native_views(views: dict) -> bool:
    return isinstance(views, dict) and bool(views) and all(
        isinstance(view, dict) and view.get("path") and Path(view["path"]).is_file()
        and view.get("sha256") == _sha(Path(view["path"])) for view in views.values())


def _pre_measurement_study(project: Path, net: Path, candidates: list,
                           measured_log: Callable, analysis_kinds=("OP",)) -> tuple[dict, dict] | None:
    """Reuse an explicitly adopted study; do not call it canonical TB evidence."""
    import analog_bound_measurements as measurements
    import analog_real_corner_sweep as ars
    selected = [(record, study) for record in candidates
                for study in (record.get("metrics") or {}).get("native_measurement_studies", [])
                if isinstance(study, dict)]
    if not selected:
        return None
    reasons = []
    for parent, study in selected:
        path = project / str(study.get("result") or "__missing_study_result__")
        record = _read(path)
        bindings = record.get("bindings") or {}
        if not isinstance(bindings, dict):
            reasons.append("study measurement bindings are malformed")
            continue
        analysis = bindings.get("analysis") or {}
        if not isinstance(analysis, dict):
            reasons.append("study analysis declaration is malformed")
            continue
        if str(analysis.get("kind", "")).upper() not in analysis_kinds:
            continue
        views = record.get("native_inputs") or {}
        if (not all(role in views for role in ("netlist", "testbench", "deck", "bindings"))
                or not _current_native_views(views)
                or Path(views["netlist"]["path"]).resolve() != net.resolve()
                or _read(Path(views["bindings"]["path"])) != bindings
                or (study.get("bindings_path") and
                    Path(study["bindings_path"]).resolve() != Path(views["bindings"]["path"]).resolve())):
            reasons.append("OP study inputs/result changed, absent or not completed")
            continue
        source = bindings.get("source") or {}
        if isinstance(source, dict) and source.get("path") and not _current_native_views({"source": source}):
            reasons.append("OP study source conditions changed or are absent")
            continue
        current, reason = measurements.validate_consumed_inputs(project, views)
        if not current:
            reasons.append("OP study consumed model/include inputs are not current: " + reason)
            continue
        executions = record.get("executions") or []
        if not executions or any(not _current_native_views(
                {"log": {"path": e.get("log"), "sha256": e.get("log_sha256")}}) for e in executions):
            reasons.append("OP study native execution/log is not current and complete")
            continue
        codes = [e.get("returncode") for e in executions]
        if any(_interrupted(code) or not isinstance(code, int) for code in codes):
            reasons.append("OP study native execution is interrupted or incomplete")
            continue
        transcript = "\n".join(Path(e["log"]).read_text(errors="replace") for e in executions)
        native_failed = any(ars._scan_analysis_failures(transcript)) or re.search(
            r"(?im)\bfatal(?: error)?\b|\bsimulation(?:\(s\)|s)?\s+aborted\b|\btimestep too small\b", transcript)
        if (any(code != 0 for code in codes) or record.get("status") == "FAIL"
                or study.get("status") == "FAIL" or native_failed):
            return {}, {"status": "FAIL", "detail": "source-bound OP study native execution failed",
                        "result": str(path), "result_sha256": _sha(path)}
        if record.get("status") != "PASS" or study.get("status") != "PASS":
            reasons.append("OP study has no completed measurement result")
            continue
        actual_temperatures = sorted({float(value) for value in re.findall(
            r"Doing analysis at TEMP\s*=\s*([-+.\deE]+)", transcript)})
        expected_temperature = analysis.get("temperature_c")
        if expected_temperature is not None and (isinstance(expected_temperature, bool)
                or not isinstance(expected_temperature, (int, float)) or not math.isfinite(expected_temperature)
                or expected_temperature <= -273.15):
            reasons.append("study analysis temperature declaration is invalid")
            continue
        if expected_temperature is not None and (not actual_temperatures or any(
                not math.isclose(value, expected_temperature, rel_tol=0, abs_tol=1e-6) for value in actual_temperatures)):
            reasons.append("study native temperature differs from declared analysis")
            continue
        actual = measured_log(transcript)
        expected = record.get("measurements") or {}
        required = bindings.get("measurements") or {}
        if (not required or any(key not in actual for key in required)
                or any(actual.get(key) != value for key, value in expected.items())):
            reasons.append("OP study measurements differ from its native transcript")
            continue
        comparison_inputs = {"study_result": {"path": str(path.resolve()), "sha256": _sha(path)},
            **{f"study_log:{i}": {"path": e["log"], "sha256": e["log_sha256"]}
               for i, e in enumerate(executions)}}
        if record.get("capture"):
            capture = record["capture"]
            if not _current_native_views({"capture": capture}):
                reasons.append("study native curve capture changed or is absent")
                continue
            comparison_inputs["study_capture"] = {key: capture[key] for key in ("path", "sha256")}
        if isinstance(source, dict) and source.get("path"):
            comparison_inputs["study_source"] = {key: source[key] for key in ("path", "sha256")}
        declaration = net.parent / "measurement_studies.json"
        if declaration.is_file():
            declared = json.loads(declaration.read_text())
            declared = declared.get("studies", []) if isinstance(declared, dict) else declared
            if isinstance(declared, list) and any(isinstance(row, dict) and row.get("result")
                    and (project / row["result"]).resolve() == path.resolve() for row in declared):
                comparison_inputs["study_declaration"] = {"path": str(declaration), "sha256": _sha(declaration)}
        return {key: actual[key] for key in required}, {
            "source": "A07 native measurement study", "result": str(path),
            "result_sha256": _sha(path), "native_inputs": views, "bindings": bindings,
            "comparison_inputs": comparison_inputs, "reused": True, "scope": record.get("scope"),
            "native_temperatures_c": actual_temperatures}
    return {}, {"detail": "no current completed source-bound OP measurement study; " +
                "; ".join(dict.fromkeys(reasons or ["no adopted OP analysis"]))}


def _pre_layout_measurements(project: Path, name: str, cfg: dict) -> tuple[dict, dict]:
    """Consume measured source-bound nominal state; never launch a PRE run."""
    import analog_real_corner_sweep as ars
    bdir, _ = _paths(project, name)
    net, tb = bdir / f"{name}.sp", bdir / f"tb_{name}.sp"
    if not net.is_file():
        return {}, {"detail": "pre-layout circuit input is absent"}

    def measured_log(text: str) -> dict:
        if any(ars._scan_analysis_failures(text)) or re.search(
                r"(?im)\bfatal(?: error)?\b|\bsimulation(?:\(s\)|s)?\s+aborted\b|\btimestep too small\b", text):
            return {}
        values = ars.native_meas_rows(text)
        for line in ars._MEAS_LINE_RE.finditer(text):
            for key, value in ars._KV_RE.findall(line[1]):
                values.setdefault(key, float(value))
        return {key: float(value) for key, value in values.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)}

    candidates = []
    if isinstance(cfg.get("_pre_result"), dict):
        candidates.append(cfg["_pre_result"])
    state = _read(project / "reports" / "analog_native" / "status.json")
    candidates += [row for row in state.get("steps", []) if isinstance(row, dict)
                   and row.get("step") == "A07" and row.get("block") == name]
    study = _pre_measurement_study(project, net, candidates, measured_log,
                                 cfg.get("_analysis_kinds", ("OP",)))
    if study is not None:
        return study
    if not tb.is_file():
        return {}, {"detail": "pre-layout canonical testbench input is absent"}
    refusal_reasons = []
    for record in candidates:
        bound = record.get("input_views") or {}
        consumed = record.get("native_inputs")
        if consumed is not None:
            if not isinstance(consumed, dict) or any(
                    not isinstance(consumed.get(role), dict)
                    or Path(str(consumed[role].get("path", ""))).resolve() != path.resolve()
                    for role, path in (("netlist", net), ("testbench", tb))):
                refusal_reasons.append("recorded nominal netlist/testbench differs from the canonical PRE comparison")
                continue
            if any(not isinstance(view, dict) or not view.get("path")
                    or not Path(view["path"]).is_file()
                    or view.get("sha256") != _sha(Path(view["path"]))
                    for view in consumed.values()):
                refusal_reasons.append("recorded consumed nominal input changed or is absent")
                continue
        elif any(bound.get(str(path)) != _sha(path) for path in (net, tb)):
            continue
        # The record already inventories the staged models; consume those
        # same bytes, without broadening into unrelated document currentness.
        models = [(Path(path), digest) for path, digest in bound.items()
                  if "/input/pdk/" in str(path)]
        if any(not path.is_file() or _sha(path) != digest for path, digest in models):
            continue
        for execution in record.get("executions", []):
            if execution.get("returncode") != 0:
                continue
            if consumed is None:
                # Older records hashed canonical files whether or not that TB
                # ran. Reuse needs the actual captured ngspice command too.
                argv = execution.get("argv")
                if (not isinstance(argv, list) or len(argv) < 3
                        or Path(str(argv[-3])).name != "ngspice" or argv[-2] != "-b"):
                    refusal_reasons.append("legacy A07 execution does not identify the canonical testbench")
                    continue
                actual_deck = Path(str(argv[-1]))
                if not actual_deck.is_absolute():
                    actual_deck = Path(execution.get("cwd") or project) / actual_deck
                if actual_deck.resolve() != tb.resolve():
                    refusal_reasons.append("legacy A07 executed a different testbench from the canonical PRE comparison")
                    continue
            path = Path(execution.get("log") or execution.get("log_path") or "")
            if not path.is_file() or (execution.get("log_sha256") and
                                      execution["log_sha256"] != _sha(path)):
                continue
            values = measured_log(path.read_text(errors="replace"))
            # Read the actual native transcript, even when nominal acceptance
            # was NOT_MEASURED because other required metrics were absent.
            if values:
                return values, {"source": "A07", "log": str(path),
                                "log_sha256": _sha(path), "reused": True}

    # A retained corner producer records the exact schematic/TB hashes and
    # its unmodified nominal sizing run separately from the corner variants.
    retained_path = bdir / "corner_results.json"
    retained = _read(retained_path)
    if (retained.get("_provenance") == "real_ngspice" and retained.get("deck_source") == "a3_netlist"
            and retained.get("netlist_sha256") == _sha(net)
            and retained.get("netlist_testbench_sha256") == _sha(tb)):
        for row in retained.get("all_runs", []):
            if not isinstance(row, dict) or not row.get("ok") or row.get("partial_measurement"):
                continue
            # Only the native no-knob nominal run is comparable to the
            # canonical post-layout testbench; do not select a best-sized arm.
            if row.get("knob") != "__noop__":
                continue
            path = project / str(row.get("ngspice_log") or "__missing_native_log__")
            if path.is_file():
                values = measured_log(path.read_text(errors="replace"))
                if values:
                    return values, {"source": "corner_results nominal run", "record": str(retained_path),
                                    "log": str(path), "log_sha256": _sha(path), "reused": True}
    detail = "no completed source-bound A07 or retained nominal pre-layout measurement"
    if refusal_reasons:
        detail += "; " + "; ".join(dict.fromkeys(refusal_reasons))
    return {}, {"detail": detail}


def _native_values(text: str) -> dict:
    import analog_real_corner_sweep as sweep
    values = sweep.native_meas_rows(text)
    for match in sweep._MEAS_LINE_RE.finditer(text):
        for key, value in sweep._KV_RE.findall(match[1]):
            values[key.casefold()] = float(value)
    return {key.casefold(): float(value) for key, value in values.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)}


def _adopted_studies(project: Path, name: str, cfg: dict) -> tuple[list, list]:
    """Validate all adopted native analyses, retaining their distinct contexts."""
    import analog_real_corner_sweep as sweep
    bdir, _ = _paths(project, name)
    candidates = [cfg["_pre_result"]] if isinstance(cfg.get("_pre_result"), dict) else []
    candidates += [row for row in _read(project / "reports/analog_native/status.json").get("steps", [])
                   if isinstance(row, dict) and row.get("step") == "A07" and row.get("block") == name]
    studies, gaps, seen = [], [], set()
    def measured(text):
        return {} if any(sweep._scan_analysis_failures(text)) else _native_values(text)
    for parent in candidates:
        for study in (parent.get("metrics") or {}).get("native_measurement_studies", []):
            if not isinstance(study, dict) or study.get("result") in seen:
                continue
            seen.add(study.get("result"))
            body = _read(project / str(study.get("result") or "__missing_study__"))
            binding_path = Path(study.get("bindings_path") or "__missing_binding__")
            declared = _read(binding_path) if binding_path.is_file() else {}
            stored = body.get("bindings")
            binding = stored if isinstance(stored, dict) else declared
            analysis = binding.get("analysis") or {}
            kind = str(analysis.get("kind", "")).upper() if isinstance(analysis, dict) else ""
            if kind not in ("OP", "DC", "AC"):
                # Other native consumers own waveform/conversion studies;
                # their presence must not change the existing OP route.
                continue
            record = {**parent, "metrics": {"native_measurement_studies": [study]}}
            selected = _pre_measurement_study(project, bdir / f"{name}.sp", [record], measured,
                                               ("OP", "DC", "AC"))
            if selected is None:
                continue
            values, state = selected
            if values:
                studies.append({"record": record, "measurements": values, "state": state})
            else:
                gaps.append(state)
    return studies, gaps


def _output_observations(spec_path: Path, bindings: dict, values: dict, limits: dict) -> tuple[dict, list]:
    """Attribute real measures to source outputs; never infer a PSRR band."""
    import analog_real_corner_sweep as sweep
    from analog_native_sim import attributed_study_measurements
    observations, missing = {}, []
    declared = bindings.get("measurements") or {}
    graded = {row["label"]: row for row in attributed_study_measurements(spec_path, bindings, values)}
    for label, binding in declared.items():
        source = binding.get("spec_key", label)
        key = sweep.normalize_spec_label(source) or str(source).casefold()
        if key not in limits:
            continue
        row = graded.get(label)
        if row is None or row["status"] != "PASS":
            missing.append(label + ": source attribution, units, limits or regulation predicate incomplete")
            continue
        value = row["value"]
        predicate = None
        if binding.get("interpretation") == "upper_bound_when_regulated":
            paired = binding.get("regulation_measurement")
            predicate = {"measurement": paired, "value": values.get(paired), "source_bounds": limits.get("vout"),
                         "passed": bool(row.get("regulation_valid"))}
        observations.setdefault(key, []).append({"label": label, "value": float(value),
                                                 "regulation_predicate": predicate})
    return observations, missing


def _outside(value: float, bound: dict) -> bool:
    return ((bound.get("min") is not None and value < bound["min"])
            or (bound.get("max") is not None and value > bound["max"]))


def _required_limits(project: Path, name: str) -> dict:
    import ams_analysis_select
    import analog_real_corner_sweep as sweep
    from corner_yield_vs_spec_check import _spec_limits
    source = _read(_paths(project, name)[0] / "spec.json")
    _analyses, mapping = ams_analysis_select.select(source)
    normalize = lambda label: sweep.normalize_spec_label(label) or str(label).casefold()
    required = {normalize(row["key"]) for row in mapping}
    return {normalize(key): bound for key, bound in _spec_limits(source).items()
            if not required or normalize(key) in required}


def _resim_studies(project: Path, name: str, container: str, image: str, pdk: str,
                    cfg: dict, studies: list, gaps: list) -> dict:
    """POST follows every adopted PRE analysis with the same bound conditions."""
    max_delta = cfg.get("max_delta_pct")
    if max_delta is not None and (not isinstance(max_delta, (int, float)) or isinstance(max_delta, bool)
            or not math.isfinite(max_delta) or max_delta < 0):
        return _result("NOT_MEASURED", "explicit max_delta_pct must be a finite nonnegative number")
    groups, outputs, inputs = [], [], {}
    native_failed = any(gap.get("status") == "FAIL" for gap in gaps)
    for index, study in enumerate(studies):
        result = _resim(project, name, container, image, pdk,
            {**cfg, "_analysis_kinds": ("OP", "DC", "AC"),
             "_pre_result": study["record"]}, _compound=True)
        groups.append({"index": index, "analysis": study["state"]["bindings"]["analysis"],
                       "result": result})
        outputs += result.get("outputs", [])
        inputs.update({f"study:{index}:{role}": view for role, view in result.get("native_inputs", {}).items()})
        if result["status"] == "FAIL" and ("simulation" in result.get("metrics", {})
                or not result.get("metrics", {}).get("corners")):
            native_failed = True
    limits = _required_limits(project, name)
    styles = list(dict.fromkeys(corner["style"] for group in groups
        for corner in group["result"].get("metrics", {}).get("corners", [])))
    records = []
    for style in styles:
        observed, measurements, selected, violations, absent = {}, {}, [], [], []
        for group in groups:
            result = group["result"]
            pre = result.get("metrics", {}).get("pre", {})
            corners = [row for row in result.get("metrics", {}).get("corners", []) if row["style"] == style]
            if not corners:
                absent.append(f"study{group['index']}: no completed POST analysis")
                continue
            corner = corners[0]
            meta = corner.get("native_measurement_study")
            if not meta:
                absent.append(f"study{group['index']}: no native measurement-study record")
                continue
            state = _read(Path(meta["result"]))
            if state.get("status") == "FAIL":
                native_failed = True
            post_transcript = "\n".join(Path(e["log"]).read_text(errors="replace")
                for e in state.get("executions", []) if e.get("log") and Path(e["log"]).is_file())
            post_temperatures = sorted({float(value) for value in re.findall(
                r"Doing analysis at TEMP\s*=\s*([-+.\deE]+)", post_transcript)})
            if not pre.get("native_temperatures_c") or post_temperatures != pre["native_temperatures_c"]:
                absent.append(f"study{group['index']}: PRE/POST native temperatures differ or are absent")
            bindings = pre["bindings"]
            values = corner.get("measurements") or {}
            attributed, missing = _output_observations(_paths(project, name)[0] / "spec.json", bindings, values, limits)
            absent += [f"study{group['index']}: {label}" for label in missing]
            for key, rows in attributed.items():
                for row in rows:
                    item = {**row, "study": group["index"]}
                    observed.setdefault(key, []).append(item)
                    if _outside(row["value"], limits[key]) or (row["regulation_predicate"] is not None
                            and not row["regulation_predicate"]["passed"]):
                        violations.append(key + ":" + row["label"])
                    before = (pre.get("measurements") or {}).get(row["label"])
                    if isinstance(before, (int, float)) and before != 0:
                        delta = 100 * abs(row["value"] - before) / abs(before)
                        item["delta_pct"] = delta
                        if max_delta is not None and delta > max_delta:
                            violations.append(key + ":pre_post_delta:" + row["label"])
            measurements.update({f"study{group['index']}_{key}": value for key, value in values.items()})
            selected.append({"index": group["index"], "bindings": bindings,
                "measurements": values, "pre": pre, **corner})
        missing = [key for key in limits if key not in observed or any(
            row["regulation_predicate"] is not None and not row["regulation_predicate"]["passed"] for row in observed[key])]
        records.append({"style": style, "measurements": measurements, "source_observations": observed,
                        "missing": sorted(missing), "missing_studies": absent,
                        "violations": sorted(set(violations)), "native_measurement_studies": selected})
    failed = native_failed or any(row["violations"] for row in records)
    incomplete = bool(gaps) or not records or any(row["missing"] or row["missing_studies"] for row in records)
    return _result("FAIL" if failed else "NOT_MEASURED" if incomplete else "PASS",
        "source-matched native OP/DC/AC post-layout comparisons", outputs,
        metrics={"study_groups": groups, "corners": records, "pre_gaps": gaps}, native_inputs=inputs)


def _resim(project: Path, name: str, container: str, image: str, pdk: str,
           cfg: dict, *, _compound: bool = False) -> dict:
    import analog_a7_post_layout_emit as a7
    import analog_real_corner_sweep as ars
    import ams_analysis_select
    import _designs_root as dr
    from corner_yield_vs_spec_check import _spec_limits, _violates

    bdir, work = _paths(project, name)
    extraction = _read(work / "A13.json")
    data = extraction.get("metrics") or {}
    net, tb = bdir / f"{name}.sp", bdir / f"tb_{name}.sp"
    gds = bdir / f"{name}.gds"
    if extraction.get("status") != "PASS" or not all(p.is_file() for p in (net, gds)):
        return _result("NOT_MEASURED", "post-layout performance requires A13 extraction and the source circuit")
    if not _compound:
        studies, gaps = _adopted_studies(project, name, cfg)
        if len(studies) + len(gaps) > 1 or any(study["state"]["bindings"]["analysis"]["kind"] != "OP" for study in studies) or (
                not studies and any(gap.get("status") == "FAIL" for gap in gaps)):
            return _resim_studies(project, name, container, image, pdk, cfg, studies, gaps)
    if data.get("layout_sha256") != _sha(gds) or data.get("netlist_sha256") != _sha(net):
        return _result("NOT_MEASURED", "A13 extraction does not describe the current layout/netlist")
    corners = data.get("corners") or []
    if not corners:
        return _result("NOT_MEASURED", "A13 measured no extraction corner")
    pre, pre_state = _pre_layout_measurements(project, name, cfg)
    if not pre:
        return _result(pre_state.get("status", "NOT_MEASURED"), pre_state["detail"], metrics={"pre": pre_state})
    study_pre = pre_state.get("source") == "A07 native measurement study"
    consumed_inputs = ({"pre:" + role: view for role, view in
        {**pre_state["native_inputs"], **pre_state["comparison_inputs"]}.items()} if study_pre else {})
    if study_pre:
        consumed_inputs.update({role: {"path": str(path), "sha256": _sha(path)} for role, path in
            (("extraction_record", work / "A13.json"), ("layout", gds))})
    source_tb = Path(pre_state["native_inputs"]["testbench"]["path"]) if study_pre else tb
    if study_pre and any(re.search(r"(?i)\b(?:v(?:db|p|m)?|i)\([^)]*\bxdut[.:]",
            str(binding.get("expression", "")))
            for binding in pre_state["bindings"]["measurements"].values()):
        return _result("NOT_MEASURED", "post-layout OP study requires a mapped internal DUT probe",
                       metrics={"pre": pre_state})
    host_root = dr.resolve_host_root(project, container)
    rows, records, outputs = [], [], []
    ports = a7.subckt_ports(net.read_text(), name)
    if not ports:
        return _result("FAIL", "source netlist declares no block subcircuit")
    source = _read(bdir / "spec.json")
    limits = _spec_limits(source)
    _analyses, mapping = ams_analysis_select.select(source)
    normalize = lambda key: ars.normalize_spec_label(key) or str(key).casefold()
    required_outputs = {normalize(row["key"]) for row in mapping}
    if required_outputs:
        # Supply/load conditions are source inputs, not measured outputs.
        # Keep the existing all-limit behavior for unclassified custom specs.
        limits = {normalize(key): bound for key, bound in limits.items()
                  if normalize(key) in required_outputs}
    if not limits:
        return _result("NOT_MEASURED", "post-layout acceptance has no declared numeric spec bounds")
    for corner in corners:
        extracted = Path(corner["extracted_netlist"])
        if not extracted.is_file() or corner.get("sha256") != _sha(extracted):
            return _result("NOT_MEASURED", "extracted SPICE changed since A13")
        slug = a7._style_slug(corner["style"])
        raw = extracted.read_text(errors="replace")
        destination = work / "measurement_studies" / slug / uuid.uuid4().hex if study_pre else work
        destination.mkdir(parents=True, exist_ok=True)
        post_net = destination / f"{name}_post_{slug}.sp"
        body, mapping = a7.post_layout_netlist(name, ports, raw,
            a7.model_binding_lines(net.read_text(), bdir, destination))
        post_net.write_text(body)
        rp, ri = a7.rcx_nets(raw, name)
        post_text, dropped = a7.remap_probes(
            a7.post_layout_testbench(source_tb.read_text(), name, post_net.name, source_tb.parent, destination),
            name, rp, ri, mapping)
        post_tb = destination / f"tb_{name}_post_{slug}.sp"
        post_tb.write_text(post_text)
        study_meta = None
        if study_pre:
            import analog_bound_measurements as measurements
            from analog_native_flow import NativeCommands
            runner = NativeCommands(project, destination, container, image)
            state = measurements.run_measurements(project, post_net, post_tb,
                pre_state["bindings"], destination, runner)
            state["native_inputs"]["bindings"] = pre_state["native_inputs"]["bindings"]
            source_binding = pre_state["bindings"].get("source") or {}
            checked = {"bindings": state["native_inputs"]["bindings"]}
            if isinstance(source_binding, dict) and source_binding.get("path"):
                checked["source"] = source_binding
            if not _current_native_views(checked) and state.get("status") != "FAIL":
                state.update(status="NOT_MEASURED", detail="measurement-study bindings/source changed during POST")
            current, reason = measurements.validate_consumed_inputs(project, state["native_inputs"])
            if not current and state.get("status") != "FAIL":
                state.update(status="NOT_MEASURED", detail="POST consumed model/include inputs changed: " + reason)
            result_path = destination / "result.json"
            _write(result_path, state)
            study_meta = {"result": str(result_path), "sha256": _sha(result_path),
                "pre_result": pre_state["result"], "pre_result_sha256": pre_state["result_sha256"],
                "native_inputs": state["native_inputs"]}
            consumed_inputs["extracted:" + slug] = {"path": str(extracted), "sha256": _sha(extracted)}
            consumed_inputs.update({"post:" + slug + ":" + role: view
                                    for role, view in state["native_inputs"].items()})
            consumed_inputs["post:" + slug + ":result"] = {"path": str(result_path), "sha256": _sha(result_path)}
            consumed_inputs.update({"post:" + slug + f":log:{i}": {"path": e["log"], "sha256": e["log_sha256"]}
                for i, e in enumerate(state.get("executions", [])) if e.get("log") and e.get("log_sha256")})
            post_tb = Path(state["native_inputs"]["deck"]["path"])
            post = state.get("measurements") or {}
            ok = state.get("status") == "PASS"
            outputs += [post_net, result_path] + [Path(path) for path in state.get("outputs", []) if path]
            logpath = next((Path(e["log"]) for e in state.get("executions", []) if e.get("log")), result_path)
        else:
            ok, post, log, state = ars._run_ngspice(container,
                ars._container_path(container, host_root, post_tb),
                deck_text=post_tb.read_text(), run_to_completion=True)
            logpath = post_tb.with_suffix(".ngspice.log")
            logpath.write_text(log or "")
            outputs += [post_tb, logpath]
        if not ok:
            status = state["status"] if study_pre else ("NOT_MEASURED" if (
                state.get("stopped") or state.get("progress_stalled") or _interrupted(state.get("rc"))) else "FAIL")
            if study_meta:
                records.append({"style": corner["style"], "native_measurement_study": study_meta,
                                "simulation": state})
            return _result(status, f"native resimulation failed: {logpath}", outputs,
                           metrics={"pre": pre_state, "simulation": state, "corners": records},
                           **({"native_inputs": consumed_inputs} if study_pre else {}))
        declared = pre_state["bindings"]["measurements"] if study_pre else a7.declared_measurements(source_tb.read_text())
        absent_pre = [m for m in declared if pre.get(m) is None]
        lost = []
        supply, margin = a7._declared_rail_reference(source_tb.read_text())
        compared = a7.compare(pre, post, corner["style"],
                              dropped, lost, supply, margin)
        rows += compared
        missing = [key for key in limits if post.get(key) is None]
        violated = [key for key, lim in limits.items() if post.get(key) is not None and
                    (not math.isfinite(post[key]) or _violates(post[key], lim["min"], lim["max"]))]
        records.append({"style": corner["style"], "post_testbench": str(post_tb),
                        "post_netlist": str(post_net), "measurements": post,
                        "post_testbench_sha256": _sha(post_tb),
                        "post_netlist_sha256": _sha(post_net),
                        "missing": missing, "violations": violated,
                        "not_comparable": dropped, "missing_pre": absent_pre, "lost_post": lost})
        if study_meta:
            records[-1]["native_measurement_study"] = study_meta
    from analog_a7_post_layout_resim_check import _check_specs, DEFAULT_MAX_DELTA_PCT
    deltas, _ = _check_specs(rows)
    measured_failure = any(c["violations"] for c in records) or any(
        d > DEFAULT_MAX_DELTA_PCT for d in deltas)
    incomplete = any(c["missing"] or c["missing_pre"] or c["not_comparable"] or
                     c["lost_post"] for c in records) or not rows
    # The compound caller applies shared source attribution (including upper
    # bounds and units) across all contexts. Legacy scalar grading below is
    # retained only for the existing single-study route.
    status = ("NOT_MEASURED" if incomplete else "PASS") if _compound else (
        "FAIL" if measured_failure else "NOT_MEASURED" if incomplete else "PASS")
    return _result(status, "post-layout native performance and pre/post comparison",
                   outputs, metrics={"pre": {**pre_state, "measurements": pre},
                                     "corners": records, "specs": rows,
                                     "max_delta_pct": max(deltas) if deltas else None},
                   **({"native_inputs": consumed_inputs} if study_pre else {}))


def compose_native_measurement_sequence(project: Path, references: list) -> tuple[str, dict]:
    """Compose actual native OP/DC/AC records, without assigning a flow stage.

    References are {path, sha256} views of source-produced result JSON. PRE
    and POST callers supply their own actual DUT records; no result is relabeled.
    """
    if not isinstance(references, list) or not references:
        raise ValueError("native population requires nonempty actual measurement result references")
    selected = []
    for reference in references:
        path = Path(reference["path"])
        if not path.is_file() or reference.get("sha256") != _sha(path):
            raise ValueError("native measurement result reference changed")
        record = _read(path)
        netlist = (record.get("native_inputs") or {}).get("netlist") or {}
        selected.append({"post_netlist": netlist.get("path"), "post_netlist_sha256": netlist.get("sha256"),
            "native_measurement_study": {"result": str(path), "sha256": reference["sha256"]}})
    text, sequence = _compose_measurement_sequence(project, selected)
    for item in sequence["studies"]:
        item["source_result"] = item.pop("post_result")
        item["source_result_sha256"] = item.pop("post_result_sha256")
    return text, sequence


def run_native_measurement_population(project: Path, name: str, references: list, destination: Path,
                                      container: str, pdk: str, samples: int, *, stage: str) -> dict:
    """Run the existing foundry-statistical producer on actual PRE or POST inputs."""
    import analog_mc_yield_run as mc
    import shutil
    if stage not in ("PRE", "POST") or not isinstance(samples, int) or isinstance(samples, bool) or samples < 2:
        return {"verdict": "NOT_MEASURED", "mc_runs": 0,
                **({"stage": stage} if stage in ("PRE", "POST") else {}),
                "reason": "explicit PRE/POST stage and integer samples >=2 required"}
    try:
        if not isinstance(references, list) or not references:
            raise ValueError("native population requires nonempty actual measurement result references")
        canonical = _paths(project, name)[0] / f"{name}.sp"
        if stage == "PRE":
            for reference in references:
                state = _read(Path(reference["path"]))
                source = (state.get("native_inputs") or {}).get("netlist") or {}
                if (Path(source.get("path") or "__missing_source__").resolve() != canonical.resolve()
                        or not canonical.is_file() or source.get("sha256") != _sha(canonical)):
                    raise ValueError("PRE population requires the current canonical source DUT; PEX records cannot substitute")
        text, sequence = compose_native_measurement_sequence(project, references)
    except NativeStudyFailed as exc:
        return {"verdict": "FAIL", "stage": stage, "mc_runs": 0, "reason": str(exc)}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"verdict": "NOT_MEASURED", "stage": stage, "mc_runs": 0, "reason": str(exc)}
    target = Path(destination) / "phase3/analog" / name
    if target.exists():
        return {"verdict": "NOT_MEASURED", "stage": stage, "mc_runs": 0,
                "reason": "population destination already exists; preserve its receipts and select a fresh directory"}
    target.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(_paths(project, name)[0] / "spec.json", target / "spec.json")
    for dirname in ("input", "phase1"):
        if (project / dirname).exists():
            (Path(destination) / dirname).symlink_to(project / dirname, target_is_directory=True)
    deck = target / f"tb_{name}.sp"
    deck.write_text(text)
    _write(Path(destination) / "measurement_sequence.json", sequence)
    selected = sequence.get("ngspice_bin")
    raw = mc.run_block(Path(destination), name, container, pdk, samples,
                        **({"ngspice_bin": selected} if selected else {}))
    record = _grade_measurement_population(project, name, Path(destination), raw, sequence, samples)
    consumed = {"compiled_deck": {"path": str(deck), "sha256": _sha(deck)}}
    for index, reference in enumerate(references):
        state = _read(Path(reference["path"]))
        consumed[f"record:{index}"] = reference
        consumed.update({f"record:{index}:{role}": view
                         for role, view in state["native_inputs"].items()})
        consumed.update({f"record:{index}:log:{j}": {"path": execution["log"], "sha256": execution["log_sha256"]}
                         for j, execution in enumerate(state.get("executions", []))})
        if state.get("capture"):
            consumed[f"record:{index}:capture"] = {key: state["capture"][key] for key in ("path", "sha256")}
    for index, binding in enumerate(raw.get("mc_model_bindings", [])):
        consumed.update({f"statistical_model:{index}:{j}": {key: view[key] for key in ("path", "sha256")}
                         for j, view in enumerate(binding.get("model_inputs", []))})
    if raw.get("mc_native_binary"):
        consumed["native_binary"] = {key: raw["mc_native_binary"][key] for key in ("path", "sha256")}
    if not _current_native_views(consumed) and record["verdict"] != "FAIL":
        record.update(verdict="NOT_MEASURED", mc_yield_pct=None,
                      reason="consumed native population inputs changed during execution")
    record.update(stage=stage, study=str(destination),
        outputs=[str(Path(destination)), str(Path(destination) / "combined_statistics.json"), str(deck)],
        native_inputs=consumed)
    _write(Path(destination) / "combined_statistics.json", record)
    return record


def _population(project: Path, name: str, container: str, image: str, pdk: str, cfg: dict) -> dict:
    """CLI transport for the existing population producer with caller image context."""
    _bdir, work = _paths(project, name)
    destination = work / "native_populations" / uuid.uuid4().hex
    record = run_native_measurement_population(project, name, cfg.get("references"), destination,
        container, pdk, cfg.get("samples"), stage=cfg.get("stage"))
    verdict = record.get("verdict")
    status = verdict if verdict in ("PASS", "FAIL") else "NOT_MEASURED"
    return _result(status, record.get("reason", "native bound statistical population"),
                   [Path(path) for path in record.get("outputs", [])], metrics=record,
                   native_inputs=record.get("native_inputs", {}))


def _pvt_studies(project: Path, name: str, container: str, image: str, pdk: str, cfg: dict) -> dict:
    from analog_native_pvt import run_pvt_studies
    return run_pvt_studies(project, name, cfg.get("result"))


class NativeStudyFailed(ValueError):
    """A current native PRE/POST failure cannot become a missing-input result."""


def _compose_measurement_sequence(project: Path, studies: list) -> tuple[str, dict]:
    """One DUT/draw, explicit source alterations, no reset or metric aliases."""
    import analog_bound_measurements as measurements
    import shlex
    signatures, sources, controls, metadata, save_lines, binaries = [], [], [], [], set(), set()
    first_body = None
    native_net = None
    number = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?[a-zA-Z]*"
    source_re = re.compile(rf"(?i)^(?:dc\s+)?({number})(?:\s+ac\s+({number})(?:\s+({number}))?)?$")
    for index, study in enumerate(studies):
        meta = study["native_measurement_study"]
        result_path = Path(meta["result"])
        record = _read(result_path)
        if not result_path.is_file() or meta.get("sha256") != _sha(result_path) or not _current_native_views(record.get("native_inputs")):
            raise ValueError("POST study result or consumed inputs changed since A14")
        current, reason = measurements.validate_consumed_inputs(project, record["native_inputs"])
        if not current:
            raise ValueError("POST study model/include inputs changed: " + reason)
        binding = record["bindings"]
        for execution in record.get("executions", []):
            if not _current_native_views({"log": {"path": execution.get("log"), "sha256": execution.get("log_sha256")}}):
                raise ValueError("POST study native transcript changed since A14")
        transcript = "\n".join(Path(e["log"]).read_text(errors="replace") for e in record.get("executions", []))
        import analog_real_corner_sweep as sweep
        if record.get("status") != "PASS" or any(sweep._scan_analysis_failures(transcript)):
            raise NativeStudyFailed("POST study native analysis failed")
        temperatures = {float(value) for value in re.findall(r"Doing analysis at TEMP\s*=\s*([-+.\deE]+)", transcript)}
        if len(temperatures) != 1:
            raise ValueError("POST study has no single native analysis temperature")
        temperature = temperatures.pop()
        if binding["analysis"].get("temperature_c", temperature) != temperature:
            raise ValueError("POST study native temperature differs from its binding")
        binaries.add((binding.get("execution") or {}).get("ngspice_bin"))
        deck = Path(record["native_inputs"]["deck"]["path"])
        text = measurements.contextual_template(deck.read_text(), deck.parent)
        body = re.sub(r"(?ims)^\s*\.control\b.*?^\s*\.endc\b[^\n]*", "", text)
        body = re.sub(r"(?im)^\s*\.end\s*$", "", body)
        net = Path(study["post_netlist"])
        if study.get("post_netlist_sha256") != _sha(net):
            raise ValueError("POST extracted DUT changed since A14")
        actual_net = record["native_inputs"]["netlist"]
        if Path(actual_net["path"]).resolve() != net.resolve() or actual_net["sha256"] != study["post_netlist_sha256"]:
            raise ValueError("measurement record consumed a different DUT")
        canonical_net_text = "\n".join(line.strip() for line in
            measurements.contextual_template(net.read_text(), net.parent).splitlines()
            if line.strip() and not line.lstrip().startswith("*"))
        if native_net is None:
            native_net = canonical_net_text
        elif canonical_net_text != native_net:
            raise ValueError("studies do not use the same extracted DUT/model equations")
        signature, declared_sources = [], {}
        for line_number, line in enumerate(body.splitlines()):
            stripped = line.strip()
            if line_number == 0 or not stripped or stripped.startswith("*"):
                continue
            if re.match(r"(?i)^\.temp\b", stripped):
                continue
            if re.match(r"(?i)^\.save\b", stripped):
                save_lines.add(stripped)
                continue
            if stripped[0].casefold() in ("v", "i"):
                fields = stripped.split(None, 3)
                parsed = source_re.fullmatch(fields[3]) if len(fields) == 4 else None
                if not parsed:
                    raise ValueError("combined OP/DC/AC supports explicit independent DC/AC source cards: " + stripped)
                declared_sources[fields[0].casefold()] = {"nodes": fields[1:3], "kind": fields[0][0].casefold(),
                    "dc": parsed[1], "acmag": parsed[2] or "0", "acphase": parsed[3] or "0"}
                signature.append(" ".join(fields[:3]))
            elif stripped.casefold().startswith((".include ", ".inc ")):
                tokens = shlex.split(stripped)
                signature.append(".include <POST_DUT>" if len(tokens) == 2 and Path(tokens[1]).resolve() == net.resolve() else stripped)
            else:
                signature.append(stripped)
        signatures.append(signature)
        sources.append(declared_sources)
        if index and (signature != signatures[0] or set(declared_sources) != set(sources[0])):
            raise ValueError("study templates differ beyond independent source values/temperature; cannot share one physical MC draw")
        if first_body is None:
            first_body = re.sub(r"(?im)^\s*\.(?:save|temp)\b[^\n]*", "", body)
        controls += [f'echo "VIBEIC_STUDY_BEGIN {index}"', "set num_threads=1", f"set temp={temperature:.17g}"]
        for source_name, source in declared_sources.items():
            controls += [f"alter @{source_name}[{parameter}] = {source[parameter]}" for parameter in ("dc", "acmag", "acphase")]
        local = {**binding, "capture": {}, "measurements": {
            f"study{index}_{label}": value for label, value in binding["measurements"].items()}}
        emitted = measurements.emit_deck("* combined native analysis commands\n", local)
        commands = re.search(r"(?is)\.control\s*\n(.*?)\n\.endc", emitted)[1]
        # The combined deck owns source/temperature changes and one scheduling
        # choice. Keep the producer's actual analysis/measurement commands.
        commands = re.sub(r"(?im)^set num_threads=.*\n?", "", commands)
        controls += commands.splitlines() + [f'echo "VIBEIC_STUDY_END {index}"']
        metadata.append({"index": index, "analysis": binding["analysis"], "temperature_c": temperature,
                         "bindings": binding, "post_result": str(result_path), "post_result_sha256": _sha(result_path),
                         "labels": {label: f"study{index}_{label}" for label in binding["measurements"]}})
    if len(binaries) > 1:
        raise ValueError("combined studies require one common selected native binary")
    text = (first_body or "* combined native studies\n").rstrip() + "\n" + "\n".join(sorted(save_lines))
    text += "\n.control\n" + "\n".join(controls) + "\n.endc\n.end\n"
    return text, {"studies": metadata, "ngspice_bin": next(iter(binaries), None),
                  "mc_execution": {"num_threads": 1, "wait_policy": "transport default; not overridden"},
                  "draw_scope": "one instantiated foundry draw across all analyses; no reset"}


def _grade_measurement_population(project: Path, name: str, study: Path, native: dict,
                                  sequence: dict, samples: int) -> dict:
    import analog_mc_yield_run as mc
    import analog_real_corner_sweep as sweep
    limits = _required_limits(project, name)
    logdir = study / str(native.get("mc_log_dir") or "__missing_logs__")
    records, observations = [], {key: [] for key in limits}
    failed = 0
    for seed in range(1, samples + 1):
        log = logdir / f"mc_{seed:04d}.log"
        text = log.read_text(errors="replace") if log.is_file() else ""
        values = _native_values(text)
        native_failed = bool(any(sweep._scan_analysis_failures(text)))
        failed += int(native_failed)
        sample, by_output, absent = {}, {}, []
        for item in sequence["studies"]:
            index = item["index"]
            sections = re.findall(rf"VIBEIC_STUDY_BEGIN {index}\s*\n(.*?)VIBEIC_STUDY_END {index}(?:\s|$)", text, re.S)
            temperatures = [float(value) for value in re.findall(r"Doing analysis at TEMP\s*=\s*([-+.\deE]+)", sections[0])] if len(sections) == 1 else []
            matched = bool(temperatures) and all(math.isclose(value, item["temperature_c"], abs_tol=1e-6, rel_tol=0) for value in temperatures)
            measured = {label: values[tag.casefold()] for label, tag in item["labels"].items() if tag.casefold() in values}
            sample[str(index)] = {"measurements": measured, "native_temperatures_c": temperatures,
                                  "temperature_matched": matched}
            if not matched:
                absent.append(f"study{index}: native temperature/analysis markers missing or mismatched")
            attributed, missing = _output_observations(_paths(project, name)[0] / "spec.json", item["bindings"], measured, limits)
            absent += [f"study{index}: {key}" for key in missing]
            for key, rows in attributed.items():
                by_output.setdefault(key, []).extend(rows)
        for key in limits:
            expected = sum(1 for item in sequence["studies"]
                for label, binding in item["bindings"]["measurements"].items()
                if (sweep.normalize_spec_label(binding.get("spec_key", label)) or str(binding.get("spec_key", label)).casefold()) == key)
            rows = by_output.get(key, [])
            missing_context = any(any((sweep.normalize_spec_label(binding.get("spec_key", label)) or str(binding.get("spec_key", label)).casefold()) == key
                and label not in sample[str(item["index"])] ["measurements"]
                for label, binding in item["bindings"]["measurements"].items()) for item in sequence["studies"])
            relevant_temperature = all(sample[str(item["index"])]["temperature_matched"]
                for item in sequence["studies"] if any(
                    (sweep.normalize_spec_label(binding.get("spec_key", label)) or str(binding.get("spec_key", label)).casefold()) == key
                    for label, binding in item["bindings"]["measurements"].items()))
            valid_predicates = all(row["regulation_predicate"] is None or row["regulation_predicate"]["passed"] for row in rows)
            if not native_failed and relevant_temperature and valid_predicates and expected and len(rows) == expected and not missing_context:
                observations[key].append([row["value"] for row in rows])
        records.append({"seed": seed, "log": str(log), "log_sha256": _sha(log) if log.is_file() else None,
                        "native_failed": native_failed, "studies": sample, "source_observations": by_output,
                        "missing": absent})
    scored = {}
    for key, population in observations.items():
        distinct = len({tuple(round(value, 12) for value in row) for row in population})
        passed = sum(all(not _outside(value, limits[key]) for value in row) for row in population)
        scored[key] = {"runs_scored": len(population), "distinct_values": distinct,
            "passed": passed, "yield_pct": round(100 * passed / len(population), 2) if population and distinct >= 2 else None,
            "min_observed": min((value for row in population for value in row), default=None),
            "max_observed": max((value for row in population for value in row), default=None)}
    grade = mc._grade_source_yield(project, str((_paths(project, name)[0] / "spec.json").relative_to(project)), scored, samples)
    failed = max(failed, int(native.get("mc_native_failed") or 0))
    if failed:
        grade.update(verdict="FAIL", rc=1, reason="native analysis failed in combined Monte Carlo population")
    elif (native.get("mc_runs") != samples or ((native.get("mc_native_binary") or {}).get("sha256") is not None
            and native["mc_native_binary"].get("sha256") != native["mc_native_binary"].get("sha256_after"))):
        grade.update(verdict="NOT_MEASURED", rc=2, mc_yield_pct=None,
                     reason="native population incomplete or selected binary changed")
    record = {**grade, "spec_yield": scored, "mc_runs": samples, "mc_native_failed": failed,
              "sequence": sequence, "samples": records, "raw_producer": native}
    _write(study / "combined_statistics.json", record)
    return record


def _statistics(project: Path, name: str, container: str, image: str, pdk: str,
                cfg: dict, *, _one_style: bool = False) -> dict:
    import analog_mc_yield_run as mc
    import analog_a7_post_layout_emit as a7
    import shutil

    bdir, work = _paths(project, name)
    prior = _read(work / "A14.json")
    corners = (prior.get("metrics") or {}).get("corners") or []
    n = cfg.get("samples")
    if not isinstance(n, int) or isinstance(n, bool) or n < 2:
        return _result("NOT_MEASURED", "post-layout statistics requires a declared sample count >= 2",
                       missing_inputs=["samples"])
    if not corners:
        return _result("NOT_MEASURED", "no extracted post-layout testbench from A14",
                       missing_inputs=["A14.metrics.corners"])
    unmeasured_styles = []
    if cfg.get("styles") is not None:
        selected_styles = cfg["styles"]
        declared_styles = {row.get("style") for row in corners}
        if (not isinstance(selected_styles, list) or not selected_styles
                or any(not isinstance(style, str) or style not in declared_styles for style in selected_styles)):
            return _result("NOT_MEASURED", "statistics styles must select existing A14 extraction styles")
        unmeasured_styles = sorted(declared_styles - set(selected_styles))
        corners = [row for row in corners if row["style"] in selected_styles]
    workers = cfg.get("workers", 1)
    if not isinstance(workers, int) or isinstance(workers, bool) or workers < 1:
        return _result("NOT_MEASURED", "statistical workers must be a positive integer")
    if not _one_style and workers > 1 and len(corners) > 1:
        from concurrent.futures import ThreadPoolExecutor
        def execute(corner):
            result = _statistics(project, name, container, image, pdk,
                {**cfg, "styles": [corner["style"]], "workers": 1}, _one_style=True)
            return corner["style"], result
        with ThreadPoolExecutor(max_workers=min(workers, len(corners))) as pool:
            completed = list(pool.map(execute, corners))
        reports = [row for _style, result in completed for row in result.get("metrics", {}).get("corners", [])]
        failed = any(result["status"] == "FAIL" for _style, result in completed)
        measured = not unmeasured_styles and len(reports) == len(corners) and all(
            row.get("verdict") == "PASS" and row.get("mc_runs") == n
            and row.get("source_coverage", {}).get("required")
            and not row["source_coverage"].get("missing") for row in reports)
        inputs = {role: view for _style, result in completed for role, view in result.get("native_inputs", {}).items()}
        return _result("FAIL" if failed else "PASS" if measured else "NOT_MEASURED",
            "independent extracted-style statistical populations completed",
            [work / "statistics"], metrics={"corners": reports, "samples": n,
                "workers": min(workers, len(corners)), "unmeasured_styles": unmeasured_styles,
                "style_results": [{"style": style, "status": result["status"], "detail": result["detail"]}
                                  for style, result in completed]}, **({"native_inputs": inputs} if inputs else {}))
    spec = bdir / "spec.json"
    if not spec.is_file():
        return _result("NOT_MEASURED", f"post-layout statistics source limits absent: {spec}",
                       missing_inputs=[str(spec)])
    reports, consumed = [], {}
    if any(row.get("native_measurement_studies") for row in corners):
        consumed = {"A14_record": {"path": str(work / "A14.json"), "sha256": _sha(work / "A14.json")},
                    **{"A14:" + role: view for role, view in (prior.get("native_inputs") or {}).items()}}
    for corner in corners:
        if corner.get("native_measurement_studies"):
            study = work / "statistics" / a7._style_slug(corner["style"]) / uuid.uuid4().hex
            target = study / "phase3/analog" / name
            target.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(spec, target / "spec.json")
            for dirname in ("input", "phase1"):
                source, dest = project / dirname, study / dirname
                if source.exists() and not dest.exists():
                    dest.symlink_to(source, target_is_directory=True)
            try:
                text, sequence = _compose_measurement_sequence(project, corner["native_measurement_studies"])
            except NativeStudyFailed as exc:
                return _result("FAIL", str(exc))
            except (OSError, ValueError, KeyError) as exc:
                return _result("NOT_MEASURED", "combined statistical analyses unavailable: " + str(exc))
            deck = target / f"tb_{name}.sp"
            deck.write_text(text)
            _write(study / "measurement_sequence.json", sequence)
            selected = sequence.get("ngspice_bin")
            raw = mc.run_block(study, name, container, pdk, n,
                               **({"ngspice_bin": selected} if selected else {}))
            result = _grade_measurement_population(project, name, study, raw, sequence, n)
            consumed[f"combined:{corner['style']}:deck"] = {"path": str(deck), "sha256": _sha(deck)}
            for index, source in enumerate(corner["native_measurement_studies"]):
                meta = source["native_measurement_study"]
                path = Path(meta["result"])
                consumed[f"combined:{corner['style']}:{index}:result"] = {"path": str(path), "sha256": _sha(path)}
                consumed.update({f"combined:{corner['style']}:{index}:{role}": view
                    for role, view in _read(path).get("native_inputs", {}).items()})
            reports.append({"style": corner["style"], "study": str(study), **result,
                            "source_coverage": result["mc_source_coverage"]})
            continue
        deck = Path(corner["post_testbench"])
        if not deck.is_file():
            return _result("NOT_MEASURED", f"post-layout testbench absent: {deck}")
        post_net = Path(corner.get("post_netlist") or "")
        if not post_net.is_file() or corner.get("post_netlist_sha256") != _sha(post_net) or \
                corner.get("post_testbench_sha256") != _sha(deck):
            return _result("NOT_MEASURED", "post-layout circuit/testbench changed since A14")
        study_meta = corner.get("native_measurement_study")
        if study_meta:
            import analog_bound_measurements as measurements
            result_path = Path(study_meta.get("result") or "__missing_post_study__")
            state = _read(result_path)
            if (not result_path.is_file() or study_meta.get("sha256") != _sha(result_path)
                    or not _current_native_views(state.get("native_inputs"))):
                return _result("NOT_MEASURED", "post-layout measurement-study inputs changed since A14")
            current, reason = measurements.validate_consumed_inputs(project, state["native_inputs"])
            if not current:
                return _result("NOT_MEASURED", "post-layout consumed model/include inputs changed since A14: " + reason)
            source = (state.get("bindings") or {}).get("source") or {}
            if isinstance(source, dict) and source.get("path") and not _current_native_views({"source": source}):
                return _result("NOT_MEASURED", "post-layout measurement-study source conditions changed since A14")
        # The existing MC producer discovers its runnable deck. Give it an
        # isolated study containing exactly the extracted deck, so it cannot
        # silently choose the earlier schematic TB or replace pre-layout MC.
        study = work / "statistics" / a7._style_slug(corner["style"]) / uuid.uuid4().hex
        target = study / "phase3" / "analog" / name
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bdir / "spec.json", target / "spec.json")
        for dirname in ("input", "phase1"):
            source = project / dirname
            dest = study / dirname
            if source.exists() and not dest.exists():
                dest.symlink_to(source, target_is_directory=True)
        # Relative includes in the extracted TB must keep referring to their
        # actual producing files after the MC producer moves the deck again.
        text = deck.read_text()
        text = re.sub(r"(?im)^(\s*\.(?:include|lib)\s+)([^\s]+)",
            lambda m: m[1] + str((deck.parent / m[2].strip("\"'")).resolve())
            if not Path(m[2].strip("\"'")).is_absolute() else m[0], text)
        if _one_style:
            # Independent style workers share the caller's CPU budget. Each
            # private copied deck owns one native thread; the original PRE
            # and POST decks are unchanged.
            text = re.sub(r"(?im)^\s*set\s+num_threads\s*=.*$", "", text)
            text = re.sub(r"(?im)^(\s*\.control\b[^\n]*)$", r"\1\nset num_threads=1", text)
        (target / f"tb_{name}.sp").write_text(text)
        selected = ((state.get("bindings") or {}).get("execution") or {}).get("ngspice_bin") if study_meta else None
        result = mc.run_block(study, name, container, pdk, n,
                              **({"ngspice_bin": selected} if selected else {}))
        coverage = mc._source_yield_coverage(project, str(spec.relative_to(project)),
                                              result.get("spec_yield") or {}, n)
        reports.append({"style": corner["style"], "study": str(study),
                        **result, "source_coverage": coverage})
    failed = any(r.get("verdict") == "FAIL" for r in reports)
    measured = not unmeasured_styles and bool(reports) and all(
        r.get("verdict") == "PASS" and r.get("mc_runs") == n and
        r["source_coverage"]["required"] and not r["source_coverage"]["missing"]
        for r in reports)
    return _result("FAIL" if failed else "PASS" if measured else "NOT_MEASURED",
                   "existing Monte Carlo producer ran on extracted post-layout decks",
                   [str(work / "statistics")], metrics={"corners": reports, "samples": n,
                        **({"unmeasured_styles": unmeasured_styles} if cfg.get("styles") is not None else {})},
                   **({"native_inputs": consumed} if consumed else {}))


def _ir_from_native_interconnect(measured: dict, setting: dict, work: Path) -> dict:
    """Reuse accepted full-RC endpoint voltages with the existing IR budget gate."""
    import ir_drop_budget_check as ir
    from decimal import Decimal
    records, outputs = [], []
    try:
        budget = (setting.get("arguments") or {}).get("budget_pct", ir._DEFAULT_BUDGET_PCT)
        if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not math.isfinite(budget) or budget <= 0:
            raise ValueError("IR budget must be a finite positive percentage")
        for case in measured.get("cases") or []:
            roles, feeds, ranges = (case.get(key) or {} for key in
                                     ("rail_roles", "feed_voltages", "pg_voltage_ranges"))
            power, ground = roles.get("vdd"), roles.get("vss")
            if not power or not ground or power == ground:
                raise ValueError("native case lacks distinct declared supply/ground networks")
            p, g = ranges.get(power) or {}, ranges.get(ground) or {}
            values = [feeds.get(power), feeds.get(ground), p.get("min_v"), p.get("max_v"),
                      g.get("min_v"), g.get("max_v")]
            if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values)
                    or not p.get("sampled_endpoints") or not g.get("sampled_endpoints")):
                raise ValueError("native case has no complete supply/ground endpoint voltages")
            vdd, vss = values[:2]
            if vdd <= vss or p["min_v"] > p["max_v"] or g["min_v"] > g["max_v"]:
                raise ValueError("native case has invalid rail voltage ranges")
            declared_vdd = (setting.get("arguments") or {}).get("vdd")
            if declared_vdd is not None and declared_vdd != vdd - vss:
                raise ValueError("explicit IR supply differs from the measured feed voltage")
            # Summing independent extrema is a conservative path bound; no
            # average-current or uniform-drop assumption is needed.
            number = lambda value: Decimal(str(value))
            droop = max(Decimal(0), number(vdd) - number(p["min_v"]))
            bounce = max(Decimal(0), number(g["max_v"]) - number(vss))
            path = work / ("native_ir-" + uuid.uuid4().hex + ".json")
            report = {"max_drop_mv": float(1000 * (droop + bounce)), "vdd": float(number(vdd) - number(vss)),
                      "supply_droop_mv": float(1000 * droop), "ground_bounce_mv": float(1000 * bounce),
                      "case": case.get("name"), "native_receipt": case.get("receipt"),
                      "rail_networks": {"vdd": power, "vss": ground},
                      "budget_source": "explicit project setting" if "budget_pct" in (setting.get("arguments") or {})
                          else "existing ir_drop_budget_check default; not a source-specified budget",
                      "scope": "conservative static IR bound for this supplied native OP case"}
            _write(path, report)
            passed, grade = ir.evaluate(path, None, budget)
            records.append({"status": "PASS" if passed else "FAIL", "measurement": report, "gate": grade})
            outputs.append(str(path))
        states = [row["status"] for row in records]
        return {"status": "FAIL" if "FAIL" in states else "PASS" if states else "NOT_MEASURED",
                "cases": records, "outputs": outputs,
                "scope": "only supplied full-RC native DC cases; no transient or omitted mission coverage"}
    except (ValueError, TypeError) as exc:
        return {"status": "FAIL" if any(row["status"] == "FAIL" for row in records) else "NOT_MEASURED",
                "detail": str(exc), "cases": records, "outputs": outputs}


def _mos_limits_from_consumed_models(model: str, views: dict) -> tuple[dict, dict]:
    """Read the actual wrapper's intrinsic model SOA parameters, without defaults."""
    import shlex
    import _analog_a8_extraction_wrapper as spice
    def active_cards(text):
        # Strip physical-line comments before joining continuations: a rating
        # mentioned in prose or after an end-of-line delimiter is not active
        # SPICE. Preserve quoted include paths and literal expressions.
        lines = []
        for raw in text.splitlines():
            line = raw.lstrip()
            if not line or line.startswith(("*", ";", "$", "//")):
                continue
            quote, end = None, len(line)
            for index, char in enumerate(line):
                if quote:
                    if char == quote:
                        quote = None
                elif char in ("'", '"'):
                    quote = char
                elif char in (";", "$") or line[index:index + 2] == "//":
                    end = index
                    break
            lines.append(line[:end])
        return spice.logical_lines("\n".join(lines))
    files = {Path(view["path"]).resolve(): view for view in views.values()
             if isinstance(view, dict) and view.get("path") and
             Path(view["path"]).suffix.lower() in (".lib", ".sp", ".spice")}
    fields = {key: "V" + key.upper() + "_MAX" for key in ("gs", "gd", "gb", "ds", "db", "sb")}
    observations, sources = {key: [] for key in fields}, {}
    wrappers = []
    pattern = re.compile(r"(?ims)^\s*\.subckt\s+" + re.escape(model) +
                         r"\s+([^\n]*)\n(.*?)^\s*\.ends\b[^\n]*")
    for path, view in files.items():
        for wrapper in pattern.finditer("\n".join(active_cards(path.read_text(errors="replace")))):
            if wrapper[1].lower().split()[:4] != ["d", "g", "s", "b"]:
                raise ValueError("MOS wrapper does not declare ordered d/g/s/b terminals")
            references, parameters = set(), []
            for line in spice.logical_lines(wrapper[2]):
                parts = line.split()
                if len(parts) >= 6 and parts[0].lower().startswith("n"):
                    references.add(parts[5].lower())
                if len(parts) >= 2 and parts[0].lower() in (".include", ".inc"):
                    name = shlex.split(line)[1]
                    candidate = Path(name)
                    candidate = candidate if candidate.is_absolute() else path.parent / candidate
                    candidate = candidate.resolve()
                    if candidate not in files:
                        raise ValueError("MOS parameter include is absent from consumed model closure")
                    parameters.append(candidate)
            if not references or not parameters:
                raise ValueError("MOS intrinsic model or parameter source is absent")
            found = set()
            for parameter in parameters:
                cards = active_cards(parameter.read_text(errors="replace"))
                for card in cards:
                    declaration = re.fullmatch(r"(?is)\s*\.model\s+(\S+)\s+(.*)", card)
                    if not declaration:
                        continue
                    if declaration[1].lower() not in references:
                        continue
                    found.add(declaration[1].lower())
                    token_pattern = re.compile(r'''"[^"]*"|'[^']*'|[=()]|[^\s=()'";]+''')
                    matches = list(token_pattern.finditer(declaration[2]))
                    end = 0
                    for match in matches:
                        if declaration[2][end:match.start()].strip():
                            raise ValueError("unsupported intrinsic model parameter syntax")
                        end = match.end()
                    if declaration[2][end:].strip():
                        raise ValueError("unsupported intrinsic model parameter syntax")
                    tokens = [match[0] for match in matches]
                    assignments, index = {}, 1  # first token is the native model type
                    while index + 2 < len(tokens):
                        if tokens[index + 1] != "=":
                            index += 1
                            continue
                        key, value = tokens[index].upper(), tokens[index + 2]
                        index += 3
                        if value == "(":
                            depth, parts = 1, [value]
                            while index < len(tokens) and depth:
                                value = tokens[index]
                                depth += (value == "(") - (value == ")")
                                parts.append(value)
                                index += 1
                            if depth:
                                raise ValueError("unterminated intrinsic model parameter expression")
                            value = "".join(parts)
                        assignments.setdefault(key, []).append(value)
                    for pair, field in fields.items():
                        values_text = assignments.get(field, [])
                        if not values_text:
                            raise ValueError("intrinsic MOS model has no explicit " + field)
                        values = [float(token.strip("'\"")) for token in values_text]
                        if any(not math.isfinite(value) or value <= 0 for value in values):
                            raise ValueError("intrinsic MOS voltage limit is invalid")
                        observations[pair].extend(values)
                sources[str(parameter)] = files[parameter]
            if found != references:
                raise ValueError("intrinsic MOS parameter declaration is absent or ambiguous")
            wrappers.append(str(path))
            sources[str(path)] = view
    if not wrappers or any(not values for values in observations.values()):
        raise ValueError("current consumed wrapper has no complete native MOS voltage limits: " + model)
    # A wrapper may select an RF variant. The minimum explicit bound across
    # its actual intrinsic declarations is conservative for every branch.
    return {pair: min(values) for pair, values in observations.items()}, {
        "wrappers": wrappers, "sources": sources,
        "limit_ranges": {pair: [min(values), max(values)] for pair, values in observations.items()},
        "selection": "explicit intrinsic SWSOA bounds; unselected branch ranges remain visible"}


def _mission_from_native_interconnect(measured: dict) -> dict:
    """Grade accepted native MOS terminal voltages using consumed PDK ratings."""
    views, cases = measured.get("native_inputs") or {}, []
    try:
        if not _current_native_views(views):
            raise ValueError("consumed native stress inputs are absent or changed")
        for case in measured.get("cases") or []:
            stress = case.get("mos_stress") or {}
            devices = stress.get("devices")
            if stress.get("status") != "PASS" or not isinstance(devices, list) or not devices:
                raise ValueError("native case has no complete accepted MOS terminal voltages")
            limits, sources = {}, {}
            for model in stress.get("source_models") or {}:
                limits[model], sources[model] = _mos_limits_from_consumed_models(model, views)
            violations, ambiguous = [], []
            for device in devices:
                model = device.get("model")
                values = device.get("pairs_v") or {}
                if model not in limits or set(values) != set(limits[model]) or any(
                        isinstance(value, bool) or not isinstance(value, (int, float)) or
                        not math.isfinite(value) or value < 0 for value in values.values()):
                    raise ValueError("native MOS model or terminal magnitude is absent/invalid")
                for pair, value in values.items():
                    low, high = sources[model]["limit_ranges"][pair]
                    observation = {"instance": device.get("instance"), "model": model, "pair": pair,
                                   "value_v": value, "possible_max_v": [low, high]}
                    if value > high:
                        violations.append(observation)
                    elif value > low:
                        ambiguous.append(observation)
            cases.append({"status": "FAIL" if violations else "NOT_MEASURED" if ambiguous else "PASS", "case": case.get("name"),
                          "devices": len(devices), "terminal_pairs": 6 * len(devices),
                          "violations": violations, "ambiguous_intrinsic_branch": ambiguous,
                          "limits": limits, "limit_sources": sources})
        if not _current_native_views(views):
            raise ValueError("consumed native stress inputs changed during derivation")
        return {"status": "FAIL" if any(row["status"] == "FAIL" for row in cases) else
                          "NOT_MEASURED" if not cases or any(row["status"] == "NOT_MEASURED" for row in cases)
                          else "PASS", "cases": cases,
                "scope": "MOS terminal stress only for the supplied accepted full-RC OP cases; no transient/lifetime claim"}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"status": "FAIL" if any(row["status"] == "FAIL" for row in cases) else "NOT_MEASURED",
                "detail": str(exc), "cases": cases}


def _reliability(project: Path, name: str, container: str, image: str, pdk: str,
                 cfg: dict) -> dict:
    """Execute the supplied mission deck; consume real thermal/EM reports."""
    import analog_real_corner_sweep as ars
    import _designs_root as dr
    import corner_yield_vs_spec_check as limits
    import thermal_screen_check as thermal
    import em_current_density_check as em
    import ir_drop_budget_check as ir
    import aging_derate_sta_check as aging
    import analog_bound_measurements as measurements

    _, work = _paths(project, name)
    work.mkdir(parents=True, exist_ok=True)
    records = {}
    outputs = []
    missing_inputs = []
    native_inputs = {}
    def remember(role, path):
        if path.is_file():
            native_inputs[role] = {"path": str(path.resolve()), "sha256": _sha(path)}
    interconnect = None
    def measured_interconnect():
        nonlocal interconnect
        if interconnect is None:
            import analog_native_em
            interconnect = analog_native_em.run(project, name, cfg.get("em") or {}, container=container)
            outputs.extend(Path(p) for p in interconnect.get("outputs", []))
            native_inputs.update({"interconnect:" + role: view for role, view in
                                  interconnect.get("native_inputs", {}).items()})
            for index, path in enumerate(interconnect.get("outputs", [])):
                remember("interconnect_output:" + str(index), Path(path))
        return interconnect
    remember("reliability_inputs", project / "phase3/analog" / name / "reliability_inputs.json")
    deck = project / str(cfg.get("deck") or "__missing_mission_deck__")
    spec = project / str(cfg.get("spec") or "__missing_reliability_spec__")
    bounds = limits._spec_limits(_read(spec))
    mission_missing = (["mission.deck"] if not deck.is_file() else []) + (
        ["mission.spec"] if not bounds else [])
    if (cfg.get("mission") or {}).get("from_em") is True:
        records["mission"] = _mission_from_native_interconnect(measured_interconnect())
    elif not mission_missing:
        remember("mission_deck", deck)
        remember("mission_spec", spec)
        native_inputs.update(measurements.consumed_input_views(project, deck))
        host = dr.resolve_host_root(project, container)
        ok, values, log, sim = ars._run_ngspice(container,
            ars._container_path(container, host, deck), deck_text=deck.read_text(),
            run_to_completion=True)
        logfile = work / f"reliability-{uuid.uuid4().hex}.ngspice.log"
        logfile.write_text(log or "")
        outputs.append(logfile)
        missing = [key for key in bounds if values.get(key) is None]
        bad = [key for key, lim in bounds.items() if values.get(key) is not None and
               (not math.isfinite(values[key]) or limits._violates(values[key], lim["min"], lim["max"]))]
        status = "FAIL" if bad or (not ok and not sim.get("stopped")) else (
            "PASS" if ok and bounds and not missing else "NOT_MEASURED")
        records["mission"] = {"status": status, "measurements": values,
                              "violations": bad, "missing": missing, "simulation": sim}
    else:
        missing_inputs.extend(mission_missing)
        records["mission"] = {"status": "NOT_MEASURED",
            "detail": "mission/stress inputs absent: " + ", ".join(mission_missing),
            "missing_inputs": mission_missing,
            "deck": str(deck) if cfg.get("deck") else None,
            "spec": str(spec) if cfg.get("spec") else None}
    # These existing programs evaluate supplied native reports; they do not
    # invent a thermal solution, an EM current or an aging corner.
    for key, module in (("thermal", thermal), ("ir", ir), ("em", em), ("aging", aging)):
        setting = cfg.get(key) or {}
        if key == "ir" and setting.get("from_em") is True:
            measured = _ir_from_native_interconnect(measured_interconnect(), setting, work)
            records[key] = {"status": measured["status"], "result": measured}
            outputs.extend(Path(p) for p in measured.get("outputs", []))
            continue
        if key == "em" and "cases" in setting:
            measured = measured_interconnect()
            records[key] = {"status": measured["status"], "result": measured}
            continue
        report = project / str(setting.get("report") or f"__missing_{key}_report__")
        if not report.is_file():
            feature = "requires_" + key
            if not setting and (cfg.get("_features") or {}).get(feature) is False:
                records[key] = {"status": "NOT_APPLICABLE", "detail":
                    f"the design declares {feature}=false; no {key} evidence was supplied",
                    "applicability": {feature: False}}
                continue
            missing_inputs.append(f"{key}.report")
            records[key] = {"status": "NOT_MEASURED", "detail": f"native {key} report absent"}
            continue
        remember(key + "_report", report)
        result_path = work / f"reliability_{key}-{uuid.uuid4().hex}.json"
        argv = [str(report), "--json", str(result_path)]
        for option, value in (setting.get("arguments") or {}).items():
            if value is False or value is None:
                continue
            if option == "assume_aging":
                continue  # A fresh report cannot be relabelled as aged evidence.
            argv.append("--" + option.replace("_", "-"))
            if value is not True:
                if option in ("die_source", "jmax", "tech_lef", "def_file", "pg_geometry", "fresh"):
                    path = project / value
                    remember(key + "_" + option, path)
                    argv.append(str(path))
                else:
                    argv.append(str(value))
        rc = module.main(argv)
        record = _read(result_path)
        records[key] = {"status": "PASS" if rc == 0 else "FAIL" if rc == 1 else "NOT_MEASURED",
                        "returncode": rc, "result": record}
        outputs.append(result_path)
    changed = [role for role, view in native_inputs.items()
               if not _current_native_views({role: view})]
    if changed:
        records["input_currentness"] = {"status": "NOT_MEASURED", "changed": changed}
    statuses = [r["status"] for r in records.values()]
    detail = "native mission/stress and thermal/IR/EM/aging evidence"
    if missing_inputs:
        detail += "; absent inputs: " + ", ".join(missing_inputs)
    return _result("FAIL" if "FAIL" in statuses else "NOT_MEASURED" if
                   "NOT_MEASURED" in statuses else "PASS", detail, outputs,
                   metrics=records, missing_inputs=missing_inputs, native_inputs=native_inputs)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("operation", choices=("pv", "extract", "resim", "statistics", "population", "pvt", "reliability"))
    parser.add_argument("project", type=Path)
    parser.add_argument("--block", required=True)
    parser.add_argument("--container", default="")
    parser.add_argument("--image", default="")
    parser.add_argument("--pdk", default="")
    parser.add_argument("--settings", default="{}")
    parser.add_argument("--json", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", args.block):
            raise ValueError("block is not a safe declared name")
        cfg = json.loads(args.settings)
        if not isinstance(cfg, dict):
            raise ValueError("step settings must be an object")
        function = {"pv": _pv, "extract": _extract, "resim": _resim,
                    "statistics": _statistics, "population": _population, "pvt": _pvt_studies,
                    "reliability": _reliability}[args.operation]
        report = function(args.project.resolve(), args.block, args.container,
                          args.image, args.pdk, cfg)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        report = _result("NOT_MEASURED", f"{args.operation} could not execute: {type(exc).__name__}: {exc}")
    _write(args.json, report)
    print(json.dumps(report, indent=2))
    return {"PASS": 0, "NOT_APPLICABLE": 0, "FAIL": 1, "NOT_MEASURED": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
