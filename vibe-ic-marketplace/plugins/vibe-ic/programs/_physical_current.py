"""Current subjects for steps 16, 31, 37.3 and 37.5ip.

These records supplement native measurements. They never turn an absent or
failed measurement into PASS. Consumers refuse changed inputs and outputs.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

SCHEMA = "vibeic.default_physical_current/1"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def entry(project, path, *, external=False):
    project, path = Path(project).resolve(), Path(path).resolve(strict=True)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"CURRENT_FILE_EMPTY: {path}")
    try:
        name = path.relative_to(project).as_posix()
    except ValueError:
        if not external:
            raise ValueError(f"CURRENT_PATH_ESCAPES: {path}")
        name = str(path)
    return {"path": name, "sha256": digest(path), "bytes": path.stat().st_size}


def native_image(project, tool):
    """The namespace selected by the existing native-tool launcher."""
    import shutil
    if shutil.which(tool):
        return None
    from librelane_contract import resolve_image
    return resolve_image(Path(project))


def _pdk_entries(project, paths, *, image=None, view="LEF"):
    """Hash image-owned PDK views there, and mounted project views locally.

    A same-named host file is not evidence about an image-owned PDK. Read
    raw bytes without copying or rewriting the PDK into the host namespace.
    """
    project = Path(project).resolve()
    paths = [Path(path).resolve() for path in paths]
    external = [path for path in paths if image and not path.is_relative_to(project)]
    measured = {}
    if external:
        from librelane_contract import run_container
        code = ("import hashlib,json,sys; from pathlib import Path; rows=[]\n"
                "for name in sys.argv[1:]:\n"
                " p=Path(name); data=p.read_bytes()\n"
                " if not data: raise ValueError('CURRENT_FILE_EMPTY: '+name)\n"
                " rows.append({'path':name,'sha256':hashlib.sha256(data).hexdigest(),"
                "'bytes':len(data)})\n"
                "print(json.dumps(rows))\n")
        argv = native_argv(project, "python3", ["-c", code, *map(str, external)], image=image)
        cp = run_container(argv, probe_deadline_s=60)
        if cp.returncode:
            raise ValueError(f"CURRENT_IMAGE_{view}_UNAVAILABLE: {image}: {cp.stderr[-1000:]}")
        try:
            # The image's normal --skip entry point emits startup diagnostics
            # before the program's single JSON line. Keep that front door.
            rows = json.loads(cp.stdout.strip().splitlines()[-1])
            if not isinstance(rows, list) or [row["path"] for row in rows] != list(map(str, external)):
                raise ValueError(f"image {view} readback does not match requested paths")
            for row in rows:
                if (not isinstance(row.get("bytes"), int) or row["bytes"] <= 0
                        or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256", "")))):
                    raise ValueError(f"image {view} readback has no measured bytes/hash")
                measured[row["path"]] = dict(row, image=image)
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise ValueError(f"CURRENT_IMAGE_{view}_UNAVAILABLE: {image}: {exc}") from exc
    return [measured[str(path)] if str(path) in measured else
            entry(project, path, external=True) for path in paths]


def lef_entries(project, paths, *, image=None):
    return _pdk_entries(project, paths, image=image, view="LEF")


def liberty_entries(project, paths, *, image=None):
    return _pdk_entries(project, paths, image=image, view="LIBERTY")


def design_of(path):
    match = re.search(r"(?m)^\s*DESIGN\s+(\S+)\s*;", Path(path).read_text())
    if not match:
        raise ValueError('CURRENT_DEF_DESIGN_MISSING' + f": {path}: DEF requires a DESIGN <name> ; statement")
    return match.group(1)


def pdk_of(project):
    """Read the producer's technology record, never guess a technology."""
    path = Path(project) / "reports/phase3/technology_units.json"
    doc = json.loads(path.read_text())
    name = doc.get("pdk")
    if not name and isinstance(doc.get("tech_lef"), str):
        parts = Path(doc["tech_lef"]).parts
        if "libs.ref" in parts:
            name = parts[parts.index("libs.ref") - 1]
    if not isinstance(name, str) or not name.strip():
        raise ValueError('CURRENT_PDK_MISSING' + f": {path}: technology_units.pdk requires a nonempty string identity; tech_lef libs.ref fallback applies only to an unset pdk; observed identity={name!r}")
    return name, path


def build(project, step, stage, design, pdk, tool, inputs, outputs, execution):
    if not all(isinstance(v, str) and v.strip()
               for v in (step, stage, design, pdk, tool)):
        raise ValueError("CURRENT_CONTEXT_EMPTY")
    return {"schema": SCHEMA, "step": step, "stage": stage,
            "design": design, "pdk": pdk, "tool": tool,
            "inputs": inputs, "outputs": outputs, "execution": execution}


