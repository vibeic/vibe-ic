#!/usr/bin/env python3
"""§4.05 as a MECHANISM: a step cannot read the oracle. vibe-ic#1079.

Adopted from OpenROAD-flow-scripts. `flow/scripts/util.tcl:164-180`
(`erase_non_stage_variables`) calls `unset ::env($var)` for every variable not
declared for the current stage, driven by `non_stage_variables.py:18-26` and the
246 `stages:` declarations in `variables.yaml`; every stage script calls it on
entry (`detail_route.tcl:11` is `erase_non_stage_variables route`). A stage does
not AGREE not to read an out-of-stage variable — it cannot.

§4.05 says a program reads only the design INPUT, never the oracle, harness or
golden. Until this module, that was enforced by Step-2.7 adversarial review —
by someone noticing. A rule stated where it cannot act is one that will
eventually be broken silently.

THE SHAPE, AND WHY IT IS A DENY-LIST WITH DECLARED EXCEPTIONS
============================================================
ORFS can allow-list because in ORFS the VARIABLE is the channel: a stage reads
`::env(CORE_UTILIZATION)` or it does not read it at all. Our steps do not take
their inputs through named variables; they construct paths under the project.
So the faithful translation is not "allow only the declared paths" — that
denies the world and would brick every step on the first path nobody thought
to declare. It is:

    DENY the oracle class, and let `required_inputs` carve the exceptions.

`required_inputs` is the declaration site the issue asks for, used as the
allow-list that overrides the deny. A step that legitimately reads a file the
oracle classifier would flag DECLARES it, in the flow YAML, where the
declaration is already checked by `step_required_inputs_check`. There is no
second declaration to drift from the flow.

WHERE THE BOUNDARY COMES FROM (two authorities, unioned, neither restated)
=========================================================================
`_reference_flow_boundary.OFF_LIMITS_TREE_SEGMENTS` is this repo's ONE
definition of WHERE §4.05 runs — twelve segments — and its own docstring says
it exists because two shipped programs once held contradictory positions about
the same directory. `blindness_audit._classify_rel` answers a DIFFERENT
question, "is this a benchmark SCORING oracle" (`score/`, `canonical_samples/`
and the `_test.` / `_ref.` / `verified_` filename forms). Both are off limits,
so both are asked.

The first version of this module asked only the second, and measured on this
tree that let all twelve canonical segments through — a §4.05 "mechanism" under
which a step may read `golden/`. The boundary is now resolved in the PARENT and
handed to the in-child shim as data, so the shim classifies nothing and there
is no second definition to drift.

WHAT IS ENFORCED, AND WHAT IS NOT — read this before believing a green run
=========================================================================
Two channels, and they are not equally closed.

  ENV      complete for what it covers. Any variable whose VALUE names an
           oracle path is removed from the child's environment.

  FILESYSTEM   covered for PYTHON children, by an audit hook (`sys.addaudithook`,
           3.8+) installed through a `sitecustomize` on `PYTHONPATH`. An `open`
           of a denied path raises PermissionError, so the child FAILS rather
           than succeeding with data it should not have.

           NOT COVERED, stated plainly because a bound nobody states is read as
           a guarantee:
             * a NON-Python child. An OpenROAD/Tcl/yosys subprocess is not
               subject to a Python audit hook and can open anything the user
               can. Closing that needs a mount namespace, which is not portable
               and is not attempted here;
             * a child that resets `PYTHONPATH`, or runs with `-E` / `-I`, or
               `-S`. Then `sitecustomize` never loads and the hook never
               installs;
             * a read through a route that is not the `open` audit event —
               `os.scandir` for existence, a memory-mapped file already open,
               a path handed over as an inherited fd;
             * anything outside the project directory. The deny is scoped to
               the project so the hook stays cheap and cannot break the
               interpreter's own imports.

           So this is a mechanism for the case it names and a partial one
           overall. It converts the DEFAULT from "reachable unless someone
           reviews" to "denied unless someone deliberately leaves the covered
           path", which is the change #1079 asks for; it does not make the
           violation physically impossible the way an unset variable does.

OFF BY DEFAULT. `enforcement_enabled()` reads `VIBEIC_STEP_SCOPE`; with it
unset, `child_env` returns the environment unchanged and this module cannot
affect any run. Sequencing the switch on is the owner's call, not this
module's.

chip-AGNOSTIC: no IC, vendor, PDK or process literal appears here or can
affect the decision.
"""
from __future__ import annotations

