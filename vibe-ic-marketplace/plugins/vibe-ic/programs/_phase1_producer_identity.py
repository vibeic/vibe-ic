#!/usr/bin/env python3
"""_phase1_producer_identity.py — are the generated L docs what THIS producer
would write? (FX_STALE_LDOCS)

THE MEASURED DEFECT
-------------------
The front door skipped Phase 1 whenever 13 L documents existed. So a Phase-1
PRODUCER fix never reached an existing project: MEASURED on subservient
(8HD-4, 2026-09-28, lane fxtb FX_P2 arm f4), an exact fresh copy of a tree
whose L1 had been written by the pre-fix producer kept FAILing
`l1_pin_table_aliases_typed_check` after the fix had landed in the producer;
only deleting `phase1/generated_docs` let the fix through (arm f5). A skip
keyed on "the files exist" instead of "these files are what the current
producer would write" is a stale cache.

The version stamp every L doc already carries (`_generator.plugin_version`)
could not have caught it: the pre-fix L1 and the fixed producer both said
1.25.64, because a version is assigned only at landing. What changed was CODE.

WHAT THIS RECORDS, AND WHERE
----------------------------
The flow's existing per-step identity, not a parallel record: `_step_identity`'s
sidecar (`phase1/step_identity.json`, kind `phase1`) and `_step_recorder`'s
whole-file record form. Phase 1 runs inside `with ProducerRecorder()` -- a
`subprocess.Popen` watch plus one `sys.addaudithook` 'open' hook, no profiler
-- and stamps, as its last act, ONLY when it actually dispatched D1:

  code          every plugin-root module it loaded, every plugin script or
                `-m` module it launched (top-level import closure), and every
                NON-.py plugin file it READ (registries, schemas, known-answer
                vectors, the flow yaml)                     [review wave8 M3]
  inputs        the design input it READ or LISTED under input/ and
                phase1/input_doc/, minus every file phase 1 itself created or
                rewrote there (in any process: step 0.5ic's declaration, which
                phase 3 rewrites again), minus the §4.05 set asked of
                `step_input_scope.oracle_reason`, plus the knobs it consumed
                (--ic-name, --pdk, --mode)            [review wave8 B1, M3, §4.05]
  outputs       sha256 of the L docs THIS run wrote; any other doc on disk is
                `carried` and forces a regeneration          [review wave8 M4]
  derivations   later FLOW rewrites (recorded at `l_doc_generator_stamp.dump`
                in any process, and by the front door for any doc a later phase
                changed while it ran): who, from, to        [review wave8 B2]

The stamp is VOIDED the moment D1 starts, so a run that dies mid-regeneration
leaves NO_PRODUCER_IDENTITY, never an old stamp vouching for new docs.

WHAT THE FRONT DOOR DECIDES (`assess`)
--------------------------------------
  REUSE       every doc holds its recorded bytes (or a recorded derivation's),
              the producer re-derives to the same digest from CURRENT source,
              the knobs match and the design input it read is unchanged.
  REGENERATE  NO_PRODUCER_IDENTITY, PRODUCER_CHANGED, KNOBS_CHANGED,
              DESIGN_INPUT_CHANGED, GENERATED_DOC_REMOVED,
              GENERATED_DOC_NOT_WRITTEN. The front door first moves the stale
              docs aside (`supersede_docs`, under .vibeic-state/).
  REFUSE      GENERATED_DOC_EDITED: a doc changed and NO flow writer recorded
              the change. Neither overwritten nor reused as current; the reason
              names the two ways out.

INPUT documents are never judged here: they are the design input. A project
whose L docs have no design input behind them was HANDED its L docs, and the
caller keeps them (see `vibe_ic_one_shot_runner._phase1_decision`).

FAILS CLOSED like its parent: a component that cannot be established is a
mismatch, and a mismatch regenerates. Reuse needs positive proof.
chip-AGNOSTIC: paths and digests only.
"""
from __future__ import annotations

import os as _os
import sys as _sys

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import _path_layout as _pl
import _step_identity as _si

KIND = "phase1"
REUSE = "REUSE"
REVALIDATE = "REVALIDATE"
REGENERATE = "REGENERATE"
REFUSE = "REFUSE"

NO_PRODUCER_IDENTITY = "NO_PRODUCER_IDENTITY"
PRODUCER_CHANGED = "PRODUCER_CHANGED"
DESIGN_INPUT_CHANGED = "DESIGN_INPUT_CHANGED"
KNOBS_CHANGED = "KNOBS_CHANGED"
GENERATED_DOC_REMOVED = "GENERATED_DOC_REMOVED"
GENERATED_DOC_NOT_WRITTEN = "GENERATED_DOC_NOT_WRITTEN"
GENERATED_DOC_EDITED = "GENERATED_DOC_EDITED"


class SupersedeError(OSError):
    """Archiving stale L docs failed; callers must refuse regeneration."""

#: The plugin root: `programs/`, `tools/` (the phase-1 engine), `data/`
#: (known-answer vectors), registries and schemas all live under it. The
#: producer is recorded at THIS granularity, not `programs/` (review wave8).
PLUGIN_ROOT = Path(__file__).resolve().parent.parent

#: The knobs phase 1 consumes that change L-doc bytes (review wave8: `--pdk`
#: selects PDK-keyed rows, `--ic-name` becomes L1 chip_name / L10 ic_name).
KNOB_NAMES = ("ic_name", "pdk", "mode")

# This fixed, Expert-authored INPUT is consumed by the normal L9 producer.
# Its absence is recorded too: adding a first choice must invalidate reuse.
# Other plugin_input files are not made Phase-1 inputs by these boundaries.
QUALIFIED_OUTPUT_INPUT = "plugin_input/qualified-outputs.json"
INTERFACE_BINDING_INPUT = "plugin_input/interface-bindings.json"
BEHAVIORAL_REFINEMENT_INPUT = "phase1/behavioral_refinement.facts.yaml"
FIXED_AUTHOR_INPUTS = (QUALIFIED_OUTPUT_INPUT, INTERFACE_BINDING_INPUT,
                       BEHAVIORAL_REFINEMENT_INPUT)
INTERFACE_CONTEXT = "plugin_input/interface_context"


def _fixed_author_input_hash(project: Path, rel: str) -> Optional[str]:
    path = Path(project)
    for part in Path(rel).parts:
        path = path / part
        if path.is_symlink():
            return "INVALID_AUTHOR_SYMLINK"
    return _sha256(path)


