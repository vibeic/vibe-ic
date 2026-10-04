"""Small source-bound Step9 request protocol.

The shared execution policy remains in ``execution_modes``.  This module only
serialises the production request and does not issue execution/adoption
authority.
"""
from __future__ import annotations
# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

from dataclasses import asdict, is_dataclass
import argparse
import json
from pathlib import Path
from typing import Mapping

import execution_modes as em


class StepRequest:
    def __init__(self, step_id: str, project: Path, parameters: Mapping[str, object],
                 lease: Path, record: Path, source_sha: str,
                 source_files: Mapping[str, str]):
        self.step_id, self.project = str(step_id), Path(project)
        self.parameters, self.lease, self.record = dict(parameters), Path(lease), Path(record)
        self.source_sha, self.source_files = source_sha, dict(source_files)
        self.check_source()

    def check_source(self):
        if not self.project.is_absolute() or self.project.is_symlink():
            raise em.Refusal("STEP_REQUEST_PATH_UNBOUND", "project")
        if not self.source_files:
            raise em.Refusal("INCOMPLETE_STEP_REQUEST", self.step_id)
        if not __import__('re').fullmatch(r"[0-9a-f]{40}", self.source_sha):
            raise em.Refusal("INVALID_SOURCE_SHA", self.source_sha)
        for name, expected in self.source_files.items():
            path = Path(name)
            if (not path.is_absolute() or path.is_symlink() or not path.is_file()
                    or em.digest(path) != expected):
                raise em.Refusal("ADAPTER_SOURCE_MISMATCH", name)


class PreparedStep:
    def __init__(self, context, registry, consume=None, disposition="execute", reason=""):
        self.context, self.registry, self.consume = context, registry, consume
        self.disposition, self.reason = disposition, reason
        self.adoption_paths = ("project/phase2/stage2/synth", "producer.json",
                               "native_commands.jsonl")


class FactoryRegistry:
    """Explicit factory table; no import/name guessing."""
    def __init__(self):
        self._factories = {}

    def register(self, module):
        import importlib
        module = importlib.import_module(module) if isinstance(module, str) else module
        ids, factory = getattr(module, "STEP_IDS", None), getattr(module, "prepare", None)
        if not isinstance(ids, tuple) or not ids or not callable(factory):
            raise em.Refusal("PRODUCTION_FACTORY_INCOMPLETE", str(module))
        for step in ids:
            if step in self._factories and self._factories[step] != factory:
                raise em.Refusal("PRODUCTION_FACTORY_DUPLICATE", str(step))
            self._factories[step] = factory

    def coverage(self):
        return {step: {"factory": getattr(fn, "__name__", ""),
                       "source": str(Path(__import__('inspect').getsourcefile(fn)).resolve())}
                for step, fn in self._factories.items()}

    def prepare(self, request):
        fn = self._factories.get(str(request.step_id))
        if fn is None:
            raise em.Refusal("PRODUCTION_FACTORY_NOT_REGISTERED", str(request.step_id))
        return fn(request)


def json_parameters(parameters: Mapping[str, object]) -> dict:
    def encode(value):
        if isinstance(value, Path):
            return str(value)
        if is_dataclass(value) and not isinstance(value, type):
            return encode(asdict(value))
        if isinstance(value, argparse.Namespace):
            return encode(vars(value))
        if isinstance(value, Mapping):
            return {str(k): encode(v) for k, v in value.items()}
        if isinstance(value, (tuple, list)):
            return [encode(v) for v in value]
        if value is None or isinstance(value, (str, bool, int, float)):
            return value
        raise em.Refusal("PRODUCTION_PARAMETER_UNSERIALIZABLE", type(value).__name__)
    return encode(parameters)


def imported_result(**values):
    return {"status": "IMPORTED", **values}