import fnmatch
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

ENV_SWITCH = "VIBEIC_STEP_SCOPE"
ENV_PROJECT = "VIBEIC_STEP_SCOPE_PROJECT"
ENV_ALLOW = "VIBEIC_STEP_SCOPE_ALLOW"
ENV_STEP = "VIBEIC_STEP_SCOPE_STEP"
#: The boundary and the liveness marker, resolved in the parent (#1079 merge).
ENV_DENY = "VIBEIC_STEP_SCOPE_DENY"
ENV_DENY_FILE_RE = "VIBEIC_STEP_SCOPE_DENY_FILE_RE"
ENV_MARKER = "VIBEIC_STEP_SCOPE_MARKER"
#: The filename forms `blindness_audit` treats as oracle. Stated ONCE, here,
#: and handed to the shim; it is not a second copy because the shim has none.
DENY_FILENAME_RE = r"(?:_test\.[a-z0-9]+|_ref\.[a-z0-9]+|^testbench|^verified_)"

DEFAULT_FLOW_REL = "flow/phase1_phase2_phase3.yaml"


def enforcement_enabled(env: Optional[Dict[str, str]] = None) -> bool:
    """OFF unless asked for. See the module docstring."""
    e = os.environ if env is None else env
    return str(e.get(ENV_SWITCH, "")).strip() not in ("", "0", "false", "False")


# --------------------------------------------------------------------------- #
# The oracle class — IMPORTED, never restated
# --------------------------------------------------------------------------- #
def oracle_reason(rel: str, project: Optional[Path] = None) -> Optional[str]:
    """Why `rel` is out of §4.05 scope, or None.

    TWO AUTHORITIES, UNIONED, AND NEITHER RESTATED HERE.

    `_reference_flow_boundary` is this repo's ONE definition of WHERE §4.05
    runs — `OFF_LIMITS_TREE_SEGMENTS`, twelve of them. Its docstring says it
    exists because two shipped programs once held contradictory positions about
    the same directory. It is the authority for the boundary and it is asked
    first.

    `blindness_audit._classify_rel` answers a DIFFERENT question — "is this a
    benchmark SCORING oracle" (`score/`, `canonical_samples/`, and the
    `_test.`/`_ref.`/`verified_` filename forms). Those are genuinely off
    limits too, so they are unioned in rather than chosen between.

    The first version of this module asked only the second one. Measured on
    this tree, that let every one of the twelve canonical segments through:

        oracle_reason('golden/x.v')                   -> None
        oracle_reason('oracle/y.json')                -> None
        oracle_reason('ground_truth/z.txt')           -> None
        oracle_reason('reference_flow/qor_rules.tcl') -> None

    i.e. a §4.05 "mechanism" under which a step may read `golden/`.
    """
    parts = [p.lower() for p in str(rel).split("/")]
    # THE SAME LIST THE CHILD GETS. An earlier draft asked the two authorities
    # separately here while handing `deny_segments()` down, and a test caught
    # the consequence immediately: `canonical_samples/y.v` was denied in the
    # child and allowed in the parent. Parent and child now consult one list by
    # construction, which is the property this merge claims.
    deny = set(deny_segments())
    try:
        import _reference_flow_boundary as rfb  # noqa: PLC0415
    except Exception:                           # noqa: BLE001
        rfb = None                              # type: ignore
    if deny:
        for seg in parts:
            if seg in deny:
                # `reference_flow/` is the MIXED one: it legitimately carries a
                # flow's own scripts as well as an oracle's QoR rules, so the
                # segment alone cannot decide and the boundary module ships
                # `is_oracle_qor_rules` for exactly that. Content wins where we
                # can read it; where we cannot, the segment stands — refusing
                # is the safe direction for a §4.05 guard.
                if (rfb is not None and seg in ("reference_flow", "ref_flow")
                        and project is not None):
                    try:
                        text = (Path(project) / rel).read_text(errors="replace")
                    except OSError:
                        return f"off-limits tree segment ({seg}/)"
                    return (f"oracle QoR rules under {seg}/"
                            if rfb.is_oracle_qor_rules(text) else None)
                return f"off-limits tree segment ({seg}/)"
    try:
        import blindness_audit as ba            # noqa: PLC0415
    except Exception:                           # noqa: BLE001
        return None
    kind = ba._classify_rel(str(rel))
    return kind if kind.startswith("hidden oracle file") else None


