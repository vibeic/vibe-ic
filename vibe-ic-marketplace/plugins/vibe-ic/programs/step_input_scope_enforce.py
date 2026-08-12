#!/usr/bin/env python3
"""step_input_scope_enforce.py — §4.05 as a MECHANISM, not a review finding.

THIS GATE BLOCKS (rc=1). It REFUSES (rc=2) rather than passing when it could
not observe anything.

WHY THIS FILE EXISTS  (vibe-ic#1079)
====================================
§4.05 says a program reads only the design INPUT — never the oracle, harness or
golden. Today that is enforced by Step-2.7 adversarial review: by a human or an
agent NOTICING. OpenROAD-flow-scripts enforces the equivalent boundary by
REMOVAL — `flow/scripts/util.tcl:164-180` `erase_non_stage_variables` calls
`unset ::env($var)` for every variable a stage did not declare, so an
out-of-stage read is not a finding to be caught, it is a state that cannot
occur.

A rule stated where it cannot act is a rule that will eventually be broken
silently. That is the same conclusion the "checks that lie" campaign keeps
arriving at, and §4.05 is currently stated in exactly that position.

WHY THIS IS NOT ORFS'S MECHANISM, AND THE MEASUREMENT THAT DECIDED IT
=====================================================================
#1079 proposed the direct translation: declare a per-step ALLOWLIST from the
flow's `required_inputs` and strip everything else. Two measurements say that
would have been a ban rather than a check.

1. THE CHANNEL IS NOT THE ENVIRONMENT. ORFS is env-var driven, so unsetting an
   env var removes the value. Swept over `programs/` — every `os.environ` /
   `getenv` read in the plugin — the whole surface is container images, PDK
   roots and tool paths (`VIBE_PROGRAMS` 14, `EDA_CONTAINER` 9,
   `VIBEIC_EDA_IMAGE` 7, `PDK_ROOT` 2 …). Exactly ONE name in it looks like an
   oracle (`XOR_GOLDEN`). Stripping env vars here would guard a channel the
   leak does not travel on. In this repo the channel is the FILESYSTEM.

2. `required_inputs` DOES EXIST — 56 steps declare it — BUT IT IS NOT AN
   ALLOWLIST. Traced every gate clause's actual `open()` calls on the published
   root `benchmark-data/ic/spm/v1.10.18_sky130A` and matched them against each
   step's own `required_inputs` ∪ `required_outputs`:

       671 project-internal reads observed
       197 covered by the declared scope          = 29%
       474 NOT covered, dominated by reports/ 297, phase1/ 115, phase2/ 49

   71% of legitimate reads are undeclared, because gates routinely read other
   gates' reports. Enforcing the declared set as an allowlist would deny two
   reads in three. A mechanism that has to be disabled to let the flow run is
   not a mechanism.

SO THE RULE IS THE PROHIBITION, WHICH IS WHAT §4.05 ACTUALLY SAYS
================================================================
§4.05 is phrased as a ban ("never the oracle/harness/golden"), not as a
permission. The OFF-LIMITS set is small, enumerable and stable; the permitted
set is neither. This enforces the ban.

AND THE BOUNDARY IS IMPORTED, NEVER RESTATED
--------------------------------------------
`_reference_flow_boundary` is this repo's ONE definition of where §4.05 runs,
and it exists precisely because two shipped programs once held contradictory
positions about the same directory. A second copy of that vocabulary here would
recreate the defect that module was written to end. So the segments come from
it, and so does the MIXED case: a `reference_flow` tree is recipe AND oracle,
and `is_oracle_qor_rules(text)` is what decides per file. A path under
`reference_flow/` is therefore only a violation when its CONTENT is the QoR
oracle — declining to read that artefact is compliance, not a coverage gap.

WHAT WOULD IT LOOK LIKE IF THE ENFORCEMENT WERE BROKEN?
=======================================================
It would look like a clean pass. `sitecustomize` is imported by `site` only if
it is the FIRST one on the path, and a host that already ships one wins
SILENTLY — the shim never loads, nothing is observed, and every run reports no
violation. That answer must not be the same as "there were none", so the shim
writes a liveness marker as its first act and a run whose log lacks it is
rc=2 REFUSED. An enforcement whose failure mode is a green tick is the shape
this whole family of defect is made of.

EXIT CODES
    0  the child ran and opened no OFF-LIMITS path
    1  an OFF-LIMITS path was reached (named, with the segment that earned it)
    2  REFUSED — the shim did not load, so this run establishes nothing
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import _reference_flow_boundary as _rfb  # noqa: E402

FLOW_YAML = HERE.parent / "flow" / "phase1_phase2_phase3.yaml"


def _plugin_programs_on_path() -> None:
    """`programs/` on sys.path once, so the declaration module is importable."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))

