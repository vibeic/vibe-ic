#!/usr/bin/env python3
"""Resolve the documented technology with LibreLane; revisions are observations."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import time


def _installed_revision(root: Path, pdk: str):
    tree = root / pdk
    for name in ("COMMIT", "SOURCES"):
        try:
            value = (tree / name).read_text().strip()
            if value:
                return value
        except OSError:
            pass
    try:
        return json.loads((tree / ".config/nodeinfo.json").read_text()).get("commit")
    except (OSError, ValueError, AttributeError):
        return None


def _resolve(config_path: Path, pdk_root: Path, *, pdk: str, project: Path):
    from librelane.flows import Flow

    meta = json.loads(config_path.read_text()).get("meta", {})
    target = Flow.factory.get(meta.get("flow", "Classic"))
    if target is None:
        raise FileNotFoundError(f"Native flow unavailable: {meta.get('flow')}")
    if meta.get("substituting_steps"):
        target = target.Substitute(meta["substituting_steps"])
    return target(str(config_path), pdk=pdk, pdk_root=str(pdk_root),
                  design_dir=str(project)).config


def execute(project: Path, directory: Path) -> dict:
    project, directory = Path(project).resolve(), Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    started, reports, metrics = False, [], {}
    before = time.perf_counter()
    try:
        from flow_config import _load, _input_docs, _pdk_name
        docs = project / "phase1/generated_docs"
        l19 = _load(docs / "L19_CONSTRAINTS_PDK.json")
        pdk = l19.get("fields", {}).get("pdk_target") or l19.get("pdk_target")
        if not pdk:
            from parametric_spec_extractor import extract_pdk_target
            for text in _input_docs(project).values():
                target = extract_pdk_target(text)
                if target:
                    pdk = target["pdk"]
                    break
        if not pdk:
            return {"ran": False, "exit_code": None, "detail": "No PDK declared in design documents."}
        pdk = _pdk_name(pdk)
        import librelane_contract as native
        config_path = project / "phase3/librelane/config.json"
        if not config_path.exists():
            design = (_load(docs / "L9_INTEGRATION_SPEC.json").get("top_module")
                      or _load(docs / "L1_DATASHEET.json").get("ic_name"))
            settings, _ = native._declared_flow_settings(l19, pdk)
            config_path = directory / "technology.json"
            config_path.write_text(json.dumps({"meta": {"version": 2, "flow": "Classic"},
                "DESIGN_NAME": design, "PDK": pdk, "VERILOG_FILES": [], **settings}, default=str) + "\n")
        root = os.environ.get("VIBEIC_LIBRELANE_PDK_ROOT") or os.environ.get("PDK_ROOT")
        if not root:
            return {"ran": False, "exit_code": None, "detail": "No installed PDK_ROOT for native technology resolution."}
        started = True
        selected = _resolve(config_path, Path(root), pdk=pdk, project=project)
        resolved = directory / "resolved.json"
        resolved.write_text(selected.dumps())
        reports = [str(config_path), str(resolved)]
        metrics = {"pdk": selected["PDK"], "standard_cell_library": selected["STD_CELL_LIBRARY"],
                   "default_corner": selected["DEFAULT_CORNER"]}
        try:
            revision = _installed_revision(Path(root), selected["PDK"])
            if revision:
                metrics["installed_pdk_revision"] = revision
        except (OSError, ValueError):
            pass
        for package in ("librelane", "ciel"):
            try:
                metrics[package + "_version"] = version(package)
            except PackageNotFoundError:
                pass
        return {"ran": True, "exit_code": 0, "metrics": metrics, "reports": reports,
                "tool_seconds": time.perf_counter() - before,
                "detail": "Native LibreLane configuration resolved; readable revision metadata is informational."}
    except (ImportError, FileNotFoundError) as exc:
        return {"ran": False, "exit_code": None, "detail": str(exc),
                "tool_seconds": time.perf_counter() - before}
    except Exception as exc:
        return {"ran": started, "exit_code": 1 if started else None, "detail": str(exc),
                "tool_seconds": time.perf_counter() - before}