def _qualified_output_input_hash(project: Path) -> Optional[str]:
    return _fixed_author_input_hash(project, QUALIFIED_OUTPUT_INPUT)


def _oracle_reason(rel: str) -> Optional[str]:
    """§4.05 — the ONE authority (`step_input_scope.oracle_reason`, which
    unions `_reference_flow_boundary.OFF_LIMITS_TREE_SEGMENTS` with the
    scoring-oracle filename forms). Never restated here."""
    import step_input_scope as _sis
    return _sis.oracle_reason(rel)


# ---------------------------------------------------------------------------
# what phase 1 READ, WROTE and LISTED -- one audit hook, no profiler
# ---------------------------------------------------------------------------
_ACTIVE: List["ProducerRecorder"] = []
_HOOK_INSTALLED = False
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def _abs(path: Any) -> Optional[str]:
    if isinstance(path, bytes):
        try:
            path = os.fsdecode(path)
        except Exception:                                  # noqa: BLE001
            return None
    if isinstance(path, os.PathLike):
        path = os.fspath(path)
    if not isinstance(path, str) or not path:
        return None
    return path if os.path.isabs(path) else os.path.join(os.getcwd(), path)


def _audit(event: str, args: Tuple[Any, ...]) -> None:
    """Record only; never touch the filesystem here (it would re-enter)."""
    if not _ACTIVE:
        return
    rec = _ACTIVE[-1]
    try:
        if event == "open":
            p = _abs(args[0])
            if p is None:
                return
            mode, flags = args[1], args[2]
            wrote = (any(c in mode for c in "wax+") if isinstance(mode, str)
                     else bool((flags or 0) & _WRITE_FLAGS))
            (rec._writes if wrote else rec._reads).add(p)
        elif event in ("os.rename", "os.replace"):
            p = _abs(args[1])
            if p is not None:
                rec._writes.add(p)
        elif event in ("os.listdir", "os.scandir"):
            p = _abs(args[0]) if args and args[0] is not None \
                else os.getcwd()
            if p is not None:
                rec._listed.add(p)
    except Exception:                                      # noqa: BLE001
        pass


def _install_hook() -> None:
    global _HOOK_INSTALLED
    if not _HOOK_INSTALLED:
        sys.addaudithook(_audit)       # permanent by design; idle when unused
        _HOOK_INSTALLED = True


#: The plugin MANIFEST directory. Phase 1 reads it for the release version,
#: which reaches an L doc only through the `_generator` stamp -- and that
#: stamp's drift is already judged, with a tolerance, by
#: `l_doc_generator_stamp`. Measured on subservient (.120): with it recorded,
#: every landing (a version bump) would read as PRODUCER_CHANGED on every
#: project and demote every window run -- the coarseness review wave8 named.
_RELEASE_METADATA_DIRS = (".claude-plugin",)


def _is_release_metadata(q: Path, root: Path) -> bool:
    try:
        return q.relative_to(root).parts[0] in _RELEASE_METADATA_DIRS
    except (ValueError, IndexError):
        return False