#: The shim's first write. Its ABSENCE is the only thing separating "nothing
#: was reached" from "nothing was watched", and the two must never share a
#: verdict. See the module docstring.
ALIVE = "!\tSCOPE_SHIM_LOADED"

_SHIM = r'''
"""Written by step_input_scope_enforce and put FIRST on PYTHONPATH.

Records — and, unless observing, DENIES — every open() of a path the §4.05
boundary calls oracle. Deliberately tiny: it runs inside every child process
of the step under enforcement, so anything it imports it pays for on every
fork.
"""
import os

_log = os.environ.get("VIBEIC_SCOPE_LOG")
_root = os.path.abspath(os.environ.get("VIBEIC_SCOPE_ROOT", "."))
_deny = os.environ.get("VIBEIC_SCOPE_DENY") == "1"
_segs = frozenset((os.environ.get("VIBEIC_SCOPE_SEGMENTS") or "").split(":")) - {""}
_declared = frozenset(
    (os.environ.get("VIBEIC_SCOPE_DECLARED") or "").split("\n")) - {""}
_oracle_files = {}
for _e in (os.environ.get("VIBEIC_SCOPE_ORACLE_FILES") or "").split("\n"):
    if "\t" in _e:
        _rel, _seg = _e.split("\t", 1)
        _oracle_files[_rel] = _seg

if _log:
    _f = open(_log, "a", buffering=1)
    _f.write("!\tSCOPE_SHIM_LOADED\n")

    def _offending_segment(rel):
        parts = rel.split(os.sep)
        for p in parts[:-1]:
            if p in _segs:
                return p
        return None

    def _judge(path, write):
        """None, or (segment, relpath) for a path this run may not read."""
        if write or isinstance(path, bytes):
            return None
        try:
            p = os.path.abspath(path)
        except Exception:
            return None
        if not p.startswith(_root + os.sep):
            return None
        rel = os.path.relpath(p, _root)
        # THE DECLARATION WINS. If the flow says this step reads this artefact,
        # the ban does not apply to it -- a step cannot be denied its own
        # declared input. This is the ONE place `required_inputs` is
        # load-bearing here, and it is used as an EXCEPTION rather than as an
        # allow-list, for the reason measured in the module docstring: the
        # declared set covers 29% of real reads, so as an allow-list it denies
        # two reads in three.
        if rel in _declared:
            return None
        seg = _offending_segment(rel)
        if seg:
            return (seg, rel)
        # MIXED tree: recipe and oracle live side by side and only the CONTENT
        # decides. That judgement is the AUTHORITY's, so the parent makes it
        # once, with the real `_reference_flow_boundary`, and hands down the
        # resulting file set. The child does membership and nothing else — it
        # must not carry a second copy of a rule this repo already had two
        # contradictory copies of.
        if rel in _oracle_files:
            return (_oracle_files[rel], rel)
        return None

    # INTERCEPTION IS AN AUDIT HOOK, not a rebinding of `io.open`.
    #
    # A first draft patched `io.open` / `builtins.open` / `os.open`. That is
    # weaker in three ways that all end the same place — a read the enforcement
    # cannot see:
    #   * `import io; io.open(...)` re-fetched from the module still went
    #     through the patched name, but a module that captured `open` BEFORE
    #     the shim loaded did not;
    #   * a C extension opening a file never touches either Python name;
    #   * anything reached through `os.fdopen`, `pathlib`'s internal accessor,
    #     or a future CPython refactor of where `open` actually lives.
    # `sys.addaudithook` sits under all of them: CPython raises the `open`
    # audit event from the C layer, so the hook sees the call however it was
    # spelled, and a hook cannot be removed once installed.
    #
    # Adopted from the sibling implementation on #1093, which reached the audit
    # hook first; the oracle VOCABULARY below is the half that one is missing.
    import sys

    def _audit(event, args):
        if event != "open" or not args:
            return
        path, mode, flags = (list(args) + [None, None])[:3]
        if not isinstance(path, (str, os.PathLike)):
            return
        # BOTH arms of the event, because the two callers fill different slots:
        # `io.open(p, "w")` carries the MODE STRING and `os.open(p, flags)`
        # carries the INT. Reading only one would let half the writes be judged
        # as reads and fire on the flow's own output.
        write = bool(
            (isinstance(mode, str) and any(c in mode for c in "wax+"))
            or (isinstance(flags, int)
                and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)))
        hit = _judge(os.fspath(path), write)
        if not hit:
            return
        _f.write("X\t%s\t%s\n" % hit)
        if _deny:
            raise PermissionError(
                "vibe-ic 4.05: %s is OFF-LIMITS oracle (segment %r)"
                % (hit[1], hit[0]))

    sys.addaudithook(_audit)
'''