def validate(project, record, *, step, stage, tools, required_inputs,
             required_outputs, marker=None):
    """Read-only, blocking subject check; return the refusal or an empty string."""
    try:
        if not isinstance(record, dict) or record.get("schema") != SCHEMA:
            raise ValueError('CURRENT_RECORD_MISSING' + f": validate.record.schema must equal {SCHEMA!r} for step={step!r}, stage={stage!r}; record argument has no valid current subject")
        if record.get("step") != step or record.get("stage") != stage:
            raise ValueError("CURRENT_STEP_STAGE_MISMATCH")
        if record.get("tool") not in tools:
            raise ValueError("CURRENT_TOOL_MISMATCH")
        if not record.get("pdk") or not record.get("design"):
            raise ValueError("CURRENT_CONTEXT_EMPTY")
        lef_rows = {}
        if step == "16" and isinstance(record.get("inputs"), dict):
            roles = [role for role in record["inputs"]
                     if role.startswith(("pdk_lef_", "pdk_liberty_"))]
            if "pdk_liberty_0" not in record["inputs"]:
                raise ValueError("CURRENT_TIMING_LIBRARIES_MISSING")
            selected = native_image(project, "openroad")
            # Compare the current pin before opening an old image. A valid old
            # hash cannot authorize reuse after the selected runtime changes.
            for role in roles:
                row = record["inputs"][role]
                if not isinstance(row, dict):
                    raise ValueError(f"CURRENT_HASH_MISSING: {role}")
                if row.get("image") and row["image"] != selected:
                    raise ValueError(f"CURRENT_IMAGE_CHANGED: {role}")
            for prefix, reader in (("pdk_lef_", lef_entries),
                                   ("pdk_liberty_", liberty_entries)):
                group = [role for role in roles if role.startswith(prefix)]
                paths = [record["inputs"][role]["path"]
                         if Path(record["inputs"][role]["path"]).is_absolute()
                         else Path(project) / record["inputs"][role]["path"]
                         for role in group]
                lef_rows.update(zip(group, reader(project, paths, image=selected)))
        for field, required in (("inputs", required_inputs),
                                ("outputs", required_outputs)):
            rows = record.get(field)
            if not isinstance(rows, dict) or not set(required) <= rows.keys():
                raise ValueError(f"CURRENT_{field.upper()}_MISSING")
            for role, row in rows.items():
                if not isinstance(row, dict) or not re.fullmatch(
                        r"[0-9a-f]{64}", str(row.get("sha256", ""))):
                    raise ValueError(f"CURRENT_HASH_MISSING: {role}")
                path = Path(row["path"])
                external = field == "inputs" and role.startswith("pdk_")
                if path.is_absolute() and not external:
                    raise ValueError(f"CURRENT_PATH_ESCAPES: {role}")
                path = path if path.is_absolute() else Path(project) / path
                actual = lef_rows[role] if role in lef_rows else entry(project, path, external=external)
                if actual != row:
                    raise ValueError(f"CURRENT_BYTES_CHANGED: {role}")
                if role in ("floorplan", "def") and design_of(path) != record["design"]:
                    raise ValueError("CURRENT_DESIGN_MISMATCH")
                if role == "technology":
                    if pdk_of(project)[0] != record["pdk"]:
                        raise ValueError("CURRENT_PDK_MISMATCH")
        execution = record.get("execution")
        if not isinstance(execution, dict) or execution.get("rc") != 0:
            raise ValueError('CURRENT_EXECUTION_MISSING' + f": validate.record.execution requires an object with rc=0; step={step!r}, stage={stage!r}")
        if not isinstance(execution.get("argv"), list) or not execution["argv"]:
            raise ValueError('CURRENT_ARGV_MISSING' + f": validate.record.execution.argv must be a nonempty list; step={step!r}, stage={stage!r}")
        images = {row.get("image") for row in lef_rows.values() if row.get("image")}
        if images:
            argv = execution["argv"]
            if (len(images) != 1 or execution.get("image") not in images
                    or "--skip" not in argv or argv[argv.index("--skip") - 1] not in images):
                raise ValueError("CURRENT_EXECUTION_IMAGE_MISMATCH")
        log = record["outputs"].get("log")
        if log is None:
            raise ValueError('CURRENT_LOG_MISSING' + f": validate.record.outputs.log binding is absent; step={step!r}, stage={stage!r}; no execution log opened")
        if marker and marker not in (Path(project) / log["path"]).read_text():
            raise ValueError('CURRENT_EXECUTION_MARKER_MISSING' + f": {Path(project) / log['path']}: execution log lacks required marker {marker!r}")
        return ""
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        return str(exc)


def native_argv(project, tool, args, *, image=None):
    """Use the local native tool in an image, or the pinned docker-run wrapper."""
    import shutil
    if image is None and shutil.which(tool):
        return [tool, *args]
    from librelane_contract import resolve_image
    from _docker_memory import docker_memory_flags
    image = image or resolve_image(Path(project))
    return ["docker", "run", *docker_memory_flags(), "--rm", "--network", "none",
            "-v", f"{Path(project).resolve()}:{Path(project).resolve()}",
            image, "--skip", tool, *args]


