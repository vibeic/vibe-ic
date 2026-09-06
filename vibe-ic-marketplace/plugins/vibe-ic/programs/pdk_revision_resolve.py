#!/usr/bin/env python3
"""pdk_revision_resolve — the PDK revision a run signed off against, read from
the tree that ran.

THE GAP (LibreLane GAP 5, and ours)
===================================
A sign-off number is a claim about a design measured against a PROCESS. The
toolchain half of that claim is already recorded: `vibe_ic_one_shot_runner`
writes `reports/container_image.json` with the container's content-addressed
image id, because "a long-running container built from an OLDER image silently
produces every tool version and every sign-off number with nothing in the run
record naming it". The PDK half was never recorded at all.

MEASURED ON THIS TREE before writing a line — `grep -rn` over `programs/`,
`flow/`, `mcp-eda/`, `benchmark/` for a PDK version/revision/commit field:

    pdk_version | pdk_revision | pdk_commit | pdk_sha        ->  0 hits

What a run DOES record about its PDK, everywhere it records anything:

    RUN_MANIFEST.json (`benchmark_run_manifest`)  verdicts, dataset+sha256,
                                                  plugin_version, image,
                                                  scorer_argv  — no PDK field
    reports/container_image.json                  image_ref, image_id  — tools only
    step repro bundle MANIFEST.json               `env_PDK_ROOT` VERBATIM
    the published cell's own directory name       `v<version>_<PDK>` — a NAME
    `pdk_registry.json`                           name -> container_path

Every one of those is the REQUEST. `env_PDK_ROOT` is what the operator set;
`--pdk <name>` is what the operator asked for; the cell's directory name is
that same word again. None of them says WHICH REVISION of that process the
tools actually read, so two runs a year apart against a re-pulled volume are
byte-identical in the record and were measured against different data.

WHAT THIS READS INSTEAD
=======================
The revision is read from the RESOLVED tree — the directory the tools actually
opened, after symlinks — and only from an artefact the tree itself carries. A
string that came from a flag, an environment variable, a registry entry or a
directory name is never accepted as a revision, because that is a record of
what we asked for.

Four declared sources, in this precedence, all of them conventions of PDK
DISTRIBUTIONS rather than of any process, foundry or vendor:

    1. TREE_PATH      the resolved realpath carries a `<hex>` path segment
                      under a `versions/` component — the shape a
                      content-addressed PDK volume manager installs into.
    2. SOURCES_FILE   a root file of `<component> <revision>` lines.
    3. COMMIT_FILE    a root file holding one bare revision token.
    4. NODE_INFO      a root JSON carrying a `commit` mapping of
                      `<component> -> <revision>`.

MEASURED over the 6 PDK trees the pinned image ships (names withheld — this is
a count, not an inventory):

    2 trees   resolve through a `versions/<hex40>/` segment AND carry both a
              SOURCES_FILE and a NODE_INFO, all three agreeing on the same
              40-hex token
    2 trees   carry a COMMIT_FILE and nothing else
    2 trees   carry NONE OF THE FOUR — `find -maxdepth 3` for any file named
              like a version, a commit, a source list, a README or any `.json`
              returns EMPTY for both

So "the revision cannot be determined" is not a hypothetical branch: it is the
state of a third of the shipped trees, and it is the state this program was
written to stop being silent about. It is reported as NOT DETERMINED and it
FAILS. It is never written as `unknown`, and there is no flag that turns it
into a pass — an `unknown` in this field would re-create the exact gap, one
layer higher, while looking like it had been closed.

TOKEN ACCEPTANCE, AND THE PLACEHOLDERS IT HAD TO REJECT
=======================================================
A revision token is a hex identifier of >= 12 characters, or a dotted release
number. That rule is not decorative: the NODE_INFO of a shipped tree carries
`"unknown"` for three of its components and the literal `SRAM_BUILD_COMMIT`
for another, both sitting in exactly the position a revision goes. Accepting
"whatever string is in the field" would have recorded a placeholder as a
revision and passed.

CORROBORATION, AND WHAT IT CANNOT SEE
=====================================
When more than one source names the SAME component, they must agree. A
disagreement is AMBIGUOUS and fails: two artefacts in one tree describing two
different states is not a tree whose revision is known.

`content_anchor` is a digest over the resolved tree's own inventory — every
file's tree-relative path and byte size, sorted. It is recorded ALWAYS and is
NEVER a substitute for a declared revision, for a reason measured on the image
this repo pins: that image's PDK volume ships a record of its own
modifications, and it declares **12 files modified locally** against the
upstream revision the volume's SOURCES_FILE names. A run on the patched volume
and a run on stock upstream therefore report the SAME declared revision and
are not the same process data. The anchor separates them; the declared
revision is what lets a reader go and fetch the thing. Neither half is
complete on its own, which is why both are recorded and only one of them is
allowed to satisfy the gate.

The anchor is a stat-only walk (path + size, never content), so it does not
see a same-size byte edit. Recorded with its own `files` count and
`truncated` flag so a reader can tell a small tree from a capped walk.

BLOCKING vs ADVISORY
====================
THIS PROGRAM IS NOT A GATE. It answers a question and writes a record; it
cannot stop anything. The BLOCKING use of its record lives in
`benchmark_evidence_publish`, which REFUSES to stage a run whose record is
absent or carries no declared revision — declared there, in the gate, as that
skill requires.

chip-, PDK- and vendor-AGNOSTIC: every name in this file is a distribution
convention or a structural shape. No process, foundry, node, SKU or design
identifier appears, and none is derivable from it.

USAGE
-----
    pdk_revision_resolve.py --tree /path/to/pdk [--container NAME] [--json OUT]
    pdk_revision_resolve.py --from-run /path/to/run [--container NAME] [--json OUT]

`--from-run` derives the candidate trees from the ABSOLUTE `.lef`/`.lib`
paths the run's own tool logs record — the same channel
`declared_pdk_is_the_pdk_used_check` uses, and for the same stated reason:
"the question is what RAN, and a configuration that was ignored is precisely
the failure being looked for".

EXIT CODES
----------
    0  a declared revision was resolved; the record says which artefact it
       came from
    1  NOT DETERMINED — no tree offered a declared revision, or two artefacts
       in one tree disagree. The record is still written, naming what was
       looked at, so the refusal is legible without re-running.
    2  the question could not be put: no tree given or derivable, or the path
       could not be read at all.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:                      # pragma: no cover - path setup
    sys.path.insert(0, str(_HERE))

#: The record's canonical location inside a run. Named here so the writer
#: (the runner) and the reader (the publish gate) cannot drift into two
#: different notions of where the run's PDK record lives.
RECORD_REL = "reports/pdk_revision.json"

#: THE NAME THIS REFUSAL HAS — vibe-ic#2069.
#:
#: The refusal itself already existed and was already blocking; what it did not
#: have was a NAME. `benchmark_evidence_publish` raised prose, the one-shot
#: runner appended different prose to its advisory list, and this program
#: printed a third wording to stderr. Three renderings of one fact, none of
#: them greppable, so a consumer could not key on "this run was refused for a
#: missing PDK revision" without matching English — and a reader of the record
#: FILE alone saw `resolved: false` and no statement at all about what that
#: costs.
#:
#: Defined HERE, in the program that writes the record, and imported by every
#: reader that refuses on it, for the same reason `record_gaps` is: a token
#: spelled in three places is three tokens.
#:
#: It is a REFUSAL, never a verdict about a design, and never a default. The
#: record's `revision` stays `None` when nothing could be read — the token
#: names the absence, it does not fill it. An `unknown` in `revision` would
#: re-create the exact gap while looking like it had been closed.
REFUSAL_NOT_RECORDED = "PDK_REVISION_NOT_RECORDED"

SCHEMA = 1

# --- source ids -------------------------------------------------------------
TREE_PATH = "TREE_PATH"
SOURCES_FILE = "SOURCES_FILE"
COMMIT_FILE = "COMMIT_FILE"
NODE_INFO = "NODE_INFO"

#: Precedence. TREE_PATH first because a content-addressed install path cannot
#: be edited without moving the tree, so it is the one source that a stale
#: file inside the tree cannot contradict silently.
SOURCE_ORDER: Tuple[str, ...] = (TREE_PATH, SOURCES_FILE, COMMIT_FILE, NODE_INFO)

#: Root-level filenames that PDK DISTRIBUTIONS use to state their own source
#: state. Named rather than sniffed: a content sniff over a tree root would
#: have to decide that some arbitrary file "looks like" a revision statement,
#: and a wrong guess here writes a wrong revision into a sign-off record.
#: Extending this list is a data change; nothing else in the program moves.
_SOURCES_NAMES: Tuple[str, ...] = ("SOURCES",)
_COMMIT_NAMES: Tuple[str, ...] = ("COMMIT",)
_NODE_INFO_RELS: Tuple[str, ...] = (".config/nodeinfo.json",)

#: The key inside a NODE_INFO document that holds SOURCE state. Deliberately
#: only this one: the same documents carry large `reference` / `stdcells`
#: mappings that describe what a build was made FROM, not what this tree IS,
#: and reading those would put a dozen unrelated tokens into the record.
_NODE_INFO_KEY = "commit"

#: Where a content-addressed volume manager keys its installs.
_VERSIONS_SEGMENT = "versions"

#: A revision token: a hex identifier of at least 12 characters, or a dotted
#: release number. See the docstring for the two placeholders this rejects.
_HEX_TOKEN = re.compile(r"^[0-9a-fA-F]{12,64}$")
_DOTTED_TOKEN = re.compile(r"^[vV]?\d+(?:\.\d+)+(?:[-+.][0-9A-Za-z]+)*$")

#: When a source names no component (a bare token file, or a path segment),
#: the record still needs a key to corroborate on. This is that key. It is not
#: a component NAME — it is "the tree itself".
TREE_COMPONENT = "_tree"

#: stat-only inventory cap. 20000 is ~1.5x the largest tree measured on the
#: pinned image (13324 files), so no shipped tree truncates today; the flag is
#: recorded anyway because a cap that is never reported is a cap that lies the
#: first time it bites.
_ANCHOR_FILE_CAP = 20000

#: Bounds every container probe. 60 s is the inner ceiling this repo holds its
#: sub-invocations to; a bound that promises time the harness will not give
#: turns one slow probe into a dead session.
_PROBE_TIMEOUT = 60


def is_revision_token(tok: Any) -> bool:
    """Is *tok* something that identifies a source state, or a placeholder?

    Pure, and deliberately narrow — see the docstring's PLACEHOLDERS note.
    """
    if not isinstance(tok, str):
        return False
    t = tok.strip()
    if not t:
        return False
    return bool(_HEX_TOKEN.match(t) or _DOTTED_TOKEN.match(t))


# ---------------------------------------------------------------------------
# Filesystem access — host or container, one interface.
# ---------------------------------------------------------------------------

class Fs:
    """Read a filesystem, on this host or inside a container.

    Every method returns None for "could not read" and never raises, so a
    missing tool or an unreachable container degrades into a NAMED not-read
    rather than into a traceback or, worse, an empty answer that reads like a
    clean one.
    """

    def __init__(self, container: Optional[str] = None) -> None:
        self.container = container or None

    # -- primitives ---------------------------------------------------------
    def _sh(self, script: str, timeout: int = _PROBE_TIMEOUT
            ) -> Tuple[int, str]:
        if self.container:
            cmd = ["docker", "exec", self.container, "sh", "-c", script]
        else:
            cmd = ["sh", "-c", script]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return 127, ""
        return p.returncode, p.stdout

    def realpath(self, path: str) -> Optional[str]:
        rc, out = self._sh(f"readlink -f {shlex.quote(path)}")
        out = out.strip()
        return out if rc == 0 and out else None

    def is_dir(self, path: str) -> bool:
        rc, _ = self._sh(f"test -d {shlex.quote(path)}")
        return rc == 0

    def read_text(self, path: str, max_bytes: int = 1_048_576) -> Optional[str]:
        """The file's head, or None when it is not a readable file.

        The cap is far above every declared-revision artefact measured (the
        largest is ~4 KB) and it fails SAFE: a file long enough to be truncated
        parses to nothing, which becomes NOT DETERMINED — a refusal — never a
        revision read off half a document.
        """
        rc, out = self._sh(
            f"test -f {shlex.quote(path)} && head -c {max_bytes} "
            f"{shlex.quote(path)}")
        return out if rc == 0 else None

    def inventory(self, path: str, cap: int = _ANCHOR_FILE_CAP
                  ) -> Optional[Tuple[List[str], bool]]:
        """Sorted `<relpath>\\0<size>` lines for every file under *path*.

        stat-only: no file content is read, so this stays cheap on a tree of
        tens of thousands of files. Sorted with `LC_ALL=C` so the digest does
        not depend on the caller's locale.
        """
        q = shlex.quote(path)
        rc, out = self._sh(
            f"cd {q} 2>/dev/null && find . -type f -printf '%p\\t%s\\n' "
            f"2>/dev/null | LC_ALL=C sort")
        if rc != 0:
            return None
        lines = [ln for ln in out.splitlines() if ln]
        truncated = len(lines) > cap
        return lines[:cap], truncated


# ---------------------------------------------------------------------------
# The four declared sources.
# ---------------------------------------------------------------------------

def _from_tree_path(resolved: str) -> Dict[str, str]:
    """`{component: revision}` from a content-addressed install path.

    The segment must sit directly under a `versions` component: a bare hex-y
    directory name anywhere in a path is not a statement about anything.
    """
    parts = [p for p in Path(resolved).parts if p not in ("/", "")]
    out: Dict[str, str] = {}
    for i, seg in enumerate(parts[:-1]):
        if seg != _VERSIONS_SEGMENT:
            continue
        cand = parts[i + 1]
        if is_revision_token(cand):
            out[TREE_COMPONENT] = cand
    return out


def _parse_sources(text: str) -> Dict[str, str]:
    """`<component> <revision>` lines. A line whose second field is not a
    revision token is skipped, not guessed at."""
    out: Dict[str, str] = {}
    for ln in text.splitlines():
        fields = ln.split()
        if len(fields) < 2:
            continue
        if is_revision_token(fields[1]):
            out[fields[0]] = fields[1].strip()
    return out


def _parse_commit(text: str) -> Dict[str, str]:
    """One bare token, keyed to the tree itself."""
    toks = text.split()
    if len(toks) == 1 and is_revision_token(toks[0]):
        return {TREE_COMPONENT: toks[0]}
    return {}


def _parse_node_info(text: str) -> Dict[str, str]:
    try:
        doc = json.loads(text)
    except (ValueError, TypeError):
        return {}
    if not isinstance(doc, dict):
        return {}
    commit = doc.get(_NODE_INFO_KEY)
    if not isinstance(commit, dict):
        return {}
    return {str(k): v.strip() for k, v in commit.items()
            if is_revision_token(v)}


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_sources(fs: Fs, tree: str, resolved: str) -> List[Dict[str, Any]]:
    """Every declared source this tree offers, in precedence order.

    Each entry names the source, where it was read, the digest of what was
    read (so the claim is checkable against the tree later) and the
    `{component: revision}` it yielded. A source that is present but yielded
    nothing is RECORDED with an empty mapping rather than dropped: "the file
    is there and says nothing usable" and "there is no such file" are
    different facts about a tree.
    """
    found: List[Dict[str, Any]] = []

    tp = _from_tree_path(resolved)
    if tp:
        found.append({"source": TREE_PATH, "read_from": resolved,
                      "sha256": None, "revisions": tp})

    for name in _SOURCES_NAMES:
        txt = fs.read_text(f"{resolved}/{name}")
        if txt is not None:
            found.append({"source": SOURCES_FILE,
                          "read_from": f"{resolved}/{name}",
                          "sha256": _sha256_text(txt),
                          "revisions": _parse_sources(txt)})

    for name in _COMMIT_NAMES:
        txt = fs.read_text(f"{resolved}/{name}")
        if txt is not None:
            found.append({"source": COMMIT_FILE,
                          "read_from": f"{resolved}/{name}",
                          "sha256": _sha256_text(txt),
                          "revisions": _parse_commit(txt)})

    for rel in _NODE_INFO_RELS:
        txt = fs.read_text(f"{resolved}/{rel}")
        if txt is not None:
            found.append({"source": NODE_INFO,
                          "read_from": f"{resolved}/{rel}",
                          "sha256": _sha256_text(txt),
                          "revisions": _parse_node_info(txt)})

    order = {s: i for i, s in enumerate(SOURCE_ORDER)}
    found.sort(key=lambda e: order.get(e["source"], len(order)))
    return found


def content_anchor(fs: Fs, resolved: str) -> Dict[str, Any]:
    """A stat-only identity for the tree that ran. Corroboration only."""
    inv = fs.inventory(resolved)
    if inv is None:
        return {"sha256": None, "files": None, "truncated": None,
                "note": "the tree's inventory could not be listed"}
    lines, truncated = inv
    payload = "\n".join(lines)
    return {"sha256": _sha256_text(payload), "files": len(lines),
            "truncated": truncated,
            "note": "sha256 over sorted <relpath>\\t<bytes> for every file; "
                    "stat-only, so a same-size byte edit is invisible to it"}


def _conflicts(sources: Sequence[Dict[str, Any]]) -> List[str]:
    """Components two sources describe differently."""
    seen: Dict[str, Tuple[str, str]] = {}
    bad: List[str] = []
    for entry in sources:
        for comp, rev in (entry.get("revisions") or {}).items():
            if comp in seen and seen[comp][1] != rev:
                bad.append(
                    f"{comp}: {seen[comp][0]} says {seen[comp][1]}, "
                    f"{entry['source']} says {rev}")
            else:
                seen.setdefault(comp, (entry["source"], rev))
    return bad


def resolve_tree(fs: Fs, tree: str) -> Dict[str, Any]:
    """The record for ONE candidate PDK tree."""
    rec: Dict[str, Any] = {
        "tree": tree,
        "resolved_tree": None,
        "resolved": False,
        "revision": None,
        "revision_source": None,
        "components": {},
        "sources": [],
        "content_anchor": None,
        "reason": None,
    }
    resolved = fs.realpath(tree)
    if not resolved or not fs.is_dir(resolved):
        rec["reason"] = f"not a readable directory: {tree}"
        return rec
    rec["resolved_tree"] = resolved
    rec["sources"] = read_sources(fs, tree, resolved)
    rec["content_anchor"] = content_anchor(fs, resolved)

    clash = _conflicts(rec["sources"])
    if clash:
        rec["reason"] = ("AMBIGUOUS — two artefacts in this tree describe "
                         "different states: " + "; ".join(clash))
        return rec

    for entry in rec["sources"]:
        revs = entry.get("revisions") or {}
        if not revs:
            continue
        comp = sorted(revs)[0] if TREE_COMPONENT not in revs else TREE_COMPONENT
        rec["resolved"] = True
        rec["revision"] = f"{comp}:{revs[comp]}"
        rec["revision_source"] = entry["source"]
        rec["components"] = dict(sorted(revs.items()))
        return rec

    present = sorted({e["source"] for e in rec["sources"]})
    rec["reason"] = (
        "NOT DETERMINED — this tree declares no revision. "
        + (f"artefacts present but stating none: {', '.join(present)}. "
           if present else "none of the declared-revision artefacts exist. ")
        + "Not written as 'unknown': a sign-off recorded against an unnamed "
          "process revision cannot be re-derived, and saying so is the whole "
          "point of the record.")
    return rec


# ---------------------------------------------------------------------------
# Deriving candidate trees from a run's own logs.
# ---------------------------------------------------------------------------

#: Same shape `declared_pdk_is_the_pdk_used_check` scans logs with, restricted
#: to ABSOLUTE paths: a bare basename names no tree.
_ABS_LIB_RE = re.compile(r"(/[A-Za-z0-9_./+-]+\.(?:lef|lib))\b")

#: How far up from a loaded library to look for the tree root. The deepest
#: shipped layout measured is `<tree>/libs.ref/<lib>/<kind>/<file>` — 4 — and
#: a macro library one level deeper is ordinary, so 8 is roomy without letting
#: the walk escape into a shared parent of several PDKs.
_WALK_UP_MAX = 8


def _install_root(path: str) -> Optional[str]:
    """`<...>/versions/<revision>/<name>` when *path* sits inside one.

    Exact rather than searched: the install root of a content-addressed volume
    is the component immediately below the revision directory, and every
    descendant of it shares the same `versions/<revision>/` prefix. That is
    why the path shape alone MUST NOT qualify a walk-up candidate — it is true
    of the library file, of its directory, and of every directory between —
    and computing the root directly is the fix for having tried it the other
    way round. (Measured: the walk stopped at
    `<tree>/libs.ref/<lib>/lib`, recorded THAT as the PDK tree, and reported
    `resolved` — a wrong tree, confidently.)
    """
    parts = list(Path(path).parts)
    for i, seg in enumerate(parts[:-2]):
        if seg == _VERSIONS_SEGMENT and is_revision_token(parts[i + 1]):
            return str(Path(*parts[: i + 3]))
    return None


def _has_file_source(fs: "Fs", d: str) -> bool:
    """Does *d* itself carry one of the FILE-based declared sources?

    File-based only, deliberately: `TREE_PATH` is a property of the path and
    therefore of every descendant, so admitting it here would stop the walk at
    the first directory examined.
    """
    for name in _SOURCES_NAMES + _COMMIT_NAMES:
        if fs.read_text(f"{d}/{name}") is not None:
            return True
    for rel in _NODE_INFO_RELS:
        if fs.read_text(f"{d}/{rel}") is not None:
            return True
    return False


def candidate_trees_from_run(run: Path, fs: Fs, cap: int = 400
                             ) -> Tuple[List[str], int]:
    """PDK tree roots derived from the libraries the run's tools actually read.

    Returns `(trees, logs_scanned)`. From each loaded library the walk goes UP
    to the first directory carrying a FILE-based declared source; failing that
    it takes the content-addressed install root the path itself names. A
    library under neither yields no tree — better than naming the wrong one.
    """
    libs: List[str] = []
    scanned = 0
    for log in sorted(run.rglob("*.log"))[:cap]:
        if "/plugin_work/" in str(log) or "/plugin_" in str(log):
            continue                     # the plugin's own tree is not the run
        try:
            text = log.read_text(errors="replace")
        except OSError:
            continue
        scanned += 1
        for m in _ABS_LIB_RE.findall(text):
            libs.append(m)

    trees: List[str] = []

    # THE STAGED PDK, which no log path can reach. A run may carry its process
    # data INSIDE itself — `<run>/input/pdk/` is the location the flow already
    # owns — and then the tools read paths that name the vendor archive's own
    # internal layout, not a tree root. MEASURED over 21 real run directories
    # on this host: 17 resolve from their logs, 1 kept no logs, and 3 are this
    # shape. So the staged root is offered as a candidate directly, and it
    # qualifies on the SAME terms as any other tree — it must carry a declared
    # revision artefact of its own. That keeps the rule intact: a hand-typed
    # revision in a config file would be the REQUEST again, one directory
    # further in.
    for rel in ("input/pdk", "run/input/pdk"):
        staged = str(Path(run) / rel)
        if _has_file_source(fs, staged):
            trees.append(staged)

    seen_lib_dirs: set = set()
    for lib in libs:
        start = Path(lib).parent
        if str(start) in seen_lib_dirs:
            continue
        seen_lib_dirs.add(str(start))
        stop_at = _install_root(lib)
        node = start
        found: Optional[str] = None
        for _ in range(_WALK_UP_MAX):
            cur = str(node)
            if cur in ("/", ""):
                break
            if _has_file_source(fs, cur):
                found = cur
                break
            if stop_at and cur == stop_at:
                break
            node = node.parent
        chosen = found or stop_at
        if chosen and chosen not in trees:
            trees.append(chosen)
    return trees, scanned


# ---------------------------------------------------------------------------
# Record.
# ---------------------------------------------------------------------------

def build_record(trees: Sequence[Dict[str, Any]], read_in: str,
                 derived_from: str, note: str = "") -> Dict[str, Any]:
    resolved = [t for t in trees if t.get("resolved")]
    rec: Dict[str, Any] = {
        "_comment": ("The PDK revision this run signed off against, read from "
                     "the resolved tree rather than from the request. The "
                     "toolchain half of the same claim is in "
                     "reports/container_image.json."),
        "schema": SCHEMA,
        "resolved": bool(resolved) and len(resolved) == len(trees),
        "read_in": read_in,
        "derived_from": derived_from,
        "trees": list(trees),
    }
    if note:
        rec["note"] = note
    if resolved:
        rec["revision"] = (resolved[0]["revision"] if len(resolved) == 1
                           else " ".join(sorted(t["revision"]
                                                for t in resolved)))
    else:
        rec["revision"] = None
    if not rec["resolved"]:
        unresolved = [t for t in trees if not t.get("resolved")]
        rec["reason"] = ("; ".join(
            f"{t.get('tree')}: {t.get('reason')}" for t in unresolved)
            or "no PDK tree could be identified for this run")
    # #2069 — the record states its own refusal, by name, so the file is
    # legible without re-deriving the gap list from it. `None` on a complete
    # record; the key is ALWAYS present so its absence cannot be read as
    # "recorded".
    rec["refusal"] = record_refusal(rec)
    return rec


def record_gaps(rec: Any) -> List[str]:
    """What is missing from a PDK-revision record. Empty means complete.

    Shared by the writer and by every reader that gates on it, so the two
    cannot drift into different notions of "recorded". A record that says
    `resolved: false`, or carries no revision, or carries a revision that is
    not a revision token, is INCOMPLETE — there is no spelling of "we could
    not tell" that satisfies this.
    """
    if not isinstance(rec, dict):
        return ["the PDK revision record is not an object"]
    gaps: List[str] = []
    if rec.get("resolved") is not True:
        gaps.append("resolved is not true — "
                    + str(rec.get("reason") or "no reason recorded"))
    rev = rec.get("revision")
    if not isinstance(rev, str) or not rev.strip():
        gaps.append("revision: the run names no PDK revision, so its sign-off "
                    "cannot be re-derived")
    else:
        # A run that read TWO trees renders both, space-separated; EVERY part
        # has to be a real token or the record names one process and gestures
        # at another.
        bad = [part for part in rev.split()
               if not is_revision_token(part.rsplit(":", 1)[-1])]
        if bad:
            gaps.append(f"revision {rev!r} is not a revision token "
                        f"({', '.join(repr(b) for b in bad)}) — a placeholder "
                        f"in this field is the gap wearing a hat")
    if not rec.get("trees"):
        gaps.append("trees: the record names no PDK tree it read")
    return gaps


def record_refusal(rec: Any) -> Optional[str]:
    """`REFUSAL_NOT_RECORDED` when this record does not name a revision, else
    `None`. vibe-ic#2069.

    The one place the answer "is this run publishable on the PDK axis" is
    decided, so the writer, this program's own exit code, the runner's advisory
    and the publish gate all refuse by the SAME name for the SAME set of
    records. `record_gaps` stays the place that says WHICH field is missing;
    this says what the refusal is CALLED.

    A record that could not be read at all is refused too: `None` reaching here
    is "no record", which is the strongest form of not-recorded, and returning
    `None` for it would make an absent record indistinguishable from a complete
    one — the substitution this whole program exists to stop.
    """
    return REFUSAL_NOT_RECORDED if record_gaps(rec) else None


def load_record(run: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """`(record, error)` for a run directory. Never raises."""
    p = Path(run) / RECORD_REL
    if not p.is_file():
        return None, f"{RECORD_REL} is absent"
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, f"{RECORD_REL} is unreadable ({exc})"


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tree", action="append", default=[],
                    help="a PDK tree to resolve; may repeat")
    ap.add_argument("--from-run",
                    help="derive the trees from this run's own tool logs")
    ap.add_argument("--container",
                    help="read the filesystem inside this container")
    ap.add_argument("--json", help="write the record here")
    args = ap.parse_args(argv)

    fs = Fs(args.container)
    read_in = f"container:{args.container}" if args.container else "host"

    trees: List[str] = list(args.tree)
    derived_from = "--tree"
    note = ""
    if args.from_run:
        run = Path(args.from_run)
        if not run.is_dir():
            print(f"pdk_revision_resolve: not a run directory: {run}",
                  file=sys.stderr)
            return 2
        derived, scanned = candidate_trees_from_run(run, fs)
        note = (f"derived from {scanned} tool log(s) in {run}; "
                f"{len(derived)} tree(s) offered a declared-revision artefact")
        for t in derived:
            if t not in trees:
                trees.append(t)
        derived_from = "run tool logs" if not args.tree else \
            "run tool logs + --tree"

    if not trees:
        rec = build_record([], read_in, derived_from, note)
        rec["reason"] = (
            "NOT DETERMINED — no PDK tree was given or derivable. "
            + (note + ". " if note else "")
            + "Either this run loaded no library from a tree that states its "
              "own revision, or it kept no tool log. REMEDY: a staged PDK "
              "under <run>/input/pdk/ is read as a tree, so give that tree a "
              "root revision file of its own (`<component> <revision>`); a "
              "revision typed into a config is the REQUEST again and is "
              "deliberately not accepted here.")
        _emit(args.json, rec)
        print("pdk_revision_resolve: rc=2 COULD NOT LOOK — " + rec["reason"],
              file=sys.stderr)
        return 2

    resolved = [resolve_tree(fs, t) for t in trees]
    rec = build_record(resolved, read_in, derived_from, note)
    _emit(args.json, rec)

    for t in resolved:
        if t["resolved"]:
            print(f"pdk_revision_resolve: {t['tree']} -> {t['revision']} "
                  f"(from {t['revision_source']}, resolved_tree="
                  f"{t['resolved_tree']})")
        else:
            print(f"pdk_revision_resolve: {t['tree']} -> {t['reason']}")

    gaps = record_gaps(rec)
    if gaps:
        print(f"pdk_revision_resolve: FAIL {REFUSAL_NOT_RECORDED} — the run's "
              f"PDK revision is not recorded:\n  - " + "\n  - ".join(gaps),
              file=sys.stderr)
        return 1
    print(f"pdk_revision_resolve: PASS — revision {rec['revision']}")
    return 0


def _emit(path: Optional[str], rec: Dict[str, Any]) -> None:
    if not path:
        return
    try:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
    except OSError as exc:
        print(f"pdk_revision_resolve: cannot write {path}: {exc}",
              file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
