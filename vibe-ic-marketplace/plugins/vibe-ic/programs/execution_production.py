"""Canonical Step 9 production front door.

Only the public ``execution_modes.Registry``/``Controller`` API is used here.
The adapter launches :mod:`execution_native_worker`, which calls the existing
LibreLane synthesis implementation once.  No Python fixture, handwritten gate
receipt, or caller supplied tool version is a producer.
"""
from __future__ import annotations


# `programs/` is a flat directory whose modules import each other by bare name
# (vibe-ic#2104): restore the condition a by-path load does not provide.
import os as _os
import sys as _sys

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from dataclasses import asdict, fields, is_dataclass
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Mapping

from _atomic_artefact import write_json
import execution_modes as em
import execution_synthesis_engines as engines
import execution_native_installation as installation

NETLIST = engines.NETLIST
AREA = engines.AREA
STATS = engines.STATS
PRODUCER_RECEIPT = engines.PRODUCER_RECEIPT
NATIVE_COMMANDS = engines.NATIVE_COMMANDS
CANONICAL_NETLIST = engines.CANONICAL_NETLIST
CANONICAL_AREA = engines.CANONICAL_AREA
CANONICAL_STATS = engines.CANONICAL_STATS
CANONICAL_AREA_ANY = engines.CANONICAL_AREA_ANY
REQUIRED_GATES = engines.REQUIRED_GATES

PROGRAMS = Path(__file__).resolve().parent
FLOW = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
PORTFOLIO = PROGRAMS / "data" / "execution_modes_portfolio.json"
WORKER = PROGRAMS / "execution_native_worker.py"
RUNNER = PROGRAMS / "phase3_one_shot_runner.py"
GATE_PROGRAMS = (
    "synth_netlist_check.py", "provenance_check.py",
    "area_total_vs_budget_check.py", "pdk_consistency_check.py",
)
_STEP9_INPUTS: dict[str, dict[str, Path]] = {}
_STEP9_EXPECTED: dict[str, dict[str, str]] = {}


class StepRequest:
    """Small source-bound request used by the normal runner route."""

    def __init__(self, step_id: str, project: Path, parameters: Mapping[str, object],
                 lease: Path | None = None, record: Path | None = None,
                 source_sha: str | None = None, source_files: Mapping[str, str] | None = None):
        self.step_id = str(step_id)
        self.project = Path(project)
        self.parameters = dict(parameters)
        self.lease = Path(lease) if lease is not None else None
        self.record = Path(record) if record is not None else None
        self.source_sha = source_sha or engines.source_sha()
        self.source_files = dict(source_files or source_identity()[1])


class PreparedStep:
    def __init__(self, context: em.Context | None, registry: em.Registry | None,
                 *, disposition: str = "execute", reason: str = ""):
        self.context, self.registry = context, registry
        self.disposition, self.reason = disposition, reason
        self.consume = import_selected
        self.adoption_paths = ("project/phase2/stage2/synth", "producer.json",
                               "native_commands.jsonl")