def run_native(project, tool, args, log, *, image=None):
    argv = native_argv(project, tool, args, image=image)
    if argv[0] == "docker":
        from librelane_contract import run_container
        cp = run_container(argv, supervised=True, log=log)
        rc, stdout, stderr = cp.returncode, cp.stdout, cp.stderr
    else:
        from _watchdog import run_host_supervised
        cp = run_host_supervised(argv, stall_grace_s=300)
        rc, stdout, stderr = cp.rc, cp.out, cp.err
    Path(log).write_text((stdout or "") + "\n" + (stderr or ""))
    execution = {"rc": rc, "argv": argv}
    if image:
        execution["image"] = image
    return rc, execution


def clock_plan_lef_paths(pdk, *, io_context=None):
    """Return the exact de-duplicated LEF load set for Step 16.

    The producer records every entry as ``pdk_lef_N``.  Reuse must compare
    against this same complete set; checking only ``pdk_lef_0`` and
    ``pdk_lef_1`` would silently accept a newly-added macro/IO LEF.
    """
    lefs = list(dict.fromkeys([
        str(pdk.tech_lef), str(pdk.cell_lef),
        *(str(path) for path in (getattr(pdk, "macro_lefs", []) or [])),
    ]))
    if io_context is not None:
        from _pad_ring import discover_io_lefs
        root, tree = io_context
        io_lefs = [str(path) for path in discover_io_lefs(root, tree)]
        if not io_lefs:
            raise ValueError('CLOCK_PLAN_IO_LEFS_ABSENT' + f": clock_plan_lef_paths.io_context=(root={root!r}, pdk={tree!r}): discover_io_lefs returned no IO LEFs; requires libs.ref/<library containing io>/lef/*.lef within resolved PDK trees; discovery can be empty when root/tree is unresolved")
        lefs = list(dict.fromkeys([*lefs, *io_lefs]))
    return lefs


def clock_plan_receipt_lef_refusal(record, pdk, *, io_context=None):
    """Refuse reuse when the receipt's complete LEF set differs from PDK."""
    if pdk is None:
        return "CURRENT_PDK_CONTEXT_MISSING"
    if not isinstance(record, dict) or record.get("pdk") != pdk.name:
        return ("CURRENT_PDK_CHANGED: recorded="
                f"{record.get('pdk') if isinstance(record, dict) else None} "
                f"expected={getattr(pdk, 'name', None)}")
    try:
        expected = [Path(path).resolve() for path in
                    clock_plan_lef_paths(pdk, io_context=io_context)]
    except (OSError, ValueError, TypeError) as exc:
        return f"CURRENT_PDK_LEF_SET_UNAVAILABLE: {exc}"
    inputs = record.get("inputs") if isinstance(record, dict) else None
    if not isinstance(inputs, dict):
        return "CURRENT_INPUTS_MISSING"
    rows = []
    for role, row in inputs.items():
        if not re.fullmatch(r"pdk_lef_\d+", str(role)):
            continue
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            return f"CURRENT_PDK_LEF_ROW_INVALID: {role}"
        rows.append((int(str(role).rsplit("_", 1)[1]),
                     Path(row["path"]).resolve()))
    actual = [path for _, path in sorted(rows)]
    if actual != expected:
        return ("CURRENT_PDK_LEF_SET_CHANGED: recorded="
                f"{[str(path) for path in actual]} expected="
                f"{[str(path) for path in expected]}")
    return ""


def clock_plan_liberty_paths(pdk):
    """The resolved active standard-cell and declared macro timing views.

    Geometry cannot supply SDC library-cell semantics. Do not guess a corner
    or borrow another library when the caller's resolved timing view is absent.
    """
    primary = getattr(pdk, "liberty", None)
    if not isinstance(primary, str) or not primary.strip():
        raise ValueError("CLOCK_PLAN_LIBERTY_MISSING")
    return list(dict.fromkeys([primary, *(str(path) for path in
                               (getattr(pdk, "macro_libs", []) or []))]))


def clock_plan_receipt_liberty_refusal(record, pdk):
    """The producer's complete timing-view set must still be selected on reuse."""
    try:
        expected = [str(Path(path).resolve()) for path in clock_plan_liberty_paths(pdk)]
        inputs = record.get("inputs") if isinstance(record, dict) else None
        if not isinstance(inputs, dict):
            raise ValueError("CURRENT_INPUTS_MISSING")
        rows = []
        for role, row in inputs.items():
            if not re.fullmatch(r"pdk_liberty_\d+", str(role)):
                continue
            if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                raise ValueError(f"CURRENT_PDK_LIBERTY_ROW_INVALID: {role}")
            rows.append((int(role.rsplit("_", 1)[1]), str(Path(row["path"]).resolve())))
        actual = [path for _, path in sorted(rows)]
        if actual != expected or sorted(i for i, _ in rows) != list(range(len(expected))):
            return f"CURRENT_PDK_LIBERTY_SET_CHANGED: recorded={actual} expected={expected}"
    except (OSError, ValueError, TypeError) as exc:
        return f"CURRENT_PDK_LIBERTY_SET_UNAVAILABLE: {exc}"
    return ""


