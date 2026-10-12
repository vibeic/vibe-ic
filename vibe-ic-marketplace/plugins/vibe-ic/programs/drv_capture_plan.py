#!/usr/bin/env python3
"""Build a DRV capture request from the routed run's own STA state.

The plan is an input inventory, never a sign-off assertion.  Missing inputs
raise an error.  Implementation-stage evidence is read from the receipts each
stage recorded when it ran (`STAGE_RECEIPT_DIR`); a stage without one stays
absent, which the judge reports as FAIL (DRV standard section 1: a stage whose
applied value cannot be extracted is FAIL, never N/A or NOT_MEASURED).  Identity
the run cannot hold before stream-out (GDS / LVS netlist) is named in
``identity["bound_at"]`` as bound at the final post-stream capture
(R-0929-DRV-IDENTITY); run and specification identity come from the record
taken at run start (`drv_run_identity`) and stay None, i.e. NOT_MEASURED,
when absent.  The final STAPostPNR state is the
source of scene identity.
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_text
from drv_signoff_judge import (_NUM, _REQUIRED_STAGES, _SCENE_PROFILES,
                               _integrator_value, _liberty_header, _liberty_limits,
                               _sdc_values, _sha, parse_check_types)

#: Where an implementation stage records its DRV-constraint receipt, one JSON
#: document per stage named ``<stage>.json`` (``synth``, ``placement_repair``,
#: ``cts``, ``post_grt_repair``, ``signoff_sta`` and, when step 32 adopted a
#: candidate, ``postroute_repair``).  Each document carries ``name``, ``ran``
#: and ``{"path", "sha256"}`` references written when the stage ran:
#: ``behavior_report`` (the declared-value DRV census, including a
#: ``sta::max_fanout_check_limit <value>`` line for an OpenROAD stage),
#: ``abc_script`` (synth) or ``sdc_snapshot`` (the ``write_sdc`` taken in the
#: same process on the line before the stage command).  The applied values are
#: derived here from those hashed bytes, never taken from the receipt's prose.
STAGE_RECEIPT_DIR = Path("reports/phase3/drv_stages")

#: Identity an in-flow capture cannot bind (R-0929-DRV-IDENTITY): it exists
#: only after stream-out, so it is "bound at" the final post-stream capture --
#: neither missing evidence nor NOT_MEASURED here.
_BOUND_AT_POST_STREAM = {
    "lvs_netlist": "the final post-stream DRV sign-off capture (after LVS)",
    "gds_netlist": "the final post-stream DRV sign-off capture (after stream-out)",
}


def _run_identity(project: Path) -> dict:
    """The run and specification identity an in-flow capture binds: the run
    id and code identity recorded at run start (`drv_run_identity.record`)
    and the Phase-1 document digest.  An absent record stays None, which the
    judge reports NOT_MEASURED; nothing is invented."""
    import drv_run_identity
    record = drv_run_identity.load(project)
    return {"run_id": record.get("run_id"),
            "tree_sha": record.get("plugin_tree_sha256"),
            "code_identity": {k: record.get(k) for k in (
                "plugin_source_commit", "plugin_tree_sha256", "recorded_at")},
            "spec_version": drv_run_identity.spec_version(project),
            "capture_point": "in_flow",
            "bound_at": dict(_BOUND_AT_POST_STREAM)}


def _ref(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"run input absent: {path}")
    return {"path": str(path.resolve()), "sha256": _sha(path)}


def _run_path(project: Path, value: str) -> Path:
    """Rebase an immutable run-state path when evaluating a copied project."""
    path = Path(value)
    if path.is_absolute():
        if path.is_relative_to(project):
            return path
        parts = path.parts
        # Rebase at the first run-tree folder the path passes through: a
        # `reports/phase3/...` path keeps its `reports` component.
        hits = [parts.index(marker) for marker in ("phase3", "phase1", "input", "reports")
                if marker in parts]
        if hits:
            return project.joinpath(*parts[min(hits):])
    return project / path if not path.is_absolute() else path


def _current_routed_identity(project: Path, recorded: Path) -> tuple[Path, str] | None:
    """Return the current deck-owned netlist path and its link subject.

    Handoff receipts can retain a predecessor state's absolute netlist path
    after the same routed bytes were adopted under ``stage3/pnr``.  The
    The direct STA deck's own ``read_verilog`` and ``link_design`` commands
    are the canonical producer contract for both fields.  Accept that
    identity only when setup and hold agree and the candidate bytes equal the
    recorded state digest.  Any missing, malformed, disagreeing, or changed
    input keeps the strict refusal path in force.
    """
    paths = []
    sta_dir = project / "phase3/stage3/sta"
    for kind in ("setup", "hold"):
        deck = sta_dir / f"sta_mcorner_ocv_{kind}.tcl"
        try:
            reads = []
            tops = []
            for line in deck.read_text().splitlines():
                words = line.strip().split()
                if len(words) != 2:
                    continue
                if words[0] == "read_verilog":
                    reads.append(words[1].strip("{}"))
                elif words[0] == "link_design":
                    tops.append(words[1].strip("{}"))
        except OSError:
            return None
        if len(reads) != 1 or len(tops) != 1:
            return None
        candidate = _run_path(project, reads[0])
        if not candidate.is_file():
            return None
        paths.append((candidate, tops[0]))
    if len(paths) != 2 or paths[0] != paths[1]:
        return None
    try:
        if _sha(paths[0][0]) != _sha(recorded):
            return None
    except OSError:
        return None
    return paths[0]


def _current_routed_netlist(project: Path, recorded: Path) -> Path:
    """Bind only the path portion of the current deck-owned identity."""
    identity = _current_routed_identity(project, recorded)
    if identity is None:
        return recorded
    return identity[0]


def _state(project: Path, final_state: dict | None = None) -> tuple[dict, Path]:
    if final_state is not None:
        final = final_state.get("final") or {}
        path = _run_path(project, str(final.get("sta_state") or ""))
        if not path.is_file() or _sha(path) != final.get("sta_state_sha256"):
            raise ValueError("final STAPostPNR state absent or differs from step 32")
        return json.loads(path.read_text()), path
    repair = project / "reports/phase3/librelane_postroute_repair.json"
    if repair.is_file():
        receipt = json.loads(repair.read_text())
        final = receipt.get("final") or {}
        path = _run_path(project, str(final.get("sta_state") or ""))
        if not path.is_file() or _sha(path) != final.get("sta_state_sha256"):
            raise ValueError("final STAPostPNR state absent or differs from repair receipt")
        return json.loads(path.read_text()), path
    candidates = sorted((project / "phase3/librelane").glob("**/04-openroad-stapostpnr/state_out.json"))
    if len(candidates) != 1:
        raise ValueError("final STAPostPNR state is not uniquely identified")
    return json.loads(candidates[0].read_text()), candidates[0]


def _recorded_ref(project: Path, item: object) -> dict | None:
    """Keep the hash a stage recorded; the judge re-reads the bytes."""
    if not isinstance(item, dict) or not item.get("path"):
        return None
    return {"path": str(_run_path(project, str(item["path"]))),
            "sha256": item.get("sha256")}


def _recorded_text(ref: dict | None) -> str:
    """Bytes a stage recorded, or nothing when they changed since."""
    if not ref or not re.fullmatch(r"[0-9a-f]{64}", str(ref.get("sha256") or "")):
        return ""
    path = Path(ref["path"])
    if not path.is_file() or _sha(path) != ref["sha256"]:
        return ""
    return path.read_text(errors="replace")


def _one(values: list[float]) -> float | None:
    return values[0] if values and len(set(values)) == 1 else None


def _cts_parameters(text: str) -> dict | None:
    """`clock_tree_synthesis`'s own argument list (a Tcl list the probe wrote)."""
    words = _tcl_words(text.strip())
    if words is None:
        return None
    params: dict = {}
    i = 0
    while i < len(words):
        key = words[i]
        if not key.startswith("-"):
            return None
        if i + 1 < len(words) and not words[i + 1].startswith("-"):
            params[key[1:]] = words[i + 1]
            i += 2
        else:
            params[key[1:]] = True
            i += 1
    return params


