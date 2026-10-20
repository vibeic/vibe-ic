"""Bounded structural applicability for the three RTL-review audit producers.

Not a gate, a waiver, or a semantic classifier. A producer may establish an
empty subject only after a complete, closed RTL census and checked elaboration.
The consumer independently selects the source root and recomputes the proof.
Unresolved inputs, parameters/generate branches, preprocessing, unsupported
cells and external multi-bit data roles remain UNKNOWN. Names are never an
absence criterion. NOT_APPLICABLE is deliberately not PASS.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _structural_absence import absence

SCHEMA = "vibeic.rtl_audit_applicability.v1"
NOT_APPLICABLE = "NOT_APPLICABLE"
UNKNOWN = "UNKNOWN"
AUDITORS = frozenset({"interface_encoding_audit", "phy_counter_audit",
                      "crc_bitorder_check"})
SOURCE_SUFFIXES = frozenset({".v", ".sv", ".vh", ".svh"})
_MAX_SOURCE_BYTES = 32 * 1024 * 1024
_STATE_CELLS = frozenset({"$dff", "$adff", "$sdff", "$dffe", "$adffe",
                          "$sdffe", "$sdffce", "$dlatch", "$adlatch"})
_COMB_CELLS = frozenset({
    "$pos", "$not", "$and", "$or", "$xor", "$xnor", "$reduce_and",
    "$reduce_or", "$reduce_xor", "$reduce_xnor", "$reduce_bool",
    "$logic_not", "$logic_and", "$logic_or", "$shl", "$shr", "$sshl",
    "$sshr", "$shift", "$shiftx", "$lt", "$le", "$eq", "$ne", "$eqx",
    "$nex", "$ge", "$gt", "$add", "$sub", "$mul", "$div", "$mod",
    "$pow", "$neg", "$mux", "$pmux", "$demux", "$bmux", "$slice",
    "$concat", "$buf",
})
_MEMORY_CELLS = frozenset({"$mem", "$mem_v2", "$meminit", "$meminit_v2",
                           "$memrd", "$memrd_v2", "$memwr", "$memwr_v2"})
_SELECTION_SCHEMA = "vibeic.rtl_audit_selected_configuration.v1"


def _scope_text(text: str) -> str:
    """Lexically blank comments/strings; never silently swallow malformed text."""
    out: list[str] = []
    i = 0
    while i < len(text):
        if text.startswith("//", i):
            end = text.find("\n", i + 2)
            i = len(text) if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise ValueError("unterminated_comment")
            out.append(" ")
            i = end + 2
        elif text[i] == '"':
            i += 1
            while i < len(text) and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            if i >= len(text):
                raise ValueError("unterminated_string")
            out.append(" ")
            i += 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _census(root: Path) -> tuple[list[Path], list[dict[str, Any]], list[str]]:
    root = root.absolute()
    if not root.is_dir() or root.resolve() != root:
        raise ValueError("source_root_missing_or_symlinked")
    files: list[Path] = []
    records: list[dict[str, Any]] = []
    texts: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("symlink_in_source_census")
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if not path.is_file() or path.is_symlink() or path.resolve() != path:
            raise ValueError("source_not_regular_or_symlinked")
        raw = path.read_bytes()
        if len(raw) > _MAX_SOURCE_BYTES:
            raise ValueError("source_too_large")
        texts.append(_scope_text(raw.decode("utf-8", errors="strict")))
        files.append(path)
        records.append({"path": path.relative_to(root).as_posix(),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "size_bytes": len(raw)})
    if not files:
        raise ValueError("empty_source_census")
    return files, records, texts


def source_census(root: Path, *, files: Iterable[Path] | None = None) -> dict[str, Any]:
    """Return the complete, byte-bound source manifest for ``root``.

    Consumers use the same function as producers, then compare the complete
    record list and canonical digest.  An optional explicit file selection is
    accepted only when it is exactly the directory census; a partial list is
    an incomplete proof rather than a smaller subject.
    """
    root = Path(root).absolute()
    sources, records, _ = _census(root)
    if files is not None:
        selected = sorted(Path(path).absolute() for path in files)
        if selected != sources:
            raise ValueError("source_set_incomplete")
    return {
        "root": str(root),
        "files": records,
        "sha256": hashlib.sha256(
            json.dumps(records, sort_keys=True).encode()).hexdigest(),
    }


def _quoted(path: Path) -> str:
    # The Yosys command language is not a shell, but still has command syntax.
    if any(c in str(path) for c in ('"', "\\", ";", "\n", "\r")):
        raise ValueError("unsupported_source_path")
    return '"' + str(path) + '"'


def _elaborate(files: list[Path], *, root: Path | None = None,
               source_sha256: dict[str, str] | None = None,
               selection: dict[str, Any] | None = None) -> dict[str, Any]:
    executable = shutil.which("yosys")
    if executable is None:
        raise ValueError("elaborator_unavailable")
    with tempfile.TemporaryDirectory(prefix="rtl-audit-applicability-") as tmp:
        # Elaborate byte-bound immutable copies. Re-opening live source paths
        # in the tool would not prove that the census hashes describe the
        # input actually elaborated, even with a later directory recheck.
        snapshots = []
        snapshot_root = Path(tmp) / "source"
        for index, path in enumerate(files):
            _quoted(path)  # Keep the declared source-path support boundary.
            raw = path.read_bytes()
            if source_sha256 is not None and hashlib.sha256(raw).hexdigest() != source_sha256.get(str(path)):
                raise ValueError("source_changed_before_elaboration")
            if root is None:
                snapshot = Path(tmp) / f"source_{index}.sv"
            else:
                snapshot = snapshot_root / path.relative_to(root)
                snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(raw)
            snapshots.append(snapshot)
        output = Path(tmp) / "design.json"
        if selection is None:
            script = ("read_verilog -sv " + " ".join(_quoted(p) for p in snapshots)
                      + "; hierarchy -check; proc; write_json " + _quoted(output))
        else:
            top = selection["top_module"]
            compile_files = [p for p in snapshots if p.suffix.lower() in {".v", ".sv"}]
            if not compile_files:
                raise ValueError("empty_selected_compilation_units")
            include_dirs = [snapshot_root / p for p in selection["include_dirs"]]
            if any(any(c.isspace() for c in str(p)) for p in [*compile_files, *include_dirs]):
                raise ValueError("unsupported_selected_source_path")
            if any(p.suffix.lower() == ".sv" for p in compile_files):
                read = ("read_slang --keep-hierarchy --single-unit "
                        "--no-synthesis-define --top " + top + " " + " ".join(
                            ["-G " + p for p in selection["parameters"]] +
                            ["-D " + d for d in selection["defines"]] +
                            ["-I " + str(p) for p in include_dirs] +
                            [str(p) for p in compile_files]))
                commands = [read]
            else:
                read = "read_verilog -sv -nosynthesis " + " ".join(
                    ["-D" + d for d in selection["defines"]] +
                    ["-I" + str(p) for p in include_dirs] +
                    [_quoted(p) for p in compile_files])
                commands = [read]
                for parameter in selection["parameters"]:
                    name, value = parameter.split("=", 1)
                    commands.append(f"chparam -set {name} {value} {top}")
            commands += [f"hierarchy -check -top {top}", "proc", "check -assert",
                         "write_json " + _quoted(output)]
            script = "; ".join(commands)
        result = subprocess.run([executable, "-Q", "-T", "-p", script],
                                capture_output=True, text=True, timeout=60)
        if result.returncode != 0 or not output.is_file():
            raise ValueError("elaboration_failed")
        payload = json.loads(output.read_text())
    if not isinstance(payload.get("modules"), dict) or not payload["modules"]:
        raise ValueError("empty_elaborated_module_census")
    return payload


def _module_facts(modules: dict[str, Any], *, allow_memory: bool = False) -> dict[str, Any]:
    """Enumerate every emitted module/cell, keeping unknowns blocking."""
    children: set[str] = set()
    child_count = 0
    wide = 0
    for module in modules.values():
        attrs = module.get("attributes", {})
        if any(int(str(attrs.get(k, "0")), 2) for k in ("blackbox", "whitebox")):
            raise ValueError("black_box_module")
        if module.get("memories") and not allow_memory:
            raise ValueError("unsupported_memory")
        wide += sum(len(n.get("bits", [])) > 1
                    for n in module.get("netnames", {}).values())
        wide += sum(len(p.get("bits", [])) > 1
                    for p in module.get("ports", {}).values())
        for cell in module.get("cells", {}).values():
            kind = cell.get("type")
            if kind in modules:
                child_count += 1
                children.add(kind)
            elif kind not in _STATE_CELLS | _COMB_CELLS | (
                    _MEMORY_CELLS if allow_memory else frozenset()):
                raise ValueError("unsupported_or_unresolved_cell")
    roots = sorted(set(modules) - children)
    if len(roots) != 1:
        raise ValueError("ambiguous_or_recursive_hierarchy")
    return {"modules": sorted(modules), "top_module": roots[0],
            "child_instances": child_count, "wide_data_nets_and_ports": wide}


def _memory_facts(texts: list[str], modules: dict[str, Any]) -> dict[str, Any]:
    """Bind a narrow literal unpacked-memory source census to native memories."""
    import module_port_audit as ports

    declaration = re.compile(
        r"\b(?:reg|logic|wire)\s+(?:signed\s+)?"
        r"\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*([A-Za-z_]\w*)\s*"
        r"\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*;")
    broad = re.compile(r"\b(?:reg|logic|wire|integer|[A-Za-z_]\w*)\s+"
                       r"(?:signed\s+)?(?:\[[^\]]+\]\s*)?"
                       r"[A-Za-z_]\w*\s*\[")
    source: dict[str, dict[str, dict[str, int]]] = {}
    for text in texts:
        issues = []
        for module, _, body_start, end in ports.module_regions(text, issues):
            body = text[body_start:end]
            matches = list(declaration.finditer(body))
            scrubbed = list(body)
            for match in matches:
                scrubbed[match.start():match.end()] = " " * (match.end() - match.start())
                msb, lsb, name, high, low = match.groups()
                row = {"width": abs(int(msb) - int(lsb)) + 1,
                       "size": abs(int(high) - int(low)) + 1,
                       "start_offset": min(int(high), int(low))}
                if row["width"] * row["size"] > _MAX_SOURCE_BYTES * 8:
                    raise ValueError("unsupported_memory_size")
                if name in source.setdefault(module, {}):
                    raise ValueError("duplicate_memory_declaration")
                source[module][name] = row
            if broad.search("".join(scrubbed)):
                raise ValueError("unsupported_memory_declaration")
        if issues:
            raise ValueError("incomplete_memory_module_census")

    native: dict[str, dict[str, dict[str, int]]] = {}
    for module, payload in modules.items():
        memories = payload.get("memories", {})
        if not isinstance(memories, dict):
            raise ValueError("malformed_native_memory_census")
        for name, row in memories.items():
            if not isinstance(row, dict) or any(type(row.get(key)) is not int
                                                for key in ("width", "size", "start_offset")):
                raise ValueError("malformed_native_memory")
            native.setdefault(module, {})[name] = {
                key: row[key] for key in ("width", "size", "start_offset")}
        for cell in payload.get("cells", {}).values():
            if cell.get("type") not in _MEMORY_CELLS:
                continue
            memid = cell.get("parameters", {}).get("MEMID")
            if not isinstance(memid, str) or memid.lstrip("\\") not in memories:
                raise ValueError("unbound_native_memory_cell")
    source = {m: rows for m, rows in source.items() if rows}
    native = {m: rows for m, rows in native.items() if rows}
    if not source or source != native:
        raise ValueError("source_native_memory_census_disagrees")
    return {"modules": source,
            "memory_bits": sum(row["width"] * row["size"]
                               for memories in source.values() for row in memories.values())}


def _relative_directory(root: Path, value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("malformed_selected_include_directory")
    path = Path(value).absolute()
    if not path.is_dir() or path.is_symlink() or path.resolve() != path:
        raise ValueError("selected_include_directory_missing_or_symlinked")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError("selected_include_directory_outside_source_root") from exc
    return relative.as_posix()


def _selected_source(texts: list[str], configuration: Any) -> bool:
    if isinstance(configuration, dict) and any(configuration.get(key)
                                               for key in ("defines", "parameters",
                                                           "include_dirs")):
        return True
    return any(re.search(r"`|\\|\b(?:parameter|defparam|generate|genvar)\b", text)
               for text in texts)


def _selection_from_configuration(configuration: Any, root: Path,
                                  sources: list[Path], records: list[dict[str, Any]],
                                  top_module: str | None, required: bool
                                  ) -> dict[str, Any] | None:
    """Validate the producer's retained native capsule and normalize its inputs."""
    if not isinstance(configuration, dict) or configuration.get("state") != "MEASURED":
        if required:
            raise ValueError("selected_native_context_unmeasured")
        return None
    top = configuration.get("top")
    if not isinstance(top, str) or not re.fullmatch(r"[A-Za-z_]\w*", top):
        raise ValueError("invalid_selected_top")
    if top_module is not None and top != top_module:
        raise ValueError("selected_top_mismatch")
    defines = configuration.get("defines")
    parameters = configuration.get("parameters")
    declared_dirs = configuration.get("include_dirs")
    if (not isinstance(defines, list) or
            any(not isinstance(item, str) or
                not re.fullmatch(r"[A-Za-z_]\w*(?:=[^\s;\"\\]+)?", item)
                for item in defines) or len(defines) != len(set(defines))):
        raise ValueError("invalid_selected_defines")
    if (not isinstance(parameters, list) or
            any(not isinstance(item, str) or
                not re.fullmatch(r"[A-Za-z_]\w*=[0-9+-]+", item)
                for item in parameters) or len(parameters) != len(set(parameters))):
        raise ValueError("invalid_selected_parameters")
    if not isinstance(declared_dirs, list):
        raise ValueError("invalid_selected_include_directories")
    declared = [_relative_directory(root, item) for item in declared_dirs]
    if len(declared) != len(set(declared)):
        raise ValueError("duplicate_selected_include_directory")
    if not required:
        if defines or parameters or declared:
            raise ValueError("selected_context_not_accounted")
        return None

    native = configuration.get("native")
    if (not isinstance(native, dict) or native.get("status") != "MEASURED" or
            native.get("native_returncode") != 0 or
            native.get("transport_returncode") != 0 or native.get("top") != top or
            native.get("defines") != defines or native.get("parameters") != parameters):
        raise ValueError("selected_native_context_unmeasured")
    expected_files = sorted(str(path) for path in sources
                            if path.suffix.lower() in {".v", ".sv"})
    if sorted(native.get("files", [])) != expected_files:
        raise ValueError("selected_native_source_set_incomplete")
    effective_dirs = sorted(set(declared) | {
        path.parent.relative_to(root).as_posix() for path in sources
        if path.suffix.lower() in {".v", ".sv"}})
    native_dirs = native.get("include_dirs")
    if (not isinstance(native_dirs, list) or
            sorted(_relative_directory(root, item) for item in native_dirs) != effective_dirs):
        raise ValueError("selected_native_include_set_mismatch")
    expected_hashes = {str(path): record["sha256"]
                       for path, record in zip(sources, records)}
    if native.get("input_sha256") != expected_hashes:
        raise ValueError("selected_native_input_digest_mismatch")
    if not re.fullmatch(r"[0-9a-f]{64}", str(native.get("native_json_sha256", ""))):
        raise ValueError("selected_native_output_digest_missing")

    context_path = configuration.get("native_context")
    context_digest = configuration.get("native_context_sha256")
    script_row = configuration.get("native_script")
    if (not isinstance(context_path, str) or not isinstance(context_digest, str) or
            not isinstance(script_row, dict) or
            not all(isinstance(script_row.get(key), str)
                    for key in ("path", "sha256", "text"))):
        raise ValueError("selected_native_capsule_missing")
    context_file, script_file = Path(context_path), Path(script_row["path"])
    try:
        context_raw, script_raw = context_file.read_bytes(), script_file.read_bytes()
        context_payload = json.loads(context_raw)
    except (OSError, ValueError) as exc:
        raise ValueError("selected_native_capsule_unreadable") from exc
    if (hashlib.sha256(context_raw).hexdigest() != context_digest or
            context_payload != native or
            hashlib.sha256(script_raw).hexdigest() != script_row["sha256"] or
            script_raw.decode("utf-8", errors="strict") != script_row["text"]):
        raise ValueError("selected_native_capsule_stale")
    return {"schema": _SELECTION_SCHEMA, "top_module": top,
            "defines": defines, "parameters": parameters,
            "declared_include_dirs": sorted(declared),
            "include_dirs": effective_dirs}


