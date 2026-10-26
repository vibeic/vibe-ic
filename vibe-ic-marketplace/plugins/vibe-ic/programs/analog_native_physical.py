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
import copy
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

from _atomic_artefact import write_text as atomic_write_text


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


_A16_OP_CONVERGENCE_OPTIONS = {
    "itl1": 500,
    "gminsteps": 100,
    "srcsteps": 100,
}


def _a16_op_convergence_deck(text: str) -> tuple[str, dict]:
    """Add only stock-ngspice DC operating-point convergence controls.

    This is deliberately narrower than a generic simulator-options escape
    hatch: A16 may ask for the fixed, documented set below only on a pure OP
    mission.  Tolerances, circuit conductances and the acceptance spec remain
    owned by the supplied deck and spec.
    """
    logical = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("*", ";", "$", "//")):
            continue
        logical.append(line.casefold())
    has_op = any(re.fullmatch(r"\.?op", line) for line in logical)
    other_analyses = [line for line in logical if re.match(
        r"^\.?(?:ac|dc|tran|noise|pz|tf|disto|sens)(?:\s|$)", line)]
    if not has_op or other_analyses:
        raise ValueError("A16 op_convergence requires a pure OP mission deck")
    protected = "|".join(map(re.escape, _A16_OP_CONVERGENCE_OPTIONS))
    if any(re.search(rf"\b(?:{protected})\s*=", line) for line in logical
           if line.startswith((".option ", ".options "))):
        raise ValueError(
            "A16 op_convergence refuses a deck that already sets its protected options")
    card = ".options " + " ".join(
        f"{key}={value}" for key, value in _A16_OP_CONVERGENCE_OPTIONS.items())
    lines = text.splitlines()
    insert = next((index for index, line in enumerate(lines)
                   if re.match(r"(?i)^\s*\.end\s*$", line)), len(lines))
    lines.insert(insert, card)
    derived = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    return derived, {
        "enabled": True,
        "analysis_scope": "OP only",
        "options": dict(_A16_OP_CONVERGENCE_OPTIONS),
        "basis": ("stock ngspice DC iteration limit plus built-in GMIN and "
                  "source stepping; no tolerance, topology, stimulus, or "
                  "acceptance change"),
    }


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
                 options: dict, run: Callable, settings: dict) -> dict:
    _, work = _paths(project, name)
    report = work / f"{step}-{uuid.uuid4().hex}.json"
    argv = [operation, str(project), "--block", name, "--json", str(report),
            "--container", str(options.get("container") or ""),
            "--pdk", str(options.get("pdk") or ""),
            "--image", str(options.get("image") or ""),
            "--settings", json.dumps(settings)]
    execution = run("analog_native_physical.py", argv, outputs=[str(report)])
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
                    "tech_lef", "wire_width_um", "via_pad_half_um"):
            if cfg.get(key) is not None:
                argv += ["--" + key.replace("_", "-"), str(cfg[key])]
        execution = run("analog_a5_layout_emit.py", argv,
                        outputs=[str(report), str(bdir / "layout.mag"),
                                 str(bdir / f"{name}.gds")])
        doc = _read(report)
        measured = (doc.get("blocks") or {}).get(name, {})
        rc = execution.get("returncode")
        state = measured.get("result", doc.get("result"))
        produced = all(p.is_file() and p.stat().st_size for p in
                       (bdir / "layout.mag", bdir / f"{name}.gds"))
        measured_failure = (state in ("FAIL", "BLOCKING")
                            or bool(measured.get("violations")))
        if measured_failure:
            status = "FAIL"
        elif _interrupted(rc):
            status = "NOT_MEASURED"
        elif rc == 0 and state == "OK" and produced:
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
    return _native_call(operations[step_id], step_id, project, name, options, run, cfg)


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
                                   namespace=f"analog/{name}/a13_{slug}", pdk_root=root)
        except lc.Refusal as exc:
            status = "NOT_MEASURED" if (lc.tool_stop_reason(exc.code) or
                exc.code in ("LL_IMAGE_INCAPABLE", "LL_CONFIG_RESOLVE_FAILED")) else "FAIL"
            return _result(status, f"{exc.code}: {exc}", metrics={"corners": corners})
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
    return _result("PASS", "native Magic.RCX extraction completed; no resimulation run",
                   [c["extracted_netlist"] for c in corners],
                   metrics={"corners": corners, "layout_sha256": _sha(gds),
                            "netlist_sha256": _sha(net), "magic_tech": str(tech)})


