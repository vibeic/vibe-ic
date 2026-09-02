#!/usr/bin/env python3
"""Prove that post-translation RTL remains the reviewed RTL bundle.

This Program is benchmark-agnostic.  It receives frozen reviewed RTL plus the
exact final path-to-bytes map that an I/O adapter intends to publish.  It does
not know a benchmark name, case ID, scorer, harness, golden, or oracle.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List

import _hdl_code_text

SCHEMA = "vibeic.rtl_final_bundle_integrity.v1"

_MODULE_BLOCK_RE = re.compile(
    r"\bmodule\s+([A-Za-z_]\w*)\b[\s\S]*?\bendmodule\b",
    re.MULTILINE)


def module_blocks(text: str) -> List[tuple[str, str]]:
    """Return complete module blocks while preserving their reviewed bytes."""
    scanned = _hdl_code_text.strip_hdl_comments_and_strings(text)
    return [(match.group(1), text[match.start():match.end()])
            for match in _MODULE_BLOCK_RE.finditer(scanned)]


def module_dependencies(body: str, module_names: set[str]) -> set[str]:
    """Known reviewed modules instantiated by one module block."""
    scanned = _hdl_code_text.strip_hdl_comments_and_strings(body)
    dependencies = set()
    for name in module_names:
        instance = re.compile(
            rf"\b{re.escape(name)}\s*"
            rf"(?:#\s*\([^;]*?\)\s*)?"
            rf"[A-Za-z_]\w*\s*\(",
            re.MULTILINE)
        if instance.search(scanned):
            dependencies.add(name)
    return dependencies


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _file_records(files: Dict[str, str]) -> List[Dict[str, Any]]:
    return [{
        "path": path,
        "sha256": _sha256(text),
        "modules": [name for name, _body in module_blocks(text)],
    } for path, text in files.items()]


def _module_map(texts: Iterable[str]) -> tuple[Dict[str, str], List[str]]:
    modules: Dict[str, str] = {}
    duplicates = set()
    for text in texts:
        for name, body in module_blocks(text):
            if name in modules:
                duplicates.add(name)
            modules[name] = body
    return modules, sorted(duplicates)


def check_final_bundle(reviewed_paths: Iterable[Path],
                       exported_files: Dict[str, str], *,
                       declared_top: str | None = None) -> Dict[str, Any]:
    """Return structured PASS/BLOCKED/NOT_MEASURED evidence.

    PASS requires the same module names and exact module bytes as the frozen
    reviewed candidate, no duplicate ownership, an optional prompt-derived top
    defined exactly once, and a successful compile of the exact output files.
    """
    reviewed = [Path(path) for path in reviewed_paths]
    reasons: List[str] = []
    if not reviewed or not all(path.is_file() for path in reviewed):
        reasons.append("reviewed RTL file set is absent")
        reviewed_texts = []
    else:
        reviewed_texts = [path.read_text(errors="replace") for path in reviewed]
    if not isinstance(exported_files, dict) or not exported_files:
        reasons.append("final RTL file map is absent")
        exported_files = {}
    elif any(not isinstance(path, str) or not isinstance(text, str)
             for path, text in exported_files.items()):
        reasons.append("final RTL file map must contain string paths and bytes")
        exported_files = {}

    reviewed_modules, reviewed_duplicates = _module_map(reviewed_texts)
    exported_modules, exported_duplicates = _module_map(exported_files.values())
    if reviewed_duplicates:
        reasons.append("reviewed RTL has duplicate module ownership: "
                       + ", ".join(reviewed_duplicates))
    if exported_duplicates:
        reasons.append("final RTL has duplicate module ownership: "
                       + ", ".join(exported_duplicates))
    missing = sorted(set(reviewed_modules) - set(exported_modules))
    added = sorted(set(exported_modules) - set(reviewed_modules))
    changed = sorted(
        name for name in set(reviewed_modules) & set(exported_modules)
        if _sha256(reviewed_modules[name]) != _sha256(exported_modules[name]))
    if missing:
        reasons.append("reviewed module(s) missing from final RTL: "
                       + ", ".join(missing))
    if added:
        reasons.append("unreviewed module(s) added to final RTL: "
                       + ", ".join(added))
    if changed:
        reasons.append("reviewed module byte(s) changed in final RTL: "
                       + ", ".join(changed))
    if declared_top:
        top_count = sum(
            1 for text in exported_files.values()
            for name, _body in module_blocks(text) if name == declared_top)
        if top_count != 1:
            reasons.append(
                f"prompt-derived declared top {declared_top!r} occurs "
                f"{top_count} times in final RTL")

    compiler = shutil.which("iverilog")
    compile_evidence: Dict[str, Any]
    if not compiler:
        compile_evidence = {
            "status": "NOT_MEASURED",
            "reason": "iverilog is unavailable; final RTL bytes were not compiled",
        }
    else:
        with tempfile.TemporaryDirectory(
                prefix="vibeic_final_bundle_") as raw_root:
            root = Path(raw_root)
            compile_paths = []
            include_dirs = {root}
            for output_path, text in exported_files.items():
                relative = Path(output_path)
                if relative.is_absolute() or ".." in relative.parts:
                    reasons.append(f"unsafe final RTL path {output_path!r}")
                    continue
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(text)
                include_dirs.add(destination.parent)
                if destination.suffix.lower() in {".v", ".sv"}:
                    compile_paths.append(destination)
            if not compile_paths:
                reasons.append("final bundle contains no Verilog source")
                compile_evidence = {
                    "status": "BLOCKED", "reason": "no compile input"}
            else:
                command = [compiler, "-g2012", "-tnull"]
                if declared_top:
                    command.extend(["-s", declared_top])
                for include_dir in sorted(include_dirs, key=str):
                    command.extend(["-I", str(include_dir)])
                command.extend(str(path) for path in compile_paths)
                try:
                    proc = subprocess.run(
                        command, cwd=root, capture_output=True, text=True,
                        timeout=30, check=False)
                except subprocess.TimeoutExpired:
                    compile_evidence = {
                        "status": "NOT_MEASURED",
                        "reason": "final RTL compile exceeded 30 seconds",
                        "tool": compiler,
                    }
                else:
                    diagnostics = (proc.stderr or proc.stdout or "").strip()
                    diagnostics = diagnostics.replace(
                        str(root), "<final_bundle>")
                    compile_evidence = {
                        "status": ("PASS" if proc.returncode == 0
                                   else "BLOCKED"),
                        "reason": ("" if proc.returncode == 0
                                   else diagnostics[:2000]),
                        "tool": compiler,
                        "returncode": proc.returncode,
                    }
                    if proc.returncode != 0:
                        reasons.append("exact final RTL compile failed: "
                                       + diagnostics[:2000])

    if reasons:
        status = "BLOCKED"
    elif compile_evidence.get("status") == "NOT_MEASURED":
        status = "NOT_MEASURED"
    elif compile_evidence.get("status") == "PASS":
        status = "PASS"
    else:
        status = "BLOCKED"
    return {
        "schema": SCHEMA,
        "status": status,
        "reasons": reasons,
        "declared_top": declared_top,
        "declared_top_source": ("prompt-derived Phase-1 declaration"
                                if declared_top else "NOT_DECLARED"),
        "reviewed_files": _file_records({str(path): text for path, text in
                                         zip(reviewed, reviewed_texts)}),
        "final_files": _file_records(exported_files),
        "reviewed_modules": sorted(reviewed_modules),
        "final_modules": sorted(exported_modules),
        "compile": compile_evidence,
    }