def resolve_oracle_files(project: Path, cap: int = 20000) -> List[Tuple[str, str]]:
    """Every file under a MIXED tree whose CONTENT the authority calls oracle.

    Computed HERE, in the parent, with the real `_reference_flow_boundary`, and
    handed to the child as a set. The alternative — teaching the shim the
    content rule — would put a second copy of the §4.05 boundary in the tree,
    which is the exact defect `_reference_flow_boundary` was written to end
    ("two shipped programs disagreed").

    A `reference_flow` tree is RECIPE + ORACLE, so walking it and judging by
    name would ban the recipe the flow is supposed to read. Judged by content,
    per file, per that module's own predicate.
    """
    out: List[Tuple[str, str]] = []
    seen = 0
    for seg in sorted(_rfb.REFERENCE_FLOW_TREE_SEGMENTS):
        for d in sorted(project.rglob(seg)):
            if not d.is_dir():
                continue
            for f in sorted(d.rglob("*")):
                seen += 1
                if seen > cap:
                    return out
                try:
                    if not f.is_file():
                        continue
                    text = f.read_text(errors="replace")[:200000]
                except OSError:
                    continue
                if _rfb.is_oracle_qor_rules(text):
                    out.append((str(f.relative_to(project)), seg))
    return out


def declared_paths(project: Path, step_id: Optional[str],
                   flow: Optional[Path] = None) -> List[str]:
    """Concrete files this step DECLARED it reads, resolved on this tree.

    Read through `step_required_inputs_check` — the same module the declaration
    CHECKER uses — so the enforcement and the check cannot disagree about what
    a step declared. Returns [] when no step is named: an enforcement with no
    declaration to consult must ban the oracle, not guess at exceptions.
    """
    if not step_id:
        return []
    try:
        _plugin_programs_on_path()
        import step_required_inputs_check as sri  # noqa: PLC0415
        steps, err = sri.load_flow(Path(flow) if flow else FLOW_YAML)
        if err:
            return []
    except Exception:                                          # pragma: no cover
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
            for atom in str(spec or "").split(" OR "):
                atom = atom.strip()
                if atom and atom != ".":
                    specs.append(atom)
    out: List[str] = []
    for spec in specs:
        for hit in sorted(project.glob(spec)):
            if hit.is_file():
                out.append(str(hit.relative_to(project)))
    return out


def scrub_env(env: dict, project: Path, oracle_rels: List[str]) -> Tuple[dict, List[str]]:
    """Remove any variable whose VALUE names a denied path under the project.

    The SECOND channel. ORFS's is the only channel because ORFS steps take
    their inputs through named variables; ours mostly do not (measured in the
    module docstring: the whole env surface is container images, PDK roots and
    tool paths). It is cheap and it is real, so it is closed too — but it is
    not where the leak travels here, and saying otherwise would be the census's
    own "guard the channel nobody uses" defect.
    """
    denied = {str((project / r).resolve()) for r in oracle_rels}
    dropped: List[str] = []
    out = dict(env)
    for k, v in list(env.items()):
        if not isinstance(v, str) or "/" not in v:
            continue
        for tok in v.split(os.pathsep):
            tok = tok.strip()
            if not tok:
                continue
            try:
                if str(Path(tok).resolve()) in denied:
                    out.pop(k, None)
                    dropped.append(k)
                    break
            except OSError:
                continue
    return out, dropped


def write_shim(where: Path) -> Path:
    where.mkdir(parents=True, exist_ok=True)
    (where / "sitecustomize.py").write_text(_SHIM, encoding="utf-8")
    return where


