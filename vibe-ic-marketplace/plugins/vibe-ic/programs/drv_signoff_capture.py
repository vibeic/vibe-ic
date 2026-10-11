#!/usr/bin/env python3
"""Capture raw post-route DRV evidence in fresh pinned OpenSTA processes.

The plan names actual routed inputs and stage receipts; this program never
invents a missing stage, pin class, owner approval, or threshold.  It writes a
bundle for drv_signoff_judge, which remains the sole verdict authority.
"""
from __future__ import annotations

import argparse
import codecs
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_text  # noqa: E402
import _eda_image  # noqa: E402
import _docker_memory  # noqa: E402
import _docker_watchdog  # noqa: E402
import _watchdog  # noqa: E402
import _container_exec as _ce  # noqa: E402
import librelane_contract as _ll  # noqa: E402
from drv_signoff_anchor import image_pdk_anchor  # noqa: E402
from drv_signoff_census import derive as derive_census  # noqa: E402
from drv_signoff_annotation import derive as derive_annotation  # noqa: E402
from drv_signoff_judge import KINDS, _COMMAND, _sha, parse_check_types  # noqa: E402

_COUNTER = re.compile(
    r"(?m)^DRV_COUNTER\s+(max_slew|max_capacitance|max_fanout)\s+(\d+)\s*$")
_MAX_TOOL_LOG_BYTES = 16 * 1024 * 1024
_READ_LOG_BYTES = 64 * 1024
_TOOL_ERROR = re.compile(r"^Error(?:\s|:)")


def _ref(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"capture input absent: {path}")
    return {"path": str(path.resolve()), "sha256": _sha(path)}


def _tcl(path: Path) -> str:
    value = str(path.resolve())
    if any(c in value for c in "{}\\\n\r"):
        raise ValueError("unsafe Tcl path")
    return "{" + value + "}"


def _has_tool_error(raw: Path) -> bool:
    """Check every line start without holding a long OpenSTA line in memory."""
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    prefix = ""

    def scan(text: str) -> bool:
        nonlocal prefix
        parts = text.split("\n")
        for index, part in enumerate(parts):
            prefix += part[:max(0, 6 - len(prefix))]
            if _TOOL_ERROR.match(prefix):
                return True
            if index < len(parts) - 1:
                if _TOOL_ERROR.match(prefix + "\n"):
                    return True
                prefix = ""
        return False

    with raw.open("rb") as stream:
        while chunk := stream.read(_READ_LOG_BYTES):
            if scan(decoder.decode(chunk)):
                return True
        return scan(decoder.decode(b"", final=True))


def _run_fresh(script: Path, roots: set[Path], *, image: str) -> str:
    """Supervise this one named OpenSTA container; retain its bounded raw log."""
    mounts = []
    for root in sorted(roots):
        root = root.resolve()
        mounts.extend(("-v", f"{root}:{root}"))
    name = _docker_watchdog.ephemeral_container_name("vibeic_drv_sta")
    raw = script.with_suffix(".tool.log")
    cidfile = script.with_suffix(".container.cid")
    argv = ["docker", "run", *_docker_memory.docker_memory_flags(),
            "--rm", "--network", "none", "--cidfile", str(cidfile),
            "--name", name,
            *mounts, image, "--skip", "bash", "-c",
            f"sta -no_init -exit {shlex.quote(str(script.resolve()))}"]
    if "--memory" not in argv:
        # An opted-out or undeterminable ceiling is a refusal here, never an
        # unbounded OpenSTA container.
        raise RuntimeError("NOT_MEASURED: OpenSTA memory ceiling unavailable")

    def launch(cmd, **kw):
        kw.pop("stdout", None)
        kw.pop("stderr", None)
        with raw.open("wb") as stream:
            return subprocess.Popen(cmd, stdout=stream, stderr=subprocess.STDOUT,
                                    start_new_session=True, **kw)

    def output_limit():
        try:
            if raw.stat().st_size >= _MAX_TOOL_LOG_BYTES:
                return f"OpenSTA raw log reached {_MAX_TOOL_LOG_BYTES} bytes"
        except OSError:
            pass
        return None

    if _ce.no_container_route():
        # The enclosing fresh EDA image already supplies the runtime. Use
        # the same attested LOCAL runner as the native LibreLane producers.
        local_argv = ["docker", "run", *_docker_memory.docker_memory_flags(),
                      "--rm", "--network", "none", *mounts, image, "--skip",
                      "bash", "-c", f"sta -no_init -exit {shlex.quote(str(script.resolve()))}"]
        done = _ll.run_container(local_argv, supervised=True, log=raw)
        # run_container returns normal output; its log argument only salvages
        # interrupted runs. Persist the native transcript for this consumer.
        raw.write_text((done.stdout or "") + (done.stderr or ""))
        outcome, rc, err = "natural", done.returncode, done.stderr or ""
    else:
        result = _watchdog.run_supervised(
            argv, log_path=raw, output_progress=False,
            cpu_probe=_docker_watchdog.ephemeral_container_cpu_probe(name),
            kill=_docker_watchdog.ephemeral_container_reap(name),
            popen_factory=launch, abort_probe=output_limit)
        outcome, rc, err = result.outcome, result.rc, result.err
    try:
        size = raw.stat().st_size
        if size >= _MAX_TOOL_LOG_BYTES:
            raise RuntimeError(
                f"NOT_MEASURED: OpenSTA raw log reached byte ceiling "
                f"{_MAX_TOOL_LOG_BYTES}; raw={raw}")
        tool_error = _has_tool_error(raw)
        with raw.open("rb") as stream:
            head = stream.read(4096)
            stream.seek(max(0, size - _READ_LOG_BYTES))
            tail = stream.read(_READ_LOG_BYTES)
        body = (head + b"\n" + tail).decode("utf-8", errors="replace")
    except OSError as exc:
        raise RuntimeError(
            f"NOT_MEASURED: OpenSTA raw log unavailable; raw={raw}; {exc}") from exc
    if outcome != "natural" or rc or tool_error:
        raise RuntimeError(
            f"NOT_MEASURED: fresh OpenSTA stopped/over-limit "
            f"outcome={outcome} rc={rc} tool_error={tool_error}; raw={raw}; "
            f"watchdog={err[-500:]}; tool={body[-1000:]}")
    return body


