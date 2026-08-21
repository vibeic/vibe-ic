#!/usr/bin/env python3
"""`_ppa/schema_validation.py` — ONE place that decides which JSON Schema engine
validates a document, and the ONE place `jsonschema` is named.

WHAT R11 ACTUALLY WAS
=====================
`jsonschema` was used by `ppa_contract_check.py` and by six test modules, and
declared nowhere. Two failures, both reproduced:

  ABSENT       the gate reports PPA-C-010 UNDETERMINED and exits 2. Honest --
               and the contract's shape is never checked on a fresh install of
               the plugin, so the flow does not complete.
  PRESENT BUT
  TOO OLD      `jsonschema` 3.2.0 is what a current distribution's system
               package gives you. `import jsonschema` succeeds. The shipped
               schemas declare draft 2020-12, and `Draft202012Validator`
               arrived in 4.0. The guard caught ImportError only, so the
               program died with an uncaught AttributeError and returned rc=1.
               In this contract rc=1 is a finding about a DESIGN -- a crash was
               publishing itself as one, and 33 tests of this repository were
               red on such a host because of it.

The second is why "declare it" alone is not the fix: a declaration does not
change what happens to somebody who already has the wrong version installed,
and the version they have is the one their distribution ships.

THE ANSWER: DECLARE IT *AND* BUNDLE IT
======================================
    declared   `PREFERRED` below is the single machine-readable statement of
               what this plugin wants and why. Every message that asks a user
               to install something reads it, so the declaration cannot drift
               from the advice.
    bundled    `_ppa/jsonschema_bundled.py` implements the keyword set the
               shipped schemas use and REFUSES any construct it does not, so
               the gate works on a bare host without ever reporting clean over
               a rule it could not apply.

The real library is still PREFERRED when a usable one is present: it is the
reference implementation, and this module's job is to make the plugin work
without it, not to replace it.

THREE OUTCOMES AND NO FOURTH
============================
`resolve()` returns exactly one of:

    an engine + which one it is        validation may proceed
    None + a REASON                    UNDETERMINED. The caller reports it and
                                       exits 2, and must never treat it as a
                                       pass -- "I could not apply the schema"
                                       and "the schema found nothing" are the
                                       two facts this package exists to keep
                                       apart.

There is no third arm that skips the schema and checks the rest.

chip-AGNOSTIC.
"""
from __future__ import annotations

from typing import Any, Callable, Iterator, List, Optional, Tuple

from . import jsonschema_bundled as _bundled

__all__ = ["PREFERRED", "ENGINE_LIBRARY", "ENGINE_BUNDLED", "Engine",
           "resolve", "engine_report"]

#: THE DECLARATION. Distribution name, the minimum version that carries the
#: validator class the shipped schemas need, and what it is wanted for. Every
#: user-facing "install this" message is built from these fields, so the advice
#: and the requirement are the same statement.
PREFERRED = {
    "distribution": "jsonschema",
    "minimum_version": "4.0",
    "why": ("the reference implementation of JSON Schema. 4.0 is the first "
            "release carrying Draft202012Validator, which the schemas this "
            "plugin ships declare"),
    "install": "python3 -m pip install 'jsonschema>=4.0'",
    "required": False,
}

ENGINE_LIBRARY = "jsonschema"
ENGINE_BUNDLED = "_ppa.jsonschema_bundled"

#: Draft URI -> the `jsonschema` validator class that implements it. A schema
#: declaring a draft not listed here is validated by the bundled engine rather
#: than by whichever class happened to be lying around: applying the wrong
#: draft is a different check, not a near-enough one.
_DRAFTS = {
    "https://json-schema.org/draft/2020-12/schema": "Draft202012Validator",
    "http://json-schema.org/draft-07/schema#": "Draft7Validator",
    "https://json-schema.org/draft-07/schema#": "Draft7Validator",
    "http://json-schema.org/draft-06/schema#": "Draft6Validator",
}
_FALLBACK_CLASS = "Draft202012Validator"


class Engine:
    """A validator, plus the name of what is doing the validating.

    `iter_errors(instance)` yields objects with `.message` and `.path` whatever
    the backing engine is, so a caller never branches on which one ran.
    """

    __slots__ = ("name", "detail", "_iter")

    def __init__(self, name: str, detail: str,
                 iter_errors: Callable[[Any], Iterator[Any]]):
        self.name = name
        self.detail = detail
        self._iter = iter_errors

    def iter_errors(self, instance: Any) -> Iterator[Any]:
        return self._iter(instance)

    def is_valid(self, instance: Any) -> bool:
        for _ in self._iter(instance):
            return False
        return True

    def errors(self, instance: Any) -> List[Any]:
        return list(self._iter(instance))


