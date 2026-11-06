"""One Vibe-IC temporary root, with execution-owned allocation and cleanup."""
from __future__ import annotations

import argparse
import atexit
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile as _stdlib
import time

_owned_tmp = set()
_owned_runs = {}
_outputs = set()
_ENV_KEYS = ("VIBEIC_TMP", "VIBEIC_EXEC_TMP", "VIBEIC_RUN_DIR", "TMPDIR",
             "XDG_CACHE_HOME", "MPLCONFIGDIR", "npm_config_cache", "PIP_CACHE_DIR",
             "PYTHONDONTWRITEBYTECODE")


def root() -> Path:
    return Path(os.environ.get("VIBEIC_TMP") or Path.home() / "vibe-ic-temp").expanduser().absolute()


def _allocate_tmp(owner_pid=None):
    parent = root() / "tmp"
    parent.mkdir(parents=True, exist_ok=True)
    prefix = datetime.now().strftime("%Y%m%d-%H%M") + f"-p{owner_pid or os.getpid()}-"
    path = Path(_stdlib.mkdtemp(prefix=prefix, dir=parent))
    _owned_tmp.add(path)
    return path


def scratch() -> Path:
    value = os.environ.get("VIBEIC_EXEC_TMP")
    if value:
        path = Path(value)
        if path.is_dir() and path.parent.resolve() == (root() / "tmp").resolve():
            return path
    path = _allocate_tmp()
    os.environ["VIBEIC_EXEC_TMP"] = str(path)
    return path


def configure() -> dict[str, str]:
    path = scratch()
    os.environ.update(VIBEIC_TMP=str(root()), TMPDIR=str(path),
                      XDG_CACHE_HOME=str(path / "cache"), MPLCONFIGDIR=str(path / "matplotlib"),
                      npm_config_cache=str(path / "npm"), PIP_CACHE_DIR=str(path / "pip"),
                      PYTHONDONTWRITEBYTECODE="1")
    _stdlib.tempdir = str(path)
    sys.dont_write_bytecode = True
    return {key: os.environ[key] for key in _ENV_KEYS if key in os.environ}


def new_run(who, what, *, keep=False, owner_pid=None) -> Path:
    slug = lambda value: re.sub(r"[^A-Za-z0-9_-]+", "-", str(value)).strip("-_") or "run"
    parent = root() / "runs"
    parent.mkdir(parents=True, exist_ok=True)
    keep = keep or os.environ.get("VIBEIC_KEEP_TEMP") == "1"
    prefix = datetime.now().strftime("%Y%m%d-%H%M") + f"-{slug(who)}-{slug(what)}-p{owner_pid or os.getpid()}-"
    prefix += "keep-" if keep else ""
    path = Path(_stdlib.mkdtemp(prefix=prefix, dir=parent))
    _owned_runs[path] = keep
    return path


def start_run(who, what, *, keep=False) -> Path:
    path = new_run(who, what, keep=keep)
    os.environ["VIBEIC_RUN_DIR"] = str(path)
    return path


def current_run(who="vibeic", what="execution") -> Path:
    value = os.environ.get("VIBEIC_RUN_DIR")
    if value:
        path = Path(value)
        if path.is_dir() and path.parent.resolve() == (root() / "runs").resolve():
            return path
    return start_run(who, what)


def _directory(directory=None):
    configure()
    run = os.environ.get("VIBEIC_RUN_DIR")
    parents = [scratch()]
    if run and Path(run).parent.resolve() == (root() / "runs").resolve():
        parents.append(Path(run))
    if directory is not None and any(Path(directory).absolute().resolve().is_relative_to(parent.resolve()) for parent in parents):
        Path(directory).mkdir(parents=True, exist_ok=True)
        return directory
    return scratch()


def gettempdir():
    configure()
    return str(scratch())


def mkdtemp(suffix=None, prefix=None, dir=None):
    return _stdlib.mkdtemp(suffix=suffix, prefix=prefix, dir=_directory(dir))


