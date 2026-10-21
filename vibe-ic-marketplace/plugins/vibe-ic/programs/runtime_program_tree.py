#!/usr/bin/env python3
"""Retain one immutable plugin program tree for a long runner invocation.

Plugin installers are allowed to replace their cache while an IC run is
active.  A runner must therefore stop resolving later children from that live
cache.  This module copies the runtime-relevant plugin files under the project,
binds every byte in a manifest, and verifies each plugin child immediately
before launch.  Descendant runners inherit the retained tree through the
environment; a separately started run does not.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


SCHEMA = "vibeic_runtime_program_tree/1"
ENV_ROOT = "VIBEIC_RETAINED_PLUGIN_ROOT"
ENV_MANIFEST = "VIBEIC_RETAINED_PLUGIN_MANIFEST"
_EXCLUDED_DIRS = frozenset({".git", ".pytest_cache", "__pycache__",
                            "node_modules", "tests", "test"})


class RuntimeTreeError(RuntimeError):
    """The retained program tree is missing, changed, or inconsistent."""


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _selected_files(plugin_root: Path) -> Iterable[Path]:
    for root, dirs, files in os.walk(plugin_root):
        dirs[:] = sorted(d for d in dirs if d not in _EXCLUDED_DIRS)
        root_path = Path(root)
        for name in sorted(files):
            path = root_path / name
            if path.is_symlink():
                raise RuntimeTreeError(f"RUNTIME_SOURCE_SYMLINK: {path}")
            if path.is_file():
                yield path


def _source_commit(plugin_root: Path) -> str | None:
    for parent in (plugin_root, *plugin_root.parents):
        if not (parent / ".git").exists():
            continue
        try:
            return subprocess.check_output(
                ["git", "-C", str(parent), "rev-parse", "HEAD"],
                text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    return None


def _plugin_version(plugin_root: Path) -> str:
    path = plugin_root / ".claude-plugin" / "plugin.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, TypeError):
        value = None
    return str(value or "unknown")


def _tree_hash(files: Mapping[str, str]) -> str:
    payload = json.dumps(dict(sorted(files.items())), separators=(",", ":"),
                         ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


@dataclass
class RuntimeProgramTree:
    plugin_root: Path
    programs_dir: Path
    manifest_path: Path
    launch_path: Path
    source_root: Path
    manifest: dict

    @property
    def tree_sha256(self) -> str:
        return str(self.manifest["source_tree_sha256"])

    def verify_tree(self) -> None:
        expected = self.manifest.get("files")
        if not isinstance(expected, dict) or not expected:
            raise RuntimeTreeError("RUNTIME_SOURCE_MANIFEST_EMPTY")
        observed = {}
        for rel, digest in expected.items():
            path = self.plugin_root / rel
            if path.is_symlink() or not path.is_file():
                raise RuntimeTreeError(f"RUNTIME_SOURCE_MISSING: {rel}")
            actual = _digest(path)
            if actual != digest:
                raise RuntimeTreeError(
                    f"RUNTIME_SOURCE_CHANGED: {rel}: {actual} != {digest}")
            observed[rel] = actual
        extras = {
            str(path.relative_to(self.plugin_root))
            for path in _selected_files(self.plugin_root)
        } - set(expected)
        if extras:
            raise RuntimeTreeError(
                "RUNTIME_SOURCE_UNMANIFESTED: " + ", ".join(sorted(extras)[:8]))
        if _tree_hash(observed) != self.tree_sha256:
            raise RuntimeTreeError("RUNTIME_SOURCE_TREE_HASH_MISMATCH")

    def verify_child(self, path: Path) -> str:
        try:
            rel = str(path.resolve().relative_to(self.plugin_root.resolve()))
        except (OSError, ValueError):
            raise RuntimeTreeError(f"RUNTIME_CHILD_OUTSIDE_RETAINED_TREE: {path}")
        expected = self.manifest["files"].get(rel)
        if not isinstance(expected, str):
            raise RuntimeTreeError(f"RUNTIME_CHILD_UNMANIFESTED: {rel}")
        target = self.plugin_root / rel
        if target.is_symlink() or not target.is_file():
            raise RuntimeTreeError(f"RUNTIME_CHILD_MISSING: {rel}")
        actual = _digest(target)
        if actual != expected:
            raise RuntimeTreeError(
                f"RUNTIME_CHILD_CHANGED: {rel}: {actual} != {expected}")
        self._record_launch(rel, actual)
        return actual

    def _record_launch(self, rel: str, digest: str) -> None:
        try:
            current = json.loads(self.launch_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            current = {"schema": "vibeic_runtime_program_launches/1",
                       "source_tree_sha256": self.tree_sha256,
                       "retained_plugin_root": str(self.plugin_root),
                       "children": {}}
        children = current.setdefault("children", {})
        row = children.setdefault(rel, {"sha256": digest, "launch_count": 0})
        if row.get("sha256") != digest:
            raise RuntimeTreeError(f"RUNTIME_CHILD_RECEIPT_CONFLICT: {rel}")
        row["launch_count"] = int(row.get("launch_count", 0)) + 1
        row["last_verified_ns"] = time.time_ns()
        _atomic_json(self.launch_path, current)

    def verify_command(self, command: Sequence[object] | str) -> None:
        values = ([command] if isinstance(command, str)
                  else [os.fspath(value) if isinstance(value, os.PathLike)
                        else str(value) for value in command])
        retained = str(self.plugin_root.resolve())
        source = str(self.source_root.resolve())
        checked = set()
        for value in values:
            if source != retained and source in value:
                raise RuntimeTreeError(
                    f"LIVE_PLUGIN_PATH_AFTER_RETENTION: {value}")
            # Normal argv carries the child as one absolute argument.  Shell
            # commands may carry it inside a script; verify every manifested
            # absolute path mentioned there.
            for rel in self.manifest["files"]:
                absolute = str(self.plugin_root / rel)
                if absolute in value and rel not in checked:
                    self.verify_child(self.plugin_root / rel)
                    checked.add(rel)

    def receipt(self) -> dict:
        return {
            "schema": SCHEMA,
            "plugin_version": self.manifest["plugin_version"],
            "source_commit": self.manifest.get("source_commit"),
            "source_tree_sha256": self.tree_sha256,
            "retained_plugin_root": str(self.plugin_root),
            "retained_programs_dir": str(self.programs_dir),
            "manifest": str(self.manifest_path),
            "launches": str(self.launch_path),
            "file_count": len(self.manifest["files"]),
        }


def _load_retained(manifest_path: Path) -> RuntimeProgramTree:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeTreeError(f"RUNTIME_SOURCE_MANIFEST_UNREADABLE: {exc}")
    if manifest.get("schema") != SCHEMA:
        raise RuntimeTreeError("RUNTIME_SOURCE_MANIFEST_SCHEMA")
    plugin_root = Path(manifest.get("retained_plugin_root", ""))
    source_root = Path(manifest.get("source_plugin_root", ""))
    tree = RuntimeProgramTree(
        plugin_root=plugin_root,
        programs_dir=plugin_root / "programs",
        manifest_path=manifest_path,
        launch_path=manifest_path.parent / "launches.json",
        source_root=source_root,
        manifest=manifest)
    tree.verify_tree()
    return tree


def retain(project: Path, source_programs: Path) -> RuntimeProgramTree:
    """Return the invocation's retained tree, creating it when necessary."""
    inherited = os.environ.get(ENV_MANIFEST)
    if inherited:
        tree = _load_retained(Path(inherited))
        if os.environ.get(ENV_ROOT) != str(tree.plugin_root):
            raise RuntimeTreeError("RUNTIME_SOURCE_ENVIRONMENT_MISMATCH")
        return tree

    source_programs = Path(source_programs).resolve()
    source_root = source_programs.parent
    files = {
        str(path.relative_to(source_root)): _digest(path)
        for path in _selected_files(source_root)
    }
    if not files:
        raise RuntimeTreeError("RUNTIME_SOURCE_EMPTY")
    tree_sha = _tree_hash(files)
    base = Path(project).resolve() / ".vibeic" / "runtime-program-trees"
    target = base / tree_sha
    manifest_path = target / "manifest.json"
    if target.exists():
        tree = _load_retained(manifest_path)
        if tree.tree_sha256 != tree_sha:
            raise RuntimeTreeError("RUNTIME_SOURCE_REUSE_HASH_MISMATCH")
    else:
        base.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f".{tree_sha[:12]}.", dir=str(base)))
        try:
            retained_root = stage / "plugin"
            for rel in sorted(files):
                source = source_root / rel
                destination = retained_root / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                if _digest(destination) != files[rel]:
                    raise RuntimeTreeError(f"RUNTIME_SOURCE_COPY_CHANGED: {rel}")
            manifest = {
                "schema": SCHEMA,
                "plugin_version": _plugin_version(source_root),
                "source_commit": _source_commit(source_root),
                "source_plugin_root": str(source_root),
                "source_tree_sha256": tree_sha,
                "retained_plugin_root": str(target / "plugin"),
                "files": files,
            }
            _atomic_json(stage / "manifest.json", manifest)
            try:
                os.replace(stage, target)
            except OSError:
                # Another invocation may have published the identical
                # content-addressed tree after our existence check.  Reuse
                # that tree only when it really exists; preserve every other
                # filesystem error.
                if not target.is_dir():
                    raise
                shutil.rmtree(stage)
            tree = _load_retained(manifest_path)
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    os.environ[ENV_ROOT] = str(tree.plugin_root)
    os.environ[ENV_MANIFEST] = str(tree.manifest_path)
    receipt = Path(project).resolve() / "reports" / "orchestrator" / "runtime_program_tree.json"
    _atomic_json(receipt, tree.receipt())
    return tree


def activate(project: Path, source_programs: Path,
             runner_file: Path) -> RuntimeProgramTree:
    """Retain the tree and put its flat programs directory first on sys.path."""
    tree = retain(project, source_programs)
    # The retained tree is immutable invocation source.  Without both forms of
    # this guard, imports in this interpreter and ordinary descendant Python
    # processes create __pycache__ below the project-owned retained tree.  That
    # is an unauthorized source-tree mutation and also self-invalidates the
    # Phase-1 RTL transaction that the retained child is serving.
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    retained_runner = tree.programs_dir / Path(runner_file).name
    tree.verify_child(retained_runner)
    retained = str(tree.programs_dir)
    sys.path[:] = [entry for entry in sys.path
                   if str(entry) != str(Path(source_programs))]
    sys.path.insert(0, retained)
    return tree