def _validate_selection(selection: Any, root: Path) -> dict[str, Any]:
    if not isinstance(selection, dict) or set(selection) != {
            "schema", "top_module", "defines", "parameters",
            "declared_include_dirs", "include_dirs"}:
        raise ValueError("malformed_selected_configuration")
    if selection.get("schema") != _SELECTION_SCHEMA:
        raise ValueError("unsupported_selected_configuration_schema")
    top = selection.get("top_module")
    defines, parameters = selection.get("defines"), selection.get("parameters")
    declared, effective = (selection.get("declared_include_dirs"),
                           selection.get("include_dirs"))
    if not isinstance(top, str) or not re.fullmatch(r"[A-Za-z_]\w*", top):
        raise ValueError("invalid_selected_top")
    if (not isinstance(defines, list) or len(defines) != len(set(defines)) or
            any(not isinstance(item, str) or
                not re.fullmatch(r"[A-Za-z_]\w*(?:=[^\s;\"\\]+)?", item)
                for item in defines)):
        raise ValueError("invalid_selected_defines")
    if (not isinstance(parameters, list) or len(parameters) != len(set(parameters)) or
            any(not isinstance(item, str) or
                not re.fullmatch(r"[A-Za-z_]\w*=[0-9+-]+", item)
                for item in parameters)):
        raise ValueError("invalid_selected_parameters")
    if (not isinstance(declared, list) or not isinstance(effective, list) or
            any(not isinstance(item, str) for item in [*declared, *effective]) or
            sorted(set(declared)) != declared or sorted(set(effective)) != effective or
            not set(declared).issubset(effective)):
        raise ValueError("invalid_selected_include_directories")
    for item in effective:
        path = root / item
        if (Path(item).is_absolute() or ".." in Path(item).parts or not path.is_dir() or
                path.is_symlink() or path.resolve() != path):
            raise ValueError("selected_include_directory_missing_or_symlinked")
    return selection