def mkstemp(suffix=None, prefix=None, dir=None, text=False):
    return _stdlib.mkstemp(suffix=suffix, prefix=prefix, dir=_directory(dir), text=text)


class TemporaryDirectory(_stdlib.TemporaryDirectory):
    def __init__(self, suffix=None, prefix=None, dir=None, **kwargs):
        super().__init__(suffix=suffix, prefix=prefix, dir=_directory(dir), **kwargs)


def NamedTemporaryFile(mode="w+b", buffering=-1, encoding=None, newline=None,
                       suffix=None, prefix=None, dir=None, delete=True, **kwargs):
    file = _stdlib.NamedTemporaryFile(mode, buffering, encoding, newline, suffix, prefix,
                                     _directory(dir), delete, **kwargs)
    if not delete:
        _outputs.add(Path(file.name))
    return file


def TemporaryFile(mode="w+b", buffering=-1, encoding=None, newline=None,
                  suffix=None, prefix=None, dir=None, **kwargs):
    return _stdlib.TemporaryFile(mode, buffering, encoding, newline, suffix, prefix, _directory(dir), **kwargs)


def atomic_file(*args, dir, **kwargs):
    """A publication staging file shares its destination's filesystem."""
    configure()
    return _stdlib.NamedTemporaryFile(*args, dir=dir, **kwargs)


def atomic_mkstemp(*args, dir, **kwargs):
    configure()
    return _stdlib.mkstemp(*args, dir=dir, **kwargs)


def docker_mounts() -> list[str]:
    actual = root().resolve()
    aliases = ["-v", f"{actual}:{actual}"] if actual != root() else []
    return ["-v", f"{actual}:{root()}", *aliases, "--workdir", str(scratch()),
            "--user", f"{os.getuid()}:{os.getgid()}", *container_env()]


def container_env() -> list[str]:
    return [item for key, value in configure().items() for item in ("-e", f"{key}={value}")]


def _remove(path):
    def writable(function, failed, error):
        if isinstance(error[1], FileNotFoundError):
            return
        item = Path(failed)
        for directory in (item.parent, item):
            if not directory.is_symlink():
                os.chmod(directory, stat.S_IMODE(directory.stat().st_mode) | 0o700)
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item, onerror=writable)
        else:
            function(failed)
    try:
        shutil.rmtree(path, onerror=writable)
    except FileNotFoundError:
        pass


