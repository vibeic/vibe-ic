"""One-operation source snapshot for adapter registration.

The snapshot amortizes reads only during a single Ultra bootstrap. Before it
can be finalized, every consumed file is reread and checked against the exact
HEAD commit/tree and its initial bytes. It is never an execution-time authority.
"""
from __future__ import annotations

import ast
from collections import deque
from functools import lru_cache
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
from pathlib import Path
import subprocess


@lru_cache(maxsize=2048)
def python_import_syntax(content: str) -> tuple:
    """Share immutable import syntax by exact source bytes, never path state.

    Registration readers retain their own import grammars and resolve current
    files independently. Keep only import records, rather than entire ASTs or
    parent maps, so a bootstrap does not retain every parsed expression.
    """
    pending = deque([(ast.parse(content), False)])
    found = []
    while pending:
        node, optional_relative = pending.popleft()
        if isinstance(node, ast.Import):
            found.append(('import', 0, '', tuple(a.name for a in node.names), False))
        elif isinstance(node, ast.ImportFrom):
            found.append(('from', node.level, node.module or '',
                          tuple(a.name for a in node.names), optional_relative))
        elif (isinstance(node, ast.Call) and node.args and
              (getattr(node.func, 'attr', None) == 'import_module' or
               getattr(node.func, 'id', None) == '__import__') and
              isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            found.append(('dynamic', 0, node.args[0].value, (), False))
        if isinstance(node, ast.Try):
            optional_relative = optional_relative or any(
                handler.type is None or any(
                    isinstance(part, ast.Name) and part.id in
                    {'ImportError', 'ModuleNotFoundError', 'Exception', 'BaseException'}
                    for part in ast.walk(handler.type)) for handler in node.handlers)
        pending.extend((child, optional_relative) for child in ast.iter_child_nodes(node))
    return tuple(found)


_ACTIVE: ContextVar["SourceSnapshot | None"] = ContextVar(
    "execution_source_snapshot", default=None)


def active() -> "SourceSnapshot | None":
    return _ACTIVE.get()


@contextmanager
def using(snapshot: "SourceSnapshot"):
    token = _ACTIVE.set(snapshot)
    try:
        yield snapshot
    finally:
        _ACTIVE.reset(token)


class SourceSnapshot:
    def __init__(self, repo: Path, source_sha: str):
        self.repo = Path(repo).resolve()
        self.source_sha = source_sha
        self.stats = {"file_reads": 0, "final_reads": 0, "git_commands": 0,
                      "git_tree_reads": 0, "closure_misses": 0, "closure_hits": 0}
        self.commit = self._git_text("rev-parse", "--verify", f"{source_sha}^{{commit}}")
        self.tree = self._git_text("rev-parse", "--verify", f"{self.commit}^{{tree}}")
        head = self._git_text("rev-parse", "HEAD")
        if head != self.commit:
            raise RuntimeError("SOURCE_AUTHORITY_STALE")
        self._bytes: dict[Path, bytes] = {}
        self._spellings: set[Path] = set()
        self._git_blobs: dict[str, str] | None = None
        self._closures: dict[object, frozenset[Path]] = {}
        self._values: dict[object, object] = {}
        self.finalized = False

    def _git_text(self, *args: str) -> str:
        self.stats["git_commands"] += 1
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True, timeout=10).stdout.strip()

    def read_bytes(self, path: Path) -> bytes:
        spelling = Path(path).absolute()
        if spelling.is_symlink() or not spelling.is_file():
            raise RuntimeError(f"SOURCE_AUTHORITY_UNAVAILABLE: {spelling}")
        self._spellings.add(spelling)
        path = spelling.resolve()
        if path not in self._bytes:
            self._bytes[path] = path.read_bytes()
            self.stats["file_reads"] += 1
        return self._bytes[path]

    def read_text(self, path: Path) -> str:
        return self.read_bytes(path).decode()

    def digest(self, path: Path) -> str:
        return hashlib.sha256(self.read_bytes(path)).hexdigest()

    def closure_get(self, key):
        value = self._closures.get(key)
        if value is None:
            self.stats["closure_misses"] += 1
            return None
        self.stats["closure_hits"] += 1
        return set(value)

    def closure_put(self, key, paths):
        self._closures[key] = frozenset(Path(p).resolve() for p in paths)

    def value_get(self, key):
        return self._values.get(key)

    def value_put(self, key, value):
        self._values[key] = value

    def git_blobs(self, commit: str, paths) -> dict[str, str]:
        if commit != self.commit:
            raise RuntimeError("SOURCE_AUTHORITY_STALE")
        blobs = self._tree_blobs()
        result = {}
        for path in paths:
            path = Path(path).resolve()
            if not path.is_relative_to(self.repo):
                continue
            relative = path.relative_to(self.repo).as_posix()
            if relative not in blobs:
                raise RuntimeError(f"SOURCE_AUTHORITY_UNAVAILABLE: {relative}")
            result[str(path)] = blobs[relative]
        return result

    def verify_tracked(self, path: Path) -> None:
        path = Path(path).resolve()
        data = self.read_bytes(path)
        if not path.is_relative_to(self.repo):
            return
        relative = path.relative_to(self.repo).as_posix()
        if self._tree_blobs().get(relative) != self._git_blob(data):
            raise RuntimeError(f"SOURCE_AUTHORITY_DIRTY: {path}")

    def _tree_blobs(self) -> dict[str, str]:
        if self._git_blobs is None:
            self.stats["git_commands"] += 1
            raw = subprocess.run(["git", "-C", str(self.repo), "ls-tree", "-r", "-z",
                                  self.commit], check=True, capture_output=True,
                                 timeout=20).stdout
            self.stats["git_tree_reads"] += 1
            blobs = {}
            for record in raw.split(b"\0"):
                if not record:
                    continue
                header, name = record.split(b"\t", 1)
                mode, kind, oid = header.decode().split()
                if kind == "blob" and mode in ("100644", "100755"):
                    blobs[name.decode()] = oid
            self._git_blobs = blobs
        return self._git_blobs

    @staticmethod
    def _git_blob(data: bytes) -> str:
        return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()

    def finalize(self) -> None:
        if self.finalized:
            return
        if (self._git_text("rev-parse", "HEAD") != self.commit or
                self._git_text("rev-parse", "HEAD^{tree}") != self.tree):
            raise RuntimeError("SOURCE_AUTHORITY_STALE")
        blobs = self._tree_blobs()
        for spelling in self._spellings:
            if spelling.is_symlink() or not spelling.is_file():
                raise RuntimeError(f"SOURCE_AUTHORITY_UNAVAILABLE: {spelling}")
        for path, original in self._bytes.items():
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(f"SOURCE_AUTHORITY_UNAVAILABLE: {path}")
            current = path.read_bytes()
            self.stats["final_reads"] += 1
            if current != original:
                raise RuntimeError(f"SOURCE_AUTHORITY_DIRTY: {path}")
            if path.is_relative_to(self.repo):
                relative = path.relative_to(self.repo).as_posix()
                if blobs.get(relative) != self._git_blob(current):
                    raise RuntimeError(f"SOURCE_AUTHORITY_DIRTY: {path}")
        self.finalized = True