def _census_script(out: Path) -> str:
    """Ask linked OpenSTA for the final netlist's pins, nets and clock cone."""
    return '''
set _drv_clock_pins [list]
set _drv_sinks [get_pins -hierarchical * -filter {is_register_clock==true}]
if {[llength $_drv_sinks]} {
  foreach _p [get_fanin -to $_drv_sinks -flat -trace_arcs enabled] {
    lappend _drv_clock_pins [get_full_name $_p]
  }
}
foreach _clock [all_clocks] {
  foreach _p [get_property $_clock sources] {
    lappend _drv_clock_pins [get_full_name $_p]
  }
}
set _drv_clock_pins [lsort -unique $_drv_clock_pins]
set _drv_f [open ''' + _tcl(out / "pin_census.tsv") + ''' w]
foreach _kind {port pin} {
  if {$_kind eq "port"} { set _pins [get_ports *] } else { set _pins [get_pins -hierarchical *] }
foreach _p $_pins {
  set _name [get_full_name $_p]
  if {[string first "\\t" $_name] >= 0 || [string first "\\n" $_name] >= 0} {
    error "unsafe pin name in DRV census"
  }
  set _inst ""
  if {$_kind eq "pin"} { set _inst [get_cells -of_objects $_p] }
  if {$_kind eq "pin" && [get_property $_p is_hierarchical]} { continue }
  set _cell ""
  set _inst_name ""
  set _cell_pin ""
  if {$_kind eq "pin"} {
    set _inst_name [get_full_name $_inst]
    set _cell [get_property $_inst ref_name]
    set _cell_pin [get_property $_p lib_pin_name]
    set _driver [sta::Pin_is_driver $_p]
    set _logic [sta::pin_sim_logic_value $_p]
    set _ideal [sta::is_ideal_clock $_p]
  } else {
    set _driver [expr {[get_property $_p direction] in {input inout}}]
    set _logic X
    set _ideal 0
  }
  if {$_kind eq "port"} {
    set _net [get_nets -quiet $_name]
  } else {
    set _net [get_nets -of_objects $_p]
  }
  set _net_name ""
  if {[llength $_net] && $_net ne "NULL"} { set _net_name [get_full_name $_net] }
  set _activity [get_property $_p activity]
  set _origin [lindex $_activity end]
  set _rise [get_property $_p slew_max_rise]
  set _fall [get_property $_p slew_max_fall]
  puts $_drv_f [join [list $_name $_kind [get_property $_p direction] $_driver \
       $_inst_name $_cell $_cell_pin $_net_name $_origin $_rise $_fall \
       [expr {$_origin eq "clock" || $_name in $_drv_clock_pins}] \
       $_logic $_ideal] "\\t"]
}
}
close $_drv_f
report_disabled_edges > ''' + _tcl(out / "disabled_edges.rpt") + '''
set _drv_n [open ''' + _tcl(out / "net_census.rpt") + ''' w]
close $_drv_n
foreach _net [get_nets -hierarchical *] {
  report_net -digits 9 [get_full_name $_net] >> ''' + _tcl(out / "net_census.rpt") + '''
}
'''