def clock_plan(project, plan, floorplan, sdcs, pdk):
    """OpenROAD reads the current floorplan and evaluates the declared SDC."""
    from _atomic_artefact import write_json
    project, plan, floorplan = map(Path, (project, plan, floorplan))
    if floorplan.resolve() != (project / "phase3/stage3/pnr/floorplan.def").resolve():
        raise ValueError("CLOCK_PLAN_REQUIRES_FLOORPLAN")
    design = design_of(floorplan)
    inputs = {"floorplan": entry(project, floorplan)}
    for i, path in enumerate(sdcs):
        inputs[f"sdc_{i}"] = entry(project, path)
    if not sdcs:
        raise ValueError('CLOCK_PLAN_SDC_MISSING' + f": clock_plan.sdcs argument={sdcs!r}: no SDC files selected for {floorplan}; native clock producer not launched")
    # The runner already supplied any required IO views in macro_lefs. Use
    # the same normalized load set that validates reuse of this measurement.
    lefs = clock_plan_lef_paths(pdk)
    liberties = clock_plan_liberty_paths(pdk)
    image = native_image(project, "openroad")
    for i, row in enumerate(lef_entries(project, lefs, image=image)):
        inputs[f"pdk_lef_{i}"] = row
    for i, row in enumerate(liberty_entries(project, liberties, image=image)):
        inputs[f"pdk_liberty_{i}"] = row
    plan.parent.mkdir(parents=True, exist_ok=True)
    script, log = plan.with_suffix(".tcl"), plan.with_suffix(".log")
    def quote(path):
        if any(c in str(path) for c in "{}\n\r"):
            raise ValueError("CLOCK_PLAN_TCL_PATH_INVALID")
        return "{" + str(Path(path).resolve()) + "}"
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", pdk.name):
        raise ValueError("CLOCK_PLAN_PDK_NAME_INVALID")
    script.write_text("\n".join([
        f'puts "CLOCK_PLAN_PDK {pdk.name}"',
        *[f"read_liberty {quote(path)}" for path in liberties],
        *[f"read_lef {quote(path)}" for path in lefs],
        f"read_def {quote(floorplan)}",
        *[f"read_sdc {quote(path)}" for path in sdcs],
        'foreach c [all_clocks] {',
        '  set pins [get_full_name [get_property $c sources]]',
        '  if {$pins eq ""} {error "CLOCK_SOURCE_MISSING"}',
        '  puts "CLOCK_PLAN_NATIVE [get_full_name $c]|[get_property $c period]|$pins"',
        '}',
        'if {[llength [all_clocks]] == 0} {error "CLOCK_PLAN_NO_CLOCKS"}',
        'puts "CLOCK_PLAN_DONE"', ""]))
    inputs["recipe"] = entry(project, script)
    native_args = ["-exit", str(script)]
    rc, execution = (run_native(project, "openroad", native_args, log, image=image)
                     if image else run_native(project, "openroad", native_args, log))
    text = log.read_text()
    clocks = []
    for name, period, source in re.findall(r"(?m)^CLOCK_PLAN_NATIVE ([^|\n]+)\|([^|\n]+)\|([^\n]+)$", text):
        period = float(period)
        if period <= 0 or not source.strip():
            raise ValueError("CLOCK_PLAN_NATIVE_CLOCK_INVALID")
        clocks.append({"name": name, "period_ns": period, "source": source})
    if rc or not clocks or "CLOCK_PLAN_DONE" not in text or re.search(r"\[ERROR\]|^Error:", text, re.M):
        raise ValueError(f"CLOCK_PLAN_NATIVE_REFUSED: rc={rc}; {text[-500:]}")
    current_lefs = lef_entries(project, lefs, image=image)
    current_liberties = liberty_entries(project, liberties, image=image)
    for role, row in inputs.items():
        if role.startswith("pdk_lef_"):
            actual = current_lefs[int(role.rsplit("_", 1)[1])]
        elif role.startswith("pdk_liberty_"):
            actual = current_liberties[int(role.rsplit("_", 1)[1])]
        else:
            actual = entry(project, project / row["path"])
        if actual != row:
            raise ValueError(f"CLOCK_PLAN_INPUT_CHANGED: {role}")
    current = build(project, "16", "stage3", design, pdk.name, "openroad",
                    inputs, {"log": entry(project, log)}, execution)
    write_json(plan, {"tool": "openroad", "primary_clock": clocks[0]["name"],
                      "clocks": clocks, "current": current,
                      "derived_from": {str(Path(p).relative_to(project)): digest(p) for p in sdcs}})
    return str(plan)