def run_scoped(argv: List[str], project: Path, deny: bool = True,
               timeout: int = 55, shim_dir: Optional[Path] = None,
               step_id: Optional[str] = None, flow: Optional[Path] = None,
               scrubbed: Optional[List[str]] = None,
               ) -> Tuple[int, str, Optional[List[Tuple[str, str]]]]:
    """Run `argv` in `project`, returning (rc, output, violations).

    `violations is None` means the shim did not load — the caller must REFUSE,
    never treat it as an empty list.
    """
    tmp = None
    if shim_dir is None:
        tmp = tempfile.mkdtemp(prefix="scope")
        shim_dir = write_shim(Path(tmp) / "shim")
    log = shim_dir / "scope.log"
    log.write_text("", encoding="utf-8")
    oracle_rels = [rel for rel, _seg in resolve_oracle_files(project)]
    base_env, dropped = scrub_env(dict(os.environ), project, oracle_rels)
    if scrubbed is not None:
        scrubbed.extend(dropped)
    env = {
        **base_env,
        "PYTHONDONTWRITEBYTECODE": "1",
        "VIBEIC_SCOPE_DECLARED": "\n".join(
            declared_paths(project, step_id, flow)),
        "VIBEIC_SCOPE_LOG": str(log),
        "VIBEIC_SCOPE_ROOT": str(project.resolve()),
        "VIBEIC_SCOPE_DENY": "1" if deny else "0",
        "VIBEIC_SCOPE_SEGMENTS": ":".join(sorted(_rfb.ORACLE_TREE_SEGMENTS)),
        "VIBEIC_SCOPE_ORACLE_FILES": "\n".join(
            f"{rel}\t{seg}" for rel, seg in resolve_oracle_files(project)),
        "PYTHONPATH": os.pathsep.join(
            [str(shim_dir)] + ([os.environ["PYTHONPATH"]]
                               if os.environ.get("PYTHONPATH") else [])),
    }
    try:
        proc = subprocess.run(argv, cwd=str(project), capture_output=True,
                              text=True, timeout=timeout, env=env)
        rc, out = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        rc, out = 124, "<TIMEOUT>"
    except OSError as exc:
        rc, out = 127, f"<NOT RUNNABLE: {exc}>"
    raw = log.read_text(errors="replace").splitlines()
    if ALIVE not in raw:
        return rc, out, None
    hits = [tuple(ln.split("\t")[1:3]) for ln in raw
            if ln.startswith("X\t") and len(ln.split("\t")) >= 3]
    return rc, out, [(a, b) for a, b in hits]


#: The switch that turns OBSERVE into DENY. Default is observe, and that is a
#: deliberate, stated choice rather than timidity: this hook runs inside the
#: one-shot runners themselves, so a misfire does not produce one red gate, it
#: makes every run of the flow fail. Observe-by-default makes the mechanism
#: REACHABLE — it records and reports — while `VIBEIC_SCOPE_DENY=1` makes the
#: violation impossible. `step_preflight`'s own docstring names the failure this
#: avoids on the other side ("the check was available; the BEHAVIOUR did not
#: exist"), and recording every read is behaviour, not availability.
DENY_SWITCH = "VIBEIC_SCOPE_DENY"

#: Every violation this process observed, in order. Read by the runners for
#: their own report; never reset, because a cleared record and a clean run must
#: not look the same.
OBSERVED: List[Tuple[str, str]] = []