def deny_segments() -> List[str]:
    """The concrete off-limits segments, resolved HERE in the parent.

    Handed to the child as data so the shim classifies NOTHING. The first
    version had the shim carry its own `_ORACLE_DIRS = ("score",
    "canonical_samples")` and its own regex — duplicated on the sound reasoning
    that "a guard that fails to import is a guard that silently does not run",
    but the consequence was two definitions with nothing pinning them together.
    Resolving in the parent keeps the no-import property AND removes the second
    definition, which is strictly better than either.
    """
    out = set()
    try:
        import _reference_flow_boundary as rfb  # noqa: PLC0415
        out |= set(rfb.OFF_LIMITS_TREE_SEGMENTS)
    except Exception:                           # noqa: BLE001
        pass
    # The benchmark-scoring channels, from the other authority.
    out |= {"score", "canonical_samples"}
    return sorted(out)


# --------------------------------------------------------------------------- #
# The declaration — READ FROM THE FLOW, never duplicated
# --------------------------------------------------------------------------- #
def declared_scope(step_id: str, flow_def: Path) -> List[str]:
    """Project-relative path SPECS step `step_id` declared it reads/writes.

    Inputs come from `required_inputs` expanded through the producing step's
    own `required_outputs` (the same `expand` the declaration checker uses, so
    the two cannot disagree); outputs are included because a step must be able
    to write what it declared it produces.
    """
    import step_required_inputs_check as sri  # noqa: PLC0415
    steps, err = sri.load_flow(Path(flow_def))
    if err:
        return []
    by_id = {str(s.get("id")): s for s in steps}
    step = by_id.get(str(step_id))
    if step is None:
        return []
    specs: List[str] = []
    for entry in (step.get("required_inputs") or []):
        try:
            pairs = sri.expand(entry, by_id)
        except (KeyError, TypeError):
            continue
        for _producer, spec in pairs:
            if spec:
                specs.extend(_split_alternatives(str(spec)))
    for spec in (step.get("required_outputs") or []):
        specs.extend(_split_alternatives(str(spec)))
    return sorted(set(specs))


def _split_alternatives(spec: str) -> List[str]:
    """`"a/* OR b/*"` -> `["a/*", "b/*"]`. The flow writes alternatives inline."""
    return [p.strip() for p in spec.split(" OR ") if p.strip()]


def in_declared_scope(rel: str, specs: Sequence[str]) -> bool:
    """Does `rel` match a declared spec, or sit under a declared directory?"""
    rel = rel.replace("\\", "/").lstrip("./")
    for spec in specs:
        s = spec.replace("\\", "/").lstrip("./")
        if fnmatch.fnmatch(rel, s) or fnmatch.fnmatch(rel, s.rstrip("/") + "/*"):
            return True
        # A declared DIRECTORY covers what is under it: the flow declares
        # `reports/phase3/` and the step writes `reports/phase3/sta.json`.
        if s.endswith("/") and rel.startswith(s):
            return True
    return False


def denies(rel: str, specs: Sequence[str]) -> Optional[str]:
    """Reason `rel` is refused, or None. Declaration WINS over the deny-list."""
    if in_declared_scope(rel, specs):
        return None
    return oracle_reason(rel)