def _tcl_words(text: str) -> list[str] | None:
    """Split one Tcl list of plain and {braced} words; None if malformed."""
    words, i = [], 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        if text[i] == "{":
            depth, j = 1, i + 1
            while j < len(text) and depth:
                depth += {"{": 1, "}": -1}.get(text[j], 0)
                j += 1
            if depth:
                return None
            words.append(text[i + 1:j - 1])
            i = j
        else:
            j = i
            while j < len(text) and not text[j].isspace():
                j += 1
            words.append(text[i:j])
            i = j
    return words


def _clock_driver_fanout(text: str) -> list[dict] | None:
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 4 or parts[0] != "clock_driver_fanout" or not parts[3].isdigit():
            return None
        rows.append({"driver": parts[1], "net": parts[2], "fanout": int(parts[3])})
    return rows


def _ideal_clock_excluded(behavior: str) -> bool:
    """The post-synthesis census states its clocks' propagation before the
    checks run; ideal clocks are what OpenSTA's checks exclude."""
    count = re.search(r"(?m)^clocks\s+(\d+)\s*$", behavior)
    states = re.findall(r"(?m)^clock\s+\S+\s+is_propagated=([01])\s*$", behavior)
    return bool(count) and int(count.group(1)) == len(states) and all(
        state == "0" for state in states)


def _pad_cells(liberties, io_library_paths=()) -> frozenset:
    """The IO class of R-0929-DRV-FANOUT-LIMIT: every cell a linked Liberty
    declares `pad_cell : true` (the judge's own IO test) and every cell of a
    Liberty the scene links as an IO library (LibreLane PAD_LIBS -- its fill,
    corner and supply cells carry the IO library's default limit but no
    pad_cell attribute).  Everything else is core."""
    io_paths = {str(Path(p).resolve()) for p in io_library_paths}
    cells: set[str] = set()
    for item in liberties:
        limits = _liberty_limits(Path(item["path"]).read_text())
        cells |= set(limits["pad_cells"])
        if str(Path(item["path"]).resolve()) in io_paths:
            cells |= set(limits["cells"])
    return frozenset(cells)


def _pad_lib_paths(env: dict, root: Path, pdk: str, pvt: str) -> list[Path]:
    """The scene's IO Liberties, as `_scene_files` links them from PAD_LIBS."""
    return [_pdk_path(value, root, pdk)
            for value in re.findall(r"/[^\s\"\\]+\.lib\b", env.get("PAD_LIBS", ""))
            if pvt in value]


def _class_fanout_limits(limits: str, pin_cells: str, pad_cells: frozenset) -> dict:
    """R-0929-DRV-FANOUT-LIMIT: the fanout limit the tool enforces, per class,
    from its own pre-command limit table.  `core` is the design-level limit
    on standard-cell drivers; `io` the IO cells' own (library) limit; a
    top-level port is neither.  A class whose pins disagree has no single
    value (None)."""
    cell_of = {}
    for line in pin_cells.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] == "pin_cell":
            cell_of[parts[1]] = parts[2]
    rows = parse_check_types(limits, scene="stage", mode="stage",
                             violators_only=False)["max_fanout"]
    by_class: dict[str, set] = {"core": set(), "io": set()}
    for row in rows:
        cell = cell_of.get(row["pin"])
        if cell is None or cell == "<port>" or not isinstance(row.get("limit"), float):
            continue
        by_class["io" if cell in pad_cells else "core"].add(row["limit"])
    return {name: (next(iter(values)) if len(values) == 1 else None)
            for name, values in by_class.items()}