def default_signoff_inputs(project):
    """The existing finished-stream and filled-view owners, when selected."""
    import librelane_fill_dfm as fill
    import execution_policy
    project = Path(project).resolve()
    if (execution_policy.request()["mode"] != "default"
            or not (project / fill.DEFAULT_STREAM_REL).is_file()):
        return None
    import gds_xor_check as xor
    import _native373_current as streams
    report = json.loads((project / "reports/phase3/gds_xor.json").read_text())
    if (report.get("gate") != xor.GATE or report.get("verdict") != "PASS"
            or report.get("design_layer_differences") != []
            or type(report.get("design__xor_difference__count")) is not int
            or report["design__xor_difference__count"] != 0
            or type(report.get("layers_compared")) is not int
            or report["layers_compared"] <= 0):
        raise ValueError("CURRENT_FINISHED_GEOMETRY_NOT_CLEAN")
    # These results belong to this call only. Public XOR readers without the
    # private arguments still obtain their own complete current proof.
    stream = fill.validate_default_stream(project)
    current = streams.read_current(project)
    refusal = xor.current_geometry_refusal(project, report, _validated_stream=stream)
    if refusal:
        raise ValueError("CURRENT_FINISHED_STREAM_REFUSED: " + refusal)
    if current.get("count") != 0:
        raise ValueError("CURRENT_STREAM_CONNECTIVITY_NOT_CLEAN")
    connectivity = xor.gds_connectivity(project, digest(Path(stream["canonical"])), report,
                                         _validated_native=current)
    if connectivity.get("verdict") != "PASS":
        raise ValueError("CURRENT_FINISHED_CONNECTIVITY_REFUSED: " + str(connectivity))
    # read_current already derived and checked these exact fill-owned roles.
    paths = {role: project / current["current"]["inputs"][role]["path"]
             for role in ("def", "netlist", "sdc")}
    for role, path in paths.items():
        if entry(project, path) != current["current"]["inputs"][role]:
            raise ValueError("CURRENT_FILLED_VIEW_CHANGED: " + role)
    return {**paths, "gds": Path(stream["canonical"]),
            "stream_fidelity": project / "reports/phase3/gds_xor.json",
            "native_streams": project / streams.REL}


def _bound(row, files):
    return files.get(row["path"]) in (row["sha256"], "sha256:" + row["sha256"])


def _lvs_def_chain(project, inputs, native, entries):
    """Re-derive the existing DEF extraction/compare and finished-stream link."""
    import phase3_one_shot_runner as runner
    import lvs_power_aware_netlist_emit as power
    selected = default_signoff_inputs(project)
    if selected is None or any(inputs[role] != entry(project, selected[role])
                               for role in ("gds", "def", "netlist")):
        raise ValueError("CURRENT_NATIVE_LAYOUT_UNBOUND")
    path = project / "reports/phase3/lvs_inputs.json"
    doc = json.loads(path.read_text())
    for key, role in (("layout_def", "def"), ("schematic_netlist", "netlist")):
        row = doc[key]
        if (Path(row["path"]).resolve() != (project / inputs[role]["path"]).resolve()
                or row["sha256"] != inputs[role]["sha256"]):
            raise ValueError("CURRENT_LVS_SOURCE_CHANGED: " + role)
    rows = {"lvs_inputs": entry(project, path)}
    required = ("extracted_spice", "comparison_netlist", "netgen_setup",
                "extraction_def", "extraction_recipe")
    names = [*required, *sorted(k for k in doc if
             re.fullmatch(r"(?:extraction|power)_lef_\d+", k))]
    for name in names:
        source = Path(doc[name]["path"])
        external = bool(re.fullmatch(r"(?:extraction|power)_lef_\d+", name))
        row = entry(project, source, external=external)
        if row["sha256"] != doc[name]["sha256"]:
            raise ValueError("CURRENT_LVS_INPUT_CHANGED: " + name)
        rows[("pdk_" if external else "") + name] = row
    for role in ("extracted_spice", "comparison_netlist", "netgen_setup"):
        if not _bound(rows[role], native.get("inputs") or {}):
            raise ValueError("CURRENT_NETGEN_INPUT_UNBOUND: " + role)
    spice = rows["extracted_spice"]
    extraction = [e for e in entries if e.get("record") == "invocation"
                  and e.get("tool") == "magic" and spice["path"] in (e.get("outputs") or {})]
    if not extraction:
        raise ValueError("CURRENT_EXTRACTION_INVOCATION_MISSING")
    extraction = extraction[-1]
    if extraction.get("measured") is not True or extraction.get("exit_code") != 0:
        raise ValueError("CURRENT_EXTRACTION_EXECUTION_MISSING")
    for role in ("extraction_def", "extraction_recipe"):
        if not _bound(rows[role], extraction.get("inputs") or {}):
            raise ValueError("CURRENT_EXTRACTION_INPUT_UNBOUND: " + role)
    original_def = (project / inputs["def"]["path"]).read_text(errors="replace")
    extracted_def = (project / rows["extraction_def"]["path"]).read_text(errors="replace")
    if extracted_def != original_def and extracted_def != runner._strip_nonlayer_blockages(original_def)[0]:
        raise ValueError("CURRENT_EXTRACTION_DEF_CHANGED")
    if not _bound(spice, extraction.get("outputs") or {}):
        # The existing loss-free top-port restoration is an in-place transform.
        old = (extraction.get("outputs") or {}).get(spice["path"], "").removeprefix("sha256:")
        if not any(e.get("record") == "declared_transform"
                   and e.get("producing_step") == "lvs:top_port_aliases"
                   and (e.get("inputs") or {}).get(spice["path"]) in (old, "sha256:" + old)
                   and _bound(spice, e.get("outputs") or {}) for e in entries):
            raise ValueError("CURRENT_EXTRACTION_OUTPUT_UNBOUND")
    log = entry(project, (project / rows["extraction_recipe"]["path"]).parent / "ext2spice.log")
    if not _bound(log, extraction.get("outputs") or {}):
        raise ValueError("CURRENT_EXTRACTION_LOG_UNBOUND")
    compared = project / rows["comparison_netlist"]["path"]
    original = project / inputs["netlist"]["path"]
    if compared.resolve() != original.resolve():
        options = doc["power_aware"]
        if not isinstance(options, dict) or any(type(options.get(k)) is not bool
                for k in ("rails_as_ports", "tie_wells_to_rails")):
            raise ValueError("CURRENT_POWER_AWARE_MODEL_MISSING")
        lef_roles = sorted((k for k in doc if re.fullmatch(r"power_lef_\d+", k)),
                           key=lambda k: int(k.rsplit("_", 1)[1]))
        lefs = [project / rows["pdk_" + k]["path"] for k in lef_roles]
        expected, stats = power.emit_power_aware_netlist(
            original.read_text(errors="replace"), pdk_of(project)[0],
            top=design_of(project / inputs["def"]["path"]),
            cell_lef=project / inputs["pdk_cell_lef"]["path"],
            additional_lefs=lefs, **options)
        if stats.get("modules_patched", 0) <= 0 or compared.read_text() != expected:
            raise ValueError("CURRENT_POWER_AWARE_NETLIST_CHANGED")
    return rows, log, extraction