def receipt_configuration_matches(claim: Any, configuration: Any,
                                  root: Path | None) -> tuple[bool, str]:
    """Bind a producer's selected native capsule to the applicability claim."""
    if root is None:
        return False, "consumer_source_root_undeclared"
    try:
        root = Path(root).absolute()
        sources, records, texts = _census(root)
        required = _selected_source(texts, configuration)
        measured = _selection_from_configuration(
            configuration, root, sources, records,
            claim.get("facts", {}).get("top_module") if isinstance(claim, dict) else None,
            required)
        expected = claim.get("selection") if isinstance(claim, dict) else None
        if measured != expected:
            raise ValueError("selected_configuration_or_capsule_drift")
        return True, "selected_configuration_bound" if required else "plain_configuration_bound"
    except (OSError, ValueError, UnicodeError, KeyError, TypeError) as exc:
        return False, str(exc) if isinstance(exc, ValueError) else type(exc).__name__


def _fixed_localparam_facts(texts: list[str], modules: dict[str, Any]) -> dict[str, Any]:
    """Resolve bounded internal constants using the existing hierarchy owner.

    Native elaboration alone can discard an unused unresolved localparam.
    Require every declaration to resolve, and independently match all source
    ports (including constant widths) to the complete native module census.
    Scoped constants and implicit generate selection remain unsupported.
    """
    import module_port_audit as ports
    import rtl_hierarchy_drivers as hierarchy

    declared = {}
    for text in texts:
        issues = []
        regions = list(ports.module_regions(text, issues))
        if issues:
            raise ValueError("incomplete_constant_module_census")
        if sum(len(re.findall(r"\blocalparam\b", text[b:e]))
               for _, _, b, e in regions) != len(re.findall(r"\blocalparam\b", text)):
            raise ValueError("unsupported_localparam_scope")
        for name, start, body_start, end in regions:
            if name in declared:
                raise ValueError("ambiguous_constant_module")
            header, body = text[start:body_start], text[body_start:end]
            if re.search(r"\b(?:if|for|case|casez|casex|function|task|begin)\b", body):
                raise ValueError("unsupported_localparam_scope_or_generate")
            groups = list(re.finditer(r"\blocalparam\b([^;]+);", body))
            names = []
            for group in groups:
                for item in ports.split_top_level(group[1]):
                    match = re.fullmatch(r".*?\b([A-Za-z_]\w*)\s*=\s*(.+)", item.strip(), re.S)
                    if match is None:
                        raise ValueError("unsupported_localparam_declaration")
                    names.append(match[1])
            if len(groups) != len(re.findall(r"\blocalparam\b", body)) or len(set(names)) != len(names):
                raise ValueError("incomplete_localparam_declarations")
            expressions = hierarchy.parameter_expressions(header, body)
            values = hierarchy.resolve_parameters(expressions)
            if set(expressions) != set(names) or set(values) != set(names) or any(
                    not isinstance(v, int) for v in values.values()):
                raise ValueError("unresolved_internal_constant")
            source_ports = ports.parse_port_list_ansi(header, "", 1, issues)
            if not source_ports or all(p.direction == "UNKNOWN" for p in source_ports.values()):
                source_ports = ports.parse_non_ansi_ports(body, "", 1, issues)
            native = modules.get(name)
            if issues or native is None or native.get("parameter_default_values"):
                raise ValueError("incomplete_constant_native_census")
            actual = {p: {"direction": row["direction"], "width": len(row["bits"])}
                      for p, row in native.get("ports", {}).items()}
            expected = {p: {"direction": row.direction,
                            "width": hierarchy.DriverContext.range_width(row.width_expr, values)}
                        for p, row in source_ports.items()}
            if expected != actual:
                raise ValueError("constant_source_native_ports_disagree")
            declared[name] = {"values": values, "ports": actual}
    if set(declared) != set(modules):
        raise ValueError("constant_source_native_modules_disagree")
    return declared


