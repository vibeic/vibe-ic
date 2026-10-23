"""Bounded Step37.3 native stream dependency and read-only current consumer.

This measures two independent streams of the current routed database. It is
geometric stream fidelity evidence, never LVS or whole-PDK signoff.
"""
from __future__ import annotations


# `programs/` is a flat directory whose modules import each other by bare name
# (vibe-ic#2104): restore the condition a by-path load does not provide.
import os as _os
import sys as _sys

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import json
import os
import re
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


def _source_def(project):
    import execution_policy
    import librelane_fill_dfm as fill
    if execution_policy.request()['mode'] == 'default':
        stream = fill.validate_default_stream(project)
        return Path(stream['filled_def']).resolve()
    return project / 'phase3/stage3/pnr/routed.def'


def _source_inputs(project, definition):
    """Use the consumed fill producer's explicit views on the Default route."""
    import execution_policy
    pnr = project / 'phase3/stage3/pnr'
    design = pc.design_of(definition)
    paths = {'def': definition, 'netlist': pnr / f'{design}_pnr.v',
             'sdc': pnr / 'constraint.sdc'}
    if execution_policy.request()['mode'] == 'default':
        import librelane_fill_dfm as fill
        fill.validate_fill_consumption(project)
        tool = _read(project / fill.RECORD_REL)['odb']['tool']
        state_path = Path(tool['state']).resolve(strict=True)
        receipt = lc.validate_step_receipt(state_path.parent, fill.ODB_FILL_STEP)
        state = _read(state_path)
        for role, key in (('netlist', 'nl'), ('sdc', 'sdc')):
            path = Path(state[key]).resolve(strict=True)
            _require(path.is_relative_to(state_path.parent)
                     and receipt['sha256'].get(str(path.relative_to(state_path.parent)))
                     == pc.digest(path), 'NATIVE373_FILL_VIEW_UNBOUND: ' + role)
            paths[role] = path
    return paths


def _local_execution(project, folder, step, image):
    """Describe existing successful LOCAL receipt evidence, not a new launch.

    run_chain publishes this receipt only after rc0 and state_out. Its LOCAL
    runner validates the enclosing image attestation before and after the tool.
    Reuse follows the same scientific-input identity as run_chain; COMMANDS is
    not receipt-bound and is deliberately not treated as an execution journal.
    """
    receipt = lc.validate_step_receipt(folder, step)
    _require(_read(folder / "pdk_root.json").get("execution_route") == "LOCAL",
             "NATIVE373_LOCAL_ROUTE_CHANGED")
    provider = receipt["input"].get("local_provider")
    if provider is not None:
        native._retained_local_provider(project, provider, image)
        return {"kind": "retained_local_step_receipt", "rc": 0,
                "argv": ["librelane_contract.run_chain", step,
                         str((folder / "vibeic_receipt.json").relative_to(project))],
                "receipt": pc.entry(project, folder / "vibeic_receipt.json"),
                "local_provider": provider}
    original = receipt["input"].get("local_image")
    _require(isinstance(original, dict), "NATIVE373_LOCAL_IMAGE_MISSING")
    current = lc.local_image_attestation(image)
    _retained_local_image(original, current)
    return {"kind": "retained_local_step_receipt", "rc": 0,
            # This argv names the proof owner, not a reconstructed tool argv.
            "argv": ["librelane_contract.run_chain", step,
                     str((folder / "vibeic_receipt.json").relative_to(project))],
            "receipt": pc.entry(project, folder / "vibeic_receipt.json"),
            "local_image": original}


def _retained_local_image(original, current):
    """Validate an immutable LOCAL producer from a read-only consumer frame.

    Memory is part of a fresh execution/cache identity, but it is not a
    scientific input to a retained rc0 stream result.  Preserve the producer's
    actual bounded frame and require the live consumer to be independently
    attested; compare only the image bytes between those two executions.
    """
    required = {'image', 'image_id', 'repo_digests', 'cid', 'network_mode',
                'memory', 'memory_swap', 'auto_remove', 'attestation_path',
                'attestation_sha256'}

    def valid_frame(record):
        return (isinstance(record, dict) and required <= set(record)
                and isinstance(record['image'], str) and bool(record['image'])
                and bool(re.fullmatch(r'sha256:[0-9a-f]{64}',
                                      str(record['image_id'])))
                and isinstance(record['repo_digests'], list)
                and all(isinstance(value, str) for value in record['repo_digests'])
                and bool(re.fullmatch(r'[0-9a-f]{64}', str(record['cid'])))
                and record['network_mode'] == 'none'
                and type(record['memory']) is int and record['memory'] > 0
                and type(record['memory_swap']) is int
                and record['memory_swap'] >= record['memory']
                and record['auto_remove'] is True
                and Path(record['attestation_path']).is_absolute()
                and bool(re.fullmatch(r'[0-9a-f]{64}',
                                      str(record['attestation_sha256']))))

    _require(valid_frame(original), 'NATIVE373_RETAINED_FRAME_INVALID')
    _require(valid_frame(current), 'NATIVE373_CONSUMER_FRAME_INVALID')
    immutable = ('image', 'image_id', 'repo_digests')
    _require(all(original[key] == current[key] for key in immutable),
             'NATIVE373_LOCAL_IMAGE_CHANGED')


def _local_chain(project, folders):
    return len(folders) == len(STEPS) and all(
        _read(project / folder / "pdk_root.json").get("execution_route") == "LOCAL"
        for folder in folders)