def direct_half(project, top, pdk, half, producer):
    """Bind the direct native DRC/LVS invocation, without masking its FAIL."""
    from _atomic_artefact import write_json
    import _signoff_drc_format as sdf
    project = Path(project)
    path = project / f"reports/phase3/direct_current_{half}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    inputs, refusal = {}, ""
    try:
        pnr = project / "phase3/stage3/pnr"
        selected = default_signoff_inputs(project) or {
            "gds": pnr / f"{top}.gds", "def": pnr / f"{top}.def",
            "netlist": pnr / f"{top}_pnr.v"}
        for role, source in {**selected, "pdk_tech_lef": pdk.tech_lef,
                             "pdk_cell_lef": pdk.cell_lef}.items():
            inputs[role] = entry(project, source, external=role.startswith("pdk_"))
        deck = pdk.drc_deck if half == "drc" else (
            getattr(pdk, "native_lvs_deck", None)
            or getattr(pdk, "bridge_netgen_setup", None))
        if not deck and half == "lvs":
            deck = Path("/foss/pdks") / pdk.name / "libs.tech/netgen" / f"{pdk.name}_setup.tcl"
        if not deck:
            raise ValueError('CURRENT_NATIVE_DECK_MISSING' + f": direct_half.pdk.{'drc_deck' if half == 'drc' else 'bridge_netgen_setup'} is unset for half={half!r}; no native deck selected")
        inputs["pdk_deck"] = entry(project, deck, external=True)
        declared_pdk, technology = pdk_of(project)
        if declared_pdk != pdk.name:
            raise ValueError("CURRENT_PDK_MISMATCH")
        inputs["technology"] = entry(project, technology)
        design = design_of(selected["def"])
    except (OSError, ValueError, AttributeError, TypeError, RuntimeError) as exc:
        refusal = str(exc)
        design = top
    before = list(sdf._prov_entries(project))
    row = producer()
    try:
        if refusal:
            raise ValueError(refusal)
        report = project / f"reports/phase3/{'drc_signoff' if half == 'drc' else 'lvs'}.rpt"
        native_report = project / "phase3/reports/drc.rpt" if half == "drc" else report
        new = list(sdf._prov_entries(project))[len(before):]
        if half == "lvs":
            verdict_path = project / "reports/phase3/lvs_verdict.json"
            if verdict_path.is_file():
                verdict = json.loads(verdict_path.read_text())
                if verdict.get("schema") == "vibeic.native_gds_lvs/1":
                    import klayout_pdk_lvs as native_lvs
                    verdict = native_lvs.read_current_verdict(project, verdict_path, selected["gds"])
                    native_report = Path(verdict["log"]["path"])
            raw = project / "reports/phase3/lvs_power_aware.rpt"
            alias = entry(project, report)
            if raw.is_file() and digest(raw) == alias["sha256"] and any(
                    e.get("record") == "declared_transform"
                    and e.get("producing_step") == "lvs:power_aware"
                    and _bound(alias, e.get("outputs") or {})
                    and _bound(entry(project, raw), e.get("inputs") or {}) for e in new):
                native_report = raw
        native_rel = str(native_report.relative_to(project))
        invoked = [e for e in new
                   if e.get("record") == "invocation"
                   and native_rel in (e.get("outputs") or {})
                   and e.get("tool") in ("klayout", "magic", "netgen", "svrfdrc")]
        if not invoked:
            raise ValueError('CURRENT_NATIVE_INVOCATION_MISSING' + f": {native_report}: no new invocation in _signoff_drc_format._prov_entries({project}) names this report with tool klayout/magic/netgen/svrfdrc")
        execution = invoked[-1]
        if execution.get("measured") is not True or execution.get("exit_code") != 0:
            raise ValueError('CURRENT_NATIVE_EXECUTION_MISSING' + f": {native_report}: selected provenance invocation requires measured=True and exit_code=0; observed measured={execution.get('measured')!r}, exit_code={execution.get('exit_code')!r}")
        for role, expected in inputs.items():
            if entry(project, project / expected["path"], external=role.startswith("pdk_")) != expected:
                raise ValueError(f"CURRENT_INPUT_CHANGED_DURING_TOOL: {role}")
        log = native_report.with_suffix(".log")
        native_execution = {"rc": execution["exit_code"],
                            "argv": [execution.get("command") or execution.get("cmd") or execution["tool"]],
                            "native_invocation": execution}
        outputs = {"report": entry(project, report), "log": entry(project, log),
                   "native_report": entry(project, native_report)}
        if half == "lvs" and not _bound(inputs["gds"], execution.get("inputs") or {}):
            rows, extraction_log, extraction = _lvs_def_chain(project, inputs, execution, new)
            inputs.update(rows)
            outputs["extraction_log"] = extraction_log
            native_execution["extraction_invocation"] = extraction
        record = build(project, "31", "stage4", design, pdk.name, execution["tool"],
                       inputs, outputs, native_execution)
        record["file_top"] = top
        write_json(path, record)
        row.extras["current_subject"] = str(path)
        row.extras["current_reader"] = read_direct_half(project, half)
        if row.extras["current_reader"]["verdict"] != "CURRENT":
            raise ValueError(row.extras["current_reader"]["reason"])
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        refusal = str(exc)
        write_json(path, {"schema": SCHEMA, "step": "31", "stage": "stage4",
                          "verdict": "NOT_MEASURED", "reason": refusal})
        if row.status == "PASS":
            row.status = "NOT_MEASURED"
            row.reason_class = "NOT_EXECUTED"
        row.detail += f"; current native subject: {refusal}"
    return row