def _has_state_recurrence(module: dict[str, Any]) -> bool:
    """Non-identity state feedback, including mux selectors/case encodings.

    Only a literal bit's hold path through mux data inputs is ignored. All
    selectors, clock/reset/enable controls and transformed data retain their
    dependencies. A renamed counter, case-encoded counter, shift recurrence,
    or cycle through two registers therefore cannot acquire an absence proof.
    """
    cells = module.get("cells", {})
    state = {name: c for name, c in cells.items() if c["type"] in _STATE_CELLS}
    owners: dict[int, str] = {}
    drivers: dict[int, tuple[dict[str, Any], str, int]] = {}
    for name, cell in cells.items():
        for port, direction in cell.get("port_directions", {}).items():
            if direction != "output":
                continue
            for offset, bit in enumerate(cell["connections"][port]):
                if not isinstance(bit, int):
                    continue
                if bit in drivers or bit in owners:
                    raise ValueError("multiple_bit_drivers")
                if name in state:
                    if port != "Q":
                        raise ValueError("unsupported_state_output")
                    owners[bit] = name
                else:
                    drivers[bit] = (cell, port, offset)

    def origins(bit: Any, hold: int | None, transformed: bool,
                visiting: frozenset[int] = frozenset()) -> set[str]:
        if not isinstance(bit, int):
            return set()
        if bit in owners:
            return set() if bit == hold and not transformed else {owners[bit]}
        if bit not in drivers:
            return set()
        if bit in visiting:
            raise ValueError("combinational_cycle")
        cell, port, offset = drivers[bit]
        conns = cell["connections"]
        deps: set[str] = set()
        if cell["type"] in ("$mux", "$pmux") and port == "Y":
            width = len(conns["Y"])
            for input_port in ("A", "B"):
                for pos in range(offset, len(conns[input_port]), width):
                    deps |= origins(conns[input_port][pos], hold, transformed,
                                    visiting | {bit})
            for selector in conns["S"]:
                deps |= origins(selector, hold, True, visiting | {bit})
        else:
            for input_port, direction in cell["port_directions"].items():
                if direction == "input":
                    for source in conns[input_port]:
                        deps |= origins(source, hold, True, visiting | {bit})
        return deps

    graph: dict[str, set[str]] = {}
    for name, cell in state.items():
        conns = cell["connections"]
        if len(conns.get("D", [])) != len(conns["Q"]):
            raise ValueError("unsupported_state_data_shape")
        deps: set[str] = set()
        for data, held in zip(conns["D"], conns["Q"]):
            deps |= origins(data, held, False)
        for port, direction in cell["port_directions"].items():
            if direction == "input" and port != "D":
                for control in conns[port]:
                    deps |= origins(control, None, True)
        graph[name] = deps

    def cycle(node: str, active: frozenset[str]) -> bool:
        if node in active:
            return True
        return any(cycle(n, active | {node}) for n in graph[node])

    return any(cycle(n, frozenset()) for n in graph)