def relocate(value, mapping):
    if isinstance(value, str):
        for old, new in mapping.items():
            value = value.replace(str(old), str(new))
        return value
    if isinstance(value, list):
        return [relocate(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: relocate(item, mapping) for key, item in value.items()}
    return value


def relocate_project(project, mapping):
    from _atomic_artefact import write_json

    for directory, folders, files in os.walk(project):
        folders[:] = [name for name in folders if name not in {"input", ".git"}]
        for name in files:
            path = Path(directory) / name
            if path.suffix.casefold() != ".json" or path.is_symlink():
                continue
            try:
                before = json.loads(path.read_text())
            except (ValueError, OSError):
                continue
            after = relocate(before, mapping)
            if after != before:
                write_json(path, after)


class Execution:
    def __init__(self, who, what, *, keep=False, destination=None, owner_pid=None):
        self.who, self.what = who, what
        self.keep = keep or os.environ.get("VIBEIC_KEEP_TEMP") == "1"
        self.destination = Path(destination) if destination is not None else None
        self.owner_pid = owner_pid
        self.published = None
        self.mapping = {}
        self.publication_failed = False

    def __enter__(self):
        self.previous = {key: os.environ.get(key) for key in _ENV_KEYS}
        self.tmp = _allocate_tmp(self.owner_pid)
        self.run = new_run(self.who, self.what, keep=self.keep, owner_pid=self.owner_pid)
        os.environ.update(VIBEIC_EXEC_TMP=str(self.tmp), VIBEIC_RUN_DIR=str(self.run))
        configure()
        return self

    def publish(self, destination=None):
        if self.published is not None:
            return self.published
        self.publication_failed = True
        destination = Path(destination) if destination is not None else (
            self.destination / self.run.name if self.destination is not None else None)
        preserved = {}
        for path in list(_outputs):
            if path.is_file() and path.resolve().is_relative_to(self.tmp.resolve()):
                relative = path.resolve().relative_to(self.tmp.resolve())
                target = self.run / "scratch" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                preserved[str(path)] = str(target)
                preserved[str(path.resolve())] = str(target)
                preserved[str(self.tmp / relative)] = str(target)
        if self.keep:
            shutil.copytree(self.tmp, self.run / "scratch", dirs_exist_ok=True)
            preserved[str(self.tmp)] = str(self.run / "scratch")
            preserved[str(self.tmp.resolve())] = str(self.run / "scratch")
        if destination is not None and not any(path.is_file() for path in self.run.rglob("*")):
            self.publication_failed = False
            return None
        if destination is not None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.run, destination)
            self.mapping = {str(self.run): str(destination), str(self.run.resolve()): str(destination),
                            **{old: new.replace(str(self.run), str(destination)) for old, new in preserved.items()}}
            self.published = destination
        elif self.keep:
            self.mapping = preserved
            self.published = self.run
        if self.published is not None:
            for path in self.published.rglob("*.json"):
                try:
                    data = json.loads(path.read_text())
                except (ValueError, OSError):
                    continue
                changed = relocate(data, self.mapping)
                if changed != data:
                    mode = stat.S_IMODE(path.stat().st_mode)
                    path.chmod(mode | stat.S_IWUSR)
                    try:
                        path.write_text(json.dumps(changed, indent=2) + "\n")
                    finally:
                        path.chmod(mode)
        self.publication_failed = False
        return self.published

    def detach(self):
        """Transfer a CLI allocation's cleanup to the calling shell or MCP process."""
        _owned_tmp.discard(self.tmp)
        _owned_runs.pop(self.run, None)
        return {"tmp": str(self.tmp), "run": str(self.run), "keep": self.keep, "env": configure()}

    def __exit__(self, *exc):
        try:
            if self.destination is not None or self.keep:
                self.publish()
        finally:
            try:
                if self.publication_failed:
                    _owned_runs.pop(self.run, None)
                    print(f"Results were not copied; unfinished run retained: {self.run}", file=sys.stderr)
                elif not self.keep:
                    _remove(self.run)
                    _owned_runs.pop(self.run, None)
            finally:
                try:
                    _remove(self.tmp)
                    _owned_tmp.discard(self.tmp)
                finally:
                    for key, value in self.previous.items():
                        if value is None:
                            os.environ.pop(key, None)
                        else:
                            os.environ[key] = value
                    _stdlib.tempdir = os.environ.get("TMPDIR")


execution = Execution


def finish(record):
    paths = {kind: Path(record[kind]) for kind in ("tmp", "run")}
    for kind, path in paths.items():
        parent = root() / ("runs" if kind == "run" else "tmp")
        if path.is_symlink() or path.parent.resolve() != parent.resolve():
            raise ValueError("Not an execution folder under VIBEIC_TMP: " + str(path))
    try:
        if record.get("keep"):
            if paths["tmp"].is_dir():
                shutil.copytree(paths["tmp"], paths["run"] / "scratch", dirs_exist_ok=True)
        else:
            _remove(paths["run"])
    finally:
        _remove(paths["tmp"])


