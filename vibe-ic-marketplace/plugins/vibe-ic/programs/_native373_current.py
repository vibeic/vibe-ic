"""Bounded Step37.3 native stream dependency and read-only current consumer.

This measures two independent streams of the current routed database. It is
geometric stream fidelity evidence, never LVS or whole-PDK signoff.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from _atomic_artefact import write_json
import _docker_memory as _dmem
import _physical_current as pc
import librelane_contract as lc
import librelane_pv_signoff as pv
import librelane_signoff_evidence as native

REL = "reports/phase3/gds_stream_current.json"
CONFIG = "phase3/librelane/37.3-config"
STEPS = ("Magic.StreamOut", "KLayout.StreamOut", "KLayout.XOR")
KEY = "design__xor_difference__count"


def _read(path):
    return json.loads(Path(path).read_text())


def _path(project, row):
    path = Path(row["path"])
    return path if path.is_absolute() else project / path


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read_current(project, record=None):
    """Validate retained native producers, inputs, material and typed count."""
    project = Path(project).resolve()
    doc = record if record is not None else _read(project / REL)
    current = doc["current"]
    refusal = pc.validate(project, current, step="37.3", stage="stage4",
                          tools=("librelane",),
                          required_inputs=("def", "netlist", "sdc", "technology"),
                          required_outputs=("magic_gds", "klayout_gds", "xor_report", "log", "launches"),
                          marker="Exit status: 0")
    _require(not refusal, refusal)
    pnr = project / "phase3/stage3/pnr"
    design = pc.design_of(_path(project, current["inputs"]["def"]))
    for role, path in (("def", pnr / "routed.def"),
                       ("netlist", pnr / f"{design}_pnr.v"),
                       ("sdc", pnr / "constraint.sdc")):
        _require(pc.entry(project, path) == current["inputs"][role],
                 "NATIVE373_CURRENT_SOURCE_CHANGED: " + role)
    _require(doc.get("steps") == list(STEPS), "NATIVE373_WRONG_CHAIN")
    config_root = project / CONFIG
    launches = [json.loads(line) for line in _path(project, current["outputs"]["launches"]).read_text().splitlines()]
    folders = []
    for step, rel in zip(STEPS, doc["folders"]):
        folder = (project / rel).resolve(strict=True)
        _require(folder.is_relative_to(project), "NATIVE373_FOREIGN_FOLDER")
        folders.append(folder)
        receipt = _read(folder / "vibeic_receipt.json")
        fp = receipt["input"]
        _require(fp == _read(folder / "input_fingerprint.json")
                 and fp["step"] == step and fp["image"] == doc["image"],
                 "NATIVE373_PRODUCER_CHANGED")
        _require(fp["config"] == pc.digest(config_root / f"{step}.json"),
                 "NATIVE373_CONFIG_CHANGED")
        mounts = native._pdk_mounts(project, _read(project / "phase3/librelane_switch.json"),
                                    folder, doc["image"])
        _require(fp["config_files"] == lc._current_config_material(
            _read(config_root / f"{step}.json"), mounts), "NATIVE373_MATERIAL_CHANGED")
        native._hashes(fp["state_files"])
        _require(all(Path(path).resolve().is_relative_to(project) for path in fp["state_files"]),
                 "NATIVE373_FOREIGN_STATE")
        for name, sha in receipt["sha256"].items():
            path = (folder / name).resolve(strict=True)
            _require(path.is_relative_to(folder) and pc.digest(path) == sha,
                     "NATIVE373_RECEIPT_CHANGED: " + name)
        matches = [run for run in launches if "--id" in run["argv"]
                   and run["argv"][run["argv"].index("--id") + 1] == step
                   and run["argv"][run["argv"].index("-o") + 1] == str(folder)]
        _require(matches, "NATIVE373_EXECUTION_MISSING: " + step)
        run = matches[-1]
        argv = run["argv"]
        if step == STEPS[-1]:
            _require(current["execution"] == run, "NATIVE373_RECORDED_EXECUTION_CHANGED")
        _require(run["rc"] == 0 and argv[argv.index(doc["image"]) + 1] == "--skip"
                 and argv[argv.index("-c") + 1] == str(config_root / f"{step}.json")
                 and argv[argv.index("--pdk-root") + 1] == "/pdk",
                 "NATIVE373_EXECUTION_CHANGED: " + step)
        text = (folder / "invocation.log").read_text()
        _require(f"--id {step} " in text and "Exit status: 0" in text,
                 "NATIVE373_NATIVE_LOG_MISSING: " + step)
    _require(len(folders) == 3, "NATIVE373_CHAIN_INCOMPLETE")
    try:
        report = lc.check_xor_report(folders[-1], _read(folders[-1] / "vibeic_receipt.json"))
    except lc.Refusal as exc:
        raise ValueError(str(exc)) from exc
    _require(report["design"] == current["design"], "NATIVE373_REPORT_DESIGN_MISMATCH")
    _require(pc.entry(project, folders[-1] / report["path"]) == current["outputs"]["xor_report"],
             "NATIVE373_REPORT_OUTPUT_SWAPPED")
    _require(type(doc.get("count")) is int and report["count"] == doc["count"],
             "NATIVE373_REPORT_COUNT_MISMATCH")
    state = _read(folders[-1] / "state_out.json")
    for view, role, index in (("mag_gds", "magic_gds", 0), ("klayout_gds", "klayout_gds", 1)):
        path = _path(project, current["outputs"][role])
        _require(pc.entry(project, Path(state[view])) == pc.entry(project, path),
                 "NATIVE373_STREAM_SWAPPED")
        produced = _read(folders[index] / "state_out.json")
        _require(produced[view] == str(path), "NATIVE373_STREAM_NOT_PRODUCED")
        row = native.count_row(project, folders[-1], STEPS[-1], KEY, path,
                               config_root, subject_view=view)
        _require(type(row["value"]) is int, row.get("reason", "NATIVE373_COUNT_NOT_MEASURED"))
        _require(type(doc.get("count")) is int and row["value"] == doc["count"],
                 "NATIVE373_COUNT_CHANGED")
    _require(current["outputs"]["magic_gds"]["sha256"] !=
             current["outputs"]["klayout_gds"]["sha256"], "NATIVE373_IDENTICAL_STREAMS")
    return doc


def produce(project, routed_def):
    """Ordinary three-step producer; retained current evidence can be reused."""
    project, routed_def = Path(project).resolve(), Path(routed_def).resolve()
    path = project / REL
    if path.is_file():
        try:
            return read_current(project)
        except (OSError, ValueError, KeyError, TypeError, lc.Refusal):
            pass
    design = pc.design_of(routed_def)
    pdk, technology = pc.pdk_of(project)
    image = lc.resolve_image(project)
    pdk_root = Path(lc.pdk_root_resolution(project, pdk, image=image)["path"])
    pnr = project / "phase3/stage3/pnr"
    sources = {"def": routed_def, "netlist": pnr / f"{design}_pnr.v",
               "sdc": pnr / "constraint.sdc", "technology": technology}
    inputs = {role: pc.entry(project, source) for role, source in sources.items()}
    launcher = str(Path(__file__).with_name("_native373_docker.py"))
    journal = project / "phase3/librelane/37.3-launches.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    saved = {key: os.environ.get(key) for key in ("VIBEIC_NATIVE373_IMAGE", "VIBEIC_NATIVE373_LAUNCH_LOG")}
    os.environ.update(VIBEIC_NATIVE373_IMAGE=image, VIBEIC_NATIVE373_LAUNCH_LOG=str(journal))
    try:
        overlay = pv.tech_lef_overlay(project) or {}
        overlay["VERILOG_FILES"] = ([str(sources["netlist"])],
                                     "current routed netlist consumed by Step37.3")
        overlay["FALLBACK_SDC"] = (str(sources["sdc"]),
                                    "current routed constraints consumed by Step37.3")
        configs = lc.resolve_step_configs(project, image, pdk, list(STEPS),
                                           pdk_root=pdk_root, docker=launcher,
                                           folder="37.3-config", overlay=overlay)
        mounts = [(pdk_root, "/pdk")]
        state = lc.state_from_direct(project, image, configs[STEPS[0]],
                                     {"def": routed_def, "nl": sources["netlist"], "sdc": sources["sdc"]},
                                     project / CONFIG / "bridge", mounts=mounts, docker=launcher)
        magic = lc.run_chain(project, image, [(STEPS[0], configs[STEPS[0]], state)],
                             mounts=mounts, pdk_root="/pdk", lane="37.3-magic", docker=launcher)[-1]
        compare = lc.run_chain(project, image,
                               [(step, configs[step], magic / "state_out.json") for step in STEPS[1:]],
                               mounts=mounts, pdk_root="/pdk", lane="37.3-compare", docker=launcher)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    folders = [magic, *compare]
    final = _read(folders[-1] / "state_out.json")
    outputs = {"magic_gds": pc.entry(project, final["mag_gds"]),
               "klayout_gds": pc.entry(project, final["klayout_gds"]),
               "xor_report": pc.entry(project, folders[-1] / "xor.xml"),
               "log": pc.entry(project, folders[-1] / "invocation.log"),
               "launches": pc.entry(project, journal)}
    for index, folder in enumerate(folders):
        inputs[f"config_{index}"] = pc.entry(project, configs[STEPS[index]])
        fp = _read(folder / "input_fingerprint.json")
        for material, sha in fp["config_files"].items():
            inputs[f"pdk_material_{index}_{len(inputs)}"] = pc.entry(project, material, external=True)
        for name in ("invocation.log", "state_in.json", "state_out.json", "vibeic_receipt.json", "pdk_root.json"):
            outputs[f"producer_{index}_{name}"] = pc.entry(project, folder / name)
    launches = [json.loads(line) for line in journal.read_text().splitlines()]
    execution = [run for run in launches if "--id" in run["argv"]
                 and run["argv"][run["argv"].index("--id") + 1] == STEPS[-1]][-1]
    doc = {"steps": list(STEPS), "folders": [str(folder.relative_to(project)) for folder in folders],
           "image": image, "count": final["metrics"].get(KEY),
           "scope": "native two-stream geometric fidelity; LVS and full signoff NOT_MEASURED",
           "current": pc.build(project, "37.3", "stage4", design, pdk, "librelane", inputs, outputs, execution)}
    read_current(project, doc)
    write_json(path, doc)
    return doc


def connectivity(project, comparison):
    """Bind the native reference to the current shipped/reference XOR pair."""
    project = Path(project).resolve()
    doc = read_current(project)
    current = comparison["current"]
    _require(comparison.get("shipped_sha256_live") == current["inputs"]["shipped"]["sha256"],
             "NATIVE373_SHIPPED_IDENTITY_CHANGED")
    _require(current["inputs"].get("connectivity") == pc.entry(project, project / REL),
             "NATIVE373_DEPENDENCY_SWAPPED")
    _require(current["inputs"]["def"] == doc["current"]["inputs"]["def"], "NATIVE373_DEF_SWAPPED")
    _require(current["design"] == doc["current"]["design"]
             and current["pdk"] == doc["current"]["pdk"], "NATIVE373_CONTEXT_CHANGED")
    _require(current["inputs"]["reference"] in (doc["current"]["outputs"]["magic_gds"],
                                                  doc["current"]["outputs"]["klayout_gds"]),
             "NATIVE373_REFERENCE_NOT_NATIVE")
    return {"verdict": "PASS" if doc["count"] == 0 else "FAIL", "xor_difference_count": doc["count"],
            "evidence": REL, "evidence_sha256": pc.digest(project / REL),
            "reference_sha256": current["inputs"]["reference"]["sha256"],
            "scope": doc["scope"]}


class ShippedXorRunner:
    """The existing geometric script through a fresh standard container run."""
    kind = "docker_run"

    def __init__(self, project, image):
        self.project = Path(project).resolve()
        self.image = image
        self.detail = image + ":klayout"
        self.execution = None

    def covers(self, path):
        return Path(path).resolve().is_relative_to(self.project)

    def run(self, script, env, *, path_keys=(), timeout=1800):
        argv = ["docker", "run", "--rm", "--network", "none", "--cpus", "2",
                *_dmem.docker_memory_flags(),
                "-v", f"{self.project}:{self.project}", "-e", "QT_QPA_PLATFORM=offscreen"]
        for key, value in env.items():
            argv += ["-e", f"{key}={value}"]
        argv += [self.image, "--skip", "/usr/bin/time", "-v", "klayout", "-b", "-r", str(script)]
        cp = lc.run_container(argv, supervised=True,
                              log=self.project / "reports/phase3/gds_xor_native.log")
        self.execution = {"rc": cp.returncode, "argv": argv}
        return cp.returncode, cp.stdout, cp.stderr