def _stages(project: Path, postroute_repair_ran: bool,
            pad_cells: frozenset = frozenset()) -> tuple[list[dict], dict]:
    """Derive each required stage row from the receipt the stage recorded.

    A receipt counts only when it belongs to the run instance that claimed
    the receipt directory (`drv_stage_receipts.claim`).  Every value, and
    every derived flag, is read from the hashed evidence files the receipt
    names; the receipt's own fields are never a value.
    """
    import drv_stage_receipts
    names = [*_REQUIRED_STAGES, *(("postroute_repair",) if postroute_repair_ran else ())]
    rows: list[dict] = []
    inventory: dict[str, dict] = {}
    run_id = drv_stage_receipts.current_run(project)
    for name in names:
        path = project / STAGE_RECEIPT_DIR / f"{name}.json"
        entry = {"receipt": str(path), "run_id": run_id}
        inventory[name] = entry
        doc, status = drv_stage_receipts.read_receipt(project, name)
        entry["status"] = status
        if doc is None:
            continue
        entry["sha256"] = _sha(path)
        row: dict = {"name": name}
        for field in ("behavior_report", "abc_script", "sdc_snapshot",
                      "command_args", "clock_fanout_report"):
            ref = _recorded_ref(project, doc.get(field))
            if ref is not None:
                row[field] = ref
        behavior = _recorded_text(row.get("behavior_report"))
        # "Ran" is what the tool's own hashed files show, never the receipt's
        # word: the stage command's census (and, for synthesis, the script
        # ABC executed) must be there, unchanged since the stage wrote it.
        row["ran"] = bool(behavior) and (
            name != "synth" or bool(_recorded_text(row.get("abc_script"))))
        if name == "synth":
            script = _recorded_text(row.get("abc_script"))
            scripts = [script]
            sources = {item["source"]: item.get("script")
                       for item in doc.get("abc_sources", [])}
            pending = drv_stage_receipts.abc_source_names(script)
            seen = set()
            while pending:
                source = pending.pop(0)
                if source in seen:
                    continue
                seen.add(source)
                text = _recorded_text(_recorded_ref(project, sources.get(source)))
                if not text:
                    row["ran"] = False
                    scripts = []
                    break
                scripts.append(text)
                pending.extend(drv_stage_receipts.abc_source_names(text))
            buffers = [float(v) for v in re.findall(
                rf"(?:^|[;\n])\s*buffer\s+-N\s+({_NUM})"
                rf"(?:\s+-S\s+{_NUM})?\s*(?=;|\n|$)", "\n".join(scripts))]
            row["applied"] = {"fanout": _one(buffers)}
            row["synth_abc_buffering"] = bool(buffers)
            row["ideal_clock_excluded"] = _ideal_clock_excluded(behavior)
        else:
            snapshot = _recorded_text(row.get("sdc_snapshot"))
            row["applied"] = {field: _one(_sdc_values(snapshot, command, include_ports=False))
                              for field, command in (
                                  ("fanout", "set_max_fanout"),
                                  ("slew_ns", "set_max_transition"),
                                  ("cap_pf", "set_max_capacitance"))}
            # The zero-argument OpenSTA call names the worst-slack pin's limit;
            # on a padded die that is an IO cell's library default.  It stays a
            # disclosure; the applied-limit check reads the core drivers'
            # enforced limit (R-0929-DRV-FANOUT-LIMIT).
            row["worst_pin_fanout_check_limit"] = _one([float(v) for v in re.findall(
                rf"(?m)^\s*sta::max_fanout_check_limit\s+({_NUM})\s*$", behavior)])
            for field in ("fanout_limit_report", "pin_cell_report"):
                ref = _recorded_ref(project, doc.get(field))
                if ref is not None:
                    row[field] = ref
            limits = _recorded_text(row.get("fanout_limit_report"))
            cells = _recorded_text(row.get("pin_cell_report"))
            by_class = (_class_fanout_limits(limits, cells, pad_cells)
                        if limits and cells else {"core": None, "io": None})
            row["fanout_check_limit"] = by_class["core"]
            row["io_fanout_limit"] = by_class["io"]
            if name == "cts":
                args = _recorded_text(row.get("command_args"))
                row["cts_parameters"] = _cts_parameters(args) if args else None
                fanout = _recorded_text(row.get("clock_fanout_report"))
                row["clock_driver_fanout"] = (_clock_driver_fanout(fanout)
                                              if fanout else None)
        rows.append(row)
    return rows, inventory


def _env(scene_dir: Path) -> dict[str, str]:
    files = list(scene_dir.glob("_env_*.tcl"))
    if len(files) != 1:
        raise ValueError(f"scene environment not unique: {scene_dir}")
    result = {}
    for line in files[0].read_text().splitlines():
        match = re.match(r"set ::env\(([^)]+)\) (.*)$", line)
        if match:
            result[match.group(1)] = match.group(2).strip('"')
    return result


def _pdk_path(value: str, root: Path, pdk: str) -> Path:
    if value.startswith("/pdk/" + pdk + "/"):
        return root / value[len("/pdk/"):]
    return Path(value)


def _clock_io_values(sdc: str) -> tuple[float | None, float | None]:
    """Read applied numeric clock and IO constraints from the run's SDC."""
    numbers = r"[0-9]+(?:\.[0-9]+)?"
    periods = re.findall(rf"(?m)^\s*create_clock\b[^\n;]*?-period\s+({numbers})(?=\s|$)", sdc)
    delays = re.findall(rf"(?m)^\s*set_(?:input|output)_delay\s+({numbers})(?=\s|$)", sdc)
    period = float(periods[0]) if len(set(periods)) == 1 and periods else None
    io_delay = float(delays[0]) if len(set(delays)) == 1 and delays else None
    return period, io_delay


def _scene_files(env: dict, root: Path, pdk: str, pvt: str) -> tuple[list[dict], list[dict]]:
    libs = []
    lefs = []
    for key in ("CELL_LIBS", "PAD_LIBS"):
        paths = re.findall(r"/[^\s\"\\]+\.lib\b", env.get(key, ""))
        selected = [_pdk_path(value, root, pdk) for value in paths if pvt in value]
        for path in selected:
            libs.append({"name": path.stem, **_ref(path)})
    for key in ("CELL_LEFS", "PAD_LEFS", "MACRO_LEFS"):
        for value in re.findall(r"/[^\s\"\\]+\.lef\b", env.get(key, "")):
            path = _pdk_path(value, root, pdk)
            lefs.append(_ref(path))
    if not libs or not lefs:
        raise ValueError("linked scene Liberty or LEF inventory absent")
    return libs, lefs


