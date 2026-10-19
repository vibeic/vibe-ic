"""Optional post-map native product, owned by the synthesis handoff.

ENFORCEMENT: blocking when requested. A present child never falls back to its
Yosys parent on a stale/missing observation. Structural/provenance acceptance
is not LEC or timing acceptance; those existing consumers still run.
"""
from __future__ import annotations
import json
import shutil
from pathlib import Path
import librelane_contract as LC
from _atomic_artefact import write_bytes, write_json

STEP = "Vibeic.PostMapRepair"
SCHEMA = "vibeic.postmap-handoff.v1"


def mode(project):
    switch = project / "phase3/librelane_switch.json"
    doc = json.loads(switch.read_text()) if switch.is_file() else {}
    if not isinstance(doc, dict):
        raise LC.Refusal("LL_POSTMAP_MODE_INVALID", "switch must be an object")
    value = doc.get("post_map_repair", "off")
    if value not in ("off", "pre_placement"):
        raise LC.Refusal("LL_POSTMAP_MODE_INVALID", repr(value))
    return value


def basis(project):
    from sdc_constraints import collect_sdc_files
    paths = collect_sdc_files(project)
    docs = project / "phase1/generated_docs"
    for prefix in ("L8_", "L9_", "L19_"):
        paths += sorted(docs.glob(prefix + "*.json"))
    return {str(p.relative_to(project)): LC.digest(p) for p in paths}


def _inside(project, value):
    rel = Path(value)
    path = project / rel
    if rel.is_absolute() or not rel.parts or ".." in rel.parts:
        raise ValueError("post-map path escaped project")
    for part in [path, *path.parents]:
        if part == project.parent:
            break
        if part.is_symlink():
            raise ValueError("post-map path is symlinked")
    if not path.resolve().is_relative_to(project.resolve()):
        raise ValueError("post-map path escaped project")
    return path


def selected(project, binding, parent, parent_folder):
    """Readonly validation and selection of the native child, or the parent."""
    child = binding.get("post_map")
    if mode(project) == "off":
        if child is not None:
            raise ValueError("post-map child present while its implementation mode is off")
        return parent, None
    if not isinstance(child, dict) or child.get("schema") != SCHEMA:
        raise ValueError("requested post-map product is absent or malformed")
    if child.get("basis") != basis(project):
        raise ValueError("post-map source/constraint basis is stale")
    folder = _inside(project, child["folder"])
    if not folder.is_relative_to(project / "phase3/librelane"):
        raise ValueError("post-map producer escaped native namespace")
    receipt = LC.validate_step_receipt(folder, STEP)
    if child.get("receipt_sha256") != LC.digest(folder / "vibeic_receipt.json"):
        raise ValueError("post-map receipt changed after publication")
    state = json.loads((folder / "state_out.json").read_text())
    cfg = json.loads((folder / "config.json").read_text())
    from synth_handoff_netlist_check import _receipt_pdk_mounts, _project_path_resolver
    resolver = _project_path_resolver(project, folder, state)
    output = resolver(state["nl"]).resolve()
    if not output.is_relative_to(folder) or output.is_symlink():
        raise ValueError("post-map native output escaped its producer")
    fp = receipt["input"]
    resolved = _inside(project, child["resolved_config"])
    config = json.loads(resolved.read_text())
    parent_receipt = json.loads((parent_folder / "vibeic_receipt.json").read_text())
    if (fp.get("image") != parent_receipt["input"]["image"] or
            fp.get("config") != LC.digest(resolved) or
            fp.get("plugin") != LC._plugin_digests(STEP) or
            cfg.get("meta", {}).get("step") != STEP or
            cfg.get("DESIGN_NAME") != binding["top"]):
        raise ValueError("post-map tool/config/code identity changed")
    mounts = _receipt_pdk_mounts(folder, receipt)
    expected = {}
    external = []
    for name in fp["config_files"]:
        source = resolver(name)
        if source.is_relative_to(project):
            expected[name] = LC.digest(source)
        else:
            external.append(name)
    expected.update(LC.config_file_hashes({"files": external}, mounts))
    # The resolved input file census is checked too: deleting a recorded PDK
    # dependency cannot turn a stale receipt into a smaller valid population.
    current = set()
    outside = []
    original_root = Path(state["nl"]).parent
    for _ in folder.relative_to(project).parts:
        original_root = original_root.parent
    for path in LC._walk_paths(config):
        target = project / path.relative_to(original_root) if path.is_relative_to(original_root) else path
        if target.is_dir() and not target.is_symlink():
            continue
        source = resolver(str(path))
        if source.is_relative_to(project):
            if source.is_file():
                current.add(str(path))
        else:
            outside.append(str(path))
    current.update(LC.config_file_hashes({"files": outside}, mounts))
    if fp["config_files"] != expected or current != set(fp["config_files"]):
        raise ValueError("post-map config/SDC/PDK input changed")
    state_in = _inside(project, child["state_in"])
    if fp.get("state") != LC.digest(state_in):
        raise ValueError("post-map input state changed")
    input_state = json.loads(state_in.read_text())
    if resolver(input_state["nl"]).resolve() != parent.resolve():
        raise ValueError("post-map input is not the retained Yosys parent")
    if (child.get("parent_sha256") != LC.digest(parent) or
            fp.get("state_files") != {input_state["nl"]: LC.digest(parent)} or
            child.get("netlist_sha256") != LC.digest(output)):
        raise ValueError("post-map input/output bytes changed")
    stats = project / "phase2/stage2/synth/stats.json"
    if child.get("stats_sha256") != LC.digest(stats):
        raise ValueError("post-map published statistics changed")
    LC.verify_synthesis_stat(folder / "reports/stat.json", {**state, "nl": str(output)}, stats, binding["top"], None)
    observation = json.loads((folder / "postmap.json").read_text())
    if (observation["input_sha256"] != LC.digest(parent) or
            observation["output_sha256"] != LC.digest(output)):
        raise ValueError("post-map observation does not bind native bytes")
    return output, folder