def _active(path):
    match = re.search(r"-p([0-9]+)-(?:keep-)?[^-]+$", path.name)
    if not match:
        return None
    try:
        os.kill(int(match[1]), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def list_runs():
    rows = []
    for kind in ("runs", "tmp"):
        parent = root() / kind
        if not parent.is_dir():
            continue
        for path in sorted(parent.iterdir()):
            if path.is_symlink() or not path.is_dir():
                continue
            if (path in _owned_tmp or path in _owned_runs) and _active(path) is True:
                continue
            size = sum(item.stat().st_size for item in path.rglob("*")
                       if not item.is_symlink() and item.is_file())
            rows.append({"name": f"{kind}/{path.name}", "date": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
                         "bytes": size, "path": str(path), "active": _active(path), "keep": bool(re.search(r"-p[0-9]+-keep-[^-]+$", path.name))})
    return rows


def delete_runs(names, *, older_than_day=False):
    if older_than_day:
        names = [row["name"] for row in list_runs() if row["active"] is False and not row["keep"]
                 and time.time() - Path(row["path"]).stat().st_mtime > 86400
                 and not any(Path(row["path"]).rglob(".git"))]
    paths = []
    for name in names:
        relative = Path(name) if "/" in name else Path("runs") / name
        path = root() / relative
        if (len(relative.parts) != 2 or relative.parts[0] not in {"tmp", "runs"}
                or relative.name in {"", ".", ".."} or relative.is_absolute()
                or path.is_symlink() or not path.is_dir()):
            raise ValueError("Choose an existing leftover from the listing: " + name)
        if _active(path) is True or any(path.rglob(".git")):
            raise ValueError("Preserving an active execution or Git worktree: " + name)
        paths.append(path)
    for path in paths:
        _remove(path)
    return [str(path) for path in paths]


def _cleanup():
    paths = [path for path, keep in _owned_runs.items() if not keep] + list(_owned_tmp)
    for path in paths:
        try:
            _remove(path)
        except OSError as exc:
            print(f"Temporary cleanup failed for {path}: {exc}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("root", "scratch", "env", "docker-mounts", "container-env"):
        sub.add_parser(command)
    command = sub.add_parser("exec")
    command.add_argument("--keep", action="store_true")
    command.add_argument("argv", nargs=argparse.REMAINDER)
    begin = sub.add_parser("begin")
    begin.add_argument("who")
    begin.add_argument("what")
    begin.add_argument("--owner-pid", type=int)
    begin.add_argument("--keep", action="store_true")
    close = sub.add_parser("finish")
    close.add_argument("--context", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--json", action="store_true")
    delete = sub.add_parser("delete")
    delete.add_argument("names", nargs="*")
    delete.add_argument("--older-than-day", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "root": print(root())
        elif args.command == "scratch": print(scratch())
        elif args.command == "env": print(json.dumps(configure()))
        elif args.command == "docker-mounts": print(json.dumps(docker_mounts()))
        elif args.command == "container-env": print(json.dumps(container_env()))
        elif args.command == "exec":
            argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
            if not argv:
                parser.error("Provide a command after exec")
            with execution("cli", Path(argv[0]).name, keep=args.keep):
                return subprocess.run(argv, env=dict(os.environ)).returncode
        elif args.command == "begin":
            session = Execution(args.who, args.what, keep=args.keep, owner_pid=args.owner_pid).__enter__()
            print(json.dumps(session.detach()))
        elif args.command == "finish": finish(json.loads(args.context))
        elif args.command == "list":
            rows = list_runs()
            if args.json: print(json.dumps(rows, indent=2))
            else:
                print("BYTES\tDATE\tNAME\tACTIVE")
                for row in rows: print(f"{row['bytes']}\t{row['date']}\t{row['name']}\t{row['active']}")
        elif args.command == "delete":
            if not args.names and not args.older_than_day:
                parser.error("Select leftover names or --older-than-day")
            for path in delete_runs(args.names, older_than_day=args.older_than_day): print(path)
    except (ValueError, OSError) as exc:
        parser.exit(2, str(exc) + "\n")
    return 0


atexit.register(_cleanup)
configure()

if __name__ == "__main__":
    raise SystemExit(main())