def _current_native_views(views: dict) -> bool:
    return isinstance(views, dict) and bool(views) and all(
        isinstance(view, dict) and view.get("path") and Path(view["path"]).is_file()
        and view.get("sha256") == _sha(Path(view["path"])) for view in views.values())


def _portable_path(project: Path, value: str) -> str:
    """Publish project-owned receipt paths relative to their transfer unit."""
    path = Path(value)
    try:
        return str(path.resolve().relative_to(project.resolve()))
    except (OSError, ValueError):
        return str(path)


def _portable_native_views(project: Path, views: dict) -> dict:
    """Keep native-input identities while making project-owned paths portable."""
    portable = {}
    for role, view in (views or {}).items():
        if not isinstance(view, dict):
            portable[role] = view
            continue
        item = dict(view)
        if item.get("path"):
            item["path"] = _portable_path(project, item["path"])
        if role.startswith("include:"):
            role = "include:" + item.get("path", role.removeprefix("include:"))
        portable[role] = item
    return portable


def _portable_measurement_state(project: Path, state: dict) -> dict:
    """Return the receipt form of a completed native measurement study."""
    portable = copy.deepcopy(state)
    portable["native_inputs"] = _portable_native_views(project, portable.get("native_inputs") or {})
    source = (portable.get("bindings") or {}).get("source")
    if isinstance(source, dict) and source.get("path"):
        source["path"] = _portable_path(project, source["path"])
    for execution in portable.get("executions") or []:
        if isinstance(execution, dict) and execution.get("log"):
            execution["log"] = _portable_path(project, execution["log"])
    return portable


def _transferred_project_root(project: Path, work: Path, recorded: str) -> Path | None:
    """Infer the old root only from the complete canonical A14 producer suffix."""
    path = Path(recorded)
    if not path.is_absolute():
        return project.resolve()
    try:
        path.resolve().relative_to(project.resolve())
        return project.resolve()
    except (OSError, ValueError):
        pass
    suffix = work.resolve().relative_to(project.resolve()).parts
    parts = path.parts
    hits = [i for i in range(len(parts) - len(suffix) + 1)
            if tuple(parts[i:i + len(suffix)]) == suffix]
    if len(hits) != 1:
        return None
    return Path(*parts[:hits[0]])


def _transferred_path(project: Path, producer_root: Path, recorded: str) -> Path | None:
    """Resolve one receipt reference without accepting an escaping/foreign path."""
    raw = Path(recorded)
    if not raw.is_absolute():
        candidate = project / raw
    else:
        try:
            relative = raw.relative_to(producer_root)
        except ValueError:
            return None
        candidate = project / relative
    try:
        resolved = candidate.resolve()
        resolved.relative_to(project.resolve())
    except (OSError, ValueError):
        return None
    return resolved


def _transferred_native_views(project: Path, producer_root: Path, views: dict) -> dict | None:
    """Rebind and hash-check project-owned inputs of a transferred study."""
    if not isinstance(views, dict) or not views:
        return None
    rebound = {}
    for role, view in views.items():
        if not isinstance(view, dict) or not view.get("path") or not view.get("sha256"):
            return None
        # This is producer provenance, not an input consumed by A15.
        if role == "native_binary":
            rebound[role] = dict(view)
            continue
        path = _transferred_path(project, producer_root, view["path"])
        if path is None or not path.is_file() or _sha(path) != view["sha256"]:
            return None
        new_role = "include:" + str(path) if role.startswith("include:") else role
        rebound[new_role] = {**view, "path": str(path)}
    return rebound


def _pre_measurement_study(project: Path, net: Path, candidates: list,
                           measured_log: Callable) -> tuple[dict, dict] | None:
    """Reuse an explicitly adopted OP study; do not call it canonical TB evidence."""
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
        if str((bindings.get("analysis") or {}).get("kind", "")).upper() != "OP":
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
            "comparison_inputs": comparison_inputs, "reused": True, "scope": record.get("scope")}
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
    study = _pre_measurement_study(project, net, candidates, measured_log)
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