def _regular(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _sha(path: Path) -> str:
    return em.digest(path)


def source_identity(extra: Mapping[str, str] | None = None) -> tuple[str, dict[str, str]]:
    """Bind caller, registry, native worker, producer and current consumer closure."""
    files = {}
    for path in (PROGRAMS / "execution_modes.py", PROGRAMS / "execution_synthesis_engines.py",
                 PROGRAMS / "execution_production.py", WORKER, RUNNER,
                 PROGRAMS / "execution_native_installation.py",
                 PROGRAMS / "execution_policy.py", PROGRAMS / "execution_frontend_providers.py",
                 PROGRAMS / "execution_authority.py", PROGRAMS / "execution_source_snapshot.py",
                 PROGRAMS / "execution_backend_snapshot.py", PROGRAMS / "execution_adapters_backend.py",
                 PROGRAMS / "execution_adapters_release.py", PROGRAMS / "execution_provider_catalog.py",
                 PROGRAMS / "vibe_ic_one_shot_runner.py",
                 PROGRAMS / "librelane_contract.py", PROGRAMS / "_atomic_artefact.py",
                 FLOW, PORTFOLIO, *(PROGRAMS / name for name in GATE_PROGRAMS),
                 PROGRAMS / "synth_area_stats_emit.py", PROGRAMS / "_yosys_stat.py"):
        if not _regular(path):
            raise em.Refusal("PRODUCTION_SOURCE_MISSING", str(path))
        files[str(path.resolve())] = _sha(path)
    if extra:
        for name, value in extra.items():
            p = Path(name)
            if (not p.is_absolute() or not _regular(p) or
                    not isinstance(value, str) or _sha(p) != value):
                raise em.Refusal("ADAPTER_SOURCE_MISMATCH", str(p))
            files[str(p.resolve())] = value
    # ca3b registers complete executable/importer closure, not only the
    # historical provider's immediate files. Keep Core's authority intact.
    from execution_provider_catalog import source_closure, implementation_closure
    closure = source_closure({Path(name) for name in files})
    closure.update(implementation_closure(WORKER))
    closure.update(em._source_closure(closure))
    for path in closure:
        if _regular(path):
            files[str(path.resolve())] = _sha(path)
    return engines.source_sha(), files


def _tool_and_image(image: object, project: Path | None = None) -> tuple[str, dict, list[str]]:
    """Measure image identity; labels and caller self-reports are rejected."""
    missing = []
    if image is None or not str(image).strip():
        try:
            import librelane_contract
            image = librelane_contract.resolve_image(project)
        except Exception as exc:
            missing.append("image:" + type(exc).__name__)
            return "UNMEASURED:image", {}, missing
    image_text = str(image)
    import _eda_pin
    digest = _eda_pin.reference_digest(image_text)
    bare_id = image_text if re.fullmatch(r"sha256:[0-9a-f]{64}", image_text) else None
    if bare_id is None and digest is None:
        missing.append("image_id")
        return "UNMEASURED:image_id", {}, missing
    try:
        import librelane_image_facts as facts
        measured = facts.image_facts(image_text)
    except Exception as exc:  # absent Docker/EDA is an honest NM arm
        return "UNMEASURED:image_facts", {}, ["image_facts:" + type(exc).__name__]
    measured_id = measured.get("image_id") if isinstance(measured, dict) else None
    if not isinstance(measured_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", measured_id):
        missing.append("measured_image_id")
    elif bare_id is not None and measured_id != bare_id:
        missing.append("measured_image_id")
    elif digest is not None and measured.get("image") != image_text:
        missing.append("measured_image_reference")
    if not measured.get("librelane_version"):
        missing.append("librelane_version")
    return (measured_id if not missing else "UNMEASURED:" + ",".join(missing),
            measured if isinstance(measured, dict) else {}, missing)


def _pdk_dict(pdk: object) -> dict:
    if is_dataclass(pdk) and not isinstance(pdk, type):
        values = asdict(pdk)
    elif isinstance(pdk, Mapping):
        values = dict(pdk)
    else:
        values = {}
        for name in ("name", "liberty", "tech_lef", "cell_lef", "cell_gds", "site", "drc_deck"):
            if hasattr(pdk, name):
                values[name] = getattr(pdk, name)
    if hasattr(pdk, "pdk_root_host"):
        values["pdk_root_host"] = getattr(pdk, "pdk_root_host")
    def jsonable(value):
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, list):
            return [jsonable(item) for item in value]
        if isinstance(value, dict):
            return {str(key): jsonable(item) for key, item in value.items()}
        return value
    return jsonable(values)


def _pdk_liberty(pdk: object) -> Path | None:
    value = _pdk_dict(pdk).get("liberty")
    if not value:
        return None
    path = Path(str(value))
    return path if _regular(path) else None


def _host_pdk(project: Path, pdk: object, image_id: str) -> dict:
    """Resolve a runner PdkConfig's declared guest assets to host bytes."""
    values = _pdk_dict(pdk)
    name = str(values.get("name", ""))
    root_value = values.get("pdk_root_host")
    root = Path(str(root_value)) if root_value else None
    if root is None or not root.is_dir():
        try:
            import librelane_contract
            resolved = librelane_contract.pdk_root_resolution(
                project, name, image=image_id)
            parent = Path(str(resolved["path"]))
            candidate = parent / name
            if candidate.is_dir():
                root = candidate
        except Exception:
            root = None
    if root is None or not root.is_dir():
        return values
    values["pdk_root_host"] = str(root.resolve())
    guest_prefixes = (f"/foss/pdks/{name}/", f"/pdk/{name}/")
    for key, value in list(values.items()):
        if isinstance(value, str):
            for prefix in guest_prefixes:
                if value.startswith(prefix):
                    values[key] = str(root / value[len(prefix):])
                    break
    return values


def _canonical_inputs(project: Path, declaration: Path | None, pdk: object) -> dict[str, Path]:
    declaration = declaration or project / "input/submission_template/tapeout_declaration.json"
    if not _regular(declaration):
        raise em.Refusal("PRODUCTION_DECLARATION_MISSING", str(declaration))
    rtl_root = project / "phase2/stage1/rtl"
    if rtl_root.is_symlink() or not rtl_root.is_dir():
        raise em.Refusal("PRODUCTION_RTL_INPUT_MISSING", str(rtl_root))
    rtl = sorted(p for p in rtl_root.rglob("*") if _regular(p))
    if not rtl:
        raise em.Refusal("PRODUCTION_RTL_INPUT_MISSING", str(rtl_root))
    inputs = {"project/input/submission_template/tapeout_declaration.json": declaration}
    for path in rtl:
        rel = path.relative_to(rtl_root).as_posix()
        inputs["project/phase2/stage1/rtl/" + rel] = path
    docs_root = project / "phase1/generated_docs"
    if docs_root.is_symlink() or not docs_root.is_dir():
        raise em.Refusal("PRODUCTION_LDOC_INPUT_MISSING", str(docs_root))
    docs = sorted(p for p in docs_root.rglob("*") if _regular(p))
    if not docs:
        raise em.Refusal("PRODUCTION_LDOC_INPUT_MISSING", str(docs_root))
    for path in docs:
        inputs["project/phase1/generated_docs/" + path.relative_to(docs_root).as_posix()] = path
    liberty = _pdk_liberty(pdk)
    if liberty is None:
        raise em.Refusal("PRODUCTION_PDK_LIBERTY_MISSING", str(pdk))
    inputs["pdk/" + liberty.name] = liberty
    pdk_values = _pdk_dict(pdk)
    root = Path(str(pdk_values.get("pdk_root_host", "")))
    if not root.is_dir() or root.is_symlink():
        raise em.Refusal("PRODUCTION_PDK_ROOT_MISSING", str(root))
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        entries.append({"path": str(path.relative_to(root)),
                        "sha256": _sha(path), "size": path.stat().st_size})
    manifest = Path(tempfile.mkstemp(prefix="step9-pdk-", suffix=".manifest.json")[1])
    write_json(manifest, {"schema": "vibe-ic/step9-pdk-tree/1",
                          "root": str(root.resolve()), "files": entries}, sort_keys=True)
    inputs["pdk/tree-manifest.json"] = manifest
    return inputs


def _require_librelane_pdk_config(pdk_root: Path, manifest: Mapping[str, object]) -> str:
    """Require the exact LibreLane/OpenLane PDK config in the measured tree."""
    if (not isinstance(manifest, Mapping) or
            manifest.get("schema") != "vibe-ic/step9-pdk-tree/1" or
            Path(str(manifest.get("root", ""))).resolve() != pdk_root.resolve()):
        raise em.Refusal("STEP9_PDK_MANIFEST_INVALID", str(pdk_root))
    rows = manifest.get("files")
    if not isinstance(rows, list):
        raise em.Refusal("STEP9_PDK_MANIFEST_INVALID", str(pdk_root))
    by_path = {str(row.get("path")): row for row in rows if isinstance(row, Mapping)}
    for relative in ("libs.tech/librelane/config.tcl", "libs.tech/openlane/config.tcl"):
        row = by_path.get(relative)
        path = pdk_root / relative
        if (row is not None and _regular(path) and
                row.get("sha256") == _sha(path) and
                row.get("size") == path.stat().st_size):
            return relative
    raise em.Refusal("STEP9_LIBRELANE_PDK_CONFIG_UNAVAILABLE",
                     "neither libs.tech/librelane/config.tcl nor "
                     "libs.tech/openlane/config.tcl is in the current PDK manifest")


def _request_spec(*, project: Path, top: str, pdk: object, image_id: str,
                  source_sha: str, source_files: Mapping[str, str],
                  inputs: Mapping[str, Path], lease: Path | None) -> dict:
    return {
        "schema": 1, "step_id": "9", "top": top,
        "original_project": str(project.resolve()),
        "pdk": _pdk_dict(pdk), "image_id": image_id,
        "pdk_root_host": _pdk_dict(pdk).get("pdk_root_host"),
        "source_sha": source_sha, "source_files": dict(source_files),
        "synthesis_engine": engines.LIBRELANE.contract(),
        "input_hashes": {name: _sha(path) for name, path in inputs.items()},
        "lease": str(lease.resolve()) if lease else None,
    }


def _native_adapter(context: em.Context, source_sha: str, source_files: Mapping[str, str],
                    image_id: str, facts: dict, spec_path: Path, pdk: object,
                    tool: object = None,
                    *, installation_receipt: Mapping[str, object] | None = None,
                    availability_reason: str | None = None,
                    include_same_family_wrapper: bool = False) -> em.Adapter:
    objective = dict(context.objective)
    binary = Path(sys.executable).resolve()
    source_files = dict(source_files)
    source_files.setdefault(str(binary), _sha(binary))
    missing = []
    if not image_id.startswith("sha256:"):
        missing.append("image_id")
    chip_steps = (facts.get("flows", {}).get("Chip", [])
                  if isinstance(facts, dict) and isinstance(facts.get("flows"), dict)
                  else [])
    if image_id.startswith("sha256:") and not set(engines.LIBRELANE.native_steps).issubset(chip_steps):
        missing.append("native_steps")
    if not _regular(binary):
        missing.append("tool")
    if tool is not None:
        try:
            requested = Path(str(tool)).resolve()
        except (OSError, RuntimeError):
            requested = Path("/") / "missing-step9-tool"
        if not _regular(requested) or requested != binary:
            missing.append("tool_identity")
    if not spec_path.is_file():
        missing.append("request")
    if not context.inputs:
        missing.append("input")
    names = set(context.inputs)
    if "request.json" not in names:
        missing.append("input:request.json")
    if not any(name == "project/input/submission_template/tapeout_declaration.json" for name in names):
        missing.append("input:tapeout_declaration.json")
    if not any(name.startswith("project/phase2/stage1/rtl/") for name in names):
        missing.append("input:rtl")
    if not any(name.startswith("project/phase1/generated_docs/") for name in names):
        missing.append("input:generated_docs")
    if not any(name.startswith("pdk/") for name in names):
        missing.append("input:pdk")
    allowed = ("request.json", "pdk/", "project/input/submission_template/tapeout_declaration.json",
               "project/phase2/stage1/rtl/", "project/phase1/generated_docs/")
    if any(not (name == allowed[0] or name.startswith(allowed[1]) or name == allowed[2]
                or name.startswith(allowed[3]) or name.startswith(allowed[4])) for name in names):
        missing.append("input:noncanonical")
    if installation_receipt is None:
        missing.append("native_installation_receipt")
    reason = availability_reason or ("MISSING_NATIVE_FACTS:" + ",".join(missing))
    adapter = em.Adapter(
        arm_id=engines.LIBRELANE.arm_id, tool_id="step9-worker",
        step_id="9", source_sha=source_sha, source_files=source_files,
        # This is measured image identity, never the caller's label/version.
        tool_version=image_id if image_id.startswith("sha256:") else "UNMEASURED:" + reason,
        engine_families=engines.LIBRELANE.engine_families,
        components=(em.Component("native-mapped-synthesis",
            (str(binary), str(WORKER), "--inputs", "{inputs}", "--outputs", "{outputs}"),
            timeout_s=7200),
            *(em.Component(name, (str(binary),str(WORKER),"--gate",name,
                "--inputs","{inputs}","--outputs","{outputs}"), timeout_s=60)
              for name in REQUIRED_GATES)), validate=validate_synthesis,
        required_outputs=(NETLIST, PRODUCER_RECEIPT, NATIVE_COMMANDS),
        objective=objective,
        qualification_evidence=json.dumps({"engine": engines.LIBRELANE.contract(),
            "image_facts": facts,
            "native_installation_receipt": dict(installation_receipt or {})}, sort_keys=True),
        qualified=installation_receipt is not None,
        available=not missing and installation_receipt is not None,
        availability_reason="" if not missing and installation_receipt is not None else reason,
        # LibreLane imports a large Python/Go toolchain; 128 MB causes the
        # image's Go runtime to abort during Config.load before synthesis.
        cpus=1, ram_mb=4096,
        output_contract={CANONICAL_NETLIST: (NETLIST,),
                         CANONICAL_AREA_ANY: (NETLIST,)},
    )
    if not include_same_family_wrapper:
        return adapter
    # Ultra may disclose the wrapper so Controller's family deduplication is
    # exercised, but it cannot claim independent engine credit.
    return adapter


def build_registry(*, context: em.Context, image: object = None, tool: object = None,
                   inputs: Mapping[str, Path] | None = None, fixture: bool = False,
                   include_same_family_wrapper: bool = False,
                   request_path: Path | None = None, pdk: object = None,
                   registry: em.Registry) -> em.Registry:
    """Build the only source-owned provider; fixture arguments are rejected."""
    if inputs is not None and dict(inputs) != dict(context.inputs):
        raise em.Refusal("PRODUCTION_INPUT_POPULATION_CHANGED", "context/input mismatch")
    source, files = source_identity()
    facts = {}
    image_id, facts, missing = _tool_and_image(image)
    if fixture:
        missing = ["synthetic_fixture_forbidden"]
        image_id = "UNMEASURED:synthetic_fixture_forbidden"
    spec = request_path or Path("/definitely/missing/step9-request.json")
    adapter = _native_adapter(context, source, files, image_id, facts, spec, pdk, tool,
                              include_same_family_wrapper=include_same_family_wrapper)
    registry.register(adapter)
    return registry


def _json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _gate_verdict(rc: int | None, report: dict | None) -> str:
    if rc == 1:
        return "FAIL"
    if rc != 0:
        return "NOT_MEASURED"
    if not isinstance(report, dict):
        return "NOT_MEASURED"
    verdict = report.get("verdict")
    if verdict in ("PASS", "FAIL"):
        return verdict
    if report.get("summary", {}).get("pass") is True:
        return "PASS"
    if report.get("summary", {}).get("pass") is False:
        return "FAIL"
    if report.get("ok") is True:
        return "PASS"
    if report.get("ok") is False:
        return "FAIL"
    return "NOT_MEASURED"


def _run_gate(name: str, argv: list[str], directory: Path) -> tuple[str, Path]:
    script = PROGRAMS / (name + ".py")
    report = directory / (name + ".json")
    if not _regular(script):
        return "NOT_MEASURED", report
    command = [str(Path(sys.executable).resolve()), str(script), *argv,
               "--json", str(report)]
    try:
        cp = subprocess.run(command, cwd=directory, capture_output=True,
                            text=True, timeout=180)
    except (OSError, subprocess.SubprocessError):
        return "NOT_MEASURED", report
    return _gate_verdict(cp.returncode, _json(report)), report


def _output_hashes(outputs: Path) -> dict[str, str]:
    result = {}
    for path in outputs.rglob("*"):
        if path.is_file() and not path.is_symlink():
            rel = path.relative_to(outputs).as_posix()
            if (rel in (PRODUCER_RECEIPT, NATIVE_COMMANDS)
                    or rel.startswith("project/phase2/stage2/synth/")
                    or rel.startswith("project/phase3/")
                    or rel.startswith("project/provenance.jsonl")
                    or rel.startswith("validations/")):
                result[rel] = _sha(path)
    return result


def _synthesis_gate_commands(outputs, spec, producer, engine):
    outputs = Path(outputs)
    project = outputs / 'project'
    rtl_root = project / 'phase2/stage1/rtl'
    netlist = project / CANONICAL_NETLIST
    native_path = Path(str(producer['native_tool_netlist']))
    rtl = [str(path) for path in sorted(rtl_root.rglob('*')) if _regular(path)]
    liberty = spec.get('pdk',{}).get('liberty')
    pdk_lib = Path(str(liberty)) if liberty else outputs/'pdk/missing.lib'
    if not pdk_lib.is_file(): pdk_lib=outputs/'pdk'/pdk_lib.name
    area_argv=[str(project)]
    if pdk_lib.is_file(): area_argv += ['--library',str(pdk_lib)]
    pdk_name=str(spec.get('pdk',{}).get('name',''))
    if pdk_name: area_argv += ['--pdk',pdk_name]
    return {
        'synth_netlist_check':['--netlist',str(netlist),'--tool-netlist',str(native_path),'--rtl',*rtl],
        'area_total_vs_budget_check':area_argv,
        'pdk_consistency_check':['--netlist',str(netlist),'--pdk-lib',str(pdk_lib)],
        'provenance_check':[str(project),'--output',str(native_path.relative_to(project)),
                            '--tool',engine.provenance_tool,'--require-measured'],
    }


def run_synthesis_gate(inputs: Path, outputs: Path, name: str) -> int:
    if name not in REQUIRED_GATES:
        raise em.Refusal('UNKNOWN_SYNTHESIS_GATE', name)
    spec=json.loads((Path(inputs)/'request.json').read_text())
    producer=_json(Path(outputs)/PRODUCER_RECEIPT)
    if not producer or producer.get('status')!='PASS':
        # The real Step9 consumer classifies a bound producer FAIL as FAIL.
        # Return a completed component status here so generic supervision can
        # reach that consumer; missing/unreadable/unmeasured stays rc=2/NM.
        return 0 if producer and producer.get('status')=='FAIL' else 2
    engine=engines.consume_producer(spec,producer)
    commands=_synthesis_gate_commands(outputs,spec,producer,engine)
    destination=Path(outputs)/'validations';destination.mkdir(exist_ok=True)
    verdict,_=_run_gate(name,commands[name],destination)
    return 0 if verdict=='PASS' else 1 if verdict=='FAIL' else 2


def validate_synthesis(outputs: Path, binding: Mapping[str, object]) -> em.Evidence:
    """Freshly consume native outputs and gates; never trust a receipt string."""
    outputs = Path(outputs).resolve()
    gates = {name: "NOT_MEASURED" for name in binding.get("required_gates", REQUIRED_GATES)}
    producer_path = outputs / PRODUCER_RECEIPT
    commands_path = outputs / NATIVE_COMMANDS
    producer = _json(producer_path)
    hashes = _output_hashes(outputs)
    if producer is None or not commands_path.is_file():
        return em.Evidence(binding, "NOT_MEASURED", gates, hashes,
                           detail="native producer receipt/command journal missing")
    if producer.get("binding") != dict(binding):
        raise em.Refusal("PRODUCTION_WORKER_BINDING_UNBOUND", str(producer_path))
    status = producer.get("status")
    if status == "FAIL":
        return em.Evidence(binding, "FAIL", gates, hashes,
                           detail=producer.get("detail", "native producer measured FAIL"))
    if status != "PASS":
        return em.Evidence(binding, "NOT_MEASURED", gates, hashes,
                           detail=producer.get("detail", "native producer not measured"))
    if not engines.native_entrypoint_is_real(producer.get("native_entrypoint")):
        raise em.Refusal("PRODUCTION_SYNTH_ENGINE_PRODUCER_CHANGED", "native_entrypoint")
    spec_path = outputs.parent / "inputs" / "request.json"
    spec = _json(spec_path)
    if spec is None:
        raise em.Refusal("PRODUCTION_REQUEST_MISSING", str(spec_path))
    if not isinstance(spec.get("image_id"), str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", spec["image_id"]):
        raise em.Refusal("PRODUCTION_IMAGE_UNBOUND", str(spec.get("image_id")))
    engine = engines.consume_producer(spec, producer)
    if producer.get("source_sha") != binding.get("source_sha") or spec.get("source_sha") != binding.get("source_sha"):
        raise em.Refusal("PRODUCTION_WORKER_SOURCE_UNBOUND", str(producer_path))
    if producer.get("source_files") != spec.get("source_files"):
        raise em.Refusal("PRODUCTION_WORKER_SOURCE_UNBOUND", "source_files")
    for name, expected in spec.get("source_files", {}).items():
        path = Path(name)
        if not _regular(path) or _sha(path) != expected:
            raise em.Refusal("ADAPTER_SOURCE_MISMATCH", name)
    expected_inputs = {k: v for k, v in binding.get("inputs", {}).items() if k != "request.json"}
    install = spec.get("native_installation_receipt")
    if (not isinstance(install, dict) or install.get("status") != "MEASURED" or
            install.get("step_id") != "9" or install.get("image_id") != spec.get("image_id") or
            install.get("source_sha") != binding.get("source_sha") or
            install.get("source_files") != spec.get("source_files") or
            install.get("input_hashes") != expected_inputs or
            spec.get("native_installation_receipt_sha256") != install.get("receipt_sha256") or
            not installation.verify_receipt_digest(install)):
        raise em.Refusal("STEP9_INSTALLATION_RECEIPT_UNBOUND", str(spec_path))
    if producer.get("native_installation_receipt_sha256") != install.get("receipt_sha256"):
        raise em.Refusal("STEP9_PRODUCER_INSTALLATION_UNBOUND", str(producer_path))
    if producer.get("input_hashes") != expected_inputs:
        raise em.Refusal("PRODUCTION_WORKER_INPUT_MANIFEST_UNBOUND", str(producer_path))
    project = outputs / "project"
    if (producer.get("schema") != engines.RECEIPT_SCHEMA or
            producer.get("step_id") != engines.STEP_ID or
            producer.get("canonical_netlist") != CANONICAL_NETLIST):
        raise em.Refusal("PRODUCTION_SYNTH_RECEIPT_SCHEMA_INVALID", str(producer_path))
    producer_top = producer.get("top")
    expected_top = spec.get("top")
    if (not isinstance(producer_top, str) or
            not isinstance(expected_top, str) or producer_top != expected_top):
        raise em.Refusal("PRODUCTION_SYNTH_TOP_UNBOUND", str(producer_path))
    source_tree_sha256 = engines.tree_digest(spec.get("source_files", {}))
    input_tree_sha256 = engines.tree_digest(expected_inputs)
    if (producer.get("source_tree_sha256") != source_tree_sha256 or
            producer.get("input_tree_sha256") != input_tree_sha256):
        raise em.Refusal("PRODUCTION_SYNTH_TREE_HASH_MISMATCH", str(producer_path))
    tool = producer.get("tool")
    expected_tool = {
        "image_id": spec.get("image_id"),
        "native_entrypoint": engine.native_entrypoint,
        "native_trace": producer.get("native_trace"),
    }
    if (tool != expected_tool or
            producer.get("tool_sha256") != engines.stable_digest(expected_tool)):
        raise em.Refusal("PRODUCTION_SYNTH_TOOL_HASH_MISMATCH", str(producer_path))
    trace_rows = producer.get("native_trace")
    if not isinstance(trace_rows, list):
        raise em.Refusal("PRODUCTION_NATIVE_TRACE_INVALID", str(producer_path))
    command_rows = []
    try:
        for line in commands_path.read_text().splitlines():
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("command row")
            command_rows.append(row)
    except (OSError, ValueError, TypeError) as exc:
        raise em.Refusal("PRODUCTION_NATIVE_COMMAND_JOURNAL_INVALID", str(exc)) from exc
    if not any(row.get("native_entrypoint") == engine.native_entrypoint
               and row.get("image_id") == spec.get("image_id")
               and row.get("executed") is True for row in command_rows):
        raise em.Refusal("PRODUCTION_NATIVE_INVOCATION_UNPROVEN", str(commands_path))
    if project.is_symlink() or not project.is_dir():
        raise em.Refusal("PRODUCTION_PROJECT_OUTPUT_MISSING", str(project))
    # The worker's writable project is a derived view. Rebind every canonical
    # declaration/RTL byte to the Controller-frozen input before any gate can
    # read it; a co-mutated output cannot launder a stale valid receipt.
    for name, expected in expected_inputs.items():
        if name.startswith("project/"):
            actual = project / name.removeprefix("project/")
        elif name.startswith("pdk/"):
            actual = outputs / name
        else:
            continue
        if not _regular(actual) or _sha(actual) != expected:
            raise em.Refusal("PRODUCTION_DERIVED_INPUT_CHANGED", name)
    receipt_outputs = producer.get("output_hashes")
    if not isinstance(receipt_outputs, dict):
        raise em.Refusal("PRODUCTION_SYNTH_OUTPUT_HASHES_MISSING", str(producer_path))
    current_outputs = _output_hashes(outputs)
    for rel, expected in receipt_outputs.items():
        if not isinstance(rel, str) or current_outputs.get(rel) != expected:
            raise em.Refusal("PRODUCTION_SYNTH_OUTPUT_HASH_MISMATCH", rel)
    project_root = project.resolve()
    for row in trace_rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise em.Refusal("PRODUCTION_NATIVE_TRACE_INVALID", str(producer_path))
        raw_path = row["path"]
        relative = Path(raw_path)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise em.Refusal("PRODUCTION_NATIVE_TRACE_INVALID", raw_path)
        trace_path = (project / relative).resolve()
        output_rel = "project/" + relative.as_posix()
        if (not trace_path.is_relative_to(project_root) or
                output_rel not in receipt_outputs or
                output_rel not in current_outputs or
                not _regular(trace_path) or
                row.get("sha256") != receipt_outputs[output_rel] or
                row.get("sha256") != current_outputs[output_rel] or
                row.get("sha256") != _sha(trace_path)):
            raise em.Refusal("PRODUCTION_NATIVE_TRACE_INVALID", raw_path)
    declaration = project / "input/submission_template/tapeout_declaration.json"
    rtl_root = project / "phase2/stage1/rtl"
    netlist = project / CANONICAL_NETLIST
    area = project / CANONICAL_AREA
    stats = project / CANONICAL_STATS
    if not _regular(declaration) or not rtl_root.is_dir() or not any(_regular(p) for p in rtl_root.rglob("*")):
        raise em.Refusal("PRODUCTION_CANONICAL_INPUT_MISSING", str(project))
    if not _regular(netlist) or not netlist.read_text(errors="replace").strip():
        return em.Evidence(binding, "NOT_MEASURED", gates, hashes,
                           detail="native mapped netlist missing or empty")
    native_path = Path(str(producer.get("native_tool_netlist", "")))
    if (not _regular(native_path) or native_path.resolve() == netlist.resolve()
            or not native_path.resolve().is_relative_to(project)):
        raise em.Refusal("PRODUCTION_NATIVE_NETLIST_UNBOUND", str(native_path))
    native_output_rel = "project/" + native_path.resolve().relative_to(project.resolve()).as_posix()
    required_output_hashes = (NETLIST, native_output_rel, NATIVE_COMMANDS)
    if any(rel not in receipt_outputs or rel not in current_outputs
           for rel in required_output_hashes):
        raise em.Refusal("PRODUCTION_SYNTH_OUTPUT_HASHES_MISSING", str(producer_path))
    expected_binding = engines.consumer_binding(
        top=str(spec.get("top", "")), native_netlist=native_output_rel,
        canonical_sha256=current_outputs[NETLIST],
        native_sha256=current_outputs[native_output_rel],
        source_tree_sha256=source_tree_sha256,
        input_tree_sha256=input_tree_sha256,
        tool_sha256=producer["tool_sha256"])
    if producer.get("consumer_binding") != expected_binding:
        raise em.Refusal("PRODUCTION_SYNTH_CONSUMER_UNBOUND", str(producer_path))
    if _sha(netlist) != _sha(native_path):
        return em.Evidence(binding, "FAIL", gates, hashes,
                           detail="canonical netlist differs from native tool netlist")
    area_valid = (_regular(area) and bool(re.search(
        r"(?:area|Area|AREA)[^0-9]*(?:[0-9]+(?:\.[0-9]+)?|[0-9]+e[+-]?[0-9]+)",
        area.read_text(errors="replace"))))
    stat = _json(stats)
    stats_valid = (isinstance(stat, dict)
                   and stat.get("schema") == "vibe-ic/synth-stats/1"
                   and type(stat.get("chip_area")) in (int, float)
                   and math.isfinite(stat["chip_area"])
                   and isinstance(stat.get("netlist"), str)
                   and ((stat.get("netlist_sha256") == "sha256:" + _sha(native_path))
                        or stat.get("netlist_digest") == _sha(netlist)))
    if not (area_valid or stats_valid):
        return em.Evidence(binding, "NOT_MEASURED", gates, hashes,
                           detail="canonical area.rpt OR stats.json missing")
    native_tool_netlist = producer.get("native_tool_netlist")
    validation_dir = outputs / "validations"
    validation_dir.mkdir(exist_ok=True)
    for name, argv in _synthesis_gate_commands(outputs, spec, producer, engine).items():
        gates[name], _ = _run_gate(name, argv, validation_dir)
    hashes = _output_hashes(outputs)
    if "FAIL" in gates.values():
        verdict = "FAIL"
    elif all(gates.get(name) == "PASS" for name in REQUIRED_GATES):
        verdict = "PASS"
    else:
        verdict = "NOT_MEASURED"
    metrics = {}
    if isinstance(stat, dict) and type(stat.get("chip_area")) in (int, float) and math.isfinite(stat["chip_area"]):
        metrics["mapped_area_um2"] = stat["chip_area"]
    return em.Evidence(binding, verdict, gates, hashes, metrics,
                       detail="fresh canonical Step9 gate consumption")


def _make_context(project: Path, inputs: Mapping[str, Path], source: str,
                  source_files: Mapping[str, str], top: str) -> em.Context:
    from execution_authority import consume
    from execution_policy import controller_fields
    route = consume()["route"]
    if route["project"] != str(project.resolve()) or route["source_sha"] != source:
        raise em.Refusal("PRODUCTION_ROUTE_UNBOUND", str(project))
    objective = {"metric": "mapped_area_um2", "direction": "min", "top": top}
    return em.Context("9", source, inputs, objective, engines.REQUIRED_GATES,
                      native_mode="librelane", project_digest=route["project_digest"],
                      **controller_fields(ic_ip_path=route["ic_ip_path"],
                                          route_receipt=route))


def prepare(project: Path | StepRequest, top: str | None = None, pdk=None,
            container: str | None = None, *, image: str | None = None,
            declaration: Path | None = None, source_binding=None,
            record: Path | None = None, registry: em.Registry | None = None) -> PreparedStep:
    if isinstance(project, StepRequest) or (
            hasattr(project, "step_id") and hasattr(project, "parameters")
            and hasattr(project, "source_sha") and hasattr(project, "source_files")):
        req = project
        params = req.parameters
        return prepare(req.project, str(params.get("top", "")), params.get("pdk"),
                       str(params.get("container", "")), image=params.get("image"),
                       declaration=Path(params["declaration"]) if params.get("declaration") else None,
                       source_binding=(req.source_sha, req.source_files), record=req.record, registry=registry)
    project = Path(project).resolve()
    if not top or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", str(top)):
        raise em.Refusal("PRODUCTION_TOP_PATH_UNSAFE", repr(top))
    actual_source, sources = source_identity()
    if source_binding:
        supplied_sha, supplied_files = source_binding
        if supplied_sha != actual_source or dict(supplied_files) != sources:
            raise em.Refusal("PRODUCTION_SOURCE_POPULATION_CHANGED", "9")
    image_arg = image or container
    image_id, facts, image_missing = _tool_and_image(image_arg, project)
    pdk = _host_pdk(project, pdk, image_id)
    inputs = _canonical_inputs(project, declaration, pdk)
    record = Path(record) if record else Path(tempfile.mkstemp(prefix="step9-request-", suffix=".json")[1])
    spec = _request_spec(project=project, top=str(top), pdk=pdk, image_id=image_id,
                         source_sha=actual_source, source_files=sources,
                         inputs=inputs, lease=None)
    write_json(record, spec, sort_keys=True)
    inputs = dict(inputs)
    inputs["request.json"] = record
    context = _make_context(project, inputs, actual_source, sources, str(top))
    if registry is None:
        raise em.Refusal("PRODUCTION_REGISTRY_REQUIRED", "use the existing ordinary registry")
    adapter = _native_adapter(context, actual_source, sources, image_id, facts, record, pdk,
                              sys.executable)
    registry.register(adapter)
    return PreparedStep(context, registry)


def import_selected(project: Path, context: em.Context, controller: em.Controller,
                    run: Path, adoption: dict) -> dict:
    """Copy only the Controller-issued generation into canonical project paths."""
    verified = controller.verify_adoption(context, run)
    generation = verified.get("selected_generation") or {}
    if adoption.get("selected_generation") != generation:
        raise em.Refusal("SELECTED_GENERATION_UNBOUND", str(run))
    directory = Path(generation.get("directory", ""))
    if directory.is_symlink() or not directory.is_dir():
        raise em.Refusal("SELECTED_GENERATION_MISSING", str(directory))
    from execution_backend_snapshot import Journal
    journal = Journal(Path(project))
    copied = {}
    try:
        for rel, expected in generation.get("outputs", {}).items():
            if not rel.startswith("project/"):
                continue
            path = directory / rel
            if not _regular(path) or _sha(path) != expected:
                raise em.Refusal("SELECTED_ARTIFACT_CHANGED", rel)
            target = rel.removeprefix("project/")
            journal.write(target, path.read_bytes())
            copied[target] = expected
        if not copied:
            raise em.Refusal("SELECTED_GENERATION_EMPTY", str(directory))
        controller.verify_adoption(context, run)
    except Exception:
        journal.rollback()
        raise
    return {"status": "IMPORTED", "step_id": "9", "copied": copied,
            "run": str(run), "adoption": adoption}


def _step9_installation(project: Path, top: str, pdk: object,
                        parameters: Mapping[str, object]):
    """Prepare the current normal-caller request and parent-verified receipt."""
    project = Path(project).resolve(strict=True)
    source, sources = source_identity()
    import librelane_contract as ll
    image_ref = ll.resolve_image(project)
    image_id, facts, missing = _tool_and_image(image_ref, project)
    if missing:
        raise em.Refusal("STEP9_INSTALLATION_NOT_MEASURED", ",".join(missing))
    if not isinstance(pdk, Mapping) and pdk is None:
        raise em.Refusal("STEP9_PDK_INPUT_MISSING", "ordinary Phase-3 PdkConfig absent")
    pdk = _host_pdk(project, pdk, image_id)
    pdk_values = _pdk_dict(pdk)
    pdk_name = str(pdk_values.get("name") or "")
    pdk_root = Path(str(pdk_values.get("pdk_root_host") or ""))
    if not pdk_name or not pdk_root.is_dir() or pdk_root.is_symlink():
        raise em.Refusal("STEP9_PDK_ROOT_MISSING", str(pdk_root))
    # Freeze only canonical Step9 inputs: declared project inputs plus the
    # exact selected liberty and a byte manifest of the complete selected PDK.
    inputs = _canonical_inputs(project, Path(parameters["declaration"])
                                if parameters.get("declaration") else None, pdk)
    record = Path(tempfile.mkstemp(prefix="step9-install-request-", suffix=".json")[1])
    spec = _request_spec(project=project, top=top, pdk=pdk, image_id=image_id,
                         source_sha=source, source_files=sources,
                         inputs=inputs, lease=None)
    write_json(record, spec, sort_keys=True)
    inputs = dict(inputs)
    inputs["request.json"] = record
    pdk_manifest = _json(inputs["pdk/tree-manifest.json"])
    if not pdk_manifest:
        raise em.Refusal("STEP9_PDK_MANIFEST_UNREADABLE", str(pdk_root))
    _require_librelane_pdk_config(pdk_root, pdk_manifest)
    config_exts = {".json", ".tcl", ".yaml", ".yml", ".cfg", ".mk"}
    model_exts = {".lib", ".lef", ".gds", ".sp", ".spi", ".spice", ".v", ".mod", ".model"}
    config_hashes = {name: _sha(path) for name, path in inputs.items()
                     if Path(name).suffix.lower() in config_exts and name != "request.json"}
    model_hashes = {str(row["path"]): str(row["sha256"])
                    for row in pdk_manifest.get("files", [])
                    if Path(str(row.get("path", ""))).suffix.lower() in model_exts}
    request = installation.request_for(
        project=project, top=top, image_ref=image_ref, image_id=image_id,
        source_sha=source, source_files=sources,
        input_hashes={name: _sha(path) for name, path in inputs.items() if name != "request.json"},
        pdk_name=pdk_name, pdk_root=pdk_root, pdk_manifest=pdk_manifest,
        config_hashes=config_hashes, model_hashes=model_hashes,
        engine_contract=engines.LIBRELANE.contract())
    receipt = installation.measure_installation(request, facts=facts)
    verified = installation.verify_installation(asdict(receipt), request, facts=facts,
                                                input_files={k: v for k, v in inputs.items()
                                                             if k != "request.json"})
    spec["native_installation_receipt"] = asdict(verified)
    spec["native_installation_receipt_sha256"] = verified.receipt_sha256
    spec["native_installation_request"] = asdict(request)
    spec["native_installation_facts"] = dict(facts)
    write_json(record, spec, sort_keys=True)
    inputs["request.json"] = record
    context = _make_context(project, inputs, source, sources, top)
    _STEP9_INPUTS[str(project)] = dict(inputs)
    _STEP9_EXPECTED[str(project)] = {name: _sha(path) for name, path in inputs.items()}
    return context, image_id, facts, record, pdk, sources, asdict(verified)


def current_step9_input_files(project: Path) -> dict[str, Path] | None:
    """Return only the input population bound at the current Step9 dispatch."""
    values = _STEP9_INPUTS.get(str(Path(project).resolve()))
    if values is None:
        return None
    for name, path in values.items():
        if not _regular(path) or _sha(path) != _STEP9_EXPECTED[str(Path(project).resolve())][name]:
            raise em.Refusal("STEP9_BOOTSTRAP_INPUT_CHANGED", name)
    return dict(values)


def register_synthesis_adapter(registry: em.Registry, *, project: Path | None = None,
                               parameters: Mapping[str, object] | None = None,
                               deferred: bool = False) -> None:
    """Reserve the ordinary slot, or measure it once its producer inputs exist."""
    source, files = source_identity()
    objective = {"metric": "mapped_area_um2", "direction": "min"}
    context = em.Context("9", source, {}, objective, REQUIRED_GATES)
    image_id, facts, pdk, spec_path = "UNMEASURED:native-installation", {}, None, Path("/missing/step9-request.json")
    receipt = None
    reason = (str(parameters.get("pdk_refusal"))
              if parameters and parameters.get("pdk_refusal")
              else "MISSING_NATIVE_FACTS:native_installation_receipt")
    if deferred:
        reason = "STEP9_DISPATCH_PREPARATION_PENDING"
    elif (project is not None and parameters and parameters.get("pdk") is not None
          and not parameters.get("pdk_refusal")):
        try:
            (context, image_id, facts, spec_path, pdk, files,
             receipt) = _step9_installation(Path(project), str(parameters.get("top", "")),
                                            parameters["pdk"], parameters)
            source = context.source_sha
        except (em.Refusal, OSError, ValueError, KeyError, TypeError) as exc:
            reason = f"STEP9_INSTALLATION_NOT_MEASURED:{exc}"
    adapter = _native_adapter(context, source, files, image_id, facts, spec_path,
                              pdk, sys.executable, installation_receipt=receipt,
                              availability_reason=reason)
    from dataclasses import replace
    register = registry.reserve_step9 if deferred else registry.register
    register(replace(adapter, input_contract=(
        "input/submission_template/tapeout_declaration.json",
        "phase2/stage1/rtl", "phase1/generated_docs",
        "phase3/librelane_switch.json")))


def dispatch_site(step_ids: tuple[str, ...], project: Path,
                  parameters: Mapping[str, object]) -> dict | None:
    """Use the current fixed-Step dispatcher and its issued AI selection.

    An unissued caller returns None through the existing policy. Issued
    callers prepare only Step9, then reuse the Controller and importer.
    """
    if "9" not in tuple(map(str, step_ids)):
        return None
    from execution_policy import dispatch_fixed_step
    return dispatch_fixed_step(Path(project), "9", parameters=dict(parameters))


STEP_IDS = ("9",)