def _library_engine(schema: Any) -> Tuple[Optional[Engine], Optional[str]]:
    """The real library, or the reason it cannot serve THIS schema.

    The reason is never fatal on its own -- the caller falls through to the
    bundled engine -- but it is recorded and printed, because "an old
    jsonschema is installed" is the single most useful sentence to put in front
    of somebody whose contract check behaves unexpectedly.
    """
    try:
        import jsonschema                               # noqa: WPS433
    except ImportError as exc:
        return None, f"{ENGINE_LIBRARY} is not importable here ({exc})"
    declared = str(schema.get("$schema", "")) \
        if isinstance(schema, dict) else ""
    want = _DRAFTS.get(declared, _FALLBACK_CLASS)
    cls = getattr(jsonschema, want, None)
    if cls is None:
        have = getattr(jsonschema, "__version__", "an unknown version")
        return None, (
            f"{ENGINE_LIBRARY} {have} is installed but has no {want}, which "
            f"the schema's declared draft ({declared or 'unstated'}) needs. "
            f"{PREFERRED['install']} to use the reference implementation")
    try:
        validator = cls(schema)
    except Exception as exc:                            # pragma: no cover
        return None, f"{ENGINE_LIBRARY}.{want} refused this schema: {exc!r}"
    return Engine(ENGINE_LIBRARY, f"{ENGINE_LIBRARY}.{want}",
                  validator.iter_errors), None


def resolve(schema: Any) -> Tuple[Optional[Engine], List[str]]:
    """(engine, notes). `engine is None` means UNDETERMINED -- never a pass.

    `notes` is always returned and always worth printing: on the happy path it
    names the engine, and on a fall-through it names why the preferred one was
    not used. A silent fallback would hide the fact that a host is running the
    bundled engine, which is exactly what a reader of a verdict needs to know.
    """
    notes: List[str] = []
    engine, why = _library_engine(schema)
    if engine is not None:
        notes.append(f"schema validated by {engine.detail}")
        return engine, notes
    notes.append(f"{why}; falling back to the bundled validator")

    gaps = _bundled.unsupported(schema)
    if gaps:
        notes.append(
            "the bundled validator cannot apply this schema, so its shape was "
            "NOT validated. This is not the schema passing. Unimplemented: "
            + "; ".join(gaps[:5])
            + (f" (+{len(gaps) - 5} more)" if len(gaps) > 5 else "")
            + f". Remedy: {PREFERRED['install']}")
        return None, notes
    notes.append(f"schema validated by {ENGINE_BUNDLED} (bundled with this "
                 f"plugin; every keyword it cannot apply is a refusal, never "
                 f"a skip)")
    return Engine(ENGINE_BUNDLED, ENGINE_BUNDLED,
                  lambda inst: _bundled.iter_errors(schema, inst)), notes


def check_schema(schema: Any) -> List[str]:
    """Is this a schema SOME available engine can be trusted on? Reasons if not.

    Used by tests that used to call `jsonschema.DraftNNValidator.check_schema`
    and skip when the library was absent -- a skip that meant the shipped
    schemas were never checked at all on a bare host.
    """
    engine, notes = resolve(schema)
    return [] if engine is not None else notes


def engine_or_skip(schema: Any):
    """The engine, or `pytest.skip` with the reason nobody can apply this.

    For TESTS that guard a shipped schema. They used to open with
    `pytest.importorskip("jsonschema")`, which asks the wrong question twice
    over: an old library imports and then has no validator class (R11), and on
    a host with nothing installed the guard silently did not run at all -- so
    the schemas this repository ships were checked only where somebody happened
    to have the right library. With the engine bundled, the skip arm is now
    genuinely unreachable for the shipped schemas, and that is the point.
    """
    engine, notes = resolve(schema)
    if engine is None:
        import pytest                                   # noqa: WPS433
        pytest.skip("no JSON Schema engine can apply this schema, so nothing "
                    "here looked. This is a SKIP and not a pass: "
                    + " ".join(notes))
    return engine


def engine_report(schema: Any) -> str:
    """One line naming what would validate this schema. For a `--json` report."""
    engine, notes = resolve(schema)
    return notes[-1] if notes else "no engine resolved"