class ProducerRecorder:
    """Which plugin code and data phase 1 USED, and which files it read,
    wrote and listed -- at FILE granularity, with no profiler.

    CODE: every module in `sys.modules` under the plugin root (so importlib /
    lazy imports count), every plugin script phase 1 LAUNCHED -- a `.py`
    token or `-m <module>` (watched at `subprocess.Popen`) -- with its
    TOP-LEVEL import closure (a checker's lazy imports inside functions are
    not followed: review wave8, the 366-file identity), and every NON-.py
    plugin file phase 1 READ (registries, schemas, `data/known_answer_vectors`,
    the flow yaml), recorded through a `sys.addaudithook` 'open' hook. All in
    the step recorder's whole-file entry form, so `_step_identity.
    code_from_stored` re-derives and compares it unchanged.

    MEASURED (subservient, .120): the per-call profiler recorder made phase 1
    ~10x slower; an audit hook fires on file opens only.

    Fails closed: nothing recorded, or an unreadable file, records nothing."""

    def __init__(self, root: Path = PLUGIN_ROOT):
        self._root = Path(root).resolve()
        self._launched: Set[str] = set()
        self._modules_launched: Set[str] = set()
        self._reads: Set[str] = set()
        self._writes: Set[str] = set()
        self._listed: Set[str] = set()
        self._prev_popen = None

    def __enter__(self) -> "ProducerRecorder":
        import subprocess
        _install_hook()
        _ACTIVE.append(self)
        self._prev_popen = subprocess.Popen
        rec = self

        class _WatchedPopen(self._prev_popen):  # type: ignore[misc]
            def __init__(self, args, *a, **k):
                rec._note(args)
                super().__init__(args, *a, **k)
        subprocess.Popen = _WatchedPopen   # type: ignore[assignment]
        return self

    def __exit__(self, *_exc) -> None:
        import subprocess
        if self in _ACTIVE:
            _ACTIVE.remove(self)
        if self._prev_popen is not None:
            subprocess.Popen = self._prev_popen  # type: ignore[assignment]

    def _note(self, argv: Any) -> None:
        import _step_recorder as _sr
        try:
            toks = [argv] if isinstance(argv, str) else [str(x) for x in argv]
        except Exception:                                  # noqa: BLE001
            return
        text = " ".join(toks)
        self._launched.update(_sr._SCRIPT_RE.findall(text))
        for i, t in enumerate(toks[:-1]):
            if t == "-m":
                self._modules_launched.add(toks[i + 1])

    # -- what was used --------------------------------------------------
    def _under_root(self, f: Any, py_only: bool = True) -> Optional[Path]:
        try:
            q = Path(str(f)).resolve()
        except (OSError, ValueError):
            return None
        if (py_only and q.suffix != ".py") or not q.is_file():
            return None
        try:
            rel = q.relative_to(self._root)
        except ValueError:
            return None
        if "__pycache__" in rel.parts or q.suffix in (".pyc", ".pyo"):
            return None
        return q

    def _resolve_module(self, dotted: str) -> Optional[Path]:
        parts = dotted.split(".")
        for base in (self._root / "programs", self._root / "tools",
                     self._root):
            cand = base.joinpath(*parts)
            for q in (cand.with_suffix(".py"), cand / "__main__.py",
                      cand / "__init__.py"):
                if q.is_file():
                    return q
        return None

    def _top_level_closure(self, path: Path, seen: Set[Path]) -> List[Path]:
        """`path` plus the in-tree modules its MODULE BODY imports,
        transitively. An import inside a function is not followed."""
        import ast
        out: List[Path] = []
        stack = [path]
        while stack:
            q = stack.pop()
            try:
                rq = q.resolve()
            except OSError:
                continue
            if rq in seen or not q.is_file():
                continue
            seen.add(rq)
            out.append(rq)
            try:
                tree = ast.parse(q.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            body = list(tree.body)
            i = 0
            while i < len(body):              # top level, incl. if/try bodies
                node = body[i]
                i += 1
                if isinstance(node, (ast.If, ast.Try)):
                    body.extend(getattr(node, "body", []))
                    body.extend(getattr(node, "orelse", []))
                    for h in getattr(node, "handlers", []):
                        body.extend(h.body)
                    continue
                names: List[str] = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module \
                        and not node.level:
                    names = [node.module]
                for dotted in names:
                    m = self._resolve_module(dotted)
                    if m is not None:
                        stack.append(m)
        return out

    def code_files(self) -> Tuple[Set[Path], Set[Path]]:
        """(python code, non-python plugin data) this run used."""
        code: Set[Path] = set()
        for mod in list(sys.modules.values()):
            q = self._under_root(getattr(mod, "__file__", None))
            if q is not None:
                code.add(q)
        seen = set(code)
        roots = []
        for tok in sorted(self._launched):
            for cand in (Path(tok), self._root / tok,
                         self._root / "programs" / Path(tok).name):
                q = self._under_root(cand)
                if q is not None:
                    roots.append(q)
                    break
        for dotted in sorted(self._modules_launched):
            q = self._resolve_module(dotted)
            if q is not None:
                roots.append(q)
        for q in roots:
            code.add(q.resolve())
            code.update(self._top_level_closure(q, seen))
        written = {Path(w).resolve() for w in self._writes}
        data: Set[Path] = set()
        for r in self._reads:
            q = self._under_root(r, py_only=False)
            if q is not None and q.suffix != ".py" and q not in written \
                    and not _is_release_metadata(q, self._root):
                data.add(q)
        return code, data

    def recorded(self):
        """``(record, why_not)`` in the step recorder's format."""
        import _step_recorder as _sr
        code, data = self.code_files()
        files = code | data
        if not code:
            return None, ("no plugin module was loaded by phase 1, so what it "
                          "ran cannot be established")
        out: Dict[str, Dict[str, str]] = {}
        for q in sorted(files):
            h = _sha256(q)
            if h is None:
                return None, f"{q} was used but could not be read"
            out[f"launched:{q.relative_to(self._root).as_posix()}"] = {
                "__whole__": h}
        # A glob of plugin data sees the directory membership before it opens
        # the selected files. Hash the directories it actually enumerated, so
        # adding a new file cannot keep the old L docs stamped CURRENT.
        for listed in sorted(self._listed):
            try:
                q = Path(listed).resolve()
                rel = q.relative_to(self._root)
            except (OSError, ValueError):
                continue
            if not rel.parts or rel.parts[0] != "data" or not q.is_dir():
                continue
            members = _sr.directory_members_digest(q)
            if members is None:
                return None, f"listed plugin data directory {q} is unreadable"
            out[f"listed:{rel.as_posix()}"] = {"__members__": members}
        out["__engine_env__"] = {name: _sr._engine_marker(name)
                                 for name in _sr.ENGINE_ENV}
        return out, ""

    def written_docs(self, project: Path) -> Set[str]:
        """Names of the L docs THIS process wrote under generated_docs."""
        gd = _pl.generated_docs_dir(Path(project)).resolve()
        out = set()
        for w in self._writes:
            q = Path(w)
            try:
                if q.resolve().parent == gd and q.name.startswith("L") \
                        and q.suffix == ".json":
                    out.add(q.name)
            except OSError:
                continue
        return out

    def io(self) -> Dict[str, Set[str]]:
        return {"reads": set(self._reads), "writes": set(self._writes),
                "listed": set(self._listed)}


def has_converged_fact_graph(project: Path) -> bool:
    """The existing structured input already carries the engine's fact schema."""
    path = project / "input/phase1_structured.yaml"
    if not path.is_file():
        return False
    try:
        import yaml
        doc = yaml.safe_load(path.read_text())
    except (OSError, ValueError, yaml.YAMLError):
        return False
    return isinstance(doc, dict) and {"version", "facts", "ic_name", "class_path"} <= doc.keys()


def design_input_mode(project: Path) -> Tuple[bool, str]:
    """Which design input a project carries: `(True, "docs")` when phase 1
    has something to extract from, else `(False, "")`. The ONE predicate the
    front door (`_phase1_decision`) and phase 2's `step_phase1` both ask;
    moved here verbatim from `vibe_ic_one_shot_runner`."""
    project = Path(project)
    if has_converged_fact_graph(project):
        return True, "prompt"
    p1_struct = project / "input" / "phase1_structured.yaml"
    p1_prompt = project / "input" / "phase1_prompt.md"
    docs = project / "input" / "docs"
    input_doc = (_pl.input_doc_dir(project)
                 if hasattr(_pl, "input_doc_dir") else None)

    def _has_extractable(d: Path) -> bool:
        # #583 — "populated" means at least one real, non-empty,
        # non-hidden document (a .gitkeep placeholder must not flip a
        # prompt-only project into docs mode).
        if not d.is_dir():
            return False
        for f in d.rglob("*"):
            if f.is_file() and not f.name.startswith(".") \
                    and f.stat().st_size > 0:
                return True
        return False

    docs_populated = _has_extractable(docs)
    input_doc_populated = bool(input_doc) and _has_extractable(input_doc)
    # UNIFIED DOC->JSON backend (owner directive 2026-06-20): EVERY front-end —
    # vendor docs, a free-text prompt, OR a dialogue convergence fact-graph —
    # flows through the one doc-extraction track so the L1-L24 JSON is
    # homogeneous. So the orchestrator now resolves ALL of them to "docs";
    # phase1_one_shot_runner --mode docs render-bridges a phase1_structured.yaml
    # (dialogue) / phase1_prompt.md (prose) into input/docs/ and re-detects the
    # precise mode. The legacy engine reverse-extractor stays reachable only via
    # an explicit `phase1_one_shot_runner --mode prompt` invocation.
    if (p1_struct.is_file() or docs_populated or input_doc_populated
            or p1_prompt.is_file()):
        return (True, "docs")
    # No inputs at all — phase1 will SKIP gracefully (don't run).
    return (False, "")


# ---------------------------------------------------------------------------
# files
# ---------------------------------------------------------------------------
def sidecar_dir(project: Path) -> Path:
    return Path(project) / "phase1"


def _sha256(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def generated_docs(project: Path) -> List[Path]:
    gd = _pl.generated_docs_dir(Path(project))
    return sorted(gd.glob("L*.json")) if gd.is_dir() else []


def docs_snapshot(project: Optional[Path]) -> Dict[str, Optional[str]]:
    """{L doc name: sha256} — what is on disk now ({} for no project)."""
    if project is None:
        return {}
    return {p.name: _sha256(p) for p in generated_docs(Path(project))}


def _input_roots(project: Path) -> List[Path]:
    roots = [Path(project) / "input", Path(project) / INTERFACE_CONTEXT]
    if hasattr(_pl, "input_doc_dir"):
        roots.append(_pl.input_doc_dir(Path(project)))
    return roots


def _rel(project: Path, p: Path) -> Optional[str]:
    try:
        return Path(p).resolve().relative_to(Path(project).resolve()).as_posix()
    except (OSError, ValueError):
        return None


def input_tree_snapshot(project: Path) -> Dict[str, Tuple[Optional[str], int]]:
    """{rel: (sha256, mtime_ns)} for every design-input-root file (§4.05
    paths excluded -- never opened). Taken before and after phase 1, so a
    file phase 1 created or rewrote, IN ANY PROCESS, is known to be the
    flow's and not the design's."""
    out: Dict[str, Tuple[Optional[str], int]] = {}
    project = Path(project)
    for root in _input_roots(project):
        if not root.is_dir():
            continue
        for f in sorted(root.rglob("*")):
            if not f.is_file() or f.name.startswith("."):
                continue
            rel = _rel(project, f)
            if rel is None or _oracle_reason(rel):
                continue
            try:
                mt = f.stat().st_mtime_ns
            except OSError:
                mt = 0
            h = (_fixed_author_input_hash(project, rel)
                 if rel.startswith(INTERFACE_CONTEXT + "/") else _sha256(f))
            out[rel] = (h, mt)
    for rel in FIXED_AUTHOR_INPUTS:
        author = project / rel
        if author.exists() or author.is_symlink():
            out[rel] = (_fixed_author_input_hash(project, rel), author.lstat().st_mtime_ns)
    return out


def phase1_written_inputs(before: Dict[str, Tuple[Optional[str], int]],
                          after: Dict[str, Tuple[Optional[str], int]]
                          ) -> List[str]:
    """Input-root files phase 1 created or rewrote (content or mtime)."""
    return sorted(r for r, v in after.items() if before.get(r) != v)


def design_input_record(project: Path, io: Dict[str, Set[str]],
                        flow_written: Iterable[str]) -> Dict[str, Any]:
    """What phase 1 READ as design input: files under the input roots it
    opened, plus the entries of input-root directories it LISTED (so a new
    input document is seen), minus what phase 1 itself wrote and minus the
    §4.05 set. Recorded by NAME, re-hashed at check time."""
    project = Path(project)
    flow_written = set(flow_written)
    roots = [r.resolve() for r in _input_roots(project) if r.is_dir()]

    def _in_roots(p: Path) -> bool:
        return any(p == r or r in p.parents for r in roots)

    files: Set[str] = set()
    for r in io.get("reads", ()):
        q = Path(r)
        try:
            q = q.resolve()
        except OSError:
            continue
        if q.is_file() and _in_roots(q):
            rel = _rel(project, q)
            if rel and not q.name.startswith(".") \
                    and rel not in flow_written and not _oracle_reason(rel):
                files.add(rel)
    listed: Set[str] = set()
    for d in io.get("listed", ()):
        q = Path(d)
        try:
            q = q.resolve()
        except OSError:
            continue
        if q.is_dir() and _in_roots(q):
            rel = _rel(project, q)
            if rel is not None and not _oracle_reason(rel):
                listed.add(rel)
    # Only these fixed author inputs and the fixed package-context root belong
    # to Phase 1. Record absent paths too, detecting first admission/addition.
    files.update(FIXED_AUTHOR_INPUTS)
    listed.add(INTERFACE_CONTEXT)
    # The external elaborator opens package files outside Python's read hook.
    # Bind the entire fixed context even before the first author manifest, so
    # a nested provider edit/addition cannot outlive a baseline source roster.
    context = project / INTERFACE_CONTEXT
    if context.is_dir() and not context.is_symlink():
        for q in sorted(context.rglob("*")):
            rel = q.relative_to(project).as_posix()
            if _oracle_reason(rel):
                continue
            if q.is_symlink() or q.is_file():
                files.add(rel)
            elif q.is_dir():
                listed.add(rel)
    return {"files": sorted(files), "listed_dirs": sorted(listed),
            "flow_written": sorted(flow_written)}


def _listing(project: Path, rel_dir: str, flow_written: Set[str]) -> List[str]:
    d = Path(project) / rel_dir
    out = []
    try:
        for q in sorted(d.iterdir()):
            rel = f"{rel_dir}/{q.name}" if rel_dir else q.name
            if q.name.startswith(".") or rel in flow_written \
                    or _oracle_reason(rel):
                continue
            out.append(q.name + ("/" if q.is_dir() else ""))
    except OSError:
        return ["<unlistable>"]
    return out


def inputs_digest(project: Path, record: Optional[Dict[str, Any]] = None,
                  knobs: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Digest of the recorded design-input read set, as it is on disk NOW,
    plus the knobs. With no record (an unstamped project), None."""
    if not isinstance(record, dict):
        return None
    project = Path(project)
    fw = set(record.get("flow_written") or ())
    parts = []
    for rel in record.get("files") or ():
        h = (_fixed_author_input_hash(project, rel)
             if rel in FIXED_AUTHOR_INPUTS
             or rel.startswith(INTERFACE_CONTEXT + "/") else _sha256(project / rel))
        parts.append(f"f\0{rel}\0{h or 'ABSENT'}")
    for rel in record.get("listed_dirs") or ():
        parts.append(f"d\0{rel}\0{'|'.join(_listing(project, rel, fw))}")
    for k in KNOB_NAMES:
        parts.append(f"k\0{k}\0{(knobs or {}).get(k, '')}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def _plugin_version() -> str:
    try:
        doc = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json")
                         .read_text())
        return str(doc.get("version") or "")
    except (OSError, ValueError):
        return ""


def normal_knobs(knobs: Optional[Dict[str, Any]]) -> Dict[str, str]:
    k = dict(knobs or {})
    pdk = str(k.get("pdk") or "").strip()
    if pdk.lower() == "auto":
        pdk = ""
    return {"ic_name": str(k.get("ic_name") or "").strip(), "pdk": pdk,
            "mode": str(k.get("mode") or "docs").strip() or "docs"}


# ---------------------------------------------------------------------------
# stamping and derivations
# ---------------------------------------------------------------------------
def void(project: Path) -> None:
    """A regeneration is STARTING: the old stamp must not survive to vouch for
    half-new docs if this run dies (review wave8). Removes the phase1 entry;
    an interrupted run then reads NO_PRODUCER_IDENTITY, which regenerates."""
    p = sidecar_dir(Path(project)) / _si.SIDECAR
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(doc, dict) and KIND in doc:
        doc.pop(KIND, None)
        try:
            if doc:
                p.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
            else:
                p.unlink()
        except OSError:
            pass


def stamp(project: Path, recorder: Any, *,
          input_before: Optional[Dict[str, Tuple[Optional[str], int]]] = None,
          knobs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Record THIS producer's identity beside the docs it just wrote.

    `outputs` holds ONLY the docs this run wrote (review wave8: a doc the
    watchdog kept from an older producer must not be blessed); a doc on disk
    that this run did not write is recorded as `carried` and forces the next
    decision to regenerate. Best-effort; never fails phase 1."""
    project = Path(project)
    recording, why_not = (recorder.recorded() if recorder is not None
                          else (None, "phase 1 ran without a recorder"))
    code, code_why = (_si.code_from_recording(recording) if recording
                      else (None, [why_not]))
    io = recorder.io() if recorder is not None else {}
    written_now = (recorder.written_docs(project) if recorder is not None
                   else set())
    after = input_tree_snapshot(project)
    flow_written = phase1_written_inputs(input_before or after, after) \
        if input_before is not None else []
    record = design_input_record(project, io, flow_written)
    kn = normal_knobs(knobs)
    ident = {"code": code, "inputs": inputs_digest(project, record, kn)}
    on_disk = docs_snapshot(project)
    outputs = {n: h for n, h in on_disk.items() if n in written_now}
    carried = {n: h for n, h in on_disk.items() if n not in written_now}
    extra = {"recording": recording, "outputs": outputs, "carried": carried,
             "input_record": record, "knobs": kn, "derivations": [],
             "plugin_version": _plugin_version(),
             "stamped_at": time.time()}
    _si.write_sidecar(sidecar_dir(project), KIND, ident,
                      {"code": list(code_why)}, extra)
    return {"ident": ident, "outputs": outputs, "carried": carried}


def _rewrite(project: Path, rec: Dict[str, Any]) -> None:
    ident = {"code": rec.get("code"), "inputs": rec.get("inputs")}
    extra = {k: v for k, v in rec.items()
             if k not in ("code", "inputs", "evidence")}
    _si.write_sidecar(sidecar_dir(Path(project)), KIND, ident,
                      rec.get("evidence"), extra)


def record_derivation(project: Path, name: str, new_sha: Optional[str],
                      writer: str) -> bool:
    """A FLOW writer rewrote a generated doc after phase 1 stamped it: the
    new bytes are the recorded ones from now on, and the chain says who.

    Called from `l_doc_generator_stamp.dump` (every L-doc write in any
    process) and by the front door for any doc a later phase changed while
    it ran. Nothing is recorded while no stamp exists (phase 1's own run, or
    an unstamped project). Only a change NO flow writer recorded is a hand
    edit (review wave8: A8 `--apply` and `restamp_l_doc_skeletons` are
    flow writes)."""
    rec = _si.read_sidecar(sidecar_dir(Path(project)), KIND)
    if rec is None or not isinstance(rec.get("outputs"), dict):
        return False
    outs = dict(rec["outputs"])
    old = outs.get(name) or (rec.get("carried") or {}).get(name)
    if old == new_sha:
        return True
    outs[name] = new_sha
    rec["outputs"] = outs
    chain = list(rec.get("derivations") or [])
    chain.append({"doc": name, "writer": writer, "from": old, "to": new_sha,
                  "at": time.time()})
    rec["derivations"] = chain
    _rewrite(project, rec)
    return True


def record_flow_changes(project: Path, before: Dict[str, Optional[str]],
                        writer: str) -> List[str]:
    """Every generated doc that changed since `before` was changed by THIS
    flow run (the caller ran a phase between the two snapshots): record it."""
    after = docs_snapshot(project)
    changed = sorted(n for n, h in after.items() if before.get(n) != h)
    for n in changed:
        record_derivation(project, n, after[n], writer)
    return changed


def restamp_outputs(project: Path, written: Iterable[str],
                    writer: str = "phase1_expert_second_track") -> bool:
    """A phase-1 pass that is NOT the doc producer rewrote `written`: record
    those as derivations. The producer's code, inputs and every other doc's
    recorded bytes are kept (review wave8: re-hashing everything laundered an
    input edit and a hand edit)."""
    snap = docs_snapshot(project)
    ok = False
    for n in written:
        ok = record_derivation(project, n, snap.get(n), writer) or ok
    return ok


# ---------------------------------------------------------------------------
# the decision
# ---------------------------------------------------------------------------
def _verdict(state: str, reason: str, why: str, **kw: Any) -> Dict[str, Any]:
    out = {"state": state, "reason": reason, "why": why}
    out.update(kw)
    return out


def _checkpoint_recording_complete(recording: Any, code: Any) -> bool:
    """A checkpoint keeps the historical producer identity, never repairs it."""
    if not isinstance(recording, dict) or not recording or not code:
        return False
    for entries in recording.values():
        if not isinstance(entries, dict) or not entries:
            return False
        if any(not isinstance(value, str) or len(value) != 64
               or any(c not in "0123456789abcdef" for c in value)
               for value in entries.values()):
            return False
    try:
        recorded_code, _ = _si.code_from_recording(recording)
    except (AttributeError, TypeError, ValueError):
        return False
    return recorded_code == code


def assess(project: Path, programs_dir: Path,
           knobs: Optional[Dict[str, Any]] = None, *,
           checkpoint: bool = False,
           input_basis: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """REUSE / REGENERATE / REFUSE, or an explicitly requested REVALIDATE.

    `knobs` are the ones THIS run would hand phase 1; None means the caller
    does not know them, and the recorded ones are used (said in the reason).
    `checkpoint` keeps intact historical outputs eligible for current D1
    consumers after source drift or a proved normal input transition. The
    optional read-only `input_basis` references the existing transport manifest;
    the initial normal invocation can select it with VIBEIC_PHASE1_INPUT_BASIS.
    Its old preimage must reproduce the stored digest; intent is validated by
    its existing normal consumer. It does not establish equivalence to
    the new producer, grant PASS, or update the historical producer identity.
    The default retains the original producer-freshness decision."""
    project = Path(project)
    gd = _pl.generated_docs_dir(project)
    rec = _si.read_sidecar(sidecar_dir(project), KIND)
    if rec is None or not isinstance(rec.get("outputs"), dict):
        return _verdict(
            REGENERATE, NO_PRODUCER_IDENTITY,
            "the generated L docs carry no producer identity "
            f"({sidecar_dir(project).name}/{_si.SIDECAR} kind {KIND!r}), so "
            "nothing proves they are what the current producer would write")
    outputs: Dict[str, Any] = rec["outputs"]
    carried: Dict[str, Any] = rec.get("carried") or {}
    on_disk = {p.name: p for p in generated_docs(project)}
    edited = sorted(n for n, h in outputs.items()
                    if n in on_disk and _sha256(on_disk[n]) != h)
    carried_edited = sorted(n for n, h in carried.items()
                            if n in on_disk and _sha256(on_disk[n]) != h)
    foreign = sorted(n for n in on_disk
                     if n not in outputs and n not in carried)
    if edited or carried_edited or foreign:
        named = ", ".join(edited + carried_edited + foreign)
        return _verdict(
            REFUSE, GENERATED_DOC_EDITED,
            f"generated doc(s) {named} under {gd} changed after phase 1 and "
            f"no flow writer recorded the change (a flow rewrite is recorded "
            f"through `l_doc_generator_stamp.dump` or by the front door). They "
            f"are neither overwritten nor reused as current. Two ways out: "
            f"(1) move the edit into the design input under input/ and delete "
            f"the doc, so phase 1 regenerates it from the input; or (2) delete "
            f"the doc to discard the edit and regenerate it",
            docs=edited + carried_edited + foreign)
    removed = sorted(n for n in outputs if n not in on_disk)
    if removed:
        return _verdict(
            REGENERATE, GENERATED_DOC_REMOVED,
            f"generated doc(s) {', '.join(removed)} recorded by phase 1 are "
            f"gone; phase 1 regenerates them", docs=removed)
    if carried:
        return _verdict(
            REGENERATE, GENERATED_DOC_NOT_WRITTEN,
            f"generated doc(s) {', '.join(sorted(carried))} were on disk when "
            f"phase 1 last stamped but that run did NOT write them (e.g. a "
            f"layer step failed and an older doc was kept), so nothing proves "
            f"they are the current producer's", docs=sorted(carried))
    old_code = rec.get("code")
    # The recorder's root is the PLUGIN root; callers pass `programs/`.
    recording = rec.get("recording")
    if checkpoint and not _checkpoint_recording_complete(recording, old_code):
        new_code, code_why = None, [
            "the stored producer recording is incomplete or does not match "
            "its historical code digest"]
    else:
        new_code, code_why = _si.code_from_stored(recording,
                                                 Path(programs_dir).parent)
    source_drift = None
    if not old_code or new_code is None or new_code != old_code:
        source_drift = _verdict(
            REGENERATE, PRODUCER_CHANGED,
            f"the phase-1 producer that wrote these docs is not the current "
            f"one: code {str(old_code or 'unrecorded')[:12]} -> "
            f"{str(new_code or 'unestablished')[:12]}, plugin "
            f"{rec.get('plugin_version') or '?'} -> "
            f"{_plugin_version() or '?'} ({'; '.join(code_why)})",
            old={"code": old_code, "plugin_version": rec.get("plugin_version")},
            new={"code": new_code, "plugin_version": _plugin_version()})
        if not checkpoint or not old_code or new_code is None:
            return source_drift
        # A digest can be derived even when a formerly recorded file/symbol
        # is ABSENT. That is missing evidence, not eligible source drift.
        import _step_recorder as _sr
        current, error = _sr.rederive(recording, Path(programs_dir).parent)
        if error or not current or any(
                value == "ABSENT" for entries in current.values()
                for value in entries.values()):
            return source_drift
    rec_knobs = normal_knobs(rec.get("knobs"))
    now_knobs = normal_knobs(knobs) if knobs is not None else rec_knobs
    if now_knobs != rec_knobs:
        diff = {k: (rec_knobs[k], now_knobs[k]) for k in KNOB_NAMES
                if rec_knobs[k] != now_knobs[k]}
        return _verdict(
            REGENERATE, KNOBS_CHANGED,
            f"this run hands phase 1 different knobs than the run that wrote "
            f"these docs: {diff}", old={"knobs": rec_knobs},
            new={"knobs": now_knobs})
    new_inputs = inputs_digest(project, rec.get("input_record"), rec_knobs)
    if not rec.get("inputs") or new_inputs != rec.get("inputs"):
        changed = _verdict(
            REGENERATE, DESIGN_INPUT_CHANGED,
            f"the design input phase 1 read changed since it wrote these docs: "
            f"inputs {str(rec.get('inputs') or 'unrecorded')[:12]} -> "
            f"{str(new_inputs or 'unreadable')[:12]}",
            old={"inputs": rec.get("inputs")}, new={"inputs": new_inputs})
        # A historical raw digest cannot be replaced by today's projection.
        # The normal continuation may supply the retained input evidence; its
        # reconstructed preimage must prove that exact immutable old digest.
        # This is an evidence selector, never an approval or a PASS switch.
        reference = input_basis
        if reference is None:
            selected = os.environ.get("VIBEIC_PHASE1_INPUT_BASIS")
            reference = {"path": selected} if selected else None
        if checkpoint and reference is None:
            # Later ordinary entries reopen the reference retained by the
            # actual checkpoint writer. Reusing this evidence is not reusing
            # its verdict: current input/intent/source epochs are derived below.
            import step_output_collector as versions
            previous = versions.latest_pass(project, "D1") or {}
            result = previous.get("result") or {}
            completion = result.get("checkpoint") or {}
            if (previous.get("canonical_pass") is True
                    and not previous.get("capture_errors")
                    and result.get("runner") == "vibe_ic_one_shot_runner"
                    and result.get("site") == "phase1_checkpoint_revalidation"
                    and completion.get("producer_identity_sha256") == _sha256(
                        sidecar_dir(project) / _si.SIDECAR)):
                reference = ((completion.get("source_assessment") or {}).get("new")
                             or {}).get("input_basis")
        if not checkpoint or not isinstance(reference, dict):
            return changed
        try:
            import fnmatch
            import _flow_yaml
            import fault_scan_chain_insert as scan

            def read_file(path):
                path = Path(path)
                if path.is_symlink() or not path.is_file():
                    raise ValueError(f"input basis is absent or symlinked: {path}")
                raw = path.read_bytes()
                return raw, hashlib.sha256(raw).hexdigest()

            basis_path = Path(reference["path"]).resolve()
            raw, basis_sha = read_file(basis_path)
            if reference.get("sha256", basis_sha) != basis_sha:
                raise ValueError("retained input basis changed")
            transport = json.loads(raw)
            parts_path = basis_path.parent / transport["basis"]
            if not parts_path.resolve().is_relative_to(basis_path.parent):
                raise ValueError("input parts escape the retained basis")
            raw, parts_sha = read_file(parts_path)
            parts = json.loads(raw)
            ir = rec["input_record"]
            old_files = parts["old_files"]
            old_dirs = parts["old_listing_members_reconstructed"]
            if (list(old_files) != ir["files"]
                    or list(old_dirs) != ir["listed_dirs"]
                    or parts["knobs"] != rec_knobs
                    or parts["knob_order"] != list(KNOB_NAMES)):
                raise ValueError("historical input parts do not match the producer record")
            old_parts = [f"f\0{rel}\0{old_files[rel] or 'ABSENT'}"
                         for rel in ir["files"]]
            old_parts += [f"d\0{rel}\0{'|'.join(old_dirs[rel])}"
                          for rel in ir["listed_dirs"]]
            old_parts += [f"k\0{k}\0{rec_knobs[k]}" for k in KNOB_NAMES]
            if hashlib.sha256("\n".join(old_parts).encode()).hexdigest() != rec["inputs"]:
                raise ValueError("historical preimage does not prove the stored input digest")
            if parts["old_aggregate"] != rec["inputs"]:
                raise ValueError("historical aggregate differs from the producer identity")
            captured_files = parts["current_files"]
            captured_dirs = parts["current_listing_members"]
            if list(captured_files) != ir["files"] or list(captured_dirs) != ir["listed_dirs"]:
                raise ValueError("captured current parts do not match the recorded read set")
            captured_parts = [f"f\0{rel}\0{captured_files[rel] or 'ABSENT'}"
                              for rel in ir["files"]]
            captured_parts += [f"d\0{rel}\0{'|'.join(captured_dirs[rel])}"
                               for rel in ir["listed_dirs"]]
            captured_parts += [f"k\0{k}\0{rec_knobs[k]}" for k in KNOB_NAMES]
            if hashlib.sha256("\n".join(captured_parts).encode()).hexdigest() != parts["current_aggregate"]:
                raise ValueError("captured current input preimage does not match its digest")

            # Resolve the historical opened manifest by its exact raw hash,
            # not a reserialization or a guessed old set of JSON keys.
            manifest_rel = "input/flow109-manifest.json"
            old_manifest_sha = old_files[manifest_rel]
            candidates = [entry for entry in transport["files"]
                          if entry.get("sha256") == old_manifest_sha]
            if len(candidates) != 1:
                raise ValueError("historical opened manifest is not uniquely retained")
            old_path = basis_path.parent / candidates[0]["staged"]
            if not old_path.resolve().is_relative_to(basis_path.parent):
                raise ValueError("historical manifest escapes the retained basis")
            old_raw, old_sha = read_file(old_path)
            if old_sha != old_manifest_sha:
                raise ValueError("historical manifest bytes changed")
            old_manifest = json.loads(old_raw)
            manifest_raw, manifest_sha = read_file(project / manifest_rel)
            manifest = json.loads(manifest_raw)
            # These are the separate runtime arguments of prepare_front_door;
            # all design selectors and all other fields must remain equal.
            for key in set(old_manifest) | set(manifest):
                if key not in ("runtime_tool_uses", "tool_uses", "qualification_registry"):
                    if old_manifest.get(key) != manifest.get(key):
                        raise ValueError(f"design manifest field changed: {key}")

            consumed = {}
            for rel, expected in old_files.items():
                actual = (_fixed_author_input_hash(project, rel)
                          if rel in FIXED_AUTHOR_INPUTS or rel.startswith(INTERFACE_CONTEXT + "/")
                          else _sha256(project / rel))
                if rel != manifest_rel and actual != expected:
                    raise ValueError(f"recorded design input changed: {rel}")
                if actual is not None:
                    consumed[rel] = actual

            # The normal reader checks declaration, source/publication
            # provenance, current D01 owner and current author decision.
            binding, problems = scan.load_d09_dft_contract(project)
            if binding is None or problems:
                raise ValueError("normal intent consumer refused: " + "; ".join(problems))
            report_path = _pl.report_path(project, "phase1_one_shot.json")
            report_raw, report_sha = read_file(report_path)
            publication = json.loads(report_raw)["dft_intent_output"]
            for rel, expected in binding["sources"].items():
                path = project / rel
                if not path.resolve().is_relative_to(project.resolve()):
                    raise ValueError("intent source escapes project")
                _, actual = read_file(path)
                if expected != "sha256:" + actual:
                    raise ValueError("intent source changed: " + rel)
                consumed[rel] = actual
            decisions_rel = "input/feature-decisions.json"
            if decisions_rel not in consumed:
                raise ValueError("new normative intent has no current publication")
            decisions = json.loads((project / decisions_rel).read_bytes())
            source_ref = binding["intent"].get("source_reference")
            if source_ref is not None:
                path = project / source_ref["path"]
                if not path.resolve().is_relative_to(project.resolve()):
                    raise ValueError("intent source reference escapes project")
                _, actual = read_file(path)
                if actual != source_ref["sha256"]:
                    raise ValueError("intent source reference changed")
                consumed[source_ref["path"]] = actual
            import spec_declaration_emit as declaration
            declared = json.loads((project / binding["path"]).read_bytes())
            if any(key not in declared or not declaration._same_declared_value(value, declared[key])
                   for key, value in decisions.items()):
                raise ValueError("author choices differ from the normal declaration")

            # A listed namespace is not itself a document input. Use the
            # normal D1 intake contract to detect new extractable inputs;
            # files newly consumed as intent are bound above, never ignored.
            row = next(r for r in _flow_yaml.load()["steps"] if str(r["id"]) == "D1")
            patterns = [alt.strip() for item in row["required_inputs"]
                        for alt in item.get("path", "").split(" OR ") if alt.strip()]
            fw = set(ir.get("flow_written", ()))
            for rel, old_members in old_dirs.items():
                current_members = _listing(project, rel, fw)
                if current_members == old_members:
                    continue
                if rel != "input" or not set(old_members).issubset(current_members):
                    raise ValueError("a recorded document listing changed: " + rel)
                for member in set(current_members) - set(old_members):
                    added = rel + "/" + member.rstrip("/")
                    if any(fnmatch.fnmatchcase(added, pattern)
                           or member.endswith("/") and pattern.startswith(added + "/")
                           for pattern in patterns):
                        raise ValueError("a normal Phase1 intake was added: " + added)
                    if not member.endswith("/") and added not in consumed:
                        raise ValueError("an added input file has no normal consumer: " + added)

            for rel in (binding["path"],
                        str(Path(binding["path"]).with_suffix(".provenance.json")),
                        str(report_path.relative_to(project))):
                _, consumed[rel] = read_file(project / rel)
            claims = [line for line in (project / "provenance.jsonl").read_bytes().splitlines()
                      if line.strip()]
            claims = [(line, json.loads(line)) for line in claims]
            claims = [(line, claim) for line, claim in claims
                      if claim.get("tool") == "spec_declaration_emit"
                      and binding["path"] in claim.get("outputs", {})
                      and claim.get("exit_code") == 0]
            claim_line, claim = claims[-1]
            claim_sha = hashlib.sha256(claim_line).hexdigest()
            _, declaration_source_sha = read_file(Path(declaration.__file__))
            if claim["source_sha256"] != "sha256:" + declaration_source_sha:
                raise ValueError("normal declaration source epoch changed")
            again, problems = scan.load_d09_dft_contract(project)
            if (again != binding or problems or read_file(report_path)[1] != report_sha
                    or inputs_digest(project, ir, rec_knobs) != new_inputs
                    or any(_sha256(project / rel) != expected
                           for rel, expected in consumed.items())
                    or read_file(basis_path)[1] != basis_sha
                    or read_file(parts_path)[1] != parts_sha):
                raise ValueError("consumed input or publication changed during assessment")
            return _verdict(
                REVALIDATE, DESIGN_INPUT_CHANGED,
                "a reconstructed preimage verifies the immutable historical raw "
                "digest, and the unchanged consumed design inputs "
                "permit normal checkpoint revalidation; the newly normative intent "
                "is bound by its current normal publication, not ignored",
                old={"code": old_code, "inputs": rec["inputs"]},
                new={"code": new_code, "inputs": new_inputs,
                     "input_basis": {"path": str(basis_path), "sha256": basis_sha,
                                     "parts_sha256": parts_sha,
                                     "historical_manifest_sha256": old_sha,
                                     "captured_current_inputs": parts["current_aggregate"],
                                     "classification": "RECONSTRUCTED_VERIFIED_PREIMAGE",
                                     "original_raw_listing_archive": False},
                     "consumed_inputs": consumed,
                     "intent": {"publication": publication,
                                "report_sha256": report_sha,
                                "manifest_sha256": manifest_sha,
                                "declaration_source_sha256": declaration_source_sha,
                                "publication_claim_sha256": claim_sha}})
        except (OSError, ValueError, KeyError, TypeError, AttributeError,
                StopIteration, IndexError) as exc:
            changed["why"] += "; normal input transition refused: " + str(exc)
            return changed
    if source_drift is not None:
        source_drift["state"] = REVALIDATE
        source_drift["why"] += (
            "; the recorded output bytes, design inputs and knobs remain "
            "intact; current D1 consumers must revalidate this historical "
            "checkpoint before it can advance. No equivalence to the new "
            "producer is established")
        return source_drift
    n_der = len(rec.get("derivations") or [])
    return _verdict(REUSE, "CURRENT",
                    f"every generated doc holds the bytes phase 1 recorded"
                    + (f" or a recorded flow derivation ({n_der})"
                       if n_der else "")
                    + f", the producer re-derives to {str(new_code)[:12]}, "
                    f"the design input it read is unchanged"
                    + ("" if knobs is not None else
                       " (knobs not supplied by the caller; recorded ones "
                       "assumed)"))


def supersede_docs(project: Path, why: str) -> Optional[Path]:
    """Move the stale generated L docs aside before a regeneration, so a
    layer step that fails cannot leave an older producer's doc in place
    (review wave8). Kept under `.vibeic-state/` -- never deleted, never where
    a doc reader looks. Only ever called for a REGENERATE, never a REFUSE."""
    project = Path(project)
    docs = generated_docs(project)
    if not docs:
        return None
    base = project / ".vibeic-state" / "superseded_generated_docs"
    try:
        base.mkdir(parents=True, exist_ok=True)
        # A second regeneration in the same second must not overwrite the
        # first archive. mkdtemp creates a unique directory atomically.
        dest = Path(tempfile.mkdtemp(
            prefix=time.strftime("%Y%m%dT%H%M%S") + "-", dir=base))
    except OSError as exc:
        raise SupersedeError(f"cannot archive stale generated docs under "
                             f"{base}: {exc}") from exc
    moved: List[Tuple[Path, Path]] = []
    try:
        for d in docs:
            target = dest / d.name
            if target.exists():
                raise SupersedeError(f"archive target already exists: {target}")
            os.replace(d, target)
            moved.append((d, target))
        (dest / "WHY.txt").write_text(why + "\n")
    except OSError as exc:
        rollback_failed = []
        for source, target in reversed(moved):
            try:
                if source.exists():
                    raise OSError(f"live path was recreated: {source}")
                os.replace(target, source)
            except OSError as undo_exc:
                rollback_failed.append(f"{target} -> {source}: {undo_exc}")
        if rollback_failed:
            try:
                (dest / "INCOMPLETE.txt").write_text(
                    "Archive failed and rollback is incomplete:\n"
                    + "\n".join(rollback_failed) + "\n")
            except OSError:
                pass
        raise SupersedeError(
            f"cannot archive stale generated docs: {exc}; "
            + ("rollback incomplete: " + "; ".join(rollback_failed)
               if rollback_failed else "live docs restored")) from exc
    void(project)
    return dest
