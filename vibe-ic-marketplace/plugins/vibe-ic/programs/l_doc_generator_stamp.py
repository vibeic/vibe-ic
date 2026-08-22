#!/usr/bin/env python3
"""
l_doc_generator_stamp.py — every emitted L document records WHICH RELEASE
produced it, and a consumer can act on that.

VERDICT SEMANTICS (as a CLI): **GATE** (0 PASS / 1 FAIL / 2 scan error).

THE DEFECT THIS CLOSES
======================
Measured over the 2554 tracked ``benchmark-data/**/generated_docs/L*.json``:
not one carried the version of the plugin that produced it. An L document
was therefore indistinguishable from a current one no matter how old it
was, and the only defence was a reader remembering that an artefact is the
output of a past run. Discipline is not a mechanism: three issues were
filed in one day against documents produced ~70 releases earlier, read as
the current state of the flow. One of them was written by the person
holding that rule in the brief they had just handed out.

Two keys in the corpus LOOK like they close this and do not:

  ``emitted_by``   present on 1137 of 2554 documents, e.g.
                   ``"phase1_post_process.emit_l_doc_skeleton v0.1.51"``.
                   The version in it is a STRING LITERAL IN THE SOURCE. It
                   has not moved since it was typed, so a document emitted
                   at v1.7.x still says v0.1.51. It is worse than absent:
                   a reader who finds it has been told a version, and the
                   version is wrong.
  ``schema_version`` the DOCUMENT SCHEMA revision (1 / 2 / "v0.1.62"), not
                   the producing release. Two releases that agree on the
                   schema still disagree on what they extract.

WHAT ``provenance`` ALREADY MEANS HERE, AND WHY THIS IS NOT THAT
================================================================
In this repo "provenance" is already taken, for a different question:
``phase1_provenance_presence_check`` and ``l_doc_path_portability_check``
use it for WHICH INPUT DOCUMENT a value was extracted from. That is the
content's lineage. This module answers WHICH RELEASE OF THE TOOL wrote the
file — the artefact's vintage. Both are provenance in English; they are not
interchangeable, so this one gets its own name (``_generator``) and its own
module.

THE STAMP
=========
One top-level key, ``_generator``::

    "_generator": {
      "plugin": "vibe-ic",
      "plugin_version": "1.7.88",
      "l_doc_taxonomy_digest": "0f3a1c8e9b2d",
      "l_doc_taxonomy_docs": 28,
      "emitter": "phase1_doc_one_shot_runner._write_l_doc"
    }

``plugin_version`` is read from ``.claude-plugin/plugin.json`` at write
time — the release identity, not a literal anyone can forget to bump.

``l_doc_taxonomy_digest`` answers the sharper question: stale RELATIVE TO
WHAT IT CLAIMS TO DESCRIBE. An L document is an instance of the L-doc
taxonomy — it declares a ``doc_name``, a ``doc_class`` and an
``applicability``, all of which are taxonomy concepts. The digest is taken
over the taxonomy's STRUCTURAL contract only: the ``(code, full_name)``
pairs and the ``ic_class -> applicable codes`` map. Prose (titles,
descriptions, rationales) is excluded on purpose, so editing a comment does
not invalidate 2554 documents while adding an L document or moving one
between applicable/not-applicable does.

``emitter`` is the code path that LAST wrote the file. A dozen post-emit
hooks re-open an L document and rewrite it after the main chokepoint has
run, so "last writer" is the only claim that stays true; it is also the
value that makes the writer census answerable from the artefact itself.

THE WRITERS, COUNTED
====================
There is no single emitter, and assuming one was the trap this module had
to avoid: a stamp on one writer while a dozen others write unstamped
documents makes the ABSENCE of a stamp ambiguous rather than uniform,
which is worse than no stamp at all. Measured by instrumenting
``Path.write_text`` during real runs and cross-checked with an AST pass,
**192 write sites across 93 modules** produce ``generated_docs/L*.json``:

    phase1_doc_one_shot_runner.py           88   (1 chokepoint + ~30 hooks)
    *_protocol_synth.py (86 modules)        93   (80 identical private
                                                  helpers + 13 inline)
    phase1_post_process.py                   4
    phase1_one_shot_runner.py                3
    phase1_protocol_spec_extract.py          1
    l22_coverage_goal_emit.py                1
    tools/phase1_engine/render.py            1
    tools/phase1_engine/cli.py               1

All of them route through ``dump`` below. One further module writes L
documents and is deliberately NOT routed:
``benchmark_evidence_publish._copy_tree`` COPIES a finished project into
the corpus, and a copy must carry the stamp of the run that produced the
document — restamping on copy would relabel an old artefact as current.

NO TIMESTAMP, DELIBERATELY
==========================
The emitter is byte-deterministic today: the same inputs at the same
release produce the same bytes (verified by re-running a design twice and
diffing). A wall-clock field would destroy that, and with it the ability to
regenerate the corpus and read the diff as "what actually changed". Every
field in the stamp is a pure function of the code, so a regeneration that
changes nothing produces no diff.

WHAT A CONSUMER IS EXPECTED TO DO WITH IT
=========================================
Before concluding anything from a published L document — filing an issue,
quoting a count, calling a gate a blocker — ask this module what release
wrote it::

    python3 l_doc_generator_stamp.py <design-or-corpus-dir>

    UNSTAMPED  produced before this stamp existed. Vintage unknown. Do not
               read it as the current state of the flow; re-derive first.
    STALE      produced by a different release, or against a different
               L-doc taxonomy, than the one you are running. The report
               gives the version distance so a caller can set its own bar
               (``--max-minor-drift N``).
    NEWER      the document was produced by a LATER release than the one
               running. Your checkout is behind, not the document.
    CURRENT    same release, same taxonomy. Safe to read as current.

In code::

    from l_doc_generator_stamp import verdict, read
    v = verdict(doc)
    if v.status != "CURRENT":
        ...  # re-derive, or widen the claim to "as of <v.stamped_version>"

The gate is wired into ``phase1_doc_one_shot_runner``'s post-emit gate list,
where it enforces the invariant in the other direction: after a fresh run
EVERY L document must carry a CURRENT stamp, so a writer that escapes the
shared ``dump()`` chokepoint FAILs the run that introduced it rather than
being discovered in the corpus a release later.

chip-AGNOSTIC: no design, vendor, PDK or part-number literal — the module
reads a version file and a taxonomy contract and knows nothing about what
the documents describe.

Usage:
    python3 l_doc_generator_stamp.py <root> [--json OUT]
                                     [--max-minor-drift N]
                                     [--allow-unstamped]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

TOOL = "l_doc_generator_stamp"

#: The one top-level key this module owns. Underscore-prefixed because that
#: is the established convention in this corpus for a key that is
#: bookkeeping rather than extracted design data (see
#: ``metadata_content_substance_check``), which is what keeps a gate that
#: counts typed fields from reading it as content.
STAMP_KEY = "_generator"

PLUGIN_NAME = "vibe-ic"
_PLUGIN_JSON = _HERE.parent / ".claude-plugin" / "plugin.json"

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


# ─────────────────────────────────────────────────────────────────────
# The two facts the stamp records
# ─────────────────────────────────────────────────────────────────────
def plugin_version() -> str:
    """The running plugin's ``version`` from ``.claude-plugin/plugin.json``.

    Returns "" when unreadable rather than raising: an emitter must never
    fail to write a design artefact because a manifest is missing. An empty
    version is itself readable — ``verdict`` reports it as UNSTAMPED-grade
    information rather than silently claiming CURRENT.
    """
    try:
        doc = json.loads(_PLUGIN_JSON.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ""
    v = doc.get("version")
    return "" if v is None else str(v)


def _taxonomy_contract() -> Optional[Dict[str, Any]]:
    """The taxonomy's STRUCTURAL contract, or None if it cannot be read.

    Structure only — codes, filenames, and which codes each ic_class
    declares applicable. Titles/descriptions/rationales are prose and are
    excluded so a wording edit does not invalidate the whole corpus.
    """
    try:
        import l_doc_taxonomy as _tax
    except Exception:
        return None
    try:
        docs = [[s.code, s.full_name] for s in _tax.L_DOCS_V2]
        applicability = {
            cls: sorted(entry.get("applicable", []))
            for cls, entry in sorted(_tax.IC_CLASS_APPLICABILITY.items())
        }
    except Exception:
        return None
    return {"docs": docs, "applicability": applicability}


def taxonomy_digest() -> Tuple[str, int]:
    """(digest, doc_count) for the current L-doc taxonomy.

    ``("", 0)`` when the taxonomy cannot be read — an unknown digest is
    reported as unknown, never as a match.

    BARE HEX, NO ALGORITHM PREFIX, AND THIS IS NOT COSMETIC. The first
    version of this stamp emitted ``"sha256:<hex>"``. Measured on a
    two-design A/B of the real emitter, that value alone flipped
    ``ic_class`` from ``bus_peripheral`` to ``crypto_accelerator`` on nine
    documents: ``ic_class_profile._looks_like_crypto_accelerator`` harvests
    every string leaf of L1+L2 and its mandatory ``algorithm_family``
    pattern is ``\\bSHA[-_]?[0-9]*\\b``. A bookkeeping value had become
    design content. The consumer-side fix (``_harvest_strings`` skips this
    key) landed with it, but the value stays inert as well: a stamp must
    not carry a token that any classifier can read as a fact about the
    chip. The algorithm is documented here and nowhere in the artefact.
    """
    contract = _taxonomy_contract()
    if contract is None:
        return "", 0
    blob = json.dumps(contract, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12], \
        len(contract["docs"])


# ─────────────────────────────────────────────────────────────────────
# Writing
# ─────────────────────────────────────────────────────────────────────
def caller_emitter(depth: int = 2) -> str:
    """``"<module-file-stem>.<function>"`` for the frame ``depth`` up.

    DERIVED, NEVER TYPED. The key this module replaces — ``emitted_by`` —
    is wrong on 1137 corpus documents for exactly one reason: it is a
    string literal, copied into 80-odd modules, that nobody re-typed when
    the code moved on. A value read off the live call frame cannot drift
    from the code that produced it, so the default is to derive it and the
    explicit argument exists only for a caller that wants to name a
    LOGICAL emitter rather than the private one-line helper it happens to
    be sitting in.

    Falls back to ``"unknown"`` rather than raising: an emitter must never
    fail to write a design artefact because introspection was unavailable.
    """
    try:
        frame = sys._getframe(depth)  # noqa: SLF001
    except (ValueError, AttributeError):
        return "unknown"
    try:
        stem = Path(frame.f_code.co_filename).stem
        return f"{stem}.{frame.f_code.co_name}"
    except Exception:
        return "unknown"


def stamp(content: dict, emitter: Optional[str] = None) -> dict:
    """Attach the generator stamp to ``content`` in place; return it.

    Overwrites any stamp already present: when a post-emit hook rewrites a
    document the honest record is the writer that produced the bytes on
    disk, not the one that produced an earlier version of them.
    """
    if not isinstance(content, dict):
        return content
    if emitter is None:
        emitter = caller_emitter(2)
    digest, n_docs = taxonomy_digest()
    content[STAMP_KEY] = {
        "plugin": PLUGIN_NAME,
        "plugin_version": plugin_version(),
        "l_doc_taxonomy_digest": digest,
        "l_doc_taxonomy_docs": n_docs,
        "emitter": str(emitter),
    }
    return content


def dump(path: Path, content: dict, emitter: Optional[str] = None,
         indent: int = 2) -> Path:
    """THE write chokepoint for an L document: stamp, then serialise.

    Every path that writes ``generated_docs/L*.json`` goes through here.
    That is enforced two ways: statically by
    ``test_l_doc_generator_stamp.py``'s writer census (a new write site
    that does not call this function fails the suite) and at runtime by
    this module's own gate in the runner's post-emit list (a document on
    disk without a current stamp fails the run that produced it).

    Serialisation is byte-identical to what the writers used before —
    ``indent=2, ensure_ascii=False`` plus a trailing newline — so adopting
    the chokepoint changes exactly one thing about the output: the stamp.
    ``indent`` is settable only because one caller
    (``phase1_engine.render.render_layers``) already exposes it to ITS
    callers; nothing else should pass it.
    """
    path = Path(path)
    if emitter is None:
        emitter = caller_emitter(2)
    stamp(content, emitter)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(content, indent=indent, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return path


# ─────────────────────────────────────────────────────────────────────
# Reading
# ─────────────────────────────────────────────────────────────────────
def read(doc: Any) -> Optional[dict]:
    """The stamp on ``doc``, or None when it carries none."""
    if not isinstance(doc, dict):
        return None
    got = doc.get(STAMP_KEY)
    return got if isinstance(got, dict) else None


def parse_version(value: Any) -> Optional[Tuple[int, int, int]]:
    """``"1.7.88"`` -> ``(1, 7, 88)``; None when it is not a version."""
    if not isinstance(value, str):
        return None
    m = _VERSION_RE.match(value.strip().lstrip("v"))
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


@dataclass
class Verdict:
    """What a consumer branches on.

    ``status`` is one of UNSTAMPED / CURRENT / STALE / NEWER /
    UNKNOWN_VERSION / UNREADABLE. ``drift`` is ``current - stamped`` per
    component, so a caller can set its own bar instead of inheriting one.
    """
    status: str
    stamped_version: Optional[str] = None
    current_version: str = ""
    stamped_taxonomy: Optional[str] = None
    current_taxonomy: str = ""
    emitter: Optional[str] = None
    drift: Optional[Dict[str, int]] = None
    reasons: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def verdict(doc: Any,
            current_version: Optional[str] = None,
            current_taxonomy: Optional[str] = None) -> Verdict:
    """Classify one L document's vintage against the running release.

    ``current_version`` / ``current_taxonomy`` are injectable so a test can
    demonstrate the distinction the stamp exists to make without editing
    the manifest.
    """
    cur_v = plugin_version() if current_version is None else current_version
    if current_taxonomy is None:
        cur_t, _ = taxonomy_digest()
    else:
        cur_t = current_taxonomy

    if doc is None:
        return Verdict(status="UNREADABLE", current_version=cur_v,
                       current_taxonomy=cur_t,
                       reasons=["document could not be parsed"])
    got = read(doc)
    if got is None:
        return Verdict(
            status="UNSTAMPED", current_version=cur_v,
            current_taxonomy=cur_t,
            reasons=[f"no {STAMP_KEY} key — produced before the emitter "
                     f"recorded its release; vintage unknown"])

    sv = got.get("plugin_version")
    st = got.get("l_doc_taxonomy_digest")
    v = Verdict(status="CURRENT", stamped_version=sv, current_version=cur_v,
                stamped_taxonomy=st, current_taxonomy=cur_t,
                emitter=got.get("emitter"))

    st_tuple = parse_version(sv)
    cur_tuple = parse_version(cur_v)

    # WHICH SIDE IS UNREADABLE DECIDES THE VERDICT, and conflating the two
    # was a real regression. The installed-plugin CACHE is a bare layout —
    # `programs/` plus `agents/class_kb`, no `.claude-plugin/plugin.json` —
    # so `plugin_version()` legitimately returns "" there, for the document
    # AND for the running process. An earlier revision reported that as
    # UNSTAMPED, and since this module is a BLOCKING gate in the runner's
    # post-emit list, every Phase-1 run from an installed cache FAILED.
    # `test_v0_2_58_phase1_engine_bundle::test_install_smoke_bare_cache_
    # layout` caught it.
    #
    # The distinction the two branches encode:
    #
    #   running version unreadable  -> nothing can be COMPARED. The document
    #       is stamped (a writer did go through the chokepoint, which is the
    #       invariant the gate exists to protect); the deployment simply
    #       cannot name its own release. Reported, never a FAIL — a verdict
    #       over an unknown is not a verdict against the thing measured.
    #
    #   stamped version unreadable while ours is fine -> the DOCUMENT is
    #       the one refusing to say. It cannot be read as current, so this
    #       is beyond tolerance exactly like STALE.
    if cur_tuple is None:
        v.status = "UNKNOWN_VERSION"
        v.reasons.append(
            f"the running plugin version is unreadable ({cur_v!r}) — no "
            f"vintage comparison is possible, so nothing is claimed about "
            f"this document either way")
        return v
    if st_tuple is None:
        v.status = "UNKNOWN_VERSION"
        v.reasons.append(
            f"{STAMP_KEY}.plugin_version is not a version: {sv!r} — the "
            f"document is stamped but cannot state its vintage")
        return v

    v.drift = {"major": cur_tuple[0] - st_tuple[0],
               "minor": cur_tuple[1] - st_tuple[1],
               "patch": cur_tuple[2] - st_tuple[2]}

    if st_tuple > cur_tuple:
        v.status = "NEWER"
        v.reasons.append(
            f"produced by {sv}, newer than the running {cur_v} — this "
            f"checkout is behind the document")
        return v
    if st_tuple < cur_tuple:
        v.status = "STALE"
        v.reasons.append(f"produced by {sv}; running {cur_v}")
    if st and cur_t and st != cur_t:
        v.status = "STALE"
        v.reasons.append(
            f"produced against L-doc taxonomy {st}; current is {cur_t} — "
            f"the document set it claims to be part of has changed")
    return v


def exceeds(v: Verdict, max_minor_drift: Optional[int]) -> bool:
    """Is this verdict beyond the caller's tolerance?

    ``max_minor_drift=None`` means strict: anything but CURRENT/NEWER is
    beyond tolerance. Otherwise a STALE document is tolerated while it is
    within N minor families AND on the same major AND on the same taxonomy
    — a taxonomy change is never tolerated by a drift budget, because the
    document is then not an instance of the same contract at all.

    UNKNOWN_VERSION splits on WHO could not answer. When the RUNNING
    process cannot name its own release (the bare installed-cache layout,
    which ships no manifest) there is no comparison to be beyond tolerance
    of, and the document is stamped, so this is not a failure. When the
    DOCUMENT cannot name the release that wrote it while we can name ours,
    it is as unusable as an unstamped one.
    """
    if v.status in ("CURRENT", "NEWER"):
        return False
    if v.status in ("UNSTAMPED", "UNREADABLE"):
        return True
    if v.status == "UNKNOWN_VERSION":
        return parse_version(v.current_version) is not None
    if max_minor_drift is None:
        return True
    if v.stamped_taxonomy and v.current_taxonomy and \
            v.stamped_taxonomy != v.current_taxonomy:
        return True
    d = v.drift or {}
    if d.get("major", 0) != 0:
        return True
    return d.get("minor", 0) > max_minor_drift


# ─────────────────────────────────────────────────────────────────────
# Scanning a tree
# ─────────────────────────────────────────────────────────────────────
def scan_tree(root: Path,
              max_minor_drift: Optional[int] = None,
              allow_unstamped: bool = False) -> Dict[str, Any]:
    """Classify every L document under ``root``.

    Always reports ``documents_read``. A clean verdict over an empty scan
    is not a clean verdict — without a denominator a PASS cannot be told
    from a wrong root.
    """
    # Imported here, never copied, and lazily: a private "what is an L
    # document" walker is how two guards drift apart on the denominator,
    # but keeping the import out of module scope keeps THIS module a leaf
    # that the hot emitters (and the ic_class classifier) can import for
    # the stamp key alone without pulling in a scan chain.
    from l_doc_path_portability_check import iter_l_docs

    cur_v = plugin_version()
    cur_t, _ = taxonomy_digest()
    rows: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    offending: List[Dict[str, Any]] = []
    read_n = 0
    for p in iter_l_docs(Path(root)):
        read_n += 1
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            doc = None
        v = verdict(doc, current_version=cur_v, current_taxonomy=cur_t)
        counts[v.status] = counts.get(v.status, 0) + 1
        try:
            rel = str(p.relative_to(Path(root)))
        except ValueError:
            rel = str(p)
        row = {"file": rel, **v.as_dict()}
        rows.append(row)
        if v.status == "UNSTAMPED" and allow_unstamped:
            continue
        if exceeds(v, max_minor_drift):
            offending.append(row)
    return {
        "tool": TOOL,
        "root": str(root),
        "current_plugin_version": cur_v,
        "current_l_doc_taxonomy_digest": cur_t,
        "documents_read": read_n,
        "counts": counts,
        "max_minor_drift": max_minor_drift,
        "allow_unstamped": allow_unstamped,
        "offending": offending,
        "documents": rows,
        # VACUOUS is its own verdict, never folded into PASS: a green over
        # an empty scan is indistinguishable from a wrong root.
        "verdict": ("VACUOUS" if read_n == 0
                    else ("FAIL" if offending else "PASS")),
    }


def _format(result: Dict[str, Any]) -> str:
    n = result["documents_read"]
    counts = result["counts"]
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "—"
    head = (f"{TOOL}: {result['verdict']} ({n} L document(s) examined; "
            f"{summary}) — running {result['current_plugin_version'] or '?'}")
    lines = [head]
    for row in result["offending"][:20]:
        why = "; ".join(row.get("reasons") or []) or row["status"]
        lines.append(f"  {row['status']}: {row['file']} — {why}")
    extra = len(result["offending"]) - 20
    if extra > 0:
        lines.append(f"  … and {extra} more")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("root")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--max-minor-drift", type=int, default=None,
                    help="tolerate a STALE document up to N minor families "
                         "behind on the same major and the same taxonomy. "
                         "Omitted = strict (only CURRENT passes).")
    ap.add_argument("--allow-unstamped", action="store_true",
                    help="report documents with no stamp but do not FAIL on "
                         "them — for reading a corpus emitted before the "
                         "stamp existed.")
    args = ap.parse_args(argv)

    root = Path(args.root).expanduser()
    if not root.is_dir():
        print(f"{TOOL}: ERROR not a directory: {root}", file=sys.stderr)
        return 2
    result = scan_tree(root, max_minor_drift=args.max_minor_drift,
                       allow_unstamped=args.allow_unstamped)
    if args.json_out:
        try:
            out = Path(args.json_out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")
        except OSError as exc:
            print(f"{TOOL}: ERROR cannot write --json: {exc}",
                  file=sys.stderr)
            return 2
    if result["documents_read"] == 0:
        print(f"{TOOL}: VACUOUS — no L document (…/generated_docs/L*.json) "
              f"under {root}; nothing was examined, so this is not a PASS.")
        return 2
    print(_format(result))
    return 1 if result["offending"] else 0


if __name__ == "__main__":
    sys.exit(main())