def install(project: Path, step_id: Optional[str] = None,
            deny: Optional[bool] = None, flow: Optional[Path] = None) -> bool:
    """Install the §4.05 boundary in THIS process. Returns whether it denies.

    The CLI (`run_scoped`) enforces on a CHILD. This enforces on the caller,
    which is where the runners actually read the design: `phase1_one_shot_runner`
    ingesting documents into L1-L27 is the §4.05-sensitive path, and it happens
    in-process, so a child-only mechanism would never see it.

    Idempotent by construction — `sys.addaudithook` cannot be removed, so a
    second install would double-record. Guarded by a module flag.
    """
    global _INSTALLED, _INSTALLED_DENIES
    if _INSTALLED:
        return _INSTALLED_DENIES
    if deny is None:
        deny = str(os.environ.get(DENY_SWITCH, "")).strip() not in ("", "0", "false", "False")
    root = str(project.resolve())
    segs = frozenset(_rfb.ORACLE_TREE_SEGMENTS)
    oracle = {rel: seg for rel, seg in resolve_oracle_files(project)}
    declared = frozenset(declared_paths(project, step_id, flow))

    def _judge(path: str, write: bool) -> Optional[Tuple[str, str]]:
        if write:
            return None
        try:
            ap = os.path.abspath(path)
        except (OSError, ValueError):
            return None
        if not ap.startswith(root + os.sep):
            return None
        rel = os.path.relpath(ap, root)
        if rel in declared:
            return None
        for part in rel.split(os.sep)[:-1]:
            if part in segs:
                return (part, rel)
        if rel in oracle:
            return (oracle[rel], rel)
        return None

    def _audit(event: str, args: tuple) -> None:
        if event != "open" or not args:
            return
        path, mode, flags = (list(args) + [None, None])[:3]
        if not isinstance(path, (str, os.PathLike)):
            return
        write = bool((isinstance(mode, str) and any(c in mode for c in "wax+"))
                     or (isinstance(flags, int)
                         and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)))
        hit = _judge(os.fspath(path), write)
        if hit is None:
            return
        OBSERVED.append(hit)
        if deny:
            raise PermissionError(
                f"vibe-ic 4.05: {hit[1]} is OFF-LIMITS oracle (segment {hit[0]!r})")

    sys.addaudithook(_audit)
    _INSTALLED = True
    _INSTALLED_DENIES = deny
    return deny


_INSTALLED = False
_INSTALLED_DENIES = False


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", type=Path, required=True,
                    help="the design tree; only paths INSIDE it are judged")
    ap.add_argument("--step", default=None,
                    help="flow step id, recorded in the report for provenance")
    ap.add_argument("--observe-only", action="store_true",
                    help="record violations but let the read succeed. This is "
                         "the OFF arm of the two-arm control: with enforcement "
                         "off the step must still finish.")
    ap.add_argument("--timeout", type=int, default=55)
    ap.add_argument("--json", type=Path)
    ap.add_argument("cmd", nargs=argparse.REMAINDER,
                    help="-- followed by the command to run")
    args = ap.parse_args(argv)

    cmd = [c for c in args.cmd if c != "--"]
    if not cmd:
        print("REFUSE — no command given. An enforcement with nothing to "
              "enforce on is not a pass.")
        return 2
    if not args.project.is_dir():
        print(f"REFUSE — project {args.project} is not a directory.")
        return 2

    scrubbed: List[str] = []
    rc, out, hits = run_scoped(cmd, args.project, deny=not args.observe_only,
                               timeout=args.timeout, step_id=args.step,
                               scrubbed=scrubbed)
    report = {"step": args.step, "project": str(args.project), "cmd": cmd,
              "env_scrubbed": sorted(set(scrubbed)),
              "declared_exceptions": len(declared_paths(args.project, args.step)),
              "child_rc": rc, "enforced": not args.observe_only,
              "segments": sorted(_rfb.ORACLE_TREE_SEGMENTS),
              "mixed_segments": sorted(_rfb.REFERENCE_FLOW_TREE_SEGMENTS)}

    if hits is None:
        report["verdict"] = "REFUSED"
        report["reason"] = "the enforcement shim did not load"
        print("REFUSED — the §4.05 shim did not load, so NOTHING was observed "
              "and this run establishes nothing. A host `sitecustomize` earlier "
              "on PYTHONPATH is the usual cause.")
        _emit(args.json, report)
        return 2

    report["violations"] = [{"segment": s, "path": p} for s, p in hits]
    if hits:
        report["verdict"] = "FAIL"
        verb = "was DENIED" if not args.observe_only else "was allowed (observe-only)"
        print(f"[FAIL] §4.05: {len(hits)} OFF-LIMITS read(s) reached; each {verb}:")
        for seg, rel in dict.fromkeys(hits):
            print(f"   {rel}   [segment {seg!r} — oracle by "
                  f"_reference_flow_boundary]")
        print(f"  child rc={rc}")
        _emit(args.json, report)
        return 1

    report["verdict"] = "PASS"
    print(f"[PASS] §4.05 enforced: no OFF-LIMITS path reached "
          f"({len(_rfb.ORACLE_TREE_SEGMENTS)} oracle segment(s) + "
          f"{len(_rfb.REFERENCE_FLOW_TREE_SEGMENTS)} mixed tree(s) watched); "
          f"child rc={rc}")
    _emit(args.json, report)
    return 0


def _emit(path: Optional[Path], report: dict) -> None:
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