def _resim(project: Path, name: str, container: str, image: str, pdk: str,
           cfg: dict) -> dict:
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
        atomic_write_text(post_tb, post_text)
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
            _write(result_path, _portable_measurement_state(project, state))
            study_meta = {"result": _portable_path(project, str(result_path)), "sha256": _sha(result_path),
                "pre_result": _portable_path(project, pre_state["result"]),
                "pre_result_sha256": pre_state["result_sha256"],
                "native_inputs": _portable_native_views(project, state["native_inputs"])}
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
            atomic_write_text(logpath, log or "")
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
        records.append({"style": corner["style"],
                        "post_testbench": _portable_path(project, str(post_tb)),
                        "post_netlist": _portable_path(project, str(post_net)), "measurements": post,
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
    status = "FAIL" if measured_failure else "NOT_MEASURED" if incomplete else "PASS"
    return _result(status, "post-layout native performance and pre/post comparison",
                   outputs, metrics={"pre": {**pre_state, "measurements": pre},
                                     "corners": records, "specs": rows,
                                     "max_delta_pct": max(deltas) if deltas else None},
                   **({"native_inputs": _portable_native_views(project, consumed_inputs)}
                      if study_pre else {}))


def _statistics(project: Path, name: str, container: str, image: str, pdk: str,
                cfg: dict) -> dict:
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
    spec = bdir / "spec.json"
    if not spec.is_file():
        return _result("NOT_MEASURED", f"post-layout statistics source limits absent: {spec}",
                       missing_inputs=[str(spec)])
    reports = []
    for corner in corners:
        producer_root = _transferred_project_root(project, work, corner.get("post_testbench") or "")
        deck = (_transferred_path(project, producer_root, corner.get("post_testbench") or "")
                if producer_root is not None else None)
        if deck is None or not deck.is_file():
            return _result("NOT_MEASURED",
                           f"post-layout testbench absent or foreign: {corner.get('post_testbench')}")
        post_net = _transferred_path(project, producer_root, corner.get("post_netlist") or "")
        if post_net is None or not post_net.is_file() or corner.get("post_netlist_sha256") != _sha(post_net) or \
                corner.get("post_testbench_sha256") != _sha(deck):
            return _result("NOT_MEASURED", "post-layout circuit/testbench changed since A14")
        study_meta = corner.get("native_measurement_study")
        if study_meta:
            import analog_bound_measurements as measurements
            result_path = _transferred_path(project, producer_root,
                                            study_meta.get("result") or "__missing_post_study__")
            if result_path is None:
                return _result("NOT_MEASURED", "post-layout measurement-study receipt is foreign")
            state = _read(result_path)
            views = _transferred_native_views(project, producer_root,
                study_meta.get("native_inputs") or state.get("native_inputs"))
            if (not result_path.is_file() or study_meta.get("sha256") != _sha(result_path)
                    or views is None):
                return _result("NOT_MEASURED", "post-layout measurement-study inputs changed since A14")
            source = (state.get("bindings") or {}).get("source") or {}
            if isinstance(source, dict) and source.get("path"):
                source_path = _transferred_path(project, producer_root, source["path"])
                if source_path is None or not source_path.is_file() or source.get("sha256") != _sha(source_path):
                    return _result("NOT_MEASURED", "post-layout measurement-study source conditions changed since A14")
        # The existing MC producer discovers its runnable deck. Give it an
        # isolated study containing exactly the extracted deck, so it cannot
        # silently choose the earlier schematic TB or replace pre-layout MC.
        study = work / "statistics" / a7._style_slug(corner["style"])
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
        include_re = re.compile(r"(?im)^(\s*\.(?:include|lib)\s+)([^\s]+)")
        def relocated_include(match, source_dir, aliases=None):
            token = match[2].strip("\"'")
            path = (_transferred_path(project, producer_root, token)
                    if Path(token).is_absolute() else (source_dir / token).resolve())
            if path is None:
                return match[0]
            path = (aliases or {}).get(path, path)
            return match[1] + str(path)
        staged_net = target / post_net.name
        staged_net.write_text(include_re.sub(
            lambda match: relocated_include(match, post_net.parent), post_net.read_text()))
        text = include_re.sub(lambda match: relocated_include(
            match, deck.parent, {post_net.resolve(): staged_net.resolve()}), deck.read_text())
        staged_deck = target / f"tb_{name}.sp"
        staged_deck.write_text(text)
        if study_meta:
            expected = measurements.consumed_input_views(project, staged_deck)
            received = {(str(Path(view["path"]).resolve()), view["sha256"])
                        for role, view in views.items() if role.startswith("include:")}
            for view in expected.values():
                path = Path(view["path"]).resolve()
                if path == staged_net.resolve():
                    continue  # derived only after the sealed source netlist passed its hash check above
                if (str(path), view["sha256"]) not in received:
                    return _result("NOT_MEASURED",
                        "post-layout consumed model/include inputs changed since A14")
            validation_inputs = dict(expected)
            validation_inputs["deck"] = {"path": str(staged_deck), "sha256": _sha(staged_deck)}
            current, reason = measurements.validate_consumed_inputs(project, validation_inputs)
            if not current:
                return _result("NOT_MEASURED",
                    "post-layout consumed model/include inputs changed since A14: " + reason)
        result = mc.run_block(study, name, container, pdk, n)
        coverage = mc._source_yield_coverage(project, str(spec.relative_to(project)),
                                              result.get("spec_yield") or {}, n)
        reports.append({"style": corner["style"], **result, "source_coverage": coverage})
    failed = any(r.get("verdict") == "FAIL" for r in reports)
    measured = bool(reports) and all(
        r.get("verdict") == "PASS" and r.get("mc_runs") == n and
        r["source_coverage"]["required"] and not r["source_coverage"]["missing"]
        for r in reports)
    return _result("FAIL" if failed else "PASS" if measured else "NOT_MEASURED",
                   "existing Monte Carlo producer ran on extracted post-layout decks",
                   [str(work / "statistics")], metrics={"corners": reports, "samples": n})


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
    remember("reliability_inputs", project / "phase3/analog" / name / "reliability_inputs.json")
    deck = project / str(cfg.get("deck") or "__missing_mission_deck__")
    spec = project / str(cfg.get("spec") or "__missing_reliability_spec__")
    bounds = limits._spec_limits(_read(spec))
    mission_missing = (["mission.deck"] if not deck.is_file() else []) + (
        ["mission.spec"] if not bounds else [])
    if not mission_missing:
        remember("mission_deck", deck)
        remember("mission_spec", spec)
        native_inputs.update(measurements.consumed_input_views(project, deck))
        execution_deck = deck
        convergence = {"enabled": False}
        if cfg.get("op_convergence") is True:
            derived, convergence = _a16_op_convergence_deck(deck.read_text())
            execution_deck = work / f"reliability-op-{uuid.uuid4().hex}.sp"
            atomic_write_text(execution_deck, derived)
            remember("mission_execution_deck", execution_deck)
            outputs.append(execution_deck)
        elif cfg.get("op_convergence") not in (None, False):
            raise ValueError("A16 op_convergence must be true or false")
        host = dr.resolve_host_root(project, container)
        ok, values, log, sim = ars._run_ngspice(container,
            ars._container_path(container, host, execution_deck),
            deck_text=execution_deck.read_text(),
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
                              "violations": bad, "missing": missing,
                              "simulation": sim, "op_convergence": convergence}
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
        if key == "em" and "cases" in setting:
            import analog_native_em
            measured = analog_native_em.run(project, name, setting, container=container)
            records[key] = {"status": measured["status"], "result": measured}
            outputs.extend(Path(path) for path in measured.get("outputs", []))
            native_inputs.update({"interconnect:" + role: view for role, view in
                                  measured.get("native_inputs", {}).items()})
            for index, path in enumerate(measured.get("outputs", [])):
                remember("interconnect_output:" + str(index), Path(path))
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
    parser.add_argument("operation", choices=("pv", "extract", "resim", "statistics", "reliability"))
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
                    "statistics": _statistics, "reliability": _reliability}[args.operation]
        report = function(args.project.resolve(), args.block, args.container,
                          args.image, args.pdk, cfg)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        report = _result("NOT_MEASURED", f"{args.operation} could not execute: {type(exc).__name__}: {exc}")
    _write(args.json, report)
    print(json.dumps(report, indent=2))
    return {"PASS": 0, "NOT_APPLICABLE": 0, "FAIL": 1, "NOT_MEASURED": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