# --------------------------------------------------------------------------- #
# Channel 1 — the environment
# --------------------------------------------------------------------------- #
def scrub_env(env: Dict[str, str], project: Path,
              specs: Sequence[str]) -> Tuple[Dict[str, str], List[str]]:
    """Drop every variable whose VALUE names a denied path under `project`.

    Returns (new env, names removed). This is the half that is complete for
    its channel: a variable that is not in the environment cannot be read out
    of it, which is the ORFS property.
    """
    root = Path(project).resolve()
    out, removed = dict(env), []
    for name, value in list(env.items()):
        if not value or os.sep not in str(value):
            continue
        for token in str(value).split(os.pathsep):
            token = token.strip()
            if not token:
                continue
            try:
                rel = Path(token).resolve().relative_to(root).as_posix()
            except (ValueError, OSError):
                continue
            if denies(rel, specs):
                out.pop(name, None)
                removed.append(name)
                break
    return out, sorted(set(removed))


# --------------------------------------------------------------------------- #
# Channel 2 — the filesystem, for Python children
# --------------------------------------------------------------------------- #
_SITECUSTOMIZE = '''\
# Generated by vibe-ic step_input_scope (#1079). §4.05 enforcement.
import json, os, sys, fnmatch

_ROOT = os.environ.get("VIBEIC_STEP_SCOPE_PROJECT") or ""
try:
    _ALLOW = json.loads(os.environ.get("VIBEIC_STEP_SCOPE_ALLOW") or "[]")
except Exception:
    _ALLOW = []
_STEP = os.environ.get("VIBEIC_STEP_SCOPE_STEP") or "?"

# RESOLVED IN THE PARENT AND HANDED DOWN. The shim classifies NOTHING: it
# matches against the list it was given. That keeps the "never import from the
# child" property that made the first version duplicate the classifier, while
# removing the second definition that duplication created.
try:
    _DENY = json.loads(os.environ.get("VIBEIC_STEP_SCOPE_DENY") or "[]")
except Exception:
    _DENY = []
_FILE_PAT = os.environ.get("VIBEIC_STEP_SCOPE_DENY_FILE_RE") or ""

# LIVENESS. Written as this shim's FIRST act. A guard whose failure mode is a
# green tick is not a guard, so the parent refuses a run whose marker is absent
# rather than reporting it enforced.
_MARK = os.environ.get("VIBEIC_STEP_SCOPE_MARKER") or ""
if _MARK:
    try:
        with open(_MARK, "w") as _fh:
            _fh.write("loaded")
    except Exception:
        pass


def _oracle(rel):
    parts = [p.lower() for p in rel.split("/")]
    for d in _DENY:
        if d in parts:
            return "off-limits tree segment (%s/)" % d
    base = parts[-1] if parts else ""
    if _FILE_PAT:
        import re as _re
        if _re.search(_FILE_PAT, base, _re.IGNORECASE):
            return "hidden oracle file (test/ref/golden)"
    return None


def _allowed(rel):
    for s in _ALLOW:
        s = s.lstrip("./")
        if fnmatch.fnmatch(rel, s) or fnmatch.fnmatch(rel, s.rstrip("/") + "/*"):
            return True
        if s.endswith("/") and rel.startswith(s):
            return True
    return False


def _hook(event, args):
    if event != "open" or not _ROOT:
        return
    path = args[0]
    if isinstance(path, int):
        return
    if isinstance(path, bytes):
        try:
            path = path.decode()
        except Exception:
            return
    if not isinstance(path, str):
        return
    try:
        ap = os.path.abspath(path)
    except Exception:
        return
    if not ap.startswith(_ROOT.rstrip(os.sep) + os.sep):
        return
    rel = os.path.relpath(ap, _ROOT).replace(os.sep, "/")
    if _allowed(rel):
        return
    why = _oracle(rel)
    if why:
        raise PermissionError(
            "vibe-ic §4.05: step %s may not read %s (%s). It is not among the "
            "step's required_inputs in the flow definition." % (_STEP, rel, why))


if _ROOT:
    sys.addaudithook(_hook)
'''


def install_guard(tmpdir: Path) -> Path:
    """Write the `sitecustomize` that installs the audit hook. Returns its dir.

    The hook is DUPLICATED here rather than imported from this module on
    purpose: it runs inside a child that may have no path to the plugin, and a
    guard that fails to import is a guard that silently does not run.
    """
    d = Path(tmpdir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "sitecustomize.py").write_text(_SITECUSTOMIZE, encoding="utf-8")
    return d


