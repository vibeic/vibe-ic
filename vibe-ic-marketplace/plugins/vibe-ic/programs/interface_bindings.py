"""Explicit source-bound Phase-1 physical interface authoring.

The normal L9 writer consumes this optional INPUT. Package-only elaboration
measures types; original source declarations/local roles constrain directions.
Neither an author-provided width nor an author-provided tool PASS is evidence.
No gate policy, implementation RTL, signature or independent verdict is made.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

INPUT = "plugin_input/interface-bindings.json"
CONTEXT = "plugin_input/interface_context"
REPORT = "reports/phase1/interface_binding"
SCHEMA = "vibeic.phase1-interface-bindings.v1"
PORT_KEYS = ("ports", "top_ports", "top_module_pins")
_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*\Z")
_TYPE = re.compile(r"(?:[A-Za-z_][A-Za-z0-9_$]*::)*[A-Za-z_][A-Za-z0-9_$]*\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9./:_-]*@sha256:[a-f0-9]{64}\Z")


def _fail(message):
    raise ValueError(f"interface binding input: {message}")


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _path(project, rel, root=None):
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
        _fail("expected a project-relative path")
    parts = Path(rel).parts
    if any(p in (".", "..") for p in parts) or Path(rel).as_posix() != rel:
        _fail(f"noncanonical path {rel!r}")
    if root and not rel.startswith(root + "/"):
        _fail(f"path must be within {root}: {rel!r}")
    here = Path(project)
    for part in parts:
        here = here / part
        if here.is_symlink():
            _fail(f"symlink is not an input/output binding: {rel!r}")
    return here


def _basis(project, value):
    import _qualified_by as qb
    if (not isinstance(value, list) or any(
            not isinstance(b, dict) or set(b) != {"file", "line", "quote"}
            or type(b.get("line")) is not int for b in value)):
        _fail("basis requires exact file/line/quote records with integer lines")
    refusal = qb.basis_refusal(Path(project), value)
    if refusal:
        _fail(refusal)


def _basis_names(basis, name):
    import _qualified_by as qb
    return qb._names_port(" ".join(b["quote"] for b in basis), name)


def input_contract(project: Path, content: dict) -> dict:
    """Describe the exact unbound source roster and current quotable inputs."""
    import _qualified_by as qb
    rosters = []
    for key in PORT_KEYS:
        rows = content.get(key)
        if not isinstance(rows, list):
            _fail(f"{key} is not a port list")
        names, roster = set(), []
        for row in rows:
            if not isinstance(row, dict) or not _ID.fullmatch(str(row.get("name", ""))):
                _fail(f"malformed {key} port")
            if row["name"] in names:
                _fail(f"duplicate {key} port {row['name']!r}")
            names.add(row["name"])
            entry = {"name": row["name"],
                     "direction": row.get("direction") or row.get("mode"),
                     "width": row.get("width"), "type_ref": row.get("type_ref")}
            for key in ("interface_type", "interface_role", "package_struct", "instance_count"):
                if key in row:
                    entry[key] = copy.deepcopy(row[key])
            roster.append(entry)
        rosters.append(sorted(roster, key=lambda r: r["name"]))
    if any(_canonical(r) != _canonical(rosters[0]) for r in rosters[1:]):
        _fail("port aliases disagree")
    # A describe operation on a bound document addresses the original source
    # roster, never a second binding of the already-expanded physical ports.
    ledger = content.get("interface_binding_authoring")
    source = ledger.get("source_interface") if isinstance(ledger, dict) else None
    return {"schema": SCHEMA,
            "input_files": {rel: _sha(path) for rel, path in sorted(
                qb._design_input_files(Path(project)).items())},
            "interface": copy.deepcopy(source if source is not None else rosters[0]),
            "context": {"image": "", "revision": "", "files": {},
                        "compile_order": [], "include_dirs": [],
                        "defines": [], "parameters": {}},
            "physical_ports": [], "logical_bindings": [], "decisions": []}


def _context(project, context):
    keys = {"image", "revision", "files", "compile_order", "include_dirs", "defines", "parameters"}
    if not isinstance(context, dict) or set(context) != keys:
        _fail("malformed context")
    if not isinstance(context["image"], str) or not _IMAGE.fullmatch(context["image"]):
        _fail("context image must be an immutable repository digest")
    if not isinstance(context["revision"], str) or not context["revision"].strip():
        _fail("context requires a selected provider revision")
    if context["parameters"] != {}:
        _fail("package parameters must be selected by pinned source bytes; overrides unsupported")
    files = context["files"]
    if not isinstance(files, dict) or not files:
        _fail("context requires pinned files")
    for rel, expected in files.items():
        path = _path(project, rel, CONTEXT)
        if not isinstance(expected, str) or not _HASH.fullmatch(expected):
            _fail(f"invalid context hash: {rel}")
        if not path.is_file() or _sha(path) != expected:
            _fail(f"context file hash mismatch: {rel}")
    root = _path(project, CONTEXT)
    actual = set()
    for path in root.rglob("*"):
        rel = path.relative_to(project).as_posix()
        _path(project, rel, CONTEXT)
        if path.is_file():
            actual.add(rel)
    if set(files) != actual:
        _fail("context files must cover the exact context subtree")
    order, dirs, defines = (context[k] for k in ("compile_order", "include_dirs", "defines"))
    if (not isinstance(order, list) or not order
            or any(not isinstance(r, str) or r not in files or Path(r).suffix not in (".sv", ".v")
                   for r in order) or len(set(order)) != len(order)):
        _fail("compile_order must list unique pinned package units")
    if not isinstance(dirs, list) or any(not isinstance(d, str) for d in dirs):
        _fail("include_dirs must be explicit paths")
    for rel in dirs:
        p = _path(project, rel, CONTEXT)
        if not p.is_dir():
            _fail(f"include directory is absent: {rel}")
    if (not isinstance(defines, list)
            or any(not isinstance(d, str) or not re.fullmatch(r"[A-Za-z_]\w*(?:=[A-Za-z0-9_'()+*/ .:-]+)?", d)
                   for d in defines) or len(set(defines)) != len(defines)):
        _fail("defines must be explicit NAME or NAME=value strings")
    # Only shared packages and their pinned includes are admitted, never a
    # design module, imported DUT or generated implementation.
    for rel in files:
        if Path(rel).suffix not in (".sv", ".v", ".svh", ".vh"):
            continue
        text = _path(project, rel).read_text()
        text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
        if re.search(r"\b(?:module|macromodule|interface|program|checker)\s+[A-Za-z_]", text):
            _fail(f"context contains non-package design unit: {rel}")
        if rel in order and not re.search(r"\bpackage\s+[A-Za-z_]", text):
            _fail(f"compilation unit is not a package: {rel}")
        for target in re.findall(r'`include\s+"([^"]+)"', text):
            if Path(target).is_absolute() or ".." in Path(target).parts:
                _fail(f"include is outside pinned context: {target}")
            candidates = [Path(rel).parent / target] + [Path(d) / target for d in dirs]
            if not any(p.as_posix() in files for p in candidates):
                _fail(f"include is not pinned: {target}")
        if re.search(r'`include\s+(?!")\S', text):
            _fail(f"nonliteral include is unsupported: {rel}")
    return context


def _probe(project, context, ports, author_sha):
    from _container_exec import local_exec_mode
    from _physical_current import run_native
    local = local_exec_mode("interface_bindings")
    if local:
        selected_image = os.environ.get("VIBEIC_EDA_IMAGE", "")
        if not shutil.which("verilator"):
            _fail("tool environment unavailable: local Verilator is absent")
        runtime_image = None
    else:
        from p0_tool_frontend_check import default_image
        from _eda_pin import resolved_image_digest
        runtime_image = default_image()
        selected_image = "runtime@" + resolved_image_digest()
    if (not _IMAGE.fullmatch(selected_image)
            or selected_image.rsplit("@", 1)[1] != context["image"].rsplit("@", 1)[1]):
        _fail("runtime image does not bind the selected immutable image")
    identity = {"transport": "local" if local else "fresh_docker_run",
                "image_digest": context["image"]}
    report = _path(project, REPORT)
    report.mkdir(parents=True, exist_ok=True)
    attempt_rel = f"{REPORT}/attempts/{author_sha}"
    attempt = _path(project, attempt_rel)
    attempt.mkdir(parents=True, exist_ok=True)
    declarations = ",\n".join(f"  {p['direction']} {p['type_ref']} {p['name']}" for p in ports)
    lines = [f"module vibeic_interface_binding_probe(\n{declarations}\n);", "initial begin"]
    for p in ports:
        lines.append(f'  $display("VIBEIC_PORT|{p["name"]}|{p["direction"]}|{p["type_ref"]}|%0d", $bits({p["name"]}));')
    lines += ["  $finish;", "end", "endmodule", ""]
    source = "\n".join(lines)
    _path(project, attempt_rel + "/type_probe.sv").write_text(source)
    with tempfile.TemporaryDirectory(prefix="build-", dir=report) as scratch:
        work = Path(scratch)
        probe = work / "type_probe.sv"
        probe.write_text(source)
        # Compile only owned copies of the already pinned package context.
        # A fresh host container mounts this scratch, never the design project.
        for rel, digest in context["files"].items():
            copied = work / rel
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(_path(project, rel), copied)
            if _sha(copied) != digest:
                _fail(f"context changed before native measurement: {rel}")
        commands = []

        def invoke(tool, args, name):
            log = attempt / name
            try:
                rc, execution = run_native(work, tool, args, log, image=runtime_image)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                _fail(f"tool environment unavailable: {exc}")
            commands.append(execution)
            output = log.read_text()
            if rc:
                _fail(f"tool refused rc={rc}: {output[-3000:]}")
            return output

        version = invoke("verilator", ["--version"], "version.log").strip()
        args = ["--binary", "--timing", "-j", "2", "--Mdir", str(work / "obj"),
                "--top-module", "vibeic_interface_binding_probe", "-Wno-fatal"]
        args += ["-I" + str(work / d) for d in context["include_dirs"]]
        args += ["-D" + d for d in context["defines"]]
        args += [str(work / r) for r in context["compile_order"]]
        args += [str(probe)]
        compile_log = invoke("verilator", args, "elaboration.log")
        run_log = invoke(str(work / "obj/Vvibeic_interface_binding_probe"), [], "measurements.log")
        if (_sha(probe) != hashlib.sha256(source.encode()).hexdigest()
                or any(_sha(work / rel) != digest for rel, digest in context["files"].items())):
            _fail("native measurement changed its pinned package/probe input")
    measurements = []
    for line in run_log.splitlines():
        if not line.startswith("VIBEIC_PORT|"):
            continue
        cells = line.split("|")
        if len(cells) != 5 or not cells[4].isdigit():
            _fail("malformed fresh type measurement")
        measurements.append({"name": cells[1], "direction": cells[2], "type_ref": cells[3], "width": int(cells[4])})
    expected = [{k: p[k] for k in ("name", "direction", "type_ref", "width")} for p in ports]
    if measurements != expected:
        _fail(f"fresh measured types/widths differ from physical_ports: {measurements!r}")
    proof = {"schema": "vibeic.phase1-interface-binding-measurement.v1",
             "author_input_sha256": author_sha, "context": context,
             "probe_sha256": hashlib.sha256(source.encode()).hexdigest(),
             "measurements": measurements, "tool_version": version,
             "execution_identity": identity,
             "elaboration_rc": 0, "simulation_rc": 0,
             "direction_authority": "original physical declaration or original logical local_role",
             "review": "PENDING_INDEPENDENT_D1"}
    # The semantic measurement is stable across identical native admissions.
    # Full commands/log hashes remain in a separate D1-bound execution receipt;
    # random build paths and tool timing cannot perturb the L9 semantic subject.
    execution = {"schema": "vibeic.phase1-interface-binding-execution.v1",
                 "author_input_sha256": author_sha, "commands": commands,
                 "execution_identity": proof["execution_identity"],
                 "elaboration_rc": 0, "simulation_rc": 0, "artifacts": {}}
    for name, text in (("type_probe.sv", source), ("elaboration.log", compile_log),
                       ("measurements.log", run_log)):
        _path(project, f"{REPORT}/{name}").write_text(text)
        execution["artifacts"][f"{REPORT}/{name}"] = _sha(report / name)
    _path(project, f"{REPORT}/proof.json").write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")
    execution["semantic_proof"] = {"path": f"{REPORT}/proof.json", "sha256": _sha(report / "proof.json")}
    _path(project, f"{REPORT}/execution.json").write_text(json.dumps(execution, indent=2, sort_keys=True) + "\n")
    return proof


def admit(project: Path, content: dict) -> dict:
    """Validate all author input and fresh measurements before changing L9."""
    return _admit(project, content, _probe)


def _admit(project: Path, content: dict, measure) -> dict:
    """Shared source/role/type admission; measurement owns its evidence mode."""
    project = Path(project)
    path = _path(project, INPUT)
    if not path.exists():
        if "interface_binding_authoring" in content:
            _fail("previously admitted author input was removed")
        return content
    if not path.is_file():
        _fail("author input is not a file")
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
    contract = input_contract(project, content)
    if not isinstance(data, dict) or set(data) != set(contract) or data.get("schema") != SCHEMA:
        _fail("unsupported schema or unexpected top-level fields")
    for key in ("input_files", "interface"):
        if _canonical(data[key]) != _canonical(contract[key]):
            _fail(f"{key} does not describe the current input/interface")
    if content.get("selected_interface_binding"):
        _fail("cannot replace an already selected reused-IP interface")
    context = _context(project, data["context"])
    if any(not isinstance(data[k], list) for k in ("physical_ports", "logical_bindings", "decisions")):
        _fail("physical_ports/logical_bindings/decisions must be lists")
    original = {r["name"]: r for r in contract["interface"]}
    physical, decisions, logical, claimed = {}, {}, {}, set()
    decision_keys = {"id", "kind", "port", "source_type_ref", "selected_type_ref", "original_claim",
                     "selected_claim", "authority", "reason", "basis"}
    ids = set()
    for d in data["decisions"]:
        if (not isinstance(d, dict) or set(d) != decision_keys
                or any(not isinstance(d[k], str) or not d[k].strip() for k in decision_keys - {"basis"})
                or d["kind"] not in ("type_correction", "source_conflict")
                or d["authority"] != "AGENT_ENGINEERING_CHOICE"
                or d["id"] in ids or d["port"] in decisions):
            _fail("malformed or duplicate engineering decision")
        _basis(project, d["basis"])
        quotes = " ".join(b["quote"] for b in d["basis"])
        if (d["source_type_ref"] not in quotes or d["original_claim"] not in quotes
                or not _basis_names(d["basis"], d["port"])):
            _fail("decision does not quote its original source claim/type")
        if d["kind"] == "source_conflict" and d["selected_type_ref"] not in quotes:
            _fail("source conflict must preserve both quoted type claims")
        ids.add(d["id"])
        decisions[d["port"]] = d
    for p in data["physical_ports"]:
        if (not isinstance(p, dict) or set(p) != {"name", "direction", "type_ref", "width", "basis"}
                or not isinstance(p["name"], str) or not _ID.fullmatch(p["name"])
                or p["direction"] not in ("input", "output", "inout")
                or not isinstance(p["type_ref"], str) or not _TYPE.fullmatch(p["type_ref"])
                or type(p["width"]) is not int or not 1 <= p["width"] <= 1048576
                or p["name"] in physical):
            _fail("malformed or duplicate physical port")
        _basis(project, p["basis"])
        source = original.get(p["name"])
        if source:
            if not _basis_names(p["basis"], p["name"]):
                _fail("physical basis does not name its original source port")
            if source["direction"] == "interface":
                _fail("a logical interface cannot become a single physical port")
            if source["direction"] != p["direction"]:
                _fail(f"physical direction differs from source: {p['name']}")
            if type(source.get("width")) is int and source["width"] != p["width"]:
                _fail(f"physical width differs from explicit source: {p['name']}")
            if source.get("type_ref") and source["type_ref"] != p["type_ref"]:
                d = decisions.get(p["name"], {})
                if (d.get("kind") != "type_correction" or d.get("source_type_ref") != source["type_ref"]
                        or d.get("selected_type_ref") != p["type_ref"]):
                    _fail(f"type differs from source without explicit correction: {p['name']}")
        physical[p["name"]] = p
    if not physical:
        _fail("no physical ports selected")
    for name, d in decisions.items():
        if name not in physical or d["selected_type_ref"] != physical[name]["type_ref"]:
            _fail("engineering decision is not attached to its selected physical type")
    logical_keys = {"source_name", "kind", "local_role", "instance_count", "request_port",
                    "response_port", "selected_payload_types", "basis"}
    for b in data["logical_bindings"]:
        if not isinstance(b, dict) or set(b) != logical_keys:
            _fail("malformed logical binding")
        name = b["source_name"]
        source = original.get(name) if isinstance(name, str) else None
        c = source or {}
        if (not source or c.get("interface_type") != "req_rsp" or c.get("direction") != "interface"
                or b["kind"] != c["interface_type"] or b["local_role"] != c.get("interface_role")
                or b["local_role"] not in ("req", "rsp") or type(b["instance_count"]) is not int
                or b["instance_count"] != c.get("instance_count") or b["instance_count"] != 1
                or name in logical):
            _fail("logical binding does not preserve the original kind/local_role/instance_count")
        _basis(project, b["basis"])
        if not _basis_names(b["basis"], name) or str(c.get("package_struct")) not in " ".join(
                quote["quote"] for quote in b["basis"]):
            _fail("logical basis does not name its original source interface/type")
        payloads = b["selected_payload_types"]
        if not isinstance(payloads, dict) or set(payloads) != {"request", "response"}:
            _fail("logical binding requires exact request/response payload types")
        # The supported Comportable declaration grammar names a package and
        # parent family. A real but unrelated type (or reversed valid pair)
        # must not pass merely because the authored wrapper compiles.
        family = c.get("package_struct")
        if not isinstance(family, str) or not re.fullmatch(r"[A-Za-z_]\w*::[A-Za-z_]\w*", family):
            _fail("unsupported logical payload family declaration")
        supported = ({"request": family + "_req_t", "response": family + "_rsp_t"},
                     {"request": family + "_h2d_t", "response": family + "_d2h_t"})
        if payloads not in supported:
            _fail("logical payload package/family/request-response association differs from source")
        for member, key in (("request", "request_port"), ("response", "response_port")):
            leaf = b[key]
            if not isinstance(leaf, str) or leaf not in physical or leaf in claimed:
                _fail("logical binding requires a complete unique request/response pair")
            expected_dir = "output" if (b["local_role"] == "req") == (member == "request") else "input"
            if physical[leaf]["direction"] != expected_dir:
                _fail("logical member direction contradicts original local_role")
            if physical[leaf]["type_ref"] != payloads[member]:
                _fail("logical member type differs from selected payload type")
            if leaf not in original and not _basis_names(physical[leaf]["basis"], name):
                _fail("new physical basis does not name its original logical interface")
            claimed.add(leaf)
        logical[name] = b
    if any(name not in original and name not in claimed for name in physical):
        _fail("new physical port is not mapped from an original logical interface")
    author_sha = hashlib.sha256(raw).hexdigest()
    proof = measure(project, context, list(physical.values()), author_sha)
    # A changed source, package, or author choice during elaboration is never
    # published against an earlier roster/hash descriptor.
    if path.read_bytes() != raw or input_contract(project, content)["input_files"] != data["input_files"]:
        _fail("source/author input changed during elaboration")
    _context(project, context)
    out = copy.deepcopy(content)
    for key in PORT_KEYS:
        rows = []
        seen = set()
        for row in out[key]:
            name = row["name"]
            if name in logical:
                continue
            if name in physical:
                p = physical[name]
                row.update({k: p[k] for k in ("direction", "type_ref", "width")})
                row["mode"] = p["direction"]
                row.pop("width_symbolic", None)
            seen.add(name)
            rows.append(row)
        for name, p in physical.items():
            if name not in seen:
                row = {k: copy.deepcopy(p[k]) for k in ("name", "direction", "type_ref", "width", "basis")}
                row.update(mode=p["direction"], io=None,
                           evidence="; ".join(sorted({b["file"] for b in p["basis"]})),
                           extraction_strategy="explicit_interface_binding_input_v1")
                rows.append(row)
        out[key] = rows
    out["interface_binding_authoring"] = {
        "schema": SCHEMA, "input": INPUT, "input_sha256": author_sha,
        "source_interface": contract["interface"], "context": context,
        "logical_bindings": data["logical_bindings"], "decisions": data["decisions"],
        "physical_ports": data["physical_ports"], "measurement": proof,
        "proof": {"path": f"{REPORT}/proof.json", "sha256": _sha(project / REPORT / "proof.json")},
        "review": "PENDING_INDEPENDENT_D1"}
    return out


def current_published_ports(project: Path, content: dict) -> dict:
    """Read-only validation of a native publication, never an authored PASS.

    Reuse ordinary source/role/type admission, then independently bind its
    retained measurement to current author/package bytes, exact probe and
    terminal execution artifacts. Reconstruct and compare the actual physical
    aliases, so a numeric width patched into L9 cannot satisfy a consumer.
    This does not rerun tools, write reports, or alter the raw L1 view.
    """
    ledger = content.get("interface_binding_authoring")
    if not isinstance(ledger, dict) or content.get("phase1_step_error"):
        _fail("current native publication is absent or failed")
    proof_rel = f"{REPORT}/proof.json"
    execution_rel = f"{REPORT}/execution.json"

    def retained(project, context, ports, author_sha):
        proof_path = _path(project, proof_rel)
        proof = json.loads(proof_path.read_text(), object_pairs_hook=_unique)
        execution = json.loads(_path(project, execution_rel).read_text(), object_pairs_hook=_unique)
        reference = {"path": proof_rel, "sha256": _sha(proof_path)}
        if (ledger.get("input") != INPUT or ledger.get("input_sha256") != author_sha
                or ledger.get("proof") != reference or ledger.get("measurement") != proof
                or proof.get("schema") != "vibeic.phase1-interface-binding-measurement.v1"
                or proof.get("author_input_sha256") != author_sha or proof.get("context") != context
                or execution.get("schema") != "vibeic.phase1-interface-binding-execution.v1"
                or execution.get("author_input_sha256") != author_sha
                or execution.get("semantic_proof") != reference):
            _fail("retained measurement is not bound to current author/proof")
        for receipt in (proof, execution):
            if any(type(receipt.get(k)) is not int or receipt[k] != 0
                   for k in ("elaboration_rc", "simulation_rc")):
                _fail("retained elaboration/simulation did not succeed")
        identity = proof.get("execution_identity")
        if (not isinstance(identity, dict) or identity != execution.get("execution_identity")
                or identity.get("image_digest") != context["image"]):
            _fail("retained execution does not bind the selected image")
        if "transport" in identity:
            # The official native runner publishes either local execution in
            # its attested image or a fresh pinned docker run. Older composed
            # writers instead identify an existing container explicitly.
            if (set(identity) != {"transport", "image_digest"}
                    or identity["transport"] not in ("local", "fresh_docker_run")):
                _fail("unsupported retained native execution identity")
        elif not all(isinstance(identity.get(k), str) and identity[k]
                     for k in ("container", "container_id", "image_id")):
            _fail("retained execution does not identify its native container")
        artifacts = execution.get("artifacts")
        expected_artifacts = {f"{REPORT}/{name}" for name in
                              ("type_probe.sv", "elaboration.log", "measurements.log")}
        if not isinstance(artifacts, dict) or set(artifacts) != expected_artifacts:
            _fail("retained execution artifact roster differs")
        for rel, digest in artifacts.items():
            if not isinstance(digest, str) or not _HASH.fullmatch(digest) or _sha(_path(project, rel)) != digest:
                _fail(f"retained execution artifact changed: {rel}")
        declarations = ",\n".join(f"  {p['direction']} {p['type_ref']} {p['name']}" for p in ports)
        lines = [f"module vibeic_interface_binding_probe(\n{declarations}\n);", "initial begin"]
        for p in ports:
            lines.append(f'  $display("VIBEIC_PORT|{p["name"]}|{p["direction"]}|{p["type_ref"]}|%0d", $bits({p["name"]}));')
        source = "\n".join(lines + ["  $finish;", "end", "endmodule", ""])
        if (_path(project, f"{REPORT}/type_probe.sv").read_text() != source
                or proof.get("probe_sha256") != hashlib.sha256(source.encode()).hexdigest()):
            _fail("retained probe differs from selected physical types")
        expected = [{k: p[k] for k in ("name", "direction", "type_ref", "width")} for p in ports]
        measured = []
        for line in _path(project, f"{REPORT}/measurements.log").read_text().splitlines():
            if line.startswith("VIBEIC_PORT|"):
                cells = line.split("|")
                if len(cells) != 5 or not cells[4].isdigit():
                    _fail("malformed retained measurement")
                measured.append(dict(name=cells[1], direction=cells[2], type_ref=cells[3], width=int(cells[4])))
        if measured != expected or proof.get("measurements") != expected:
            _fail("retained measured types/widths differ from selected ports")
        return proof

    rebuilt = _admit(Path(project), content, retained)
    if rebuilt.get("interface_binding_authoring") != ledger:
        _fail("published binding ledger differs from current admission")
    if any(rebuilt[key] != content[key] for key in PORT_KEYS):
        _fail("published physical ports differ from current measured binding")
    return {p["name"]: copy.deepcopy(p) for p in ledger["physical_ports"]}