def run_and_publish(project, top, pdk, container, *, parent_folder, image, mounts, pdk_root,
                    area_receipt=None, area_run_manifest=None):
    """Run the existing native chain and area consumers, then publish child last."""
    if mode(project) == "off":
        return None
    import phase3_one_shot_runner as runner
    import synth_handoff_netlist_check as H
    import librelane_prelayout as prelayout
    import synth_area_stats_emit as area
    import subprocess, sys
    parent, _, _ = H._native_synthesis(project, parent_folder, top,
        path_resolver=H._project_path_resolver(project, parent_folder,
            json.loads((parent_folder / "state_out.json").read_text())))
    # ONE ordinary SDC producer, also used by Step10 and PnR. No private deck.
    deck = runner._ppa_timing.emit_step7_asic_sdc(runner._runner_module(), project, top, pdk, container)
    sdc = project / deck["path"]
    root = project / "phase3/librelane/postmap-config"
    root.mkdir(parents=True, exist_ok=True)
    raw = root / "design.json"
    cfg = prelayout.emit_prelayout_config(project, str(pdk.name), top, sdc, [], raw,
                                          Path(str(pdk.liberty)).stem.split("__", 1)[0])
    cfg["meta"] = {"step": STEP}
    LC.write_json(raw, cfg)
    resolved = LC.resolve_step_config(project, image, raw, root / "resolved.json", mounts=mounts, pdk_root=pdk_root)
    config = json.loads(resolved.read_text())
    config["PNR_CORNERS"] = config["STA_CORNERS"]
    LC.write_json(resolved, config)
    state_in = root / "state_in.json"
    LC.write_json(state_in, {"nl": str(parent.resolve())})
    folders = LC.run_chain(project, image, [(STEP, resolved, state_in)], mounts=mounts,
                           pdk_root=pdk_root, namespace="postmap")
    folder = folders[-1]
    LC.validate_step_receipt(folder, STEP)
    state = json.loads((folder / "state_out.json").read_text())
    native = Path(state["nl"])
    # Emit in a staging project-shaped directory, so a failed candidate cannot
    # silently overwrite the old mapped file while retaining its old metadata.
    staging = folder / "publication"
    netlist = staging / "phase2/stage2/synth" / (top + "_synth.v")
    netlist.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(native, netlist)
    stats = area.emit_for_run(staging, folder / "reports/stat.rpt", netlist, liberty=pdk.liberty, container=None)
    if stats is None:
        raise LC.Refusal("LL_POSTMAP_STAT_UNMEASURED", str(folder))
    LC.verify_synthesis_stat(folder / "reports/stat.json", state, Path(stats), top, folder / "postmap-stat-binding.json")
    # Area check must see the candidate stat under the real project namespace.
    # Publish its measured stats before netlist copies; old sidecar+different
    # bytes must refuse until the final child binding is atomically committed.
    target = project / "phase2/stage2/synth" / (top + "_synth.v")
    target_stats = target.parent / "stats.json"
    doc_stats = json.loads(Path(stats).read_text())
    doc_stats["netlist"] = str(target.relative_to(project))
    write_json(target_stats, doc_stats)
    report = folder / "area-budget.json"
    flags = runner._area_receipt_flags(area_receipt, area_run_manifest)
    result = subprocess.run([sys.executable, str(Path(__file__).parent / "area_total_vs_budget_check.py"), str(project),
                             "--json", str(report), *flags], capture_output=True, text=True)
    if result.returncode not in (0, 2):
        raise LC.Refusal("LL_POSTMAP_AREA_REJECTED", result.stdout[-500:])
    if result.returncode == 2 and json.loads(report.read_text()).get("verdict") != "INCOMPLETE":
        raise LC.Refusal("LL_POSTMAP_AREA_UNREADABLE", result.stdout[-500:])
    # Every output master must still belong to the selected PDK. Parent critical
    # synthesis checks stay bound to their unchanged native Yosys product.
    checked = H.check(native, json.loads((parent_folder / "config.json").read_text()))
    if checked["verdict"] != "PASS":
        raise LC.Refusal("LL_POSTMAP_NETLIST_REJECTED", str(checked))
    child = {"schema": SCHEMA, "folder": str(folder.relative_to(project)),
             "resolved_config": str(resolved.relative_to(project)), "state_in": str(state_in.relative_to(project)),
             "parent_sha256": LC.digest(parent), "netlist_sha256": LC.digest(native),
             "receipt_sha256": LC.digest(folder / "vibeic_receipt.json"),
             "stats_sha256": LC.digest(target_stats), "basis": basis(project)}
    sidecar = target.parent / "synth_inputs.json"
    doc = json.loads(sidecar.read_text())
    doc["librelane_synthesis"]["post_map"] = child
    doc["librelane_synthesis"]["netlist_sha256"] = LC.digest(native)
    write_bytes(target, native.read_bytes())
    write_bytes(target.parent / "netlist.v", native.read_bytes())
    write_json(sidecar, doc)
    bound = H.bound_handoff(project)
    if bound is None or bound.get("verdict") != "PASS":
        raise LC.Refusal("LL_POSTMAP_HANDOFF_REJECTED", str(bound))
    return {"folder": str(folder), "netlist": str(target), "stats": str(target_stats),
            "area_budget_rc": result.returncode, "equivalence": "NOT_MEASURED"}