def _direct_half_refusal(project, half):
    """Strict reader for the Step-31 declared DRC/LVS gates."""
    project = Path(project)
    try:
        record = json.loads((project / f"reports/phase3/direct_current_{half}.json").read_text())
    except (OSError, ValueError) as exc:
        return f"CURRENT_NATIVE_RECORD_MISSING: {exc}"
    refusal = validate(project, record, step="31", stage="stage4",
                       tools=("klayout", "magic", "netgen", "svrfdrc"),
                       required_inputs=("gds", "def", "netlist", "technology", "pdk_deck", "pdk_tech_lef", "pdk_cell_lef"),
                       required_outputs=("report", "native_report", "log"))
    if refusal:
        return refusal
    report = project / f"reports/phase3/{'drc_signoff' if half == 'drc' else 'lvs'}.rpt"
    if record["outputs"]["report"] != entry(project, report):
        return "CURRENT_NATIVE_REPORT_SWAPPED"
    native = record["execution"].get("native_invocation") or {}
    if (native.get("tool") != record["tool"] or native.get("measured") is not True
            or native.get("exit_code") != 0):
        return "CURRENT_NATIVE_INVOCATION_MISMATCH"
    import _signoff_drc_format as sdf
    entries = list(sdf._prov_entries(project))
    if native not in entries:
        return "CURRENT_NATIVE_INVOCATION_MISSING"
    for role in ("native_report", "log"):
        row = record["outputs"][role]
        if (native.get("outputs") or {}).get(row["path"]) != "sha256:" + row["sha256"]:
            return "CURRENT_NATIVE_OUTPUT_UNBOUND"
    pnr = project / "phase3/stage3/pnr"
    selected = default_signoff_inputs(project)
    file_top = record.get("file_top", record["design"])
    expected = selected or {"gds": pnr / f"{file_top}.gds",
                            "def": pnr / f"{file_top}.def",
                            "netlist": pnr / f"{file_top}_pnr.v"}
    for role, source in expected.items():
        if record["inputs"].get(role) != entry(project, source):
            return "CURRENT_NATIVE_SUBJECT_SWAPPED"
    # The report's own invocation must bind the layout, not only its filename.
    want = record["inputs"]["gds"]
    bound = (native.get("inputs") or {}).get(want["path"])
    if half == "lvs" and bound not in (want["sha256"], "sha256:" + want["sha256"]):
        rows, extraction_log, extraction = _lvs_def_chain(project, record["inputs"], native, entries)
        if (any(record["inputs"].get(k) != v for k, v in rows.items())
                or record["outputs"].get("extraction_log") != extraction_log
                or record["execution"].get("extraction_invocation") != extraction):
            return "CURRENT_EXTRACTION_CHAIN_CHANGED"
    elif bound not in (want["sha256"], "sha256:" + want["sha256"]):
        return "CURRENT_NATIVE_LAYOUT_UNBOUND"
    raw, canonical = record["outputs"]["native_report"], record["outputs"]["report"]
    if half == "lvs" and raw["path"] != canonical["path"]:
        if raw["sha256"] != canonical["sha256"] or not any(
                e.get("record") == "declared_transform"
                and e.get("producing_step") in ("lvs:power_aware", "lvs:native_gds_report")
                and _bound(raw, e.get("inputs") or {})
                and _bound(canonical, e.get("outputs") or {}) for e in entries):
            return "CURRENT_NATIVE_REPORT_TRANSFORM_UNBOUND"
    return ""


