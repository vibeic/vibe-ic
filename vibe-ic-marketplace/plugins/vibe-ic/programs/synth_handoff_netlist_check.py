#!/usr/bin/env python3
"""Step 14 on the tool path: judge the synthesis HANDOFF NETLIST, not its recipe.

When step 9 runs LibreLane Yosys.Synthesis the recipe is the tool's fixed code
(setundef -> hilomap -> opt_clean -purge), so auditing script text has nothing
to audit. What must still hold at the handoff is a property of the netlist:

* no constant reaches a cell pin or a port as a literal (`1'h0`, `1'b1`,
  `1'bx`...). A literal constant is what `hilomap` exists to remove; OpenROAD
  turns it into `zero_`/`one_` nets and the detailed router fails on them
  (DRT-0305, the fresh-agent v068 run). An x/z literal is an undefined value.
* the resolved configuration names both tie cells (SYNTH_TIEHI_CELL /
  SYNTH_TIELO_CELL), so the recipe had somewhere to map a constant.
* the tie cells it placed are counted, as evidence.

LibreLane's Checker.YosysUnmappedCells / YosysSynthChecks /
NetlistAssignStatements run beside this gate; they do not look at constants.

ENFORCEMENT: blocking — `phase3_one_shot_runner._step_synth_librelane` runs
this gate on the tool's netlist and a nonzero exit fails the step.

chip-AGNOSTIC: the tie-cell names come from the resolved tool config.
Exit: 0 PASS, 1 FAIL, 2 NOT_MEASURED (unreadable input).
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_bytes, write_json  # noqa: E402
import instrument_calibration  # noqa: E402

#: A Verilog sized literal as Yosys `write_verilog` prints a constant.
_LITERAL = r"\d+'[bhdo][0-9a-fA-FxXzZ_?]+"
_ASSIGN_CONST_RE = re.compile(r"^\s*assign\s+(\S+)\s*=\s*(" + _LITERAL + r")\s*;", re.M)
_PIN_CONST_RE = re.compile(r"\.(\w+)\(\s*(" + _LITERAL + r")\s*\)")
_CONST_NET_RE = re.compile(r"\b(zero_|one_)\b")


def constant_connections(netlist: str) -> list[dict[str, str]]:
    """Every literal constant driving a port (assign) or a cell pin."""
    instrument_calibration.assert_calibrated(
        "synth_handoff_netlist_check::constant_connections")
    found = [{"kind": "assign", "target": m.group(1), "value": m.group(2)}
             for m in _ASSIGN_CONST_RE.finditer(netlist)]
    found += [{"kind": "pin", "target": m.group(1), "value": m.group(2)}
              for m in _PIN_CONST_RE.finditer(netlist)]
    found += [{"kind": "net", "target": m.group(1), "value": m.group(1)}
              for m in _CONST_NET_RE.finditer(netlist)]
    return found


def _master(cell: Any) -> Optional[str]:
    return str(cell).split("/", 1)[0] if cell else None


def check(netlist: Path, resolved: dict) -> dict:
    text = netlist.read_text(errors="replace")
    findings = []
    tiehi, tielo = _master(resolved.get("SYNTH_TIEHI_CELL")), _master(resolved.get("SYNTH_TIELO_CELL"))
    if not tiehi or not tielo:
        findings.append(f"TIE_CELL_UNDECLARED: SYNTH_TIEHI_CELL={resolved.get('SYNTH_TIEHI_CELL')!r} "
                        f"SYNTH_TIELO_CELL={resolved.get('SYNTH_TIELO_CELL')!r}")
    constants = constant_connections(text)
    undefined = [c for c in constants if re.search(r"[xXzZ?]", c["value"].split("'", 1)[-1])]
    if constants:
        findings.append(f"CONSTANT_NOT_TIED: {len(constants)} literal constant(s) at the handoff "
                        f"(first: {constants[0]['kind']} {constants[0]['target']} = {constants[0]['value']})")
    if undefined:
        findings.append(f"UNDEFINED_CONSTANT: {len(undefined)} x/z literal(s)")
    ties = {name: len(re.findall(r"^\s*" + re.escape(name) + r"\s", text, re.M))
            for name in (tiehi, tielo) if name}
    return {"program": "synth_handoff_netlist_check", "step": "14",
            "verdict": "FAIL" if findings else "PASS", "netlist": str(netlist),
            "tie_cells": ties, "constants": constants[:50],
            "constant_count": len(constants), "findings": findings}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _yosys_check_errors(report, resolved: dict) -> int:
    """Use the native warning-block rules, including configured exclusions.

    Source: vibeic/librelane 50567b0576db59ebfe26e5a22bec56f2486f8292,
    librelane/steps/pyosys.py::_parse_yosys_check (source SHA256
    e125208701d12371f54879cb350f480cd7dd3acfcc077375700a93b3190dae73).
    Only native debug/verbose logging is omitted; parsing needs no installed
    LibreLane package or a container launch in a retained-evidence reader.
    """
    errors, current_warning = 0, None
    for line in report:
        if line.startswith("Warning:") or line.startswith("Found and reported"):
            last_warning, current_warning = current_warning, line
            if last_warning is None:
                continue
            cells = re.findall(r"cell\s+\S+\s+\((\S+)\)", last_warning)
            if resolved["SYNTH_ELABORATE_ONLY"] and "but has no driver" in last_warning:
                continue
            if resolved["SYNTH_CHECKS_ALLOW_TRISTATE"] and (
                    "tribuf" in last_warning or any(
                        fnmatch.fnmatch(cell, pattern) for cell in cells
                        for pattern in (resolved["TRISTATE_CELLS"] or []))):
                continue
            errors += 1
        elif re.match(r"^\s+.+$", line) is not None and current_warning is not None:
            current_warning += line
    return errors


def critical_synthesis_checks(folder: Path, resolved: dict) -> dict[str, int]:
    """Judge both original CHECK reports at their receipt-bound bytes.

    Older images counted only the pre-synthesis report in their state metric.
    The critical final CHECK remains an obligation of that same producer.
    """
    receipt = json.loads((folder / "vibeic_receipt.json").read_text())
    recorded = receipt["sha256"]
    if recorded.get("config.json") != _sha(folder / "config.json"):
        raise ValueError("native receipt mismatch: config.json")
    if resolved != json.loads((folder / "config.json").read_text()):
        raise ValueError("critical CHECK config differs from native producer")
    counts = {}
    for name in ("pre_synth_chk.rpt", "chk.rpt"):
        rel = "reports/" + name
        path = folder / rel
        if recorded.get(rel) != _sha(path):
            raise ValueError(f"native receipt mismatch: {rel}")
        with path.open() as stream:
            counts[name] = _yosys_check_errors(stream, resolved)
    if any(counts.values()):
        raise ValueError(f"native synthesis critical CHECK errors: {counts}")
    return counts


def _runtime_pdk_mount(root: Path, guest: Path, receipt: dict) -> Path | None:
    """Find an equivalent PDK mount in the current consumer runtime.

    A native producer can record its host-side cache path even though the
    consumer is running in a fresh attested container.  In that namespace the
    recorded host path is intentionally absent; the image's PDK_ROOT is the
    only valid alternate source.  Admit it only when every recorded config
    file covered by this mount is present there with its receipt SHA-256.
    """
    runtime_value = os.environ.get("PDK_ROOT")
    if not isinstance(runtime_value, str):
        return None
    runtime_root = Path(runtime_value)
    if (not runtime_root.is_absolute() or runtime_root.is_symlink()
            or not runtime_root.is_dir()):
        return None
    try:
        relative_guest = guest.relative_to(root)
    except ValueError:
        return None
    raw_runtime_mount = runtime_root / relative_guest
    try:
        runtime_mount = raw_runtime_mount.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if (not runtime_mount.is_dir()
            or not runtime_mount.is_relative_to(runtime_root.resolve())):
        return None
    inp = receipt.get("input") if isinstance(receipt, dict) else None
    config_files = inp.get("config_files") if isinstance(inp, dict) else None
    if not isinstance(config_files, dict) or not config_files:
        return None
    pdk_files = []
    for recorded, expected in config_files.items():
        if not isinstance(recorded, str):
            return None
        path = Path(recorded)
        if (not path.is_absolute() or ".." in path.parts
                or str(path) != recorded
                or not isinstance(expected, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected)):
            return None
        if not path.is_relative_to(guest):
            continue
        pdk_files.append((path, expected))
    if not pdk_files:
        return None
    for path, expected in pdk_files:
        relative = path.relative_to(guest)
        candidate = raw_runtime_mount / relative
        # The mount root itself may be the image's canonical PDK alias (for
        # example gf180mcuD -> ciel/...); a symlink below that root is not an
        # immutable file binding and must remain refused unless it resolves
        # within the same runtime PDK root.  A symlink at the recorded file
        # itself is always refused.
        cursor = raw_runtime_mount
        for part in relative.parts:
            cursor /= part
            if cursor.is_symlink():
                try:
                    linked = cursor.resolve(strict=True)
                except (OSError, RuntimeError):
                    return None
                if (not linked.is_relative_to(runtime_root.resolve())
                        or cursor == candidate):
                    return None
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        if (not resolved.is_relative_to(runtime_mount)
                or not resolved.is_file() or _sha(resolved) != expected):
            return None
    return runtime_mount


def _receipt_pdk_mounts(folder: Path, receipt: dict) -> list[tuple[Path, str]]:
    """Return the producer's bound guest-to-host PDK mounts.

    ``run_chain`` records config-file keys as the guest paths the child read,
    while this handoff consumer runs on the host.  The mount record is part of
    the producer receipt; a changed or foreign record must refuse before any
    digest is credited.
    """
    metadata = folder / "pdk_root.json"
    recorded = (receipt.get("sha256") or {}).get("pdk_root.json")
    if not isinstance(recorded, str) or _sha(metadata) != recorded:
        raise ValueError("native receipt mismatch: pdk_root.json")
    fingerprint = folder / "input_fingerprint.json"
    fingerprint_sha = (receipt.get("sha256") or {}).get("input_fingerprint.json")
    if (not isinstance(fingerprint_sha, str) or _sha(fingerprint) != fingerprint_sha
            or json.loads(fingerprint.read_text()) != receipt.get("input")):
        raise ValueError("native receipt mismatch: input_fingerprint.json")
    doc = json.loads(metadata.read_text())
    root_value = doc.get("cli_pdk_root")
    root = Path(str(root_value or ""))
    if (not isinstance(root_value, str) or not root.is_absolute()
            or doc.get("stated_by") != "run_chain(pdk_root=...)"):
        raise ValueError("native receipt has an unstated or foreign PDK root")
    raw = doc.get("mounts_under_it")
    if not isinstance(raw, list):
        raise ValueError("native receipt is missing PDK mount metadata")
    mounts: list[tuple[Path, str]] = []
    for item in raw:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("native receipt has malformed PDK mount metadata")
        host, guest_value = Path(str(item[0])).resolve(), item[1]
        guest = Path(str(guest_value))
        if (not isinstance(guest_value, str) or not guest.is_absolute()
                or not (guest == root or guest.is_relative_to(root))):
            raise ValueError("native receipt has a foreign PDK mount")
        if not host.is_dir():
            runtime_host = _runtime_pdk_mount(root, guest, receipt)
            if runtime_host is None:
                raise ValueError("native receipt has a foreign PDK mount")
            host = runtime_host
        mounts.append((host, guest_value))
    return mounts


def _project_path_resolver(project: Path, folder: Path, state: dict):
    """Resolve receipt paths from the producer project into a staged project.

    LibreLane receipts intentionally retain the absolute paths seen by the
    native producer.  A backend arm runs from a clean ``outputs/project`` and
    must not read those original paths as an ambient side channel.  Derive the
    original project root from the receipt's state path and the *relative*
    producer folder, then admit only the corresponding regular staged file.
    External paths (notably ``/pdk``) remain external and are checked by the
    existing PDK mount validator.
    """
    project = Path(project).resolve(strict=True)
    folder = Path(folder).resolve(strict=True)
    try:
        recorded = Path(str(state["nl"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("native state has no absolute netlist path") from exc
    if (not recorded.is_absolute() or ".." in recorded.parts
            or str(recorded) != state["nl"]):
        raise ValueError("native state netlist path is not absolute")
    rel_folder = folder.relative_to(project)
    recorded_parent = recorded.parent
    if len(recorded_parent.parts) <= len(rel_folder.parts):
        raise ValueError("native state netlist has no project prefix")
    original_root = recorded_parent
    for _ in rel_folder.parts:
        original_root = original_root.parent
    if original_root / rel_folder != recorded_parent:
        raise ValueError("native state netlist folder is not canonical")
    # This is the producer's lexical namespace, which need not exist on this
    # host.  Resolving it against the consumer filesystem would follow ambient
    # symlinks and change the meaning of the receipt's original path keys.

    def resolve(value):
        path = Path(str(value))
        if (not isinstance(value, (str, Path)) or not path.is_absolute()
                or ".." in path.parts or str(path) != str(value)):
            raise ValueError(f"native receipt input path is unsafe: {value}")
        if not path.is_relative_to(original_root):
            return path
        relative = path.relative_to(original_root)
        target = project / relative
        try:
            resolved = target.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"staged project input is absent: {relative}") from exc
        if (resolved != target or not resolved.is_relative_to(project)
                or not resolved.is_file() or target.is_symlink()):
            raise ValueError(f"staged project input is unsafe: {relative}")
        return resolved

    return resolve


def mapped_receipt_state_files(project: Path, folder: Path,
                               receipt: dict, state: dict | None = None
                               ) -> tuple[str, ...]:
    """Map producer state files into the current project, with proof.

    Native receipts retain the absolute paths from the producer's project.
    A relocated backend arm may use the corresponding current-project path
    only when the receipt's lexical namespace resolves to that path and the
    current bytes match the recorded digest.  Foreign, traversal, missing,
    symlinked, ambiguous, or digest-mismatched entries are rejected instead
    of being silently dropped or read from an ambient absolute path.
    """
    project = Path(project).resolve(strict=True)
    folder = Path(folder).resolve(strict=True)
    if not folder.is_relative_to((project / "phase3/librelane").resolve()):
        raise ValueError("native receipt producer folder is outside project")
    state = state if isinstance(state, dict) else json.loads(
        (folder / "state_out.json").read_text())
    inp = receipt.get("input") if isinstance(receipt, dict) else None
    state_files = inp.get("state_files") if isinstance(inp, dict) else None
    if not isinstance(state_files, dict):
        raise ValueError("native receipt has malformed state_files")
    resolver = _project_path_resolver(project, folder, state)
    mapped: list[str] = []
    seen: set[str] = set()
    for raw, recorded in state_files.items():
        if not isinstance(raw, str) or not isinstance(recorded, str):
            raise ValueError("native receipt has malformed state_files entry")
        path = Path(raw)
        if (not path.is_absolute() or ".." in path.parts
                or str(path) != raw):
            raise ValueError(f"native receipt state path is unsafe: {raw}")
        target = resolver(raw)
        if (not target.is_absolute() or not target.is_relative_to(project)
                or target.is_symlink() or not target.is_file()):
            raise ValueError(f"native receipt state path is foreign: {raw}")
        rel = target.relative_to(project).as_posix()
        if rel in seen:
            raise ValueError(f"native receipt state path maps ambiguously: {raw}")
        if _sha(target) != recorded:
            raise ValueError(f"native receipt state digest mismatch: {raw}")
        seen.add(rel)
        mapped.append(rel)
    return tuple(mapped)


def _native_synthesis(project: Path, folder: Path, top: str, *, path_resolver=None) -> tuple[Path, dict, dict]:
    """Verify the existing run_chain receipt against its consumed/output bytes."""
    import librelane_contract as LC
    from _rtl_include_hub import silicon_rtl_selection

    folder = folder.resolve()
    if not folder.is_relative_to((project / 'phase3/librelane').resolve()):
        raise ValueError('tool folder is outside the production LibreLane directory')
    receipt = json.loads((folder / 'vibeic_receipt.json').read_text())
    cfg = json.loads((folder / 'config.json').read_text())
    state = json.loads((folder / 'state_out.json').read_text())
    inp = receipt['input']
    if inp['step'] != 'Yosys.Synthesis' or cfg['meta']['step'] != inp['step']:
        raise ValueError('not a Yosys.Synthesis producer')
    resolve_path = path_resolver or (lambda value: Path(value))
    raw = resolve_path(state['nl']).resolve()
    if not raw.is_relative_to(folder):
        raise ValueError('native netlist is outside its producer folder')
    for rel in ('state_out.json', 'config.json', 'reports/stat.json', str(raw.relative_to(folder))):
        if receipt['sha256'].get(rel) != _sha(folder / rel):
            raise ValueError(f'native receipt mismatch: {rel}')
    if inp['config'] != _sha(project / 'phase3/librelane/synthesis_resolved.json'):
        raise ValueError('producer consumed a different resolved config')
    declared = LC.synthesis_levers(project)
    if (('synthesis_levers' in inp) != (declared is not None)
            or inp.get('synthesis_levers') != declared):
        raise ValueError('native producer synthesis declaration differs from current source authority')
    expected_strategy = (declared or {}).get('SYNTH_STRATEGY', 'AREA 0')
    # Older default-only receipts may omit the field. An explicit declaration
    # must be carried by the actual native config, not inferred by this reader.
    strategy = cfg.get('SYNTH_STRATEGY', 'AREA 0' if declared is None else None)
    if strategy != expected_strategy:
        raise ValueError('producer synthesis strategy differs from current declaration/default')
    pdk, _ = LC.phase2_pdk(project, selected=cfg.get('PDK'))
    if cfg.get('PDK') != pdk or cfg.get('DESIGN_NAME') != top:
        raise ValueError('producer PDK/top differs from declared input')
    rtl = silicon_rtl_selection(project / 'phase2/stage1/rtl')
    paths = [str(p.resolve()) for p in rtl]
    declared_rtl = [str(resolve_path(path).resolve()) for path in cfg.get('VERILOG_FILES', ())]
    if not paths or declared_rtl != paths:
        raise ValueError('producer RTL file set differs from current synthesis input')
    for declared, path in zip(cfg.get('VERILOG_FILES', ()), rtl):
        if inp['config_files'].get(declared) != _sha(path):
            raise ValueError('producer consumed stale RTL bytes')
    mounts = _receipt_pdk_mounts(folder, receipt)
    # Rehash the producer's recorded population. A later reader namespace may
    # expose additional image files; those were not part of this receipt.
    expected_config_files = {}
    external_config_files = []
    for recorded_path in inp['config_files']:
        source = resolve_path(recorded_path)
        if source.is_relative_to(project.resolve()):
            # Preserve the producer's receipt key, but read only the frozen
            # staged bytes.  Rehashing the original absolute path silently
            # reintroduced an ambient-project dependency after relocation.
            expected_config_files[recorded_path] = _sha(source)
        else:
            external_config_files.append(recorded_path)
    expected_config_files.update(LC.config_file_hashes(
        {'files': external_config_files}, mounts))
    if inp.get('config_files') != expected_config_files:
        raise ValueError('producer consumed stale or incomplete config material')
    for path, recorded in inp['state_files'].items():
        resolved = resolve_path(path)
        if not resolved.is_absolute() or not resolved.is_relative_to(project):
            raise ValueError(f'producer state_files contains a foreign path: {path}')
        if recorded != _sha(resolved):
            raise ValueError(f'producer consumed stale state_files: {path}')
    stat = json.loads((folder / 'reports/stat.json').read_text())
    modules = stat.get('modules')
    module = (modules.get('\\' + top) or modules.get(top)) if isinstance(modules, dict) else None
    if not module or len(modules) != 1 or module.get('num_submodules') != 0:
        raise ValueError('native stat does not establish a flattened top')
    metrics = state.get('metrics', {})
    if metrics.get('design__instance_unmapped__count') != 0 or metrics.get('synthesis__check_error__count') != 0:
        raise ValueError('native synthesis checks did not measure zero errors')
    critical_synthesis_checks(folder, cfg)
    report = check(raw, cfg)
    if report['verdict'] != 'PASS':
        raise ValueError('; '.join(report['findings']))
    return raw, cfg, report


def publish_handoff(project: Path, folder: Path, mapped: Path, top: str) -> dict:
    """Publish exactly the checked native bytes into the existing handoff contract."""
    raw, _, _ = _native_synthesis(project, folder, top,
                                  path_resolver=_project_path_resolver(
                                      project, folder,
                                      json.loads((folder / 'state_out.json').read_text())))
    if mapped.read_bytes() != raw.read_bytes():
        raise ValueError('mapped copy differs from native output')
    canonical = mapped.parent / 'netlist.v'
    write_bytes(canonical, raw.read_bytes())
    sidecar = mapped.parent / 'synth_inputs.json'
    doc = json.loads(sidecar.read_text())
    doc['librelane_synthesis'] = {
        'schema': 'vibe-ic/librelane-synthesis-handoff/1', 'top': top,
        'folder': str(folder.relative_to(project)),
        'mapped': str(mapped.relative_to(project)),
        'netlist_sha256': _sha(raw),
        'receipt_sha256': _sha(folder / 'vibeic_receipt.json')}
    declared = json.loads((folder / 'vibeic_receipt.json').read_text())['input'].get('synthesis_levers')
    if declared is not None:
        doc['librelane_synthesis']['synthesis_levers'] = declared
    write_json(sidecar, doc)
    return doc['librelane_synthesis']


def bound_handoff(project: Path) -> Optional[dict]:
    """Step14's existing gates and PnR/LEC judge the same current tool product.

    None retains the direct producer's existing recipe gate. A tool-selected
    project never falls back to an older .ys script or generic netlist.
    """
    import librelane_contract as LC
    sidecar = project / 'phase2/stage2/synth/synth_inputs.json'
    try:
        doc = json.loads(sidecar.read_text()) if sidecar.is_file() else {}
        binding = doc.get('librelane_synthesis')
        if LC.selected_mode(project, '9') != 'librelane' and binding is None:
            return None
        if not isinstance(binding, dict) or binding.get('schema') != 'vibe-ic/librelane-synthesis-handoff/1':
            raise ValueError('current LibreLane synthesis handoff is absent')
        declared = LC.synthesis_levers(project)
        if (('synthesis_levers' in binding) != (declared is not None)
                or binding.get('synthesis_levers') != declared):
            raise ValueError('published synthesis declaration differs from current source authority')
        from l_doc_consumer_contract import l_doc_fields
        l9 = l_doc_fields(LC._ldoc(project / 'phase1/generated_docs', 'L9_INTEGRATION_SPEC.json'))
        declared_top = l9.get('top_module')
        current_top = declared_top.strip() if isinstance(declared_top, str) else None
        if not current_top or current_top != binding['top']:
            raise ValueError(f'current L9 subject {declared_top!r} differs from '
                             f'published synthesis top {binding["top"]!r}')
        folder = project / binding['folder']
        mapped = project / binding['mapped']
        expected = project / 'phase2/stage2/synth' / (binding['top'] + '_synth.v')
        if mapped.resolve() != expected.resolve() or doc.get('netlist') != mapped.name:
            raise ValueError('handoff does not name the production mapped netlist')
        state = json.loads((folder / 'state_out.json').read_text())
        raw, config, report = _native_synthesis(
            project, folder, binding['top'],
            path_resolver=_project_path_resolver(project, folder, state))
        if binding['receipt_sha256'] != _sha(folder / 'vibeic_receipt.json'):
            raise ValueError('native producer receipt changed after publication')
        import librelane_postmap as postmap
        parent = raw
        raw, child_folder = postmap.selected(project, binding, parent, folder)
        if child_folder:
            report = check(raw, config)
            if report["verdict"] != "PASS":
                raise ValueError('; '.join(report['findings']))
        canonical = mapped.parent / 'netlist.v'
        if any(_sha(p) != binding['netlist_sha256'] for p in (raw, mapped, canonical)):
            raise ValueError('native/mapped/canonical handoff bytes disagree')
        report.update({'producer': ('LibreLane.Yosys.Synthesis -> Vibeic.PostMapRepair'
                                    if child_folder else 'LibreLane.Yosys.Synthesis'),
                       'native': str(raw), 'parent': str(parent),
                       'canonical': str(canonical), 'mapped': str(mapped),
                       'netlist_sha256': binding['netlist_sha256'],
                       'flattened': True, 'reason_class': 'tool_handoff_verified'})
        return report
    except (LC.Refusal, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {'program': 'synth_handoff_netlist_check', 'step': '14',
                'verdict': 'FAIL', 'reason_class': 'tool_handoff_invalid',
                'findings': [str(exc)]}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--netlist", type=Path, required=True)
    parser.add_argument("--resolved", type=Path, required=True,
                        help="the synthesis step's resolved config (config.json)")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    try:
        resolved = json.loads(args.resolved.read_text())
        report = check(args.netlist, resolved)
    except (OSError, ValueError) as exc:
        report = {"program": "synth_handoff_netlist_check", "verdict": "NOT_MEASURED",
                  "findings": [str(exc)]}
    if args.json:
        write_json(args.json, report)
    print(f"[{report['verdict']}] " + "; ".join(report["findings"]))
    return {"PASS": 0, "FAIL": 1}.get(report["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