def _direct_script(path: Path) -> dict:
    """Read only literal inputs from the post-route STA deck that actually ran."""
    if not path.is_file():
        raise ValueError(f"direct post-route STA deck absent: {path}")
    result: dict[str, object] = {"liberties": []}
    commands = {"read_verilog": "netlist", "read_sdc": "sdc",
                "read_spef": "spef", "link_design": "top"}
    for line in path.read_text().splitlines():
        words = line.strip().split()
        if not words:
            continue
        if words[0] == "read_liberty" and len(words) == 2:
            result["liberties"].append(words[1])
        elif words[0] in commands and len(words) == 2:
            key = commands[words[0]]
            if key in result:
                raise ValueError(f"direct STA deck repeats {words[0]}")
            result[key] = words[1]
    if any(not result.get(key) for key in ("netlist", "sdc", "spef", "top", "liberties")):
        raise ValueError("direct STA deck lacks a frozen input")
    return result


def _current_report_sdc(project: Path, fallback: Path) -> Path:
    """Return the raw SDC the current direct STA report names.

    A final STAPostPNR scene may point at ``signoff_scene.sdc``, a derived
    bridge that carries the OCV commands.  The strict DRV currentness consumer
    compares ``current.sources.signoff_sdc`` with the SDC named by the actual
    current report, so that field must remain the direct deck's raw input.
    The bridge/native measurement recipe stays owned by its existing STA
    producer; this helper only chooses the authority path for the DRV receipt.
    If no direct setup/hold decks are present, the final state's own SDC is the
    only available raw authority.  A partial pair or disagreeing pair refuses
    rather than silently selecting one.
    """
    sta_dir = project / "phase3/stage3/sta"
    paths = [sta_dir / f"sta_mcorner_ocv_{kind}.tcl" for kind in ("setup", "hold")]
    present = [path.is_file() for path in paths]
    if not any(present):
        return fallback
    if not all(present):
        raise ValueError("direct setup and hold decks are incomplete")
    def literal(path: Path, command: str) -> str:
        values = [words[1] for words in
                  (line.strip().split() for line in path.read_text().splitlines())
                  if len(words) == 2 and words[0] == command]
        if len(values) != 1:
            raise ValueError(f"direct STA deck {path} has no unique {command}")
        return values[0]

    decks = [{command: literal(path, command)
              for command in ("read_verilog", "read_sdc", "link_design")}
             for path in paths]
    if any(decks[0][key] != decks[1][key]
           for key in ("read_verilog", "read_sdc", "link_design")):
        raise ValueError("direct setup and hold decks use different current inputs")
    value = decks[0]["read_sdc"]
    return _run_path(project, value)


def _ocv_recipe(paths: list[Path]) -> dict:
    """Bind the existing flat-OCV recipe to its source bytes.

    The DRV currentness SDC is the raw report input, while the capture still
    has to apply the same derate that the direct/native STA used.  Read the
    recipe from the already-produced derived scene (or both direct decks),
    verify every source reference, and refuse an incomplete or conflicting
    pair instead of silently measuring without OCV.
    """
    if not paths:
        raise ValueError("DRV OCV recipe source absent")
    sources = [_ref(path) for path in paths]
    recipes = []
    for path in paths:
        found: dict[str, float] = {}
        for line in path.read_text(errors="replace").splitlines():
            words = line.strip().split()
            if not words or words[0] != "set_timing_derate":
                continue
            if len(words) != 3 or words[1] not in ("-early", "-late"):
                raise ValueError(f"malformed DRV OCV recipe: {path}: {line}")
            key = words[1][1:]
            if key in found:
                raise ValueError(f"duplicate DRV OCV recipe: {path}: {key}")
            try:
                value = float(words[2])
            except ValueError as exc:
                raise ValueError(f"invalid DRV OCV recipe: {path}: {line}") from exc
            if not math.isfinite(value):
                raise ValueError(f"non-finite DRV OCV recipe: {path}: {line}")
            found[key] = value
        if set(found) != {"early", "late"}:
            raise ValueError(f"DRV OCV recipe incomplete: {path}: {found}")
        recipes.append(found)
    if any(recipe != recipes[0] for recipe in recipes[1:]):
        raise ValueError("setup/hold/derived DRV OCV recipes disagree")
    early, late = recipes[0]["early"], recipes[0]["late"]
    if not 0 < early <= 1 <= late:
        raise ValueError(f"DRV OCV recipe outside flat-OCV bounds: {recipes[0]}")
    return {"early": early, "late": late, "source_refs": sources}