# --------------------------------------------------------------------------- #
# The launcher entry point
# --------------------------------------------------------------------------- #
def child_env(base_env: Optional[Dict[str, str]],
              *,
              project: Optional[Path],
              step_id: Optional[str],
              guard_dir: Optional[Path] = None,
              flow_def: Optional[Path] = None) -> Tuple[Optional[Dict[str, str]], Dict[str, Any]]:
    """The environment a step's child should get. OFF -> unchanged, and None
    stays None so a caller that passed nothing still inherits, byte-for-byte as
    before this module existed."""
    meta: Dict[str, Any] = {"enforced": False}
    if not enforcement_enabled(base_env if base_env is not None else None):
        return base_env, meta
    if project is None or step_id is None:
        meta["why"] = "no project/step; nothing to scope"
        return base_env, meta

    root = Path(project).resolve()
    flow = Path(flow_def) if flow_def else (_HERE.parent / DEFAULT_FLOW_REL)
    specs = declared_scope(str(step_id), flow)

    env = dict(os.environ if base_env is None else base_env)
    env, removed = scrub_env(env, root, specs)
    env[ENV_PROJECT] = str(root)
    env[ENV_ALLOW] = json.dumps(specs)
    env[ENV_STEP] = str(step_id)
    # The boundary, resolved HERE with the real authority and handed down as
    # data. The child classifies nothing.
    deny = deny_segments()
    env[ENV_DENY] = json.dumps(deny)
    env[ENV_DENY_FILE_RE] = DENY_FILENAME_RE
    marker = None
    if guard_dir is not None:
        gd = install_guard(Path(guard_dir))
        prior = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(gd) + (os.pathsep + prior if prior else "")
        marker = Path(guard_dir) / "vibeic_scope_loaded"
        env[ENV_MARKER] = str(marker)
    meta.update({"enforced": True, "step": str(step_id),
                 "declared_specs": len(specs), "env_removed": removed,
                 "deny_segments": len(deny),
                 "marker": str(marker) if marker else None,
                 "guard": str(guard_dir) if guard_dir else None})
    return env, meta


def liveness(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Did the guard actually load in the child? Call AFTER the child exits.

    An enforcement whose failure mode is a green tick is not an enforcement.
    A `sitecustomize` can silently fail to load for reasons the parent cannot
    see from here — `-S`, `-E`, a `PYTHONPATH` the child rewrote, an
    interpreter that is not CPython. So the claim `enforced: True` is not
    allowed to stand on having SET the variables; it has to be confirmed by the
    child having written the marker.

    Mutates and returns `meta`: `enforced` drops to False and `liveness` says
    why, so a caller reading the record cannot mistake "we asked for it" for
    "it happened".
    """
    if not meta.get("enforced"):
        return meta
    mark = meta.get("marker")
    if not mark:
        # No guard dir was requested: env scrubbing happened, the in-child hook
        # did not. Say which, rather than claiming both.
        meta["liveness"] = "no in-child guard requested (env scrub only)"
        return meta
    if Path(mark).is_file():
        meta["liveness"] = "confirmed"
        return meta
    meta["enforced"] = False
    meta["liveness"] = ("REFUSED: the in-child guard left no liveness marker, "
                        "so §4.05 was NOT enforced in this child. Reporting it "
                        "as enforced would be an enforcement whose failure "
                        "mode is a green tick.")
    return meta


def main(argv: Optional[List[str]] = None) -> int:
    """Inspection only: print what a step would be allowed to read."""
    import argparse  # noqa: PLC0415
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step_id")
    ap.add_argument("--flow", default=str(_HERE.parent / DEFAULT_FLOW_REL))
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(list(argv) if argv is not None else None)
    specs = declared_scope(args.step_id, Path(args.flow))
    doc = {"step": args.step_id, "declared_specs": specs,
           "enforcement_enabled": enforcement_enabled()}
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(doc, indent=1) + "\n")
    print(f"step {args.step_id}: {len(specs)} declared path spec(s)")
    for s in specs:
        print(f"  {s}")
    if not specs:
        print("[INFO] this step declares no required_inputs — the deny-list "
              "applies with no carve-out", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