def read_current(project, record=None):
    """Validate retained native producers, inputs, material and typed count."""
    project = Path(project).resolve()
    doc = record if record is not None else _read(project / REL)
    current = doc["current"]
    local = _local_chain(project, doc["folders"])
    refusal = pc.validate(project, current, step="37.3", stage="stage4",
                          tools=("librelane",),
                          required_inputs=("def", "netlist", "sdc", "technology"),
                          required_outputs=("magic_gds", "klayout_gds", "xor_report", "log") +
                                           (() if local else ("launches",)),
                          marker=None if local else "Exit status: 0")
    _require(not refusal, refusal)
    design = pc.design_of(_path(project, current["inputs"]["def"]))
    for role, path in _source_inputs(project, _source_def(project)).items():
        _require(pc.entry(project, path) == current["inputs"][role],
                 "NATIVE373_CURRENT_SOURCE_CHANGED: " + role)
    _require(doc.get("steps") == list(STEPS), "NATIVE373_WRONG_CHAIN")
    config_root = project / CONFIG
    launches = [] if local else [json.loads(line) for line in
        _path(project, current["outputs"]["launches"]).read_text().splitlines()]
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
        switch = project / "phase3/librelane_switch.json"
        mounts = native._pdk_mounts(project, _read(switch) if switch.is_file() else {},
                                    folder, doc["image"])
        _require(fp["config_files"] == lc._current_config_material(
            _read(config_root / f"{step}.json"), mounts), "NATIVE373_MATERIAL_CHANGED")
        import execution_policy
        if step == 'KLayout.StreamOut' and execution_policy.request()['mode'] == 'default':
            import _stream_input_record as sir
            import librelane_fill_dfm as fill
            stream = fill.validate_default_stream(project)
            source, why = sir.read(sir.record_path(Path(stream['pnr_gds'])))
            _require(source is not None, 'NATIVE373_STREAM_READSET_ABSENT: ' + why)
            for entry in source['native_cli']['inputs']:
                material = Path(entry['path'])
                for host, guest in mounts:
                    if material.is_relative_to(guest):
                        material = Path(host) / material.relative_to(guest)
                        break
                _require(fp['config_files'].get(str(material)) == entry['sha256'],
                         'NATIVE373_STREAM_READSET_CHANGED: ' + str(material))
        native._hashes(fp["state_files"])
        _require(all(Path(path).resolve().is_relative_to(project) for path in fp["state_files"]),
                 "NATIVE373_FOREIGN_STATE")
        for name, sha in receipt["sha256"].items():
            path = (folder / name).resolve(strict=True)
            _require(path.is_relative_to(folder) and pc.digest(path) == sha,
                     "NATIVE373_RECEIPT_CHANGED: " + name)
        if local:
            execution = _local_execution(project, folder, step, doc["image"])
            if step == STEPS[-1]:
                _require(current["execution"] == execution,
                         "NATIVE373_RECORDED_EXECUTION_CHANGED")
        else:
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
    _require(routed_def == _source_def(project), 'NATIVE373_WRONG_SOURCE_DEF')
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
    sources = {**_source_inputs(project, routed_def), "technology": technology}
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
        die = lc._def_die_area(routed_def)
        _require(die is not None, 'NATIVE373_DEF_DIE_AREA_NOT_MEASURED')
        overlay['DIE_AREA'] = (die, f'{routed_def}: DIEAREA / UNITS DISTANCE MICRONS')
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
               "log": pc.entry(project, folders[-1] / "invocation.log")}
    local = _local_chain(project, folders)
    if not local:
        outputs["launches"] = pc.entry(project, journal)
    for index, folder in enumerate(folders):
        inputs[f"config_{index}"] = pc.entry(project, configs[STEPS[index]])
        fp = _read(folder / "input_fingerprint.json")
        for material, sha in fp["config_files"].items():
            inputs[f"pdk_material_{index}_{len(inputs)}"] = pc.entry(project, material, external=True)
        for name in ("invocation.log", "state_in.json", "state_out.json", "vibeic_receipt.json", "pdk_root.json"):
            outputs[f"producer_{index}_{name}"] = pc.entry(project, folder / name)
    if local:
        execution = _local_execution(project, folders[-1], STEPS[-1], image)
    else:
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
    """The geometric script through the existing attested LOCAL or Docker route."""
    kind = "docker_run"

    def __init__(self, project, image):
        self.project = Path(project).resolve()
        # read_current retains the producer's identity. Execute a new XOR in
        # the current admitted provider, including after an ordinary resume.
        if str(image).startswith(lc.LOCAL_PROVIDER_IDENTITY_PREFIX):
            image = lc.resolve_image(self.project)
        self.image = image
        self.local = lc._provider_for_image(image) is not None or lc._ce.no_container_route()
        self.binary = "klayout"
        if self.local:
            import shutil
            self.binary = shutil.which("klayout") or "klayout"
            self.kind = "host"
        self.detail = self.binary + " -b -r" if self.local else image + ":klayout"
        self.execution = None

    def covers(self, path):
        return Path(path).resolve().is_relative_to(self.project)

    def run(self, script, env, *, path_keys=(), timeout=1800):
        network, command = lc.native_tool_command(
            self.image, ["/usr/bin/time", "-v", self.binary, "-b", "-r", str(script)])
        argv = ["docker", "run", *_dmem.docker_memory_flags(), "--rm",
                "--network", network, *([] if self.local else ["--cpus", "2"]),
                "-v", f"{self.project}:{self.project}", "-e", "QT_QPA_PLATFORM=offscreen"]
        for key, value in env.items():
            argv += ["-e", f"{key}={value}"]
        argv += [self.image, "--skip", *command]
        cp = lc.run_container(argv, supervised=True,
                              log=self.project / "reports/phase3/gds_xor_native.log")
        self.execution = {"rc": cp.returncode, "argv": list(cp.args) if self.local else argv}
        return cp.returncode, cp.stdout, cp.stderr
