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
    # The existing block PV producer has no analog ERC engine. Its DRC/LVS
    # execution is useful evidence but cannot stand in for the missing ERC.
    record["erc"] = {"status": "NOT_MEASURED", "reason": "no native block ERC producer"}
    return _result("NOT_MEASURED", "native DRC/LVS executed; block ERC remains unmeasured"
                   if record.get("ran") else record.get("reason", "native PV did not run"),
                   reports, metrics=record)


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


def _pre_layout_measurements(project: Path, name: str, cfg: dict) -> tuple[dict, dict]:
    """Consume measured source-bound nominal state; never launch a PRE run."""
    import analog_real_corner_sweep as ars
    bdir, _ = _paths(project, name)
    net, tb = bdir / f"{name}.sp", bdir / f"tb_{name}.sp"
    if not net.is_file() or not tb.is_file():
        return {}, {"detail": "pre-layout circuit/testbench input is absent"}

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
    import _designs_root as dr
    from corner_yield_vs_spec_check import _spec_limits, _violates

    bdir, work = _paths(project, name)
    extraction = _read(work / "A13.json")
    data = extraction.get("metrics") or {}
    net, tb = bdir / f"{name}.sp", bdir / f"tb_{name}.sp"
    gds = bdir / f"{name}.gds"
    if extraction.get("status") != "PASS" or not all(p.is_file() for p in (net, tb, gds)):
        return _result("NOT_MEASURED", "post-layout performance requires A13 extraction and the A05 testbench")
    if data.get("layout_sha256") != _sha(gds) or data.get("netlist_sha256") != _sha(net):
        return _result("NOT_MEASURED", "A13 extraction does not describe the current layout/netlist")
    corners = data.get("corners") or []
    if not corners:
        return _result("NOT_MEASURED", "A13 measured no extraction corner")
    pre, pre_state = _pre_layout_measurements(project, name, cfg)
    if not pre:
        return _result("NOT_MEASURED", pre_state["detail"], metrics={"pre": pre_state})
    host_root = dr.resolve_host_root(project, container)
    rows, records, outputs = [], [], []
    ports = a7.subckt_ports(net.read_text(), name)
    if not ports:
        return _result("FAIL", "source netlist declares no block subcircuit")
    limits = _spec_limits(_read(bdir / "spec.json"))
    if not limits:
        return _result("NOT_MEASURED", "post-layout acceptance has no declared numeric spec bounds")
    for corner in corners:
        extracted = Path(corner["extracted_netlist"])
        if not extracted.is_file() or corner.get("sha256") != _sha(extracted):
            return _result("NOT_MEASURED", "extracted SPICE changed since A13")
        slug = a7._style_slug(corner["style"])
        raw = extracted.read_text(errors="replace")
        post_net = work / f"{name}_post_{slug}.sp"
        body, mapping = a7.post_layout_netlist(name, ports, raw,
            a7.model_binding_lines(net.read_text(), bdir, work))
        post_net.write_text(body)
        rp, ri = a7.rcx_nets(raw, name)
        post_text, dropped = a7.remap_probes(
            a7.post_layout_testbench(tb.read_text(), name, post_net.name, bdir, work),
            name, rp, ri, mapping)
        post_tb = work / f"tb_{name}_post_{slug}.sp"
        post_tb.write_text(post_text)
        ok, post, log, state = ars._run_ngspice(container,
            ars._container_path(container, host_root, post_tb),
            deck_text=post_tb.read_text(), run_to_completion=True)
        logpath = post_tb.with_suffix(".ngspice.log")
        logpath.write_text(log or "")
        outputs += [post_tb, logpath]
        if not ok:
            status = "NOT_MEASURED" if (state.get("stopped") or state.get("progress_stalled")
                or _interrupted(state.get("rc"))) else "FAIL"
            return _result(status, f"native resimulation failed: {logpath}", outputs,
                           metrics={"pre": pre_state, "simulation": state, "corners": records})
        absent_pre = [m for m in a7.declared_measurements(tb.read_text()) if pre.get(m) is None]
        lost = []
        supply, margin = a7._declared_rail_reference(tb.read_text())
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
                                     "max_delta_pct": max(deltas) if deltas else None})


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
        return _result("NOT_MEASURED", "post-layout statistics requires a declared sample count >= 2")
    if not corners:
        return _result("NOT_MEASURED", "no extracted post-layout testbench from A14")
    reports = []
    for corner in corners:
        deck = Path(corner["post_testbench"])
        if not deck.is_file():
            return _result("NOT_MEASURED", f"post-layout testbench absent: {deck}")
        post_net = Path(corner.get("post_netlist") or "")
        if not post_net.is_file() or corner.get("post_netlist_sha256") != _sha(post_net) or \
                corner.get("post_testbench_sha256") != _sha(deck):
            return _result("NOT_MEASURED", "post-layout circuit/testbench changed since A14")
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
        text = deck.read_text()
        text = re.sub(r"(?im)^(\s*\.(?:include|lib)\s+)([^\s]+)",
            lambda m: m[1] + str((deck.parent / m[2].strip("\"'")).resolve())
            if not Path(m[2].strip("\"'")).is_absolute() else m[0], text)
        (target / f"tb_{name}.sp").write_text(text)
        result = mc.run_block(study, name, container, pdk, n)
        reports.append({"style": corner["style"], **result})
    failed = any(r.get("verdict") == "FAIL" for r in reports)
    from corner_yield_vs_spec_check import _spec_limits
    required = _spec_limits(_read(bdir / "spec.json"))
    measured = bool(required) and all(
        r.get("verdict") == "PASS" and r.get("mc_runs") == n and
        all((r.get("spec_yield") or {}).get(key, {}).get("runs_scored") == n
            and (r.get("spec_yield") or {}).get(key, {}).get("yield_pct") is not None
            for key in required) for r in reports)
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
    import aging_derate_sta_check as aging

    _, work = _paths(project, name)
    work.mkdir(parents=True, exist_ok=True)
    records = {}
    outputs = []
    deck = project / str(cfg.get("deck") or "__missing_mission_deck__")
    spec = project / str(cfg.get("spec") or "__missing_reliability_spec__")
    if deck.is_file():
        host = dr.resolve_host_root(project, container)
        ok, values, log, sim = ars._run_ngspice(container,
            ars._container_path(container, host, deck), deck_text=deck.read_text(),
            run_to_completion=True)
        logfile = work / "reliability.ngspice.log"
        logfile.write_text(log or "")
        outputs.append(logfile)
        bounds = limits._spec_limits(_read(spec))
        missing = [key for key in bounds if values.get(key) is None]
        bad = [key for key, lim in bounds.items() if values.get(key) is not None and
               (not math.isfinite(values[key]) or limits._violates(values[key], lim["min"], lim["max"]))]
        status = "FAIL" if bad or (not ok and not sim.get("stopped")) else (
            "PASS" if ok and bounds and not missing else "NOT_MEASURED")
        records["mission"] = {"status": status, "measurements": values,
                              "violations": bad, "missing": missing, "simulation": sim}
    else:
        records["mission"] = {"status": "NOT_MEASURED", "detail": "no foundry mission/stress deck"}
    # These existing programs evaluate supplied native reports; they do not
    # invent a thermal solution, an EM current or an aging corner.
    for key, module in (("thermal", thermal), ("em", em), ("aging", aging)):
        setting = cfg.get(key) or {}
        report = project / str(setting.get("report") or f"__missing_{key}_report__")
        if not report.is_file():
            records[key] = {"status": "NOT_MEASURED", "detail": f"native {key} report absent"}
            continue
        argv = [str(report), "--json", str(work / f"reliability_{key}.json")]
        for option, value in (setting.get("arguments") or {}).items():
            if value is False or value is None:
                continue
            if option == "assume_aging":
                continue  # A fresh report cannot be relabelled as aged evidence.
            argv.append("--" + option.replace("_", "-"))
            if value is not True:
                argv.append(str(project / value) if option in
                            ("die_source", "jmax", "tech_lef", "def_file", "pg_geometry", "fresh")
                            else str(value))
        rc = module.main(argv)
        record = _read(work / f"reliability_{key}.json")
        records[key] = {"status": "PASS" if rc == 0 else "FAIL" if rc == 1 else "NOT_MEASURED",
                        "returncode": rc, "result": record}
        outputs.append(work / f"reliability_{key}.json")
    statuses = [r["status"] for r in records.values()]
    return _result("FAIL" if "FAIL" in statuses else "NOT_MEASURED" if
                   "NOT_MEASURED" in statuses else "PASS",
                   "native mission/stress and thermal/EM/aging evidence", outputs,
                   metrics=records)


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