def _native_sta_ocv(state_path: Path, corners: set[str]) -> dict:
    """Read the derate actually applied by this STAPostPNR invocation."""
    from librelane_signoff import CORNER_REPORT
    folder = state_path.parent
    receipt_path = folder / 'vibeic_receipt.json'
    receipt = json.loads(receipt_path.read_text())
    if (receipt.get('input') or {}).get('step') != 'OpenROAD.STAPostPNR':
        raise ValueError('native OCV receipt names another producer step')
    bound = receipt.get('sha256') or {}
    config_path = folder / 'config.json'
    refs = [_ref(receipt_path)]
    for path in (state_path, config_path):
        ref = _ref(path)
        if bound.get(path.name) != ref['sha256']:
            raise ValueError(f'native OCV input absent or changed: {path}')
        refs.append(ref)
    config = json.loads(config_path.read_text())
    if set(config.get('STA_CORNERS') or []) != corners:
        raise ValueError('native OCV corner coverage differs from selected STA scenes')
    extra = Path(str(config.get('STA_EXTRA_CORNER_TCL_FILE') or ''))
    extra_ref = _ref(extra)
    if ((receipt.get('input') or {}).get('config_files') or {}).get(str(extra)) != extra_ref['sha256']:
        raise ValueError('native OCV extra-corner Tcl absent or changed')
    refs.append(extra_ref)
    try:
        percent = float(config['TIME_DERATING_CONSTRAINT'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('native OCV derate constraint absent or malformed') from exc
    if not math.isfinite(percent) or not 0 <= percent < 100:
        raise ValueError('native OCV derate constraint outside flat-OCV bounds')
    expected = {'early': 1 - percent / 100, 'late': 1 + percent / 100}
    marker = re.compile(r'^OCV_DERATE_APPLIED early=(\S+) late=(\S+) '
                        r'flat-OCV source=TIME_DERATING_CONSTRAINT=(\S+)\s*$', re.M)
    for corner in sorted(corners):
        report = folder / corner / CORNER_REPORT
        ref = _ref(report)
        if bound.get(f'{corner}/{CORNER_REPORT}') != ref['sha256']:
            raise ValueError(f'native OCV report absent or changed: {report}')
        rows = marker.findall(report.read_text())
        if len(rows) != 1:
            raise ValueError(f'native OCV applied recipe absent or ambiguous: {corner}')
        try:
            early, late, applied_percent = map(float, rows[0])
        except ValueError as exc:
            raise ValueError(f'native OCV applied recipe malformed: {corner}') from exc
        values = (early, late, applied_percent)
        wanted = (expected['early'], expected['late'], percent)
        if any(not math.isfinite(value) or not math.isclose(value, target, rel_tol=1e-12,
                                                         abs_tol=1e-12)
               for value, target in zip(values, wanted)):
            raise ValueError(f'native OCV applied recipe differs from declared constraint: {corner}')
        refs.append(ref)
    return {**expected, 'source_refs': refs}


def _build_direct(project: Path) -> dict:
    """Capture the scenes a direct OCV deck really used, leaving gaps visible."""
    import _eda_image
    import librelane_contract
    sta_dir = project / "phase3/stage3/sta"
    deck_paths = [sta_dir / f"sta_mcorner_ocv_{kind}.tcl"
                  for kind in ("setup", "hold")]
    decks = [_direct_script(path) for path in deck_paths]
    if any(decks[0][key] != decks[1][key] for key in ("netlist", "sdc", "top")):
        raise ValueError("direct setup and hold decks use different routed identities")
    library_path = Path(decks[0]["liberties"][0])
    parts = library_path.parts
    if "libs.ref" not in parts:
        raise ValueError("direct linked Liberty lacks installed PDK identity")
    i = parts.index("libs.ref")
    pdk, library = parts[i - 1], parts[i + 1]
    image = _eda_image.resolve()
    resolved_root = librelane_contract.resolve_pdk_root(project, pdk, image=image)
    if not resolved_root:
        raise ValueError("direct STA PDK root unavailable")
    root = Path(resolved_root)
    profile = next((v for k, v in json.loads(_SCENE_PROFILES.read_text()).items()
                    if pdk.lower().startswith(k.lower())), None)
    if profile is None:
        raise ValueError("PDK has no declared DRV scene profile")
    expected = [f"{pvt}_{rc}" for pvt in profile["pvt"]
                for rc in profile["rc_corners"]]
    def host_lib(value: str) -> Path:
        components = Path(value).parts
        marker = components.index(pdk)
        return root.joinpath(*components[marker:])
    netlist = _run_path(project, str(decks[0]["netlist"]))
    routed = project / "phase3/stage3/pnr/routed.def"
    odb = project / "phase3/stage3/pnr/routed.odb"
    artifacts = {"sta_netlist": _ref(netlist), "lvs_netlist": {},
                 "gds_netlist": {}, "odb": _ref(odb) if odb.is_file() else {},
                 "def": _ref(routed)}
    sdc = _run_path(project, str(decks[0]["sdc"]))
    ocv_recipe = _ocv_recipe(deck_paths)
    config = root / pdk / "libs.tech/librelane" / library / "config.tcl"
    sources = {"signoff_sdc": _ref(sdc), "pdk_config": _ref(config)}
    for layer in ("L7", "L9"):
        paths = [p for folder in ("input/docs", "phase1/generated_docs")
                 for p in sorted((project / folder).glob(layer + "*")) if p.is_file()]
        if not paths:
            raise ValueError(f"{layer} declaration absent")
        sources[layer.lower()] = _ref(paths[0])
    linked_all = {}
    scenes = []
    scene_libs = {}
    pvt_headers = {}
    for deck in decks:
        linked = []
        lefs = []
        for value in deck["liberties"]:
            path = host_lib(value)
            item = {"name": path.stem, **_ref(path)}
            linked.append(item)
            linked_all[item["name"]] = item
            for lef in sorted((path.parent.parent / "lef").glob("*.lef")):
                lefs.append(_ref(lef))
        header = _liberty_header(Path(linked[0]["path"]).read_text())
        matches = [key for key, spec in profile["pvt"].items()
                   if all(header.get(field) == value for field, value in spec.items())]
        spef = _run_path(project, str(deck["spef"]))
        rc_matches = [rc for rc in profile["rc_corners"]
                      if re.search(rf"(?:^|\.){re.escape(rc)}\.spef$", spef.name)]
        if len(matches) != 1 or len(rc_matches) != 1:
            raise ValueError("direct STA deck PVT/RC scene cannot be identified")
        name = f"{matches[0]}_{rc_matches[0]}"
        if name in scene_libs:
            raise ValueError("direct STA decks repeat one scene")
        scene_libs[name] = [item["name"] for item in linked]
        pvt_headers[name] = header
        scenes.append({"name": name, "mode": "functional", "rc_corner": rc_matches[0],
                       "spef": _ref(spef), "spef_layout_sha256": artifacts["def"]["sha256"],
                       "liberty": linked[0]["name"], "linked_liberties": linked,
                       "linked_lefs": lefs,
                       "positive_control_limits": {"max_fanout": 1,
                                                   "max_slew": 1e-6,
                                                   "max_capacitance": 1e-6}})
    pdk_text = config.read_text()
    from declared_knob_applied_parity import collect_declared
    declared = collect_declared(project, pdk=pdk, library=library)
    fanout = _integrator_value(pdk_text, "MAX_FANOUT_CONSTRAINT", "SYNTH_MAX_FANOUT")
    sdc_text = sdc.read_text()
    period, io_delay = _clock_io_values(sdc_text)
    values = {"fanout": (declared.get("SYNTH_MAX_FANOUT") or (fanout,))[0],
              "slew_ns": _integrator_value(pdk_text, "MAX_TRANSITION_CONSTRAINT", "MAX_SLEW_CONSTRAINT"),
              "cap_pf": _integrator_value(pdk_text, "MAX_CAPACITANCE_CONSTRAINT", "MAX_CAP_CONSTRAINT"),
              "default_fanout_ceiling": fanout,
              "period_ns": period, "io_delay_ns": io_delay}
    frozen = {"sources": {k: v["sha256"] for k, v in sources.items()},
              "ocv_recipe": ocv_recipe,
              "liberties": {k: v["sha256"] for k, v in linked_all.items()},
              "values": values, "scope": "whole final netlist", "scenes": expected,
              "scene_profile_sha256": _sha(_SCENE_PROFILES),
              "scene_liberties": scene_libs, "rc_corners": profile["rc_corners"],
              "pvt": pvt_headers}
    current = {"sources": sources, "ocv_recipe": ocv_recipe,
               "liberties": list(linked_all.values()),
               "values": values, "scope": frozen["scope"], "scenes": expected,
               "scene_liberties": scene_libs}
    identity = {"project": str(project), **_run_identity(project), "pdk": pdk,
                "library": library, "artifacts": artifacts,
                "source_tool_image": image,
                "sta_netlist": artifacts["sta_netlist"]["sha256"],
                "lvs_netlist": None, "gds_netlist": None}
    stages, stage_receipts = _stages(project, False,
                                     _pad_cells(linked_all.values()))
    return {"top": decks[0]["top"], "identity": identity,
            "frozen": frozen, "current": current, "stages": stages,
            "stage_receipts": stage_receipts, "pins": {},
            "scenes": scenes, "postroute_repair_ran": False}


def _native_spef(project: Path, spef: Path, rc: str) -> Path:
    """Follow the existing RCX handoff when STA reads a canonical alias."""
    handoff_path = project / 'reports/phase3/librelane_rcx_handoff.json'
    if not handoff_path.is_file():
        return spef
    handoff = json.loads(handoff_path.read_text())
    matches = [view for view in (handoff.get('views') or {}).values()
               if isinstance(view, dict) and view.get('dest') and
               _run_path(project, view['dest']).resolve() == spef.resolve()]
    if not matches:
        return spef
    if len(matches) != 1:
        raise ValueError('RCX handoff SPEF alias is ambiguous')
    view = matches[0]
    state = _run_path(project, str(handoff.get('state') or ''))
    if not state.is_file() or _sha(state) != handoff.get('state_sha256'):
        raise ValueError('RCX handoff state absent or changed')
    source = _run_path(project, str(view.get('source') or ''))
    native = json.loads(state.read_text()).get('spef') or {}
    if not native.get(rc + '_*') or _run_path(project, native[rc + '_*']).resolve() != source.resolve():
        raise ValueError('RCX handoff SPEF source differs from extraction state')
    if (not source.is_file() or not spef.is_file() or
            _sha(source) != view.get('source_sha256') or
            _sha(spef) != view.get('dest_sha256') or
            view.get('source_sha256') != view.get('dest_sha256')):
        raise ValueError('RCX handoff SPEF source or alias changed')
    return source


def build(project: Path, *, final_state: dict | None = None) -> dict:
    project = project.resolve()
    if (final_state is None and
            not (project / "reports/phase3/librelane_postroute_repair.json").is_file() and
            not list((project / "phase3/librelane").glob(
                "**/04-openroad-stapostpnr/state_out.json"))):
        return _build_direct(project)
    state, state_path = _state(project, final_state)
    provenance = json.loads((project / "phase3/librelane_pdk_root.provenance.json").read_text())
    pdk = provenance["derivation"]["pdk"]
    image = provenance["derivation"]["image"]
    # A same-host checkpoint already names its PDK inputs. Reading them does
    # not require launching the older executable that produced the layout.
    # Only recreate the original image's PDK when that cache is unavailable.
    root = Path(provenance["path"])
    if not (root / pdk).is_dir():
        from librelane_contract import pdk_root_resolution
        resolution = pdk_root_resolution(None, pdk, image=image)
        if resolution["derivation"]["image_id"] != provenance["derivation"]["image_id"]:
            raise ValueError("final STA PDK image differs from run provenance")
        root = Path(resolution["path"])
    recorded_netlist = _run_path(project, state["nl"])
    routed_identity = _current_routed_identity(project, recorded_netlist)
    if routed_identity is None:
        netlist = recorded_netlist
        top = netlist.name.removesuffix(".nl.v")
    else:
        netlist, top = routed_identity
    state_def = _ref(_run_path(project, state["def"]))
    current_step23 = final_state is not None and final_state.get('capture_step') == '23'
    if final_state is None or current_step23:
        # After handoff the canonical routed DEF must be the layout the final
        # STA state measured.
        layout = _ref(project / "phase3/stage3/pnr/routed.def")
        if state_def["sha256"] != layout["sha256"]:
            raise ValueError("final STA DEF differs from routed DEF")
    else:
        # Step 32 captures its candidate before handoff writes routed.def.
        # Bind the candidate's own DEF; the pre-stream capture repeats the
        # routed.def comparison once the handoff has happened.
        layout = state_def
    artifacts = {"sta_netlist": _ref(netlist),
                 "lvs_netlist": {}, "gds_netlist": {},
                 "odb": _ref(_run_path(project, state["odb"])),
                 "def": layout}
    scene_root = state_path.parent
    profile = next((v for k, v in json.loads(_SCENE_PROFILES.read_text()).items()
                    if pdk.lower().startswith(k.lower())), None)
    if profile is None:
        raise ValueError("PDK has no declared DRV scene profile")
    expected_order = [f"{pvt}_{rc}" for pvt in profile["pvt"]
                      for rc in profile["rc_corners"]]
    expected = set(expected_order)
    actual_scenes = {f"{rc}_{pvt}" for pvt in profile["pvt"]
                     for rc in profile["rc_corners"]}
    if set(state.get("lib") or {}) != actual_scenes:
        raise ValueError("final STAPostPNR state lacks required scenes")
    scene_libs = {}
    liberties = {}
    scenes = []
    io_library_paths: list[Path] = []
    signoff_sdc = None
    for name in sorted(expected):
        pvt, _, rc = name.rpartition("_")
        actual_name = f"{rc}_{pvt}"
        folder = scene_root / actual_name
        env = _env(folder)
        sdc = _run_path(project, env["SIGNOFF_SDC_FILE"])
        if signoff_sdc is not None and sdc != signoff_sdc:
            raise ValueError("scene sign-off SDC differs")
        signoff_sdc = sdc
        # state["lib"] is STAPostPNR's generated top Liberty output. It was
        # not linked as an input by this scene; only the environment's CELL_LIBS
        # and PAD_LIBS were read into STA.
        generated_liberty = _run_path(project, state["lib"][actual_name])
        linked, lefs = _scene_files(env, root, pdk, pvt)
        io_library_paths.extend(_pad_lib_paths(env, root, pdk, pvt))
        for item in linked:
            existing = liberties.setdefault(item["name"], item)
            if existing != item:
                raise ValueError("linked Liberty identity collision")
        scene_libs[name] = [item["name"] for item in linked]
        spef = _native_spef(project, _run_path(project, state["spef"][rc + "_*"]), rc)
        scenes.append({"name": name, "mode": "functional", "rc_corner": rc,
                       "spef": _ref(spef), "spef_layout_sha256": artifacts["def"]["sha256"],
                       "generated_top_liberty": _ref(generated_liberty),
                       "liberty": linked[0]["name"], "linked_liberties": linked,
                       "linked_lefs": lefs,
                       "positive_control_limits": {"max_fanout": 1,
                                                   "max_slew": 1e-6,
                                                   "max_capacitance": 1e-6}})
    if signoff_sdc is None:
        raise ValueError("sign-off SDC absent")
    pdk_config = root / pdk / "libs.tech/librelane" / env["STD_CELL_LIBRARY"] / "config.tcl"
    # ``signoff_sdc`` is the raw SDC named by the current direct STA report.
    # ``signoff_scene.sdc`` remains the derived bridge consumed by its native
    # STA producer; it must not masquerade as the strict consumer's authority.
    raw_signoff_sdc = _current_report_sdc(project,
                                          _run_path(project, state["sdc"]))
    derived_signoff_sdc = _ref(signoff_sdc)
    ocv_recipe = (_native_sta_ocv(state_path, actual_scenes) if current_step23
                  else _ocv_recipe([signoff_sdc]))
    sources = {"pdk_config": _ref(pdk_config),
               "signoff_sdc": _ref(raw_signoff_sdc),
               "signoff_sdc_derived": derived_signoff_sdc}
    previous_path = project / "reports/phase3/sta/drv_capture_plan.json"
    if previous_path.is_file():
        previous = json.loads(previous_path.read_text())
        if ((previous.get("identity") or {}).get("source_tool_image_id") ==
                provenance["derivation"]["image_id"]):
            expected_pdk = ((previous.get("frozen") or {}).get("sources") or {}).get("pdk_config")
            if expected_pdk and expected_pdk != sources["pdk_config"]["sha256"]:
                raise ValueError("retained checkpoint PDK config changed")
            for scene in previous.get("scenes") or []:
                for item in [*(scene.get("linked_liberties") or []),
                             *(scene.get("linked_lefs") or [])]:
                    if _ref(Path(item["path"]))["sha256"] != item.get("sha256"):
                        raise ValueError(f"retained checkpoint PDK input changed: {item['path']}")
    native_measurement = (state_path.parent.parent /
                          "01-vibeic-postrouterepair/native_signoff/measurement_scene.sdc")
    if native_measurement.is_file():
        native_ref = _ref(native_measurement)
        sources["native_measurement_sdc"] = native_ref
        ocv_recipe["native_measurement_ref"] = native_ref
    for layer in ("L7", "L9"):
        paths = [p for directory in ("input/docs", "phase1/generated_docs")
                 for p in sorted((project / directory).glob(layer + "*")) if p.is_file()]
        if not paths:
            raise ValueError(f"{layer} declaration absent")
        sources[layer.lower()] = _ref(paths[0])
    sdc_text = raw_signoff_sdc.read_text()
    pdk_text = pdk_config.read_text()
    from declared_knob_applied_parity import collect_declared
    declared = collect_declared(project, pdk=pdk, library=env["STD_CELL_LIBRARY"])
    integrator_fanout = _integrator_value(pdk_text, "MAX_FANOUT_CONSTRAINT", "SYNTH_MAX_FANOUT")
    period, io_delay = _clock_io_values(sdc_text)
    values = {"fanout": (declared.get("SYNTH_MAX_FANOUT") or (integrator_fanout,))[0],
              "slew_ns": _integrator_value(pdk_text, "MAX_TRANSITION_CONSTRAINT", "MAX_SLEW_CONSTRAINT"),
              "cap_pf": _integrator_value(pdk_text, "MAX_CAPACITANCE_CONSTRAINT", "MAX_CAP_CONSTRAINT"),
              "default_fanout_ceiling": integrator_fanout,
              "period_ns": period, "io_delay_ns": io_delay}
    observed = {}
    for field, command in (("fanout", "set_max_fanout"),
                           ("slew_ns", "set_max_transition"),
                           ("cap_pf", "set_max_capacitance")):
        observed[field] = _sdc_values(sdc_text, command, include_ports=False)
    frozen = {"sources": {k: v["sha256"] for k, v in sources.items()},
              "ocv_recipe": ocv_recipe,
              "liberties": {k: v["sha256"] for k, v in liberties.items()},
              "values": values, "scope": "whole final netlist",
              "scenes": expected_order, "scene_profile_sha256": _sha(_SCENE_PROFILES),
              "scene_liberties": scene_libs, "rc_corners": profile["rc_corners"],
              "pvt": {name: _liberty_header(Path(next(item["path"] for item in scene["linked_liberties"]
                                                     if item["name"] == scene["liberty"])).read_text())
                      for name in sorted(expected)
                      for scene in scenes if scene["name"] == name}}
    current = {"sources": sources, "ocv_recipe": ocv_recipe,
               "liberties": list(liberties.values()),
               "values": values, "scope": frozen["scope"],
               "scenes": frozen["scenes"], "scene_liberties": scene_libs,
               "applied_sdc": observed}
    identity = {"project": str(project), **_run_identity(project),
                "pdk": pdk, "library": env["STD_CELL_LIBRARY"],
                "source_tool_image": image,
                "source_tool_image_id": provenance["derivation"]["image_id"],
                "artifacts": artifacts,
                **{key: artifacts[key].get("sha256") for key in
                   ("sta_netlist", "lvs_netlist", "gds_netlist")}}
    # The judge requires post-route repair constraints exactly when step 32
    # adopted a candidate; use the same adoption record.
    if current_step23:
        from librelane_contract import postroute_repair_adoption
        identity['repair_adoption'] = postroute_repair_adoption(project, Path(layout['path']))
        postroute_repair_ran = identity['repair_adoption']['adopted']
    elif final_state is not None:
        postroute_repair_ran = bool(final_state.get("adopted"))
    else:
        repair = project / "reports/phase3/librelane_postroute_repair.json"
        postroute_repair_ran = bool(repair.is_file() and
                                    json.loads(repair.read_text()).get("adopted"))
    stages, stage_receipts = _stages(project, postroute_repair_ran,
                                     _pad_cells(liberties.values(), io_library_paths))
    return {"top": top, "identity": identity, "frozen": frozen,
            "current": current, "stages": stages,
            "stage_receipts": stage_receipts, "pins": {}, "scenes": scenes,
            "postroute_repair_ran": postroute_repair_ran}


#: What step 31 records about the layout and netlist it compared, and what
#: the GDS admission records about the stream (both written by the flow).
LVS_INPUTS = Path("reports/phase3/lvs_inputs.json")
LVS_VERDICT = Path("reports/phase3/lvs_verdict.json")
GDS_ADMISSION = Path("reports/phase3/gds_admission.json")


def _read_json(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def post_stream_identity(project: Path, plan: dict) -> dict:
    """R-0929-DRV-IDENTITY: the FINAL capture binds the streamed GDS and the
    LVS netlist and records how they derive from the judged DEF / netlist.

    * GDS: `gds_admission.json` names the admitted GDS, its sha256 and the
      routed DEF it was streamed from (`basis_inputs`).
    * LVS: `lvs_inputs.json` names the DEF step 31 extracted the layout from
      and the gate netlist it compared against; `lvs_verdict.json` says
      whether the compare matched.
    The judge re-hashes every file and checks each link; this only gathers
    the records.  A missing record leaves its identity absent (NOT_MEASURED).
    """
    identity = dict(plan["identity"])
    artifacts = dict(identity.get("artifacts") or {})
    identity.pop("bound_at", None)
    identity["capture_point"] = "post_stream"
    derivation: dict = {}
    admission = _read_json(project / GDS_ADMISSION)
    gds_rel = admission.get("gds_relpath")
    if gds_rel and (project / gds_rel).is_file():
        basis = admission.get("basis_inputs") or {}
        derivation["gds"] = {
            "path": str((project / gds_rel).resolve()),
            "sha256": admission.get("gds_sha256"),
            "streamed_from_def_sha256": basis.get("phase3/stage3/pnr/routed.def"),
            "record": _ref(project / GDS_ADMISSION)}
    lvs = _read_json(project / LVS_INPUTS)
    verdict = _read_json(project / LVS_VERDICT)
    # The netlist LVS compared is the one step 31 RECORDED (path + sha256 at
    # compare time), never whatever that path holds now; the judge re-hashes it.
    schematic = lvs.get("schematic_netlist") or {}
    if (schematic.get("path") and schematic.get("sha256")
            and (project / LVS_INPUTS).is_file() and (project / LVS_VERDICT).is_file()):
        derivation["lvs"] = {
            "layout_def_sha256": (lvs.get("layout_def") or {}).get("sha256"),
            "schematic_netlist": {"path": str(schematic["path"]),
                                  "sha256": str(schematic["sha256"])},
            "verdict": verdict.get("status"),
            "compare_performed": verdict.get("compare_performed"),
            "inputs_record": _ref(project / LVS_INPUTS),
            "verdict_record": _ref(project / LVS_VERDICT),
            "records": [_ref(project / LVS_INPUTS), _ref(project / LVS_VERDICT)]}
        artifacts["lvs_netlist"] = derivation["lvs"]["schematic_netlist"]
        identity["lvs_netlist"] = artifacts["lvs_netlist"]["sha256"]
    if "gds" in derivation:
        # The netlist a streamed layout carries is the netlist of the DEF it
        # was streamed from; the judge accepts it only when that DEF is the
        # judged DEF (the plan binds DEF and STA netlist from one state).
        artifacts["gds_netlist"] = dict(artifacts["sta_netlist"])
        identity["gds_netlist"] = artifacts["gds_netlist"]["sha256"]
    identity["artifacts"] = artifacts
    identity["derivation"] = derivation
    return {**plan, "identity": identity}


def publish(project: Path, *, final_state: dict | None = None,
            capture_point: str = "in_flow") -> Path:
    output = project / "reports/phase3/sta/drv_capture_plan.json"
    plan = build(project, final_state=final_state)
    if capture_point == "post_stream":
        plan = post_stream_identity(project, plan)
    write_text(output, json.dumps(plan, indent=2) + "\n")
    return output


def capture_and_publish(project: Path, *, final_state: dict | None = None,
                        capture_point: str = "in_flow") -> Path:
    """Measure the current routed state and publish the judge's only input.

    `capture_point="post_stream"` is the FINAL capture (after stream-out and
    LVS); only its verdict counts toward IC PASS (R-0929-DRV-IDENTITY)."""
    import drv_signoff_capture
    output = project / "reports/phase3/sta/drv_signoff_bundle.json"
    output.unlink(missing_ok=True)
    plan_path = publish(project, final_state=final_state, capture_point=capture_point)
    plan = json.loads(plan_path.read_text())
    from librelane_contract import resolve_image
    bundle = drv_signoff_capture.capture(
        plan, project / "reports/phase3/sta/drv_capture",
        image=resolve_image(project, record=False))
    write_text(output, json.dumps(bundle, indent=2) + "\n")
    return output