def check_direct_half(project, half):
    try:
        return _direct_half_refusal(project, half)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        return f"CURRENT_NATIVE_REFUSED: {exc}"


def read_direct_half(project, half):
    """Explicit strict-reader receipt; an empty refusal is never the evidence."""
    refusal = check_direct_half(project, half)
    if refusal:
        return {"verdict": "NOT_MEASURED", "reason": refusal, "half": half}
    path = Path(project) / f"reports/phase3/direct_current_{half}.json"
    record = json.loads(path.read_text())
    return {"verdict": "CURRENT", "half": half, "subject": entry(project, path),
            "step": record["step"], "stage": record["stage"], "design": record["design"],
            "tool": record["tool"], "pdk": record["pdk"],
            "inputs": record["inputs"], "outputs": record["outputs"]}


def check_kit(project):
    """Both kit and documentation gates consume this exact current kit."""
    project = Path(project)
    hm = project / "phase3/stage4/hardmacro"
    try:
        record = json.loads((hm / "current_kit.json").read_text())
        refusal = validate(
            project, record, step="37.5ip", stage="stage4", tools=("magic+opensta",),
            required_inputs=("def", "gds", "route", "technology", "timing_netlist",
                             "timing_sdc", "timing_spef", "timing_sta_report", "timing_recipe",
                             "pdk_timing_liberty", "pdk_magicrc", "lef_recipe"),
            required_outputs=("lef", "liberty", "gds", "verilog", "log", "timing_log"),
            marker="DIGITAL_LEF_WRITE_DONE")
        if refusal:
            return refusal
        import digital_hardmacro_gen as producer
        if (record["inputs"]["def"] != entry(project, producer.find_def(project))
                or record["inputs"]["gds"] != entry(project, producer.find_signoff_gds(project))):
            return "IP_KIT_CURRENT_SUBJECT_SWAPPED"
        import _tapeout_declaration as td
        declaration = project / td.DECLARATION_REL
        doc, error = td.load(declaration)
        if (error or td.answer(doc, "deliverable") != td.DELIVERABLE_HARDMACRO
                or record["inputs"]["route"] != entry(project, declaration)):
            return "IP_KIT_ROUTE_CHANGED"
        for role, suffix in (("lef", ".lef"), ("liberty", ".lib"),
                             ("gds", ".gds"), ("verilog", ".v")):
            if record["outputs"][role] != entry(project, hm / (record["design"] + suffix)):
                return "IP_KIT_VIEW_SWAPPED"
        if record["outputs"]["gds"]["sha256"] != record["inputs"]["gds"]["sha256"]:
            return "IP_KIT_LAYOUT_SWAPPED"
        if record["outputs"]["verilog"]["sha256"] != record["inputs"]["timing_netlist"]["sha256"]:
            return "IP_KIT_NETLIST_SWAPPED"
        timing = record["execution"].get("timing") or {}
        text = (project / record["outputs"]["timing_log"]["path"]).read_text()
        if timing.get("rc") != 0 or not timing.get("argv") or "TIMING_MODEL_DONE" not in text:
            return "IP_KIT_TIMING_EXECUTION_MISSING"
        return ""
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return f"IP_KIT_CURRENT_REFUSED: {exc}"
