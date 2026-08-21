#!/usr/bin/env python3
"""`_ppa/jsonschema_bundled.py` — a JSON Schema validator that ships WITH the
plugin, so the contract gate does not depend on what a host happens to have.

WHY THIS EXISTS (R11)
=====================
`ppa_contract_check.py` validates a contract against `contract.v1.schema.json`
using `jsonschema`, which is not declared anywhere in this repository and is not
bundled. Two failures were reproduced, and the second is the one nobody had
seen:

    jsonschema ABSENT      the gate reports PPA-C-010 UNDETERMINED and exits 2.
                           Honest -- and the contract's shape is never checked
                           on a fresh install, so the flow does not complete.
    jsonschema 3.2.0       `import jsonschema` SUCCEEDS. The shipped schemas
    (a current distro       declare draft 2020-12, `Draft202012Validator`
     system package)        arrived in 4.0, and the guard catches ImportError
                           only -- so the program died with an uncaught
                           AttributeError and returned rc=1. In this contract
                           rc=1 means a finding about a DESIGN. A crash was
                           publishing itself as a design finding, and 33 tests
                           of this repository were red on that host for it.

Declaring a dependency does not fix either one for somebody who has just
downloaded the plugin and run it. Bundling does.

THE RULE THAT MAKES A HAND-WRITTEN VALIDATOR SAFE
=================================================
A validator that quietly ignores a keyword it does not implement is worse than
no validator: it reports clean over a rule it never applied, which is the exact
defect this whole package exists to remove. So this one REFUSES.

`unsupported(schema)` walks the schema first and returns every construct this
engine cannot apply. `ppa_contract_check` calls it BEFORE validating, and a
non-empty answer is UNDETERMINED (rc=2) with the construct named -- never a
pass, and never a silent skip of one keyword while the others are checked.

That inverts the usual risk. The dangerous direction for a re-implementation is
"it missed something and said fine"; here missing something is a refusal that
names what was missed, and the remedy printed alongside it is the real library.

WHAT IT IMPLEMENTS
==================
Measured against the ten schemas this plugin ships (`schemas/ppa/*.json`), which
between them use 29 keywords and seven types. The set below is that measurement
plus the symmetric partners of what they use (`maximum` beside `minimum`, and so
on), because implementing one side of a pair and refusing the other would be an
arbitrary edge nobody could predict.

    structural   type enum const
    object       properties patternProperties additionalProperties required
                 propertyNames minProperties maxProperties
    array        items minItems maxItems uniqueItems
    string       minLength maxLength pattern
    number       minimum maximum exclusiveMinimum exclusiveMaximum multipleOf
    logic        allOf anyOf oneOf not if then else
    reference    $ref, to a LOCAL pointer only (`#`, `#/$defs/...`,
                 `#/definitions/...`, `#/properties/...`)
    ignored      $schema $id $comment title description default examples
                 deprecated readOnly writeOnly $defs definitions

Everything else -- `format` as an assertion, `contains`, `prefixItems`,
`dependentSchemas`, a remote `$ref`, draft-04's boolean `exclusiveMinimum` --
is UNSUPPORTED and refuses.

ERROR SHAPE
===========
`iter_errors` yields objects with `.message` and `.path`, which is the subset of
`jsonschema.ValidationError` that `ppa_contract_check._apply` reads. The caller
therefore does not branch on which engine ran.

chip-AGNOSTIC: JSON Schema semantics only.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence

__all__ = ["Error", "unsupported", "iter_errors", "validate_schema_itself",
           "SUPPORTED", "IGNORED"]

#: Keywords this engine APPLIES.
SUPPORTED = frozenset({
    "type", "enum", "const",
    "properties", "patternProperties", "additionalProperties", "required",
    "propertyNames", "minProperties", "maxProperties",
    "items", "minItems", "maxItems", "uniqueItems",
    "minLength", "maxLength", "pattern",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "multipleOf",
    "allOf", "anyOf", "oneOf", "not", "if", "then", "else",
    "$ref",
})

#: Keywords that carry no assertion. Ignoring these is correct, not a gap.
IGNORED = frozenset({
    "$schema", "$id", "$anchor", "$comment", "title", "description",
    "default", "examples", "deprecated", "readOnly", "writeOnly",
    "$defs", "definitions",
})

_TYPES: Dict[str, Any] = {
    "object": dict, "array": list, "string": str,
    "boolean": bool, "null": type(None),
}


class Error:
    """One violation. Duck-compatible with `jsonschema.ValidationError`."""

    __slots__ = ("message", "path")

    def __init__(self, message: str, path: Sequence[Any]):
        self.message = message
        self.path = list(path)

    def __repr__(self) -> str:                          # pragma: no cover
        return f"Error({self.message!r}, {self.path!r})"


# ---------------------------------------------------------------------------
# the refusal half -- asked BEFORE anything is validated
# ---------------------------------------------------------------------------
def unsupported(schema: Any, where: str = "#") -> List[str]:
    """Every construct in `schema` this engine cannot apply. Empty = it can.

    Walked EAGERLY over the whole document rather than discovered lazily during
    validation, because a keyword only reached on the failing branch would let
    a passing instance be reported clean by an engine that could not have
    checked it.
    """
    out: List[str] = []
    if isinstance(schema, bool):
        return out
    if not isinstance(schema, Mapping):
        return [f"{where}: a schema must be an object or a boolean, "
                f"got {type(schema).__name__}"]
    for key, val in schema.items():
        if key in IGNORED:
            continue
        if key not in SUPPORTED:
            out.append(f"{where}: keyword {key!r} is not implemented by the "
                       f"bundled validator")
            continue
        if key == "$ref":
            if not (isinstance(val, str) and val.startswith("#")):
                out.append(f"{where}/$ref: only a LOCAL pointer is "
                           f"implemented; {val!r} is not one")
            continue
        if key in ("exclusiveMinimum", "exclusiveMaximum") \
                and isinstance(val, bool):
            out.append(f"{where}/{key}: a BOOLEAN here is draft-04 spelling, "
                       f"which this engine does not implement")
            continue
        if key == "items" and isinstance(val, list):
            out.append(f"{where}/items: the ARRAY (tuple) form is not "
                       f"implemented")
            continue
        if key == "pattern" or key == "patternProperties":
            pats = [val] if key == "pattern" else list(val or {})
            for pat in pats:
                try:
                    re.compile(pat)
                except (re.error, TypeError) as exc:
                    out.append(f"{where}/{key}: {pat!r} is not a regular "
                               f"expression Python can compile: {exc}")
        # recurse into every subschema position
        if key in ("properties", "patternProperties"):
            if isinstance(val, Mapping):
                for name, sub in val.items():
                    out.extend(unsupported(sub, f"{where}/{key}/{name}"))
        elif key in ("allOf", "anyOf", "oneOf"):
            if isinstance(val, list):
                for i, sub in enumerate(val):
                    out.extend(unsupported(sub, f"{where}/{key}[{i}]"))
        elif key in ("not", "if", "then", "else", "items", "propertyNames",
                     "additionalProperties"):
            if isinstance(val, (Mapping, bool)):
                out.extend(unsupported(val, f"{where}/{key}"))
    for pocket in ("$defs", "definitions"):
        block = schema.get(pocket)
        if isinstance(block, Mapping):
            for name, sub in block.items():
                out.extend(unsupported(sub, f"{where}/{pocket}/{name}"))
    return out


def validate_schema_itself(schema: Any) -> List[str]:
    """`check_schema`'s job: is this a schema this engine can be trusted on?

    Same answer as `unsupported`, named for the question a caller asks.
    """
    return unsupported(schema)


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------
def _resolve_ref(root: Any, ref: str) -> Any:
    """`#/a/b` -> the subschema, or a schema that fails everything if absent.

    A `$ref` that does not resolve is a defect in the SCHEMA, not the instance.
    `unsupported` cannot see it (the pointer may be built from a fragment it
    walked past), so it surfaces here as an error against the instance whose
    message says plainly that the schema is at fault.
    """
    if ref == "#":
        return root
    node: Any = root
    for token in ref.lstrip("#/").split("/"):
        if not token:
            continue
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, Mapping) and token in node:
            node = node[token]
        elif isinstance(node, list) and token.isdigit() \
                and int(token) < len(node):
            node = node[int(token)]
        else:
            return {"__unresolved_ref__": ref}
    return node


def _is_int(v: Any) -> bool:
    # `True` is an int in Python and a boolean is not an integer instance.
    return isinstance(v, int) and not isinstance(v, bool)


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _type_ok(value: Any, name: str) -> bool:
    if name == "integer":
        return _is_int(value) or (isinstance(value, float)
                                  and value.is_integer())
    if name == "number":
        return _num(value)
    if name == "boolean":
        return isinstance(value, bool)
    cls = _TYPES.get(name)
    if cls is None:
        return False
    if cls is str:
        return isinstance(value, str)
    if cls is dict:
        return isinstance(value, Mapping)
    if cls is list:
        return isinstance(value, list)
    return isinstance(value, cls)


def _canon(v: Any) -> Any:
    """A hashable, comparison-stable form for `enum` / `const` / `uniqueItems`.

    `1` and `1.0` are the same JSON value and `True` is not `1`; comparing with
    `==` alone gets the second wrong, which is how a boolean slips past an enum
    of integers.
    """
    if isinstance(v, bool):
        return ("bool", v)
    if isinstance(v, (int, float)):
        return ("num", float(v))
    if isinstance(v, str):
        return ("str", v)
    if v is None:
        return ("null",)
    if isinstance(v, Mapping):
        return ("obj", tuple(sorted((k, _canon(x)) for k, x in v.items())))
    if isinstance(v, list):
        return ("arr", tuple(_canon(x) for x in v))
    return ("other", repr(v))                           # pragma: no cover


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
def iter_errors(schema: Any, instance: Any) -> Iterator[Error]:
    """Every violation of `schema` by `instance`, in document order."""
    yield from _walk(schema, instance, schema, [])


def _walk(schema: Any, inst: Any, root: Any,
          path: List[Any]) -> Iterator[Error]:
    if schema is True:
        return
    if schema is False:
        yield Error("a schema of `false` accepts nothing", path)
        return
    if not isinstance(schema, Mapping):
        return
    if "__unresolved_ref__" in schema:
        yield Error(f"the schema's $ref {schema['__unresolved_ref__']!r} does "
                    f"not resolve; this is a defect in the SCHEMA, not in the "
                    f"document", path)
        return

    if "$ref" in schema:
        yield from _walk(_resolve_ref(root, str(schema["$ref"])), inst, root,
                         path)
        # 2020-12 lets $ref sit beside other keywords, so the rest still runs.

    # --- type ---------------------------------------------------------------
    if "type" in schema:
        names = schema["type"]
        names = names if isinstance(names, list) else [names]
        if not any(_type_ok(inst, str(n)) for n in names):
            yield Error(f"{_show(inst)} is not of type "
                        + " or ".join(repr(str(n)) for n in names), path)
            return          # every other assertion here is about that type

    # --- generic ------------------------------------------------------------
    if "enum" in schema:
        allowed = schema["enum"] if isinstance(schema["enum"], list) else []
        if _canon(inst) not in [_canon(x) for x in allowed]:
            yield Error(f"{_show(inst)} is not one of "
                        f"{[x for x in allowed]!r}", path)
    if "const" in schema and _canon(inst) != _canon(schema["const"]):
        yield Error(f"{_show(inst)} was expected to be "
                    f"{_show(schema['const'])}", path)

    # --- logic --------------------------------------------------------------
    for i, sub in enumerate(schema.get("allOf") or []):
        yield from _walk(sub, inst, root, path)
    if "anyOf" in schema:
        subs = schema["anyOf"] or []
        if not any(not _any_error(s, inst, root) for s in subs):
            yield Error(f"{_show(inst)} is not valid under any of the "
                        f"{len(subs)} schemas in anyOf", path)
    if "oneOf" in schema:
        subs = schema["oneOf"] or []
        n = sum(1 for s in subs if not _any_error(s, inst, root))
        if n != 1:
            yield Error(f"{_show(inst)} is valid under {n} of the "
                        f"{len(subs)} schemas in oneOf; exactly one is "
                        f"required", path)
    if "not" in schema and not _any_error(schema["not"], inst, root):
        yield Error(f"{_show(inst)} is valid under the schema in `not`, and "
                    f"must not be", path)
    if "if" in schema:
        taken = "then" if not _any_error(schema["if"], inst, root) else "else"
        if taken in schema:
            yield from _walk(schema[taken], inst, root, path)

    # --- per type -----------------------------------------------------------
    if isinstance(inst, Mapping):
        yield from _object(schema, inst, root, path)
    elif isinstance(inst, list):
        yield from _array(schema, inst, root, path)
    elif isinstance(inst, str):
        yield from _string(schema, inst, path)
    if _num(inst):
        yield from _number(schema, inst, path)


def _any_error(schema: Any, inst: Any, root: Any) -> bool:
    for _ in _walk(schema, inst, root, []):
        return True
    return False


def _object(schema: Mapping, inst: Mapping, root: Any,
            path: List[Any]) -> Iterator[Error]:
    for name in schema.get("required") or []:
        if name not in inst:
            yield Error(f"{name!r} is a required property", path)
    props = schema.get("properties") or {}
    patterns = schema.get("patternProperties") or {}
    extra = schema.get("additionalProperties")
    if isinstance(props, Mapping):
        for name, sub in props.items():
            if name in inst:
                yield from _walk(sub, inst[name], root, path + [name])
    for name, value in inst.items():
        matched = isinstance(props, Mapping) and name in props
        if isinstance(patterns, Mapping):
            for pat, sub in patterns.items():
                try:
                    hit = re.search(pat, str(name)) is not None
                except re.error:                        # pragma: no cover
                    hit = False
                if hit:
                    matched = True
                    yield from _walk(sub, value, root, path + [name])
        if matched or extra is None or extra is True:
            continue
        if extra is False:
            yield Error(f"Additional properties are not allowed "
                        f"({name!r} was unexpected)", path)
        else:
            yield from _walk(extra, value, root, path + [name])
    if "propertyNames" in schema:
        for name in inst:
            for err in _walk(schema["propertyNames"], name, root,
                             path + [name]):
                yield Error(f"the property name {name!r} is invalid: "
                            f"{err.message}", path + [name])
    if _is_int(schema.get("minProperties")) \
            and len(inst) < schema["minProperties"]:
        yield Error(f"{_show(inst)} does not have enough properties "
                    f"(minimum {schema['minProperties']})", path)
    if _is_int(schema.get("maxProperties")) \
            and len(inst) > schema["maxProperties"]:
        yield Error(f"{_show(inst)} has too many properties "
                    f"(maximum {schema['maxProperties']})", path)


def _array(schema: Mapping, inst: list, root: Any,
           path: List[Any]) -> Iterator[Error]:
    if "items" in schema and not isinstance(schema["items"], list):
        for i, item in enumerate(inst):
            yield from _walk(schema["items"], item, root, path + [i])
    if _is_int(schema.get("minItems")) and len(inst) < schema["minItems"]:
        yield Error(f"{_show(inst)} is too short (minimum "
                    f"{schema['minItems']} items)", path)
    if _is_int(schema.get("maxItems")) and len(inst) > schema["maxItems"]:
        yield Error(f"{_show(inst)} is too long (maximum "
                    f"{schema['maxItems']} items)", path)
    if schema.get("uniqueItems") is True:
        seen = [_canon(x) for x in inst]
        if len(set(seen)) != len(seen):
            yield Error(f"{_show(inst)} has non-unique elements", path)


def _string(schema: Mapping, inst: str, path: List[Any]) -> Iterator[Error]:
    if _is_int(schema.get("minLength")) and len(inst) < schema["minLength"]:
        yield Error(f"{inst!r} is too short (minimum {schema['minLength']} "
                    f"characters)", path)
    if _is_int(schema.get("maxLength")) and len(inst) > schema["maxLength"]:
        yield Error(f"{inst!r} is too long (maximum {schema['maxLength']} "
                    f"characters)", path)
    pat = schema.get("pattern")
    if isinstance(pat, str):
        try:
            hit = re.search(pat, inst) is not None
        except re.error:                                # pragma: no cover
            hit = True
        if not hit:
            yield Error(f"{inst!r} does not match {pat!r}", path)


def _number(schema: Mapping, inst: Any, path: List[Any]) -> Iterator[Error]:
    for key, ok, word in (
            ("minimum", lambda v, b: v >= b, "less than the minimum"),
            ("maximum", lambda v, b: v <= b, "greater than the maximum"),
            ("exclusiveMinimum", lambda v, b: v > b,
             "less than or equal to the exclusive minimum"),
            ("exclusiveMaximum", lambda v, b: v < b,
             "greater than or equal to the exclusive maximum")):
        bound = schema.get(key)
        if _num(bound) and not ok(inst, bound):
            yield Error(f"{inst!r} is {word} {bound!r}", path)
    mult = schema.get("multipleOf")
    if _num(mult) and mult > 0:
        q = inst / mult
        if abs(q - round(q)) > 1e-9:
            yield Error(f"{inst!r} is not a multiple of {mult!r}", path)


def _show(v: Any) -> str:
    """Short, deterministic rendering for a message. Never the whole document."""
    if isinstance(v, str):
        return repr(v if len(v) <= 60 else v[:57] + "...")
    if isinstance(v, Mapping):
        return "{...}" if v else "{}"
    if isinstance(v, list):
        return f"[... {len(v)} items]" if v else "[]"
    return repr(v)