def _script(plan: dict, scene: dict, out: Path, *, control: bool,
            max_count: int) -> str:
    libs = [Path(item["path"]) for item in scene["linked_liberties"]]
    for path in libs:
        _ref(path)
    netlist = Path(plan["identity"]["artifacts"]["sta_netlist"]["path"])
    sdc = Path(plan["current"]["sources"]["signoff_sdc"]["path"])
    spef = Path(scene["spef"]["path"])
    for path in (netlist, sdc, spef):
        _ref(path)
    recipe = (plan.get("current") or {}).get("ocv_recipe") or {}
    if recipe:
        try:
            early, late = float(recipe["early"]), float(recipe["late"])
            refs = list(recipe["source_refs"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("DRV OCV recipe malformed") from exc
        if not (0 < early <= 1 <= late) or not refs:
            raise ValueError("DRV OCV recipe outside required flat-OCV bounds")
        for item in refs:
            if not isinstance(item, dict) or not item.get("path"):
                raise ValueError("DRV OCV recipe source reference malformed")
            ref = _ref(Path(item["path"]))
            if item.get("sha256") != ref["sha256"]:
                raise ValueError("DRV OCV recipe source changed")
        native = recipe.get("native_measurement_ref")
        if native is not None:
            ref = _ref(Path(native.get("path") or ""))
            if native.get("sha256") != ref["sha256"]:
                raise ValueError("native OCV measurement source changed")
    prefix = "".join(f"read_liberty {_tcl(path)}\n" for path in libs)
    prefix += (f"read_verilog {_tcl(netlist)}\n"
               f"link_design {{{plan['top']}}}\n"
               f"read_sdc {_tcl(sdc)}\n"
               + (f"set_timing_derate -early {early}\n"
                  f"set_timing_derate -late {late}\n" if recipe else "")
               + f"read_spef {_tcl(spef)}\n"
               + "set_propagated_clock [all_clocks]\n")
    if control:
        limits = scene["positive_control_limits"]
        prefix += ("set_max_fanout 1 [current_design]\n"
                   f"set_max_transition {limits['max_slew']} [current_design]\n"
                   f"set_max_capacitance {limits['max_capacitance']} [current_design]\n")
        return (prefix + f"{_COMMAND} -digits 6 -max_count {max_count} > {_tcl(out / 'positive_control.rpt')}\n"
                f"set _f [open {_tcl(out / 'positive_control_counters.log')} w]\n"
                + "".join(
                    f'puts $_f "DRV_COUNTER {kind} [sta::{kind}_violation_count]"\n'
                    for kind in KINDS) + "close $_f\n")
    return (prefix
            + _census_script(out)
            + f"report_parasitic_annotation -report_unannotated > {_tcl(out / 'annotation.rpt')}\n"
            + f"report_clock_properties [all_clocks] > {_tcl(out / 'clocks.rpt')}\n"
            + f"{_COMMAND} -digits 6 -max_count {max_count} > {_tcl(out / 'violators.rpt')}\n"
            + f"report_check_types -max_slew -max_capacitance -max_fanout -verbose -digits 6 -max_count {max_count} > {_tcl(out / 'all_limits.rpt')}\n"
            + f"set _f [open {_tcl(out / 'counters.log')} w]\n"
            + "".join(
                f'puts $_f "DRV_COUNTER {kind} [sta::{kind}_violation_count]"\n'
                for kind in KINDS) + "close $_f\n")


def _spef_extraction_receipt(plan: dict, scene: dict, out: Path) -> dict:
    """Bind one captured SPEF to the RCX producer record already on disk.

    The capture plan carries the SPEF bytes, but it is not itself an
    extraction receipt.  The RCX step's own ``vibeic_receipt.json`` is the
    authority for the output digest and its recorded route input; the
    adjacent ``COMMANDS`` file is the only command provenance we publish.
    Missing, ambiguous, changed, or cross-corner records refuse here rather
    than letting the judge infer provenance from file presence.
    """
    spef = Path(scene["spef"]["path"]).resolve()
    rcx_dir = spef.parent.parent
    source_receipt = rcx_dir / "vibeic_receipt.json"
    command_path = rcx_dir / "COMMANDS"
    if not source_receipt.is_file() or not command_path.is_file():
        raise ValueError(f"RCX extraction receipt/command absent for {spef}")
    try:
        record = json.loads(source_receipt.read_text())
        recorded_input = record["input"]
        recorded_sha = record["sha256"]
        if recorded_input.get("step") != "OpenROAD.RCX":
            raise ValueError("RCX receipt names a different producer step")
        recorded_image = recorded_input.get("image")
        bound_image = (plan.get("identity") or {}).get("tool_image")
        if recorded_image != bound_image:
            raise ValueError("RCX receipt image differs from capture image")
        rel_spef = spef.relative_to(rcx_dir).as_posix()
        spef_sha = _sha(spef)
        if recorded_sha.get(rel_spef) != spef_sha:
            raise ValueError("RCX receipt SPEF digest differs from captured bytes")
        def_items = [(path, digest) for path, digest in
                     (recorded_input.get("state_files") or {}).items()
                     if str(path).endswith(".def")]
        if len(def_items) != 1:
            raise ValueError("RCX receipt must name exactly one routed DEF")
        _def_path, def_sha = def_items[0]
        judged_def_sha = (((plan.get("identity") or {}).get("artifacts") or {})
                          .get("def") or {}).get("sha256")
        if def_sha != judged_def_sha:
            raise ValueError("RCX receipt DEF differs from judged DEF")
        if not re.fullmatch(r"[0-9a-f]{64}", str(def_sha)):
            raise ValueError("RCX receipt DEF digest malformed")
        if scene.get("rc_corner") not in {"nom", "min", "max"}:
            raise ValueError("scene RC corner is not an RCX corner")
    except (OSError, TypeError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid RCX extraction receipt: {exc}") from exc
    command_ref = _ref(command_path)
    receipt = {
        "schema": "vibeic.spef_extraction_receipt.v1",
        "producer": "drv_signoff_capture",
        "source_receipt": _ref(source_receipt),
        "routed_def_sha256": def_sha,
        "spef_sha256": spef_sha,
        "rc_corner": scene["rc_corner"],
        "extraction_command": command_ref,
        "extraction_command_sha256": command_ref["sha256"],
    }
    receipt_path = out / "spef_extraction_receipt.json"
    write_text(receipt_path, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return _ref(receipt_path)


#: What the pinned image says about its OpenROAD builds: one line per binary
#: next to the one `openroad` resolves to (the LibreLane dispatcher runs the
#: `openroad-python` build for its scripts, the direct deck runs `openroad`).
_OPENROAD_PROBE = (
    'd=$(dirname "$(readlink -f "$(command -v openroad)")"); '
    'for b in "$d"/openroad "$d"/openroad-python; do [ -x "$b" ] || continue; '
    'echo "OPENROAD_BINARY $b $(sha256sum "$b" | cut -d" " -f1) '
    '$(LD_LIBRARY_PATH=/opt/or-tools/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH} '
    '"$b" -version 2>&1 | tail -n 1)"; done')
_OPENROAD_LINE = re.compile(r"(?m)^OPENROAD_BINARY (\S+) ([0-9a-f]{64}) (\S+)\s*$")


def openroad_identity(image: str, *, run=None) -> dict:
    """The OpenROAD commit of the builds in the pinned image, asked of the
    binaries themselves (review wave 58: `openroad_commit` was required by the
    judge and produced by nothing, so every real capture was NOT_MEASURED).

    `commit` is the `-g<hash>` or CMake's full-SHA fallback every build reports; builds that
    disagree, a version with no commit, or no build at all leave it None with
    the reason, never a guess."""
    argv = ["docker", "run", *_docker_memory.docker_memory_flags(), "--rm", "--network", "none",
            image, "--skip", "bash", "-c", _OPENROAD_PROBE]
    try:
        if run is None and _ce.no_container_route():
            done = _ll.run_container(argv, probe_deadline_s=300)
        else:
            done = (run or subprocess.run)(argv, capture_output=True, text=True, timeout=300)
        text = (done.stdout or "") + (done.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"commit": None, "reason": f"OpenROAD version probe failed: {exc}"}
    binaries = [{"path": m.group(1), "sha256": m.group(2), "version": m.group(3)}
                for m in _OPENROAD_LINE.finditer(text)]
    versions = {b["version"] for b in binaries}
    record: dict = {"binaries": binaries, "commit": None}
    if not binaries:
        record["reason"] = "no OpenROAD binary answered the version probe"
    elif len(versions) != 1:
        record["reason"] = f"OpenROAD builds report different versions: {sorted(versions)}"
    else:
        version = versions.pop()
        commit = re.search(r"-g([0-9a-f]{7,40})$", version) or re.fullmatch(r"([0-9a-f]{40})", version)
        record["version"] = version
        if commit:
            record["commit"] = commit.group(1)
        else:
            record["reason"] = f"OpenROAD version {version!r} names no commit"
    return record


def capture(plan: dict, out_dir: Path, *, image: str | None = None) -> dict:
    """Run each scene and its planted control; return a content-addressed bundle."""
    import instrument_calibration
    instrument_calibration.assert_calibrated("drv_signoff_capture::capture")
    image = image or _eda_image.resolve()
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = {k: plan[k] for k in ("identity", "frozen", "current", "stages",
                                  "pins")}
    bundle["identity"] = dict(bundle["identity"])
    image_info = None
    try:
        if _ce.no_container_route():
            attestation = _ll.local_image_attestation(image)
            inspected = json.loads(Path(attestation["attestation_path"]).read_text())
            image_doc = next(item for item in inspected["image_inspect"]
                             if item["Id"] == attestation["image_id"])
        else:
            image_info = subprocess.run(
                ["docker", "image", "inspect", image, "--format", "{{json .}}"],
                capture_output=True, text=True, check=False)
            image_doc = json.loads(image_info.stdout)
        digest = image_doc["Id"]
        version = (image_doc.get("Config") or {}).get("Labels", {}).get(
            "org.opencontainers.image.version")
    except (ValueError, TypeError, KeyError, AttributeError):
        digest, version = None, None
    if (image_info is not None and image_info.returncode) or not str(digest).startswith("sha256:"):
        raise ValueError("pinned OpenSTA image identity unavailable")
    expected_id = bundle["identity"].get("source_tool_image_id")
    if expected_id and digest != expected_id:
        raise ValueError("capture image differs from final STA image identity")
    bundle["identity"]["tool_image"] = image
    bundle["identity"]["tool_image_digest"] = digest
    bundle["identity"]["tool_image_oci_version"] = version
    openroad = openroad_identity(image)
    bundle["identity"]["openroad_build"] = openroad
    if openroad.get("commit"):
        bundle["identity"]["openroad_commit"] = openroad["commit"]
    try:
        bundle["threshold_anchor"] = image_pdk_anchor(
            image, str(bundle["identity"].get("pdk") or ""),
            str(bundle["identity"].get("library") or ""))
        bundle["identity"]["pdk_commit"] = bundle["threshold_anchor"]["pdk_commit"]
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        # Keep the run inspectable.  The judge must refuse PASS without this
        # independent source and must never accept a plan-supplied substitute.
        bundle["threshold_anchor_error"] = str(exc)
    bundle["postroute_repair_ran"] = bool(plan.get("postroute_repair_ran"))
    bundle["scenes"] = []
    bundle["pins"] = {}
    roots = {out_dir}
    for scene in plan["scenes"]:
        for item in (*scene["linked_liberties"], scene["spef"],
                     plan["identity"]["artifacts"]["sta_netlist"],
                     plan["current"]["sources"]["signoff_sdc"]):
            roots.add(Path(item["path"]).resolve().parent)
        scene_dir = out_dir / scene["name"]
        scene_dir.mkdir(parents=True, exist_ok=True)
        # The author of a capture plan cannot lower the OpenSTA report bound.
        # Read the resulting census back from the fresh tool output instead.
        max_count = 2_147_483_647
        for control in (False, True):
            script = scene_dir / ("positive_control.tcl" if control else "measure.tcl")
            write_text(script, _script(plan, scene, scene_dir,
                                       control=control, max_count=max_count))
            tool_output = _run_fresh(script, roots, image=image)
            commit = re.search(r"OpenSTA\s+\S+\s+([0-9a-f]{10,40})", tool_output)
            if not commit:
                raise ValueError("fresh process did not report OpenSTA commit")
            bundle["identity"]["opensta_commit"] = commit.group(1)
        counts = dict((kind, int(value)) for kind, value in _COUNTER.findall(
            (scene_dir / "counters.log").read_text()))
        control_counts = dict((kind, int(value)) for kind, value in _COUNTER.findall(
            (scene_dir / "positive_control_counters.log").read_text()))
        if set(counts) != set(KINDS) or set(control_counts) != set(KINDS):
            raise ValueError("OpenSTA did not emit every DRV counter")
        annotation = (scene_dir / "annotation.rpt").read_text()
        unannotated = re.findall(
            r"Found\s+(\d+)\s+(?:partially\s+)?unannotated\s+(?:drivers|nets)",
            annotation)
        row = dict(scene)
        row.pop("positive_control_expected", None)
        all_rows = parse_check_types((scene_dir / "all_limits.rpt").read_text(),
                                     scene=scene["name"],
                                     mode=scene["mode"], violators_only=False)
        population = {kind: len(all_rows[kind]) for kind in KINDS}
        census = None
        try:
            census = derive_census(scene_dir, scene["linked_liberties"], all_rows,
                                   scene.get("linked_lefs"), allow_unproven=True,
                                   signoff_sdc=Path(plan["current"]["sources"]["signoff_sdc"]["path"]),
                                   core_liberty=scene.get("liberty"))
            population = census["population"]
            if bundle["pins"] and set(bundle["pins"]) != set(census["pins"]):
                raise ValueError("OpenSTA pin names differ between scenes")
            if not bundle["pins"]:
                bundle["pins"] = census["pins"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            census_error = str(exc)
        annotation_census = None
        row_annotation_error = "pin census or linked LEF inventory absent"
        if census is not None and scene.get("linked_lefs"):
            try:
                annotation_census = derive_annotation(
                    scene_dir, census["pins"], scene["linked_liberties"],
                    scene["linked_lefs"],
                    Path(plan["identity"]["artifacts"]["def"]["path"]),
                    Path(scene["spef"]["path"]))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                row_annotation_error = str(exc)
        # A plan is only a request for measurement. It cannot attest which
        # pins OpenSTA excluded from its own DRV checks.
        row.pop("excluded_pins", None)
        row.pop("excluded_pins_recorded", None)
        row.pop("excluded_pins_report", None)
        row.pop("clock_network_pins", None)
        row["spef_extraction_receipt"] = _spef_extraction_receipt(
            bundle, scene, scene_dir)
        row.update(fresh_process=True, postroute=True, propagated_clocks=True,
                   excluded_pins_recorded=census is not None,
                   command=_COMMAND, all_limits_max_count=max_count,
                   population=population,
                   positive_control_fresh_process=True,
                   counters=counts, positive_control_counters=control_counts,
                   unannotated_nets=(len(annotation_census["unresolved"])
                                     if annotation_census is not None else
                                     sum(map(int, unannotated)) if unannotated else None),
                   report=_ref(scene_dir / "violators.rpt"),
                   all_limits_report=_ref(scene_dir / "all_limits.rpt"),
                   counter_report=_ref(scene_dir / "counters.log"),
                   positive_control_report=_ref(scene_dir / "positive_control.rpt"),
                   parasitic_annotation_report=_ref(scene_dir / "annotation.rpt"),
                   clock_properties=_ref(scene_dir / "clocks.rpt"),
                   tool_scripts=[_ref(scene_dir / "measure.tcl"),
                                 _ref(scene_dir / "positive_control.tcl")])
        if census is not None:
            excluded_path = scene_dir / "excluded_pins.json"
            write_text(excluded_path, json.dumps(census["excluded"], sort_keys=True) + "\n")
            row.update(excluded_pins=census["excluded"],
                       pins=census["pins"],
                       excluded_pins_report=_ref(excluded_path),
                       clock_network_pins=census["clock_network_pins"],
                       driver_pin_census=census["driver_pins"],
                       unproven_omitted_pins=census["unproven"],
                       pin_census_report=_ref(scene_dir / "pin_census.tsv"),
                       net_census_report=_ref(scene_dir / "net_census.rpt"),
                       disabled_edges_report=_ref(scene_dir / "disabled_edges.rpt"))
        else:
            row["census_error"] = census_error
        if annotation_census is not None:
            annotation_path = scene_dir / "annotation_census.json"
            write_text(annotation_path,
                       json.dumps(annotation_census, sort_keys=True) + "\n")
            row["annotation_census"] = annotation_census
            row["annotation_census_report"] = _ref(annotation_path)
        elif scene.get("linked_lefs"):
            row["annotation_census_error"] = row_annotation_error
        bundle["scenes"].append(row)
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan = json.loads(args.plan.read_text())
        bundle = capture(plan, args.out.parent / "drv_capture")
        write_text(args.out, json.dumps(bundle, indent=2) + "\n")
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"DRV capture NOT_MEASURED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
