#!/usr/bin/env python3
"""Isolated pytest entry for the protected landing runtime.

Invoke this file with ``python3 -I``.  The isolated interpreter imports pytest
from the digest-pinned runner image, then loads the protected progress plugin
by exact path.  The subject cwd never participates in either import.  A
canonical identity record travels through the plugin's private semantic stream
so the parent can prove what actually executed, not merely what argv named.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from types import ModuleType
from typing import Sequence


IDENTITY_ENV = "VIBEIC_PYTEST_RUNTIME_IDENTITY"
PROGRESS_PLUGIN_NAME = "_vibeic_protected_pytest_progress"


class Refusal(RuntimeError):
    pass


def _raw_identity(path: Path, label: str) -> dict[str, object]:
    try:
        lexical = path.absolute()
        before = lexical.lstat()
        if (not stat.S_ISREG(before.st_mode) or lexical.is_symlink()
                or before.st_nlink != 1):
            raise Refusal(f"{label} is not a single-link regular file")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(lexical, flags)
        try:
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
            held = os.fstat(fd)
        finally:
            os.close(fd)
        after = lexical.lstat()
    except OSError as exc:
        raise Refusal(f"cannot raw-attest {label}: {exc}") from exc
    identity = lambda st: (st.st_dev, st.st_ino, st.st_mode, st.st_nlink,
                           st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    if identity(before) != identity(held) or identity(before) != identity(after):
        raise Refusal(f"{label} changed while raw-attested")
    return {
        "path": str(lexical.resolve(strict=True)),
        "sha256": digest.hexdigest(),
        "size": size,
    }


def _module_file(module: ModuleType, label: str) -> Path:
    value = getattr(module, "__file__", None)
    if not isinstance(value, str) or not value:
        raise Refusal(f"{label} has no file identity")
    return Path(value)


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return True


def _strip_progress_plugin(argv: Sequence[str]) -> list[str]:
    out: list[str] = []
    index = 0
    while index < len(argv):
        if argv[index] == "-p":
            if index + 1 >= len(argv):
                raise Refusal("pytest -p has no plugin name")
            name = argv[index + 1]
            if name == "_pytest_progress_plugin":
                index += 2
                continue
            if name != "no:cacheprovider":
                raise Refusal(f"unreviewed pytest plugin request: {name!r}")
        out.append(argv[index])
        index += 1
    return out


def run(argv: Sequence[str]) -> int:
    if not sys.flags.isolated or not sys.flags.ignore_environment:
        raise Refusal("trusted pytest entry requires python3 -I")
    programs = Path(__file__).resolve(strict=True).parent
    subject = Path.cwd().resolve(strict=True)
    if any(item in {"", "."} for item in sys.path):
        raise Refusal("isolated interpreter still exposes the subject cwd")

    import pytest  # type: ignore[import-not-found]  # image-owned dependency
    import _pytest  # type: ignore[import-not-found]
    import pluggy  # type: ignore[import-not-found]

    dependency_rows = []
    for name, module in (("pytest", pytest), ("_pytest", _pytest),
                         ("pluggy", pluggy)):
        module_path = _module_file(module, name).resolve(strict=True)
        if _under(module_path, subject) or _under(module_path, programs):
            raise Refusal(f"{name} resolved inside the subject checkout")
        dependency_rows.append({"name": name,
                                **_raw_identity(module_path, name)})

    plugin_path = programs / "_pytest_progress_plugin.py"
    plugin_identity = _raw_identity(plugin_path, "protected progress plugin")
    spec = importlib.util.spec_from_file_location(
        PROGRESS_PLUGIN_NAME, plugin_path)
    if spec is None or spec.loader is None:
        raise Refusal("protected progress plugin has no import loader")
    plugin = importlib.util.module_from_spec(spec)
    sys.modules[PROGRESS_PLUGIN_NAME] = plugin
    spec.loader.exec_module(plugin)

    identity = {
        "schema": 1,
        "python": _raw_identity(
            Path(sys.executable).resolve(strict=True), "python executable"),
        "entry": _raw_identity(Path(__file__), "trusted pytest entry"),
        "plugin": plugin_identity,
        "modules": dependency_rows,
    }
    os.environ[IDENTITY_ENV] = json.dumps(
        identity, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False)
    return int(pytest.main(_strip_progress_plugin(list(argv)), plugins=[plugin]))


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except (ImportError, OSError, Refusal, ValueError, TypeError) as exc:
        print(f"[NORECORD] trusted pytest entry: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