def assess(auditor: str, root: Path, *, files: Iterable[Path] | None = None,
           top_module: str | None = None, configuration: Any = None,
           selected_configuration: Any = None) -> dict[str, Any]:
    """Build a reproducible absence claim or an explicit blocking UNKNOWN."""
    result: dict[str, Any] = {"schema": SCHEMA, "auditor": auditor,
                             "state": UNKNOWN}
    if auditor not in AUDITORS:
        result["reason"] = "unsupported_auditor"
        return result
    try:
        root = Path(root).absolute()
        sources, records, texts = _census(root)
        if files is not None and sorted(Path(p).absolute() for p in files) != sources:
            raise ValueError("source_set_incomplete")
        result["source"] = {"root": str(root), "files": records,
                            "sha256": hashlib.sha256(json.dumps(
                                records, sort_keys=True).encode()).hexdigest()}
        requires_selection = _selected_source(texts, configuration)
        if selected_configuration is not None:
            selection = _validate_selection(selected_configuration, root)
            requires_selection = True
        else:
            selection = _selection_from_configuration(
                configuration, root, sources, records, top_module, requires_selection)
        if requires_selection and selection is None:
            raise ValueError("unsupported_configuration_or_preprocessing")
        if selection is not None:
            if top_module is not None and selection["top_module"] != top_module:
                raise ValueError("selected_top_mismatch")
            result["selection"] = selection
        if auditor != "interface_encoding_audit" and any(
                re.search(r"\blocalparam\b", t) for t in texts):
            raise ValueError("unsupported_configuration_or_preprocessing")
        # Frontends can drop an unused unpacked memory before writing JSON.
        # Its absence there is not a complete census of the source structure.
        source_memory = any(re.search(
            r"\b(?:reg|logic|wire)\s+(?:signed\s+)?"
            r"(?:\[[^\]]+\]\s*)?[A-Za-z_]\w*\s*\[", t)
            or re.search(r"\]\s*[A-Za-z_]\w*\s*\[", t) for t in texts)
        if auditor != "interface_encoding_audit" and source_memory:
            raise ValueError("unsupported_memory")
        modules = _elaborate(sources, root=root, selection=selection, source_sha256={
            str(path): record["sha256"] for path, record in zip(sources, records)
        })["modules"]
        # The tool read immutable snapshots of the census bytes. Reject live
        # source or membership changes while it ran as well, so the resulting
        # claim also describes the directory the consumer will remeasure.
        after_sources, after_records, _ = _census(root)
        if after_sources != sources or after_records != records:
            raise ValueError("source_changed_during_elaboration")
        facts = _module_facts(modules, allow_memory=auditor == "interface_encoding_audit")
        if auditor == "interface_encoding_audit" and (
                source_memory or any(module.get("memories") for module in modules.values())):
            facts["internal_memories"] = _memory_facts(texts, modules)
        if any(re.search(r"\blocalparam\b", t) for t in texts):
            facts["fixed_internal_constants"] = _fixed_localparam_facts(texts, modules)
        if top_module is not None and top_module != facts["top_module"]:
            raise ValueError("declared_top_mismatch")
        result["facts"] = facts
        if auditor == "interface_encoding_audit":
            present = facts["child_instances"] != 0
            criterion = "closed_hierarchy_has_no_child_instances"
        elif auditor == "phy_counter_audit":
            # Child connections are not yet expanded into the state graph.
            if facts["child_instances"]:
                raise ValueError("unsupported_cross_module_state_graph")
            present = any(_has_state_recurrence(m) for m in modules.values())
            criterion = "closed_state_graph_has_no_nonidentity_recurrence"
        else:
            # Multi-bit external capture is intentionally UNKNOWN: its role
            # could be CRC data, even when no identifier contains 'crc'.
            present = facts["wide_data_nets_and_ports"] != 0
            criterion = "closed_scalar_design_has_no_multibit_crc_order_subject"
        if present:
            raise ValueError("subject_present_or_role_unknown")
        result["criterion"] = criterion
        result["structural_absence"] = absence(
            "elaborated source modules", len(modules), names=sorted(modules),
            detail=criterion)
        result["state"] = NOT_APPLICABLE
    except (OSError, ValueError, UnicodeError, KeyError, TypeError,
            subprocess.TimeoutExpired, RecursionError) as exc:
        result["reason"] = (str(exc) if isinstance(exc, ValueError)
                            else type(exc).__name__)
    return result


def source_root(files: Iterable[Path]) -> Path:
    """One explicit source directory, not an unbounded common-path guess."""
    parents = {Path(p).absolute().parent for p in files}
    if len(parents) != 1:
        raise ValueError("source_files_require_one_closed_directory")
    return next(iter(parents))


def from_files(auditor: str, files: Iterable[Path]) -> dict[str, Any]:
    selected = [Path(p) for p in files]
    try:
        return assess(auditor, source_root(selected), files=selected)
    except ValueError as exc:
        return {"schema": SCHEMA, "auditor": auditor, "state": UNKNOWN,
                "reason": str(exc)}


def verify(claim: Any, auditor: str, root: Path | None,
           *, top_module: str | None = None) -> tuple[bool, str]:
    """Consumer-side remeasurement, never a trust of the receipt's counters."""
    if root is None:
        return False, "consumer_source_root_undeclared"
    if not isinstance(claim, dict) or claim.get("state") != NOT_APPLICABLE:
        return False, "no_structural_not_applicable_claim"
    measured = assess(auditor, root, top_module=top_module,
                      selected_configuration=claim.get("selection"))
    if measured.get("state") != NOT_APPLICABLE:
        return False, "remeasurement_" + measured.get("reason", UNKNOWN)
    if claim != measured:
        return False, "source_or_proof_drift"
    return True, measured["criterion"]
