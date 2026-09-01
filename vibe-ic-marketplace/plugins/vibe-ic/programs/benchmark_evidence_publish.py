#!/usr/bin/env python3
"""benchmark_evidence_publish.py — stage a CONVERGED (IC × PDK) run's evidence
into the canonical benchmark-data layout (the PUBLISH half of the program-first
publish contract).

WHY THIS EXISTS (owner directive 2026-07-25)
============================================
"The way we publish a CONVERGED (IC × PDK) result's evidence into
benchmark-data/ic/ must become a PROGRAM in the plugin (program-first), so
EVERY future push to benchmark-data/ic/<IC>/ automatically follows the same
structure — never again a lone RESULT.md or a messy folder."

This program takes a completed run directory + the IC / PDK / plugin-version and
STAGES exactly the canonical structure into
`benchmark-data/ic/<IC>/v<version>_<PDK>/`, copying the right evidence, EXCLUDING
the large gitignored files (*.gds/*.def/*.spef/*.oas), generating the
GDS_MANIFEST (sha256 + byte size), and REFUSING to publish a run that is NOT
converged. Its companion `benchmark_evidence_structure_check.py` validates the
result (and this program runs it as a post-stage self-check).

  It STAGES ONLY — it never `git add` / `git commit` / `git push`. Publishing to
  the repo stays a deliberate human/agent act. The program prints the exact
  `git add` command; a person commits it.

THE CANONICAL STRUCTURE it produces
===================================
    benchmark-data/ic/<IC>/v<version>_<PDK>/
        RESULT.md                           independent-audit verdict (required)
        provenance.jsonl                    (copied if present)
        phase1/…                            L* generated_docs + input_doc + json
        phase2/…                            RTL + synth + constraints
        phase3/reports/…                    DRC/STA rpt (if present)
        phase3/stage4/gds/GDS_MANIFEST.txt  <name> <bytes>B sha256:<hash>
        reports/…                           reports/phase3 + audit + orchestrator…
    benchmark-data/ic/<IC>/input/           shared design input (staged once)

LAYOUT ARTEFACTS ARE ROUTED BY SIZE, NOT BY EXTENSION (#419). Within the
PUBLISHED SCOPE — the copied subtrees listed above plus the signoff GDS —
*.gds, *.def, *.spef and *.oas under the ceiling are STAGED; above it the
blob is not copied and the routing decision is RECORDED so the omission is
legible. Size does NOT widen that scope: an artefact in a subtree this
program does not publish stays unpublished however small it is, and is
recorded as such rather than passed over in silence.

  This paragraph used to declare these four extensions excluded as a matter
  of construction, on the grounds that they were gitignored or too large, and
  both halves had stopped being true. `.gitignore` negates
  `.gds`/`.def` back for `benchmark-data/ic/**`, and `.spef`/`.oas` were never
  ignored at all. "Too large" is a property of the FILE: this project's own
  GDS range from 0.73 MB (spm) to 105 MB (sha256). Dropping by extension threw
  away the small artefact a reviewer wants in order to avoid the large one
  nobody can commit — so a cell published by this program carried LESS
  evidence than the hand-staged cells it replaced.

  THE SIGNOFF GDS IS PART OF THAT POPULATION, and until this change it was
  not. v1.6.61 replaced the extension test with a size test, but the size
  test only ever saw files inside the copied subtrees (phase1, phase2,
  phase3/reports, reports) — and the signoff GDS lives in
  `phase3/stage4/gds/`, which is not one of them. So a 0.8 MB GDS, three
  orders of magnitude under the ceiling and explicitly accepted by
  `.gitignore`, was still dropped: measured on a synthetic run at v1.6.61,
  the published cell contained ZERO layout artefacts and the program
  reported "excluded raw: 0", because the file it silently omitted was never
  offered to the predicate. The GDS the manifest is ABOUT is now staged when
  it fits, which is what makes the reference cells' shape reproducible by
  program rather than by hand.

EVERY LAYOUT ARTEFACT LEAVES A RECORD — `LAYOUT_ROUTING.txt` at the cell root,
one line per layout artefact found under the source run directory:

    <relpath> <bytes>B sha256:<64hex> <DECISION> <destination>
    DECISION ∈ STAGED | ROUTED_AWAY | NOT_PUBLISHED | OFF_CANONICAL_PATH

A reader can therefore distinguish "big, stored elsewhere, here is its hash"
from "in the run but out of published scope" from "never existed" — three
states the count on stdout collapsed into one, because stdout is not part of
the deliverable. The fourth, OFF_CANONICAL_PATH, exists because staging
`_ROUTED_DEF_RELPATH` created a state that did not exist before it: an artefact
that IS in published scope and is not where the scope looks. Saying
NOT_PUBLISHED there asserts a policy decision nobody made. `--oversize-route` names the destination for the routed-away
ones; it defaults to `not-retained`, which is the honest answer when nobody
has said otherwise. A cell that records "not-retained" is a better deliverable
than one that quietly looks whole.

Raw PnR scratch under phase3/stage3 is still not staged: that is a decision
about what counts as evidence, which is separate from how big a file is.
`placed.def`, `floorplan.def`, `post_cts.def`, the stage's `.tcl`, and
`phase3/stage3/extracted/*.spef` are all still NOT_PUBLISHED, and widening the
SUBTREE remains an evidence-policy call left alone here.

ONE artefact out of that subtree is now staged: `phase3/stage3/pnr/routed.def`,
under `_ROUTED_DEF_RELPATH`, size-routed exactly like the GDS. Not a widening
of the scratch policy -- a repair of the same omission the GDS block below
carries its own comment about. Its directory is not a copy subtree, so the size
routing could not reach it and the artefact was dropped at EVERY size; MEASURED
at 38 bytes, six orders of magnitude under the ceiling, recorded
`NOT_PUBLISHED source-run-only`. A BLOCKING hygiene loop selects its whole
population on that one path, so no number of published cells could make it
check anything. It also moves this program TOWARD the hand-staged reference
cells rather than away from them: they carry that file, and on the rest of the
subtree (`extracted/*.spef`) this program still publishes less than they do.

COMPILER BUILD RESIDUE IS NOT EVIDENCE AND IS NEVER STAGED (#2006)
===================================================================
`phase2/` is a copied subtree, and the coverage measurement builds a Verilator
model under `phase2/stage1/sim/cov_build/`: precompiled headers, object files,
dependency listings, the generated C++ model and the compiled simulator.
`_copy_tree` walked that directory wholesale.

MEASURED (one published cell, 2026-09-01): 55 files and 174,624,038 bytes
landed from that one directory, the two precompiled headers 84 MB EACH -- over
the commit ceiling, which the size routing applies to layout artefacts and to
nothing else -- beside ONE file with evidentiary value, the 71,241-byte
`coverage.dat` the coverage report is derived from. A clone of that cell
downloads more than two thousand times the evidence to receive it.

The rule is `is_build_residue`: a compiler intermediate by EXTENSION (`.gch`,
`.pch`, `.o`, `.obj`, `.a`, `.so`, `.d`), anything under an `obj_dir/`, and --
inside a directory Verilator populated, which it marks with
`<prefix>__verFiles.dat` -- every file carrying that model prefix or the
`verilated*` runtime name. The simulation's OWN outputs carry neither
(`coverage.dat`, the junit XML, `pass.flag`, the testbenches, logs) and stay.
The Verilator half is bound to the MARKER, not to a directory name: the flow
names its model directory `cov_build`, and a rule keyed on the tool's default
`obj_dir` would have missed the measured case entirely.

This is not size routing and gets no `LAYOUT_ROUTING.txt` line. A build
intermediate is reproduced by re-running the build, so "dropped at publish"
and "never existed" call for the same action from a reader -- unlike a layout
artefact, where the two call for opposite ones. The omission is still legible:
the count, the bytes and the paths are in the JSON summary
(`build_residue_skipped`) and on stdout, and the `provenance.jsonl` pruning
below discloses any declared output among them.

A STAGED DOCUMENT'S CITED PROOF SHIPS WITH IT — CITATION CLOSURE (#2007)
=========================================================================
The copy subtrees decide what is staged by WHERE a file sits. A document
inside them decides what it needs by NAME: `RESULT.md` says "retained in
`full_acceptance.log`", `reports/phase3/antenna.json` says `"source":
"phase3/stage3/pnr/openroad.log"` under `"verdict": "PASS"`. Neither path is in
a copied subtree, so the cell shipped both documents and neither proof, and
`CITATION_ROUTING.txt` recorded the two rows DANGLING / DANGLING_UNDER_PASS --
this program KNEW the cited proofs were absent and staged the citing documents
anyway. `evidence_citation_resolves_check` deliberately does not honour those
two words (a hole is not a reason for the hole), so the cell was unlandable.

MEASURED (spm x gf180mcuD v1.14.88, benchmark-data 0798cc8e): 2 NEW dangling
citations against a register of 4; both artefacts existed in the run tree,
28,993 B and 57,311 B, three orders of magnitude under the commit ceiling.

THE RULE (`close_citations`): after every subtree, the GDS, the routed DEF and
the step records are decided, every citation a staged document carries -- the
same population `CITATION_ROUTING.txt` records, so the record and the closure
cannot disagree about what "cites" means -- is resolved along the gate's own
ladder (the citing document's directory, then each ancestor to the cell root).
A rung that names a regular file in the RUN tree is STAGED at that same
relative path: it is evidence by definition, the document's own proof, and the
reader following the pointer finds it exactly where the document said. ONE
reason not to: the commit ceiling, recorded OVER_CEILING. Two policies the
closure defers to rather than overrides, because each already has a record of
its own: a cited LAYOUT artefact (`.gds`/`.def`/`.spef`/`.oas`) stays under the
size-and-scope routing in `LAYOUT_ROUTING.txt`, and a cited `steps/` path stays
under `STEP_ROUTING.txt` (the view is symlinks and is recorded, not mirrored).

WHAT GENUINELY DOES NOT EXIST IS NEVER INVENTED. A citation with no file at any
rung is ABSENT_IN_RUN; its routing row stays DANGLING, and the staged document
is amended by the honest-absence mechanism the gate already honours
(vibe-ic#381; the kcite3 precedent, benchmark-data aa8a19b4): a JSON gate
report whose top-level field cites the absent artefact is rewritten IN THE
CELL -- never in the run -- with `evidence_present: false`, the citing field
nulled and kept under `evidence_absent`, and its `verdict` moved to
UNSUBSTANTIATED with the run's own word retained as `verdict_as_run`. A
Markdown document has no such field and is prose this program will not edit:
it is reported as UNAMENDED on stdout and in the summary, and the corpus gate
stays red on it until a person amends it. Only the citations the gate JUDGES
(`.log`/`.rpt`/`.sby`, and `.md` carrying a directory) are amended, because
those are the ones the gate would otherwise fail; a `.json` cited by the audit
record is recorded absent and left as the run wrote it.

THE PER-STEP EVIDENCE — RECORDED, NOT MIRRORED (`STEP_ROUTING.txt`, `steps/`)
============================================================================
`steps/` used to be excluded here by name, as "per-step scratch". The effect
was that NO published cell carried anything per-step, so a reader — or a
per-step dimension of the evaluation matrix — had nothing to read even when
the run had produced a full steps tree.

But the run's `steps/` tree is a view made of SYMLINKS into that run
directory, and a symlink is a promise about a filesystem, not evidence. Two
measurements, both on this repo:

  * `_car15_evidence`, a CONVERGED run whose steps tree was materialized and
    whose run directory was then renamed: 63 steps, 90 declared outputs,
    **83 of 83 view symlinks DANGLING**. Copying that tree would have
    published 83 broken links.
  * the legacy hand-staged cells that DID commit their steps tree:
    **142 tracked symlinks, 31 of whose targets the index does not carry** —
    so a clean clone receives 31 dangling links from a committed cell. The
    same hole `_published_tree` documents at #404.

So the published form is the RECORD, never the view. Per step folder, mirrored
into the owner's nested `steps/<phase>/<stage>/<id>_<slug>/` layout,
`STEP_RECORD.json` states each declared output as a RUN-RELATIVE path with its
byte size, its sha256, and where a reader of THIS cell can find it. No symlink
is created and none is copied. That is the same doctrine `GDS_MANIFEST.txt`
already applies to geometry: the hash is what makes an artefact verifiable
whether or not it is stored.

Recording it resolves the declaration against the run at PUBLISH time, which
is the load-bearing part. On the same `_car15_evidence` run, **7 outputs
declared present by 7 steps whose own status is `pass` no longer exist** —
`phase3/stage3/pnr/{floorplan,placed,post_cts,post_hold,routed,filled}.def`
and one `.spef`. Mirroring the view would have shown 83 identical broken
links and named none of them; the record names the step, the path and the
size that was claimed.

`STEP_ROUTING.txt` at the cell root is the flat, greppable index of the same
data, and — like `LAYOUT_ROUTING.txt` — it is emitted even when there is
nothing to report. A cell whose run produced no steps tree at all says so in
one line, which is a different fact from a cell published before this
existed.

THE PDK-REVISION GUARD (anti-irreproducibility) — BLOCKING
==========================================================
A cell published here is a sign-off number for one (IC x PDK). The toolchain
half of that claim has been recorded since `reports/container_image.json`
existed; the PDK half was never recorded at all. Everything a run said about
its PDK said the REQUEST — `--pdk <name>` on this program's own command line,
`env_PDK_ROOT` in a repro bundle, the registry entry, and this cell's own
`v<version>_<PDK>` directory name — and a name is not a revision. Two cells a
year apart, against a re-pulled volume, are byte-identical in that record and
were measured against different process data.

So a run must arrive carrying `reports/pdk_revision.json`, written at run time
by `pdk_revision_resolve` from the tree the tools ACTUALLY READ (resolved
through symlinks, revision taken from an artefact the tree itself ships).
Absent, unreadable, or carrying no declared revision -> REFUSE, nothing is
staged. There is no flag that turns this into a warning and no spelling of
"unknown" that satisfies it: a record that says the revision could not be
determined is the gap restated, not the gap closed.

This is a guard on the RUN, not a retroactive rule about cells already
published: a cell that predates the record is untouched, and only a NEW
sign-off has to arrive attributable. That is the same scoping the repo already
chose for `benchmark_run_manifest` -- "what must not happen again is a NEW
number arriving without its composition".

THE CONVERGENCE GUARD (anti-fabrication)
========================================
Only a run whose machine verdict is PASS or PASS_WITH_WAIVERS is publishable.
The verdict is read from the run's own
`reports/audit/phase23_completion_audit.json` (`flow_compliance_check.py`'s
canonical machine artifact). No audit artifact, a FAIL verdict, a missing/FAIL
RESULT.md, or no streamed GDS -> the program REFUSES and stages nothing. A
failing run can never be staged as if it passed.

chip-AGNOSTIC: the IC, PDK and version are parameters; NO IC / PDK / vendor /
SKU literal appears in this program's logic.

USAGE
=====
    python3 benchmark_evidence_publish.py \
        --run-dir /path/to/completed_run \
        --ic <IC> --pdk <PDK> --plugin-version 1.5.66 \
        --dest-root benchmark-data \
        [--result-md RESULT.md] [--input-docs docs/] [--gds streamed.gds] \
        [--force] [--dry-run] [--json out.json]

EXIT CODES
==========
    0  staged (or, with --dry-run, would stage) a conformant evidence folder
    1  REFUSED — not converged / missing required input / nonconformant result
    2  usage / I/O error
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess

import _published_tree
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# The layout artefacts. These used to be dropped from every copied subtree by
# EXTENSION, on the stated grounds that they were "gitignored / too large".
# Neither half is true any more (#419):
#
#   * `.gds` / `.def` are ignored at the repo root AND negated back for
#     `benchmark-data/ic/**` — git accepts them. `.spef` / `.oas` were never
#     ignored at all, so the spm cells' .spef files needed no force-add.
#   * "too large" is a property of the FILE, not of its extension. Measured
#     spread across this project's own GDS: 0.73 MB (spm) to 105 MB (sha256),
#     three orders of magnitude. The extension rule threw away the 0.8 MB
#     artefact a reviewer wants in order to avoid the 105 MB one nobody can
#     commit, and a cell published TODAY therefore carried less evidence than
#     the hand-staged cells this program replaced.
#
# So they are ROUTED BY SIZE, and either way the manifest records the sha256,
# which is what makes an artefact verifiable whether or not it is stored.
_LAYOUT_EXTS = (".gds", ".def", ".spef", ".oas")

# Must match `tracked_blob_size_guard._CEILING`, which is the gate that
# actually blocks the commit. `_size_policy_drift_check` below fails if these
# two, `.gitignore`, and this module's docstring ever stop agreeing.
_SIZE_CEILING = 50 * 1000 * 1000
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_CONVERGED = ("PASS", "PASS_WITH_WAIVERS")

# Evidence subtrees copied verbatim (minus oversize layout artefacts and
# compiler build residue, see `_copy_tree`). Order = the
# canonical committed shape of the reference cells; NOT phase3/stage3 (raw PnR),
# NOT sim/ (empty in the reference).
#
# `steps/` is deliberately NOT in this list and never will be: it is a tree of
# symlinks into the run directory, and `_copy_tree` would either dereference
# them (duplicating every artefact's bytes into the cell — measured 358 MB
# twice on edge_llm_accel, see `rtl_scan_scope`) or ship links that dangle for
# any reader who is not on the authoring host. It is published by
# `publish_steps` below, as a RECORD.
_COPY_SUBTREES = (
    "phase1",
    "phase2",
    Path("phase3") / "reports",
    # The A-track's own evidence. This list was derived from the DIGITAL
    # reference cells, so it staged `phase3/reports` and nothing else under
    # phase3 — and an ANALOG cell keeps its substance in `phase3/analog/`:
    # per-block specs, extracted netlists, and the hardmacro layouts.
    #
    # MEASURED (u_hawaii_adc x sky130A, 2026-08-06). The cell published with 31
    # analog files left behind, so the folder that is supposed to BE the
    # evidence did not contain the evidence — while `reports/analog/` came
    # across and made it look complete. Eight tests read
    # `phase3/analog/hardmacro/` and could only find it in the pre-canonical
    # run tree at the IC level, which is exactly the sibling directory the
    # layout contract forbids and which therefore could not be retired.
    #
    # Absent on a digital cell, where `_copy_tree` skips a missing source, so
    # the staged output of every digital cell is byte-identical to before.
    Path("phase3") / "analog",
    "reports",
)
_COPY_FILES = ("provenance.jsonl",)

# THE ONE ARTEFACT PUBLISHED OUT OF `phase3/stage3`, AND WHY IT IS NAMED HERE
# RATHER THAN ADDED TO `_COPY_SUBTREES`.
#
# `repo_hygiene_gates.sh` declares a BLOCKING loop over the corpus "published
# cells carrying a routed DEF", and `tools/ci/routed_def_corpus.py` selects its
# population on exactly one path shape inside the published tree:
#
#     ic/<design>/<version>/phase3/stage3/pnr/routed.def
#
# MEASURED (2026-08-22, synthetic converged run, supported publish path): a
# routed DEF of 38 bytes -- six orders of magnitude under `_SIZE_CEILING` --
# produced a cell containing ZERO `.def` files, recorded as
# `NOT_PUBLISHED source-run-only`. `phase3/stage3` is not a copy subtree, so
# the size routing never reached it and NO number of published cells could add
# a member to that corpus. The gate was not one publish away from checking
# something; it was unreachable from every supported action.
#
# That is the SAME defect the GDS block in `publish` already carries its own
# comment about, one artefact over: "`phase3/stage4` is not a copy subtree, so
# until this existed the GDS was omitted at EVERY size -- the size routing
# could not reach the one artefact the manifest is actually about."
#
# ONE ARTEFACT, NOT THE SUBTREE, and that distinction is the whole design. The
# docstring above records that widening published scope to raw PnR scratch is
# an evidence-policy call, deliberately left alone -- and it stays left alone:
# `placed.def`, `floorplan.def`, `post_cts.def`, the `.tcl`, and
# `phase3/stage3/extracted/` are all still NOT_PUBLISHED. What changes is only
# that the artefact three registered gates are ABOUT can reach a reader, routed
# by the same size rule as every other layout blob, so a cell over the ceiling
# is still ROUTED_AWAY rather than made unlandable.
#
# It is also a RESTORATION, not a new policy: the docstring already records
# that "the three hand-staged reference cells DO carry `phase3/stage3/pnr/
# routed.def` ... so on that subtree this program still publishes less than
# they do."
_ROUTED_DEF_RELPATH = Path("phase3") / "stage3" / "pnr" / "routed.def"


class Refuse(Exception):
    """A guard tripped; publish must not proceed."""


# --------------------------------------------------------------------------
# Verdict helpers.
# --------------------------------------------------------------------------

def _pdk_revision(run_dir: Path) -> Dict[str, object]:
    """The run's resolved PDK revision, or REFUSE. **BLOCKING** — a failure
    here stops the publish and stages nothing.

    The record is READ, never re-derived: at publish time the tree that ran may
    be on another host, another image, or gone, so anything computed here would
    describe the PUBLISHER's PDK rather than the run's. That substitution is
    the whole failure class this guard exists to close, one layer up.

    `record_gaps` is IMPORTED from the program that writes the record, so the
    writer and this reader cannot drift into two different notions of
    "recorded" — the same rule the write-ledger guard below follows.

    WHAT IT DOES NOT DEFEND AGAINST, stated so nobody reads more into it: a
    hand-written record. Anyone can type forty hex characters into the file.
    This closes the ACCIDENTAL gap — the one where a real run is published and
    nobody, including its author, can say afterwards which process data it was
    measured against — and that is the same floor `benchmark_run_manifest`
    accepts for its own fields. Corroborating the claimed tree against the
    run's own tool logs would raise it, and is deliberately NOT done here: a
    published run does not have to keep its logs (measured by
    `declared_pdk_is_the_pdk_used_check` at 7 of 107 tracked run dirs carrying
    no `*.log` at all), so requiring it would refuse runs for a property of
    their archive rather than of their sign-off.
    """
    _here = str(Path(__file__).resolve().parent)
    if _here not in sys.path:
        sys.path.insert(0, _here)
    import pdk_revision_resolve as _prr

    rec, err = _prr.load_record(run_dir)
    if rec is None:
        raise Refuse(
            f"the run records no PDK revision ({err} under {run_dir}). A "
            f"sign-off is a claim about a design measured against a PROCESS, "
            f"and this run names the process only by the word passed on the "
            f"command line — so the numbers in it cannot be re-derived later. "
            f"Produce the record from the tree that ran:\n"
            f"    python3 {Path(__file__).parent}/pdk_revision_resolve.py "
            f"--from-run {run_dir} --container <name> "
            f"--json {run_dir}/{_prr.RECORD_REL}\n"
            f"  (the one-shot runner writes it automatically at finalize)")
    gaps = _prr.record_gaps(rec)
    if gaps:
        raise Refuse(
            f"{run_dir}/{_prr.RECORD_REL} does not name a PDK revision:\n  - "
            + "\n  - ".join(gaps)
            + "\n  This is NOT waivable by writing 'unknown' into the field: "
              "an unnamed process revision makes every sign-off number in this "
              "cell unreproducible, which is the one thing publishing it is "
              "supposed to prevent.")
    return rec


def _audit_verdict(run_dir: Path, verdict_json: Optional[Path]) -> Tuple[str, Path]:
    """Return (verdict, source_path) from the run's flow-compliance audit JSON."""
    cand = verdict_json or (run_dir / "reports" / "audit" / "phase23_completion_audit.json")
    if not cand.is_file():
        raise Refuse(
            f"convergence unverifiable: no audit verdict at {cand} "
            f"(run flow_compliance_check.py --strict first, or pass --verdict-json)")
    try:
        data = json.loads(cand.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        raise Refuse(f"cannot parse audit verdict {cand}: {exc}")
    verdict = str(data.get("verdict", "")).upper().replace("-", "_")
    if not verdict:
        raise Refuse(f"audit verdict at {cand} has no 'verdict' field")
    return verdict, cand


def _result_md_verdict(result_md: Path) -> Optional[str]:
    """Best-effort verdict token from a RESULT.md's VERDICT section."""
    try:
        upper = result_md.read_text(encoding="utf-8", errors="replace").upper()
    except Exception:
        return None
    m = re.search(r"^#{1,6}\s*VERDICT\b", upper, re.MULTILINE)
    region = upper
    if m:
        start = m.end()
        nxt = re.search(r"^#{1,6}\s", upper[start:], re.MULTILINE)
        region = upper[start:start + nxt.start()] if nxt else upper[start:]
    for tok in ("PASS_WITH_WAIVERS", "PASS", "FAIL"):
        for tm in re.finditer(r"\b" + re.escape(tok) + r"\b", region):
            if tok == "PASS" and region[tm.start():tm.start() + 17] == "PASS_WITH_WAIVERS":
                continue
            return tok
    return None


# --------------------------------------------------------------------------
# Copy helpers.
# --------------------------------------------------------------------------

def is_layout_artefact(p: Path) -> bool:
    """True for the four extensions whose routing this program decides."""
    return p.suffix.lower() in _LAYOUT_EXTS


def over_ceiling(p: Path, ceiling: int = _SIZE_CEILING) -> bool:
    """True when `p` is too big to commit.

    Named and exported on purpose: `size_policy_drift_check` CALLS this to
    confirm the decision follows the declared ceiling. A checker that only
    greps for the constant proves the policy is spelled, not that it is
    obeyed — and a mutant that reverts to an extension rule while leaving the
    constant in place passed exactly such a grep.
    """
    try:
        return p.stat().st_size > ceiling
    except OSError:
        # Unreadable size is not evidence of smallness. Route it away and let
        # the record carry what is known, rather than copying blind.
        return True


def _excluded(p: Path) -> bool:
    """A layout artefact is excluded only when it is TOO BIG to commit.

    #419. The predicate used to be `suffix in _RAW_EXTS` — an extension test
    standing in for a size test. Everything else is copied as before; a
    layout artefact under the ceiling now ships, and one over it is skipped
    for the reason that is actually true of it.
    """
    return is_layout_artefact(p) and over_ceiling(p)


# Compiler build residue (#2006). Not evidence, not size-routed, never staged.
#
# Extensions no tool in this flow writes as a deliverable: precompiled headers,
# object files, static and shared archives, dependency listings. Binary except
# for `.d`, which is a list of the BUILD HOST's include paths — residue with a
# host-path leak on top.
_BUILD_RESIDUE_EXTS = frozenset({".gch", ".pch", ".o", ".obj", ".a", ".so", ".d"})
# Verilator's default model directory; `.gitignore` already names it.
_BUILD_RESIDUE_DIRS = frozenset({"obj_dir"})
# Verilator writes `<prefix>__verFiles.dat` into every model directory it
# populates (`-Mdir`), whatever that directory is called. `<prefix>` is the
# model's own name (`V<top>` unless `--prefix` says otherwise), and every file
# Verilator emits there carries it: the C++ model, its headers, `<prefix>.mk`,
# `<prefix>_classes.mk`, the compiled executable. The runtime it copies in
# beside them is named `verilated*`. The SIMULATION's outputs carry neither.
_VERILATOR_MDIR_MARKER = "__verFiles.dat"
_VERILATOR_RUNTIME_PREFIX = "verilated"


def _verilator_model_prefixes(directory: Path) -> Tuple[str, ...]:
    """The model prefixes Verilator has written into `directory` — empty when
    Verilator never populated it. One `listdir`; no cache, because the walk
    that calls this is bounded by the run tree and a stale answer would be
    worse than a repeated syscall."""
    try:
        names = os.listdir(directory)
    except OSError:
        return ()
    n = len(_VERILATOR_MDIR_MARKER)
    return tuple(sorted(name[:-n] for name in names
                        if name.endswith(_VERILATOR_MDIR_MARKER) and len(name) > n))


def is_build_residue(p: Path) -> bool:
    """True for a compiler / Verilator build intermediate.

    Named and exported on purpose, like `over_ceiling`: the test for #2006
    probes this decision directly as well as through a publish, so a mutant
    that keeps the name and loses the Verilator half is still caught.

    Bound to evidence the TOOL leaves, not to a directory name or a `V*`
    file-name shape on its own: a `Vtop.h` in a directory Verilator never
    populated is somebody's source and stays.
    """
    if any(part in _BUILD_RESIDUE_DIRS for part in p.parts[:-1]):
        return True
    if p.suffix.lower() in _BUILD_RESIDUE_EXTS:
        return True
    prefixes = _verilator_model_prefixes(p.parent)
    if not prefixes:
        return False
    name = p.name
    if name.startswith(_VERILATOR_RUNTIME_PREFIX):
        return True
    return any(name.startswith(prefix) for prefix in prefixes)


def _residue_record(p: Path, rel_base: Path) -> dict:
    """One JSON-summary entry for a build intermediate left behind."""
    try:
        size = p.stat().st_size
    except OSError:
        size = -1
    try:
        rel = p.resolve().relative_to(rel_base).as_posix()
    except ValueError:
        rel = p.name
    return {"path": rel, "bytes": size}


def _record(p: Path, rel_base: Path, decision: str,
            route: str, sha: Optional[str] = None) -> dict:
    """One line's worth of routing evidence for a single layout artefact.

    `path` is always relative to the RUN directory — one frame of reference
    for all three decisions, so the lines can be compared with each other.
    For an artefact staged into the CELL it is also the path inside the cell,
    because the copied subtrees keep their run-relative layout. That does NOT
    hold for the shared design input, which is staged to `ic/<IC>/input/`;
    its `destination` column says `shared-input` precisely because the path
    column cannot be read as a cell path there.
    """
    try:
        size = p.stat().st_size
    except OSError:
        size = -1
    try:
        rel = p.resolve().relative_to(rel_base).as_posix()
    except ValueError:
        rel = p.name
    dest = {"STAGED": "in-cell",
            "ROUTED_AWAY": route,
            # The artefact IS in published scope and is not where the scope
            # looks. Its DESTINATION is the same as an excluded artefact's --
            # it went nowhere -- so the distinction has to live in the
            # DECISION, which is the column that says why.
            "OFF_CANONICAL_PATH": "source-run-only",
            "NOT_PUBLISHED": "source-run-only"}[decision]
    return {
        "path": rel,
        "bytes": size,
        "sha256": sha if sha is not None else (_sha256(p) if size >= 0 else ""),
        "decision": decision,
        "destination": dest,
        "src": str(p.resolve()),
    }


def _copy_tree(src: Path, dst: Path, dry: bool,
               rel_base: Optional[Path] = None,
               route: str = "not-retained",
               residue_out: Optional[List[dict]] = None,
               copied_out: Optional[List[Tuple[Path, str]]] = None
               ) -> Tuple[int, List[dict]]:
    """Copy every non-excluded regular file under src into dst (preserving
    relative layout).

    Every file copied (or, on a dry run, that WOULD be copied) is appended to
    `copied_out` as `(source, path relative to rel_base)` when the caller
    passes a list. For the copy subtrees `rel_base` is the run directory and
    the cell mirrors the run, so that path is also the file's path in the
    cell -- which is what `close_citations` (#2007) needs: the population of
    staged documents, decided by the same walk that stages them, in both
    modes.

    Returns (files_copied, layout_records) — one record per LAYOUT artefact
    seen, whether it was staged or routed away. The routed-away ones used to
    be a bare integer that reached stdout and nothing else; an omission that
    leaves no trace in the deliverable is indistinguishable from an artefact
    that never existed.

    Compiler build residue (`is_build_residue`, #2006) is never copied; each
    skipped file is appended to `residue_out` when the caller passes a list,
    so the summary can say what was left behind and how big it was.
    """
    copied = 0
    records: List[dict] = []
    for f in sorted(src.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(src)
        if is_build_residue(f):
            if residue_out is not None:
                residue_out.append(_residue_record(
                    f, rel_base if rel_base is not None else src))
            continue
        if _excluded(f):
            if rel_base is not None:
                records.append(_record(f, rel_base, "ROUTED_AWAY", route))
            continue
        if is_layout_artefact(f) and rel_base is not None:
            records.append(_record(f, rel_base, "STAGED", route))
        target = dst / rel
        if not dry:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
        if copied_out is not None and rel_base is not None:
            copied_out.append((f, f.relative_to(rel_base).as_posix()))
        copied += 1
    return copied, records


def _inventory_unpublished(run_dir: Path, seen: set, route: str) -> List[dict]:
    """Every layout artefact under the run that the cell does NOT carry and
    that was never offered to the size rule — phase3/stage3 scratch, steps/,
    anything outside the published subtrees.

    Without this the record could not support the claim a reader most needs
    from it. An artefact in neither the cell nor the record would be
    ambiguous between "never existed" and "exists in the run, published
    scope just does not include it" — and those call for opposite actions.
    Recording the sha256 is what turns recovery into a verifiable file copy
    rather than a guess about which of two same-named layouts is the one the
    verdict describes.

    ONE LINE PER UNDERLYING BLOB, not per path that reaches it. Converged runs
    alias their artefacts: this run carries 63 symlinks under `steps/` pointing
    back into `phase3/stage3/`, 8 of them layout artefacts. `rglob` yields the
    symlink and its target as separate entries, and `_record` resolves before
    computing the path column, so both would emit a BYTE-IDENTICAL line. That
    is not extra evidence — it is the same evidence twice, and it inflates the
    counts printed beside it. Dedupe on the resolved path, accumulating as we
    go; `seen` (the caller's staged set) is read, never mutated.
    """
    out = []
    recorded = set(seen)
    for f in sorted(run_dir.rglob("*")):
        if not f.is_file() or not is_layout_artefact(f):
            continue
        real = f.resolve()
        if real in recorded:
            continue
        recorded.add(real)
        out.append(_record(f, run_dir, "NOT_PUBLISHED", route))
    return out


def _find_gds(run_dir: Path, explicit: Optional[Path]) -> List[Path]:
    """Return the streamed GDS file(s) to manifest.

    --gds wins; else every *.gds directly in the canonical streamout dir
    phase3/stage4/gds/ (one manifest line each, matching the reference shape);
    else, as a fallback, the single largest *.gds anywhere under the run.
    """
    if explicit is not None:
        if not explicit.is_file():
            raise Refuse(f"--gds {explicit} not found")
        return [explicit]
    canonical = run_dir / "phase3" / "stage4" / "gds"
    if canonical.is_dir():
        hits = sorted(p for p in canonical.glob("*.gds") if p.is_file())
        if hits:
            return hits
    anywhere = sorted((p for p in run_dir.rglob("*.gds") if p.is_file()),
                      key=lambda p: p.stat().st_size, reverse=True)
    if anywhere:
        return [anywhere[0]]
    raise Refuse(
        "no streamed *.gds found under the run — a converged tapeout must have "
        "a GDS to manifest (pass --gds to point at it)")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_manifest(gds_files: List[Path], dst_gds_dir: Path,
                    dry: bool) -> Tuple[str, List[Tuple[Path, str]]]:
    """Emit GDS_MANIFEST.txt. ALWAYS — whether or not the GDS itself ships.

    Returns (printable summary, [(gds_path, sha256)]) so the caller can stage
    the blobs that fit without hashing them a second time.
    """
    hashed = [(g, _sha256(g)) for g in gds_files]
    lines = [f"{g.name} {g.stat().st_size}B sha256:{sha}" for g, sha in hashed]
    body = "\n".join(lines) + "\n"
    if not dry:
        dst_gds_dir.mkdir(parents=True, exist_ok=True)
        (dst_gds_dir / "GDS_MANIFEST.txt").write_text(body, encoding="utf-8")
    return "; ".join(lines), hashed


_ROUTING_FILENAME = "LAYOUT_ROUTING.txt"
_ROUTE_CHOICES = ("not-retained", "git-lfs", "github-release")

_ROUTING_HEADER = (
    "# LAYOUT_ROUTING — every *.gds/*.def/*.spef/*.oas found under the source\n"
    "# run, and what was decided about each one. Paths are relative to that\n"
    "# run; for anything STAGED it is also the path inside this cell.\n"
    "#\n"
    "#   STAGED        the blob is in this cell.\n"
    "#   ROUTED_AWAY   in published scope but over the commit ceiling. The\n"
    "#                 destination column says where it went; 'not-retained'\n"
    "#                 means nobody claimed to have kept it.\n"
    "#   NOT_PUBLISHED exists in the source run, in a subtree this cell does\n"
    "#                 not publish (PnR scratch, per-step scratch). Not a\n"
    "#                 size decision — small ones are not published either.\n"
    "#   OFF_CANONICAL_PATH\n"
    "#                 a `routed.def` that IS in published scope and is not\n"
    "#                 where the scope looks. `phase3/stage3/pnr/routed.def`\n"
    "#                 is the only path the published-corpus population is\n"
    "#                 built from, so a DEF anywhere else is dropped — and\n"
    "#                 recording that as NOT_PUBLISHED would assert a policy\n"
    "#                 decision nobody made. Same repair CITATION_ROUTING.txt\n"
    "#                 makes for citations: the wrong word here retires a\n"
    "#                 finding instead of reporting one.\n"
    "#\n"
    "# The sha256 is recorded in all four cases: it is what makes an\n"
    "# artefact verifiable without being stored, and what turns recovering\n"
    "# one from a source host into a checkable file copy rather than a guess.\n"
    "#\n"
    "# SCOPE, stated so it is not over-read: this is every layout artefact\n"
    "# found under the SOURCE RUN DIRECTORY at publish time. It cannot speak\n"
    "# for artefacts the run never wrote there, and it is a record of what\n"
    "# was decided — not a promise that a ROUTED_AWAY blob still exists\n"
    "# wherever the destination column says it went.\n"
    "#\n"
    "# ONE LINE PER BLOB, not per path: converged runs symlink their artefacts\n"
    "# (steps/<step>/routed.def -> phase3/stage3/pnr/routed.def). Aliases are\n"
    "# collapsed onto the resolved path, so a line count here is a count of\n"
    "# distinct artefacts, not of directory entries.\n"
    "# <relpath> <bytes>B sha256:<64hex> <DECISION> <destination>\n"
)


def _write_routing(records: List[dict], dest: Path, dry: bool) -> None:
    """Write the per-cell routing record. Emitted even when nothing was routed
    away: a record that only appears on omission cannot be relied on to prove
    that nothing was omitted."""
    body = _ROUTING_HEADER + "".join(
        f"{r['path']} {r['bytes']}B sha256:{r['sha256']} "
        f"{r['decision']} {r['destination']}\n"
        for r in sorted(records, key=lambda r: r["path"]))
    if not dry:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / _ROUTING_FILENAME).write_text(body, encoding="utf-8")


_CITATION_ROUTING_FILENAME = "CITATION_ROUTING.txt"

_CITATION_HEADER = (
    "# CITATION_ROUTING — every path a published JSON CITES as its evidence,\n"
    "# and whether a reader of THIS cell can follow it (vibe-ic#448).\n"
    "#\n"
    "#   <doc> :: <cited path> <DECISION>\n"
    "#   DECISION in RESOLVES | OUT_OF_PUBLISHED_SCOPE |\n"
    "#                DANGLING_UNDER_PASS | DANGLING | UNFOLLOWABLE_ABSOLUTE\n"
    "#\n"
    "# OUT_OF_PUBLISHED_SCOPE is the one that needed a name. The publisher\n"
    "# copies phase1/, phase2/, phase3/reports/ and reports/ — a run-directory\n"
    "# citation such as `phase3/stage3/sta/x.rpt` is therefore correct WHERE\n"
    "# THE RUN PUT IT and unfollowable HERE. Measured on the three converged\n"
    "# cells: each asserts `timing_closed_multi_corner: true` citing\n"
    "# `phase3/stage3/sta/sta_mcorner_ocv.rpt`, which the published layout\n"
    "# never carries. The evidence was not lost; the POINTER was published\n"
    "# unchanged, so a reader following it finds nothing and is told nothing.\n"
    "#\n"
    "# This is the same repair LAYOUT_ROUTING.txt makes for blobs: an artefact\n"
    "# that is out of scope is RECORDED as out of scope rather than vanishing.\n"
    "# It does not decide whether the claim is TRUE — the run may well have\n"
    "# closed timing — only whether this cell lets you check it.\n"
    "#\n"
    "# WHAT OUT_OF_PUBLISHED_SCOPE IS NOT. It is not a name for every path a\n"
    "# reader cannot reach. The cell is asked whether it carries ANYTHING at\n"
    "# that location: nothing there means the layout excludes it; a directory\n"
    "# that ships its neighbours and not this file is a HOLE, and is recorded\n"
    "# as DANGLING / DANGLING_UNDER_PASS. The distinction is load-bearing\n"
    "# downstream — evidence_citation_resolves_check honours\n"
    "# OUT_OF_PUBLISHED_SCOPE and deliberately does not honour DANGLING*, so\n"
    "# the wrong word here retires a finding instead of reporting one.\n"
    "#\n"
    "# Emitted even when every citation resolves: a record that only appears\n"
    "# on failure cannot be used to prove there were none.\n")

# Extensions that name an EVIDENCE artefact rather than prose.
_CITE_KEYS = frozenset({
    "report", "rpt", "log", "evidence", "artifact", "artefact",
    "source", "path", "file", "sby", "sby_log",
})

_CITED_EXT = (".rpt", ".log", ".json", ".txt", ".def", ".spef", ".v", ".sv")
_CITED_RE = re.compile(
    r"(?:phase\d/stage\d|phase\d/reports|reports|steps)/[\w./*-]+"
    r"(?:" + "|".join(re.escape(e) for e in _CITED_EXT) + r")")


def _gate_citations(doc: Path) -> set:
    """The citations `evidence_citation_resolves_check` would find in `doc`.

    ONE definition of "a citation", borrowed from the gate rather than
    re-derived. `_CITED_RE` above only matches a path ROOTED at a known
    published prefix (`phaseN/stageN`, `reports`, `steps`), and this function
    only ever scanned `*.json`. Two real citations in the caravel cell sat
    outside both: `RESULT.md` cites `sta_mcorner_ocv.rpt` (Markdown, and a bare
    filename), and `quartus_map_audit.json` carries `[compile_log]
    fpga/compile.log` (a JSON KEY whose value starts at no known prefix).

    Neither appeared in CITATION_ROUTING.txt, so the record silently answered
    for a narrower set than the one a reader actually follows — and the gate
    and the record disagreed about the same cell. A disclosure that does not
    cover a citation is indistinguishable, to a reader, from one that says the
    citation is fine.

    Degrades to nothing if the gate cannot be imported: this must never be the
    reason a publish fails."""
    try:
        import evidence_citation_resolves_check as _g       # sibling program
    except Exception:
        return set()
    try:
        if doc.suffix.lower() == ".json":
            return {tok for _field, tok in _g._json_artifact_refs(doc)}
        text = doc.read_text(errors="replace")
        # BRACE GROUPS ARE EXPANDED FIRST, as the gate's `scan` does
        # (vibe-ic#1044): `{setup,hold}.rpt` names two artefacts, and
        # `_is_citation` rejects the unexpanded token as a template, so
        # without this step a multi-artefact citation the gate judges was
        # one this record never saw. An over-bound token expands to
        # nothing, which is the gate's answer too.
        out: set = set()
        for raw in _g._CITE_RE.findall(text):
            for tok in _g.expand_braces(raw) or ():
                if _g._is_citation(tok):
                    out.add(tok)
        return out
    except Exception:
        return set()


def _git_tracked(dest: Path) -> Optional[set]:
    """Paths git already TRACKS under `dest`, relative to it — or None when
    git cannot answer, which is a different fact from "nothing is tracked".

    At publish time `dest` is freshly staged and not yet added, so the honest
    answer there is the empty set; run as a re-derivation over an already
    published cell it is the cell's own file list."""
    try:
        cp = subprocess.run(["git", "ls-files", "-z", "--", "."],
                            cwd=str(dest), capture_output=True, text=True,
                            timeout=55)
    except (OSError, subprocess.SubprocessError):
        return None
    if cp.returncode != 0:
        return None
    return {p for p in cp.stdout.split("\0") if p}


def _clone_visible(dest: Path, rels: set) -> set:
    """Of `rels` (paths relative to `dest`, all present on disk), the ones a
    CLONE of this repository actually receives.

    THE DEFECT THIS CLOSES. "It is in `dest`" and "the reader gets it" are two
    different facts, and a repo-wide `.gitignore` rule is the gap between them.
    MEASURED on the two published spm cells as committed: 45 CITATION_ROUTING
    rows said RESOLVES because the cited log WAS sitting in the staged
    directory when this program ran — and `*.log` at the repo root meant `git
    add` never carried one of them. The record whose entire job is to tell a
    reader whether a pointer can be followed asserted the good outcome for 45
    pointers no reader could follow. Not a stale record: false when written.

    `_prune_provenance` already draws this exact line, on the same publish,
    for the same class of file — its docstring names `phase2/stage2/synth/
    synth.log` by path. This function is that definition applied to the other
    record, so the one publish stops holding two answers to one question.

    CARRIAGE IS `tracked OR not ignored`, never `not ignored` alone: git stops
    applying ignore rules to a path it already tracks, and this repo force-adds
    evidence logs for exactly that reason. Asking only about ignore rules would
    disclose a file the reader demonstrably receives.

    FAIL-OPEN, deliberately. If git cannot answer, every disk-present path is
    treated as carried — the behaviour that shipped before this. The wrong
    direction to fail is toward a false disclosure: `evidence_citation_resolves
    _check` HONOURS OUT_OF_PUBLISHED_SCOPE, so a disclosure invented by a git
    hiccup would suppress a real finding. A false RESOLVES, by contrast, is
    caught by `citation_routing_is_true_check`.
    """
    if not rels:
        return set()
    tracked = _git_tracked(dest)
    if tracked is None:
        return set(rels)
    return (set(rels) - _git_ignored(dest, rels)) | (tracked & set(rels))


def _carried_dirs(dest: Path) -> Optional[set]:
    """The directories a CLONE of this cell RECEIVES, as posix relatives
    ("" is the cell root). None when git could not be asked.

    WHY THIS REPLACES A STRING PREFIX. `OUT_OF_PUBLISHED_SCOPE` makes one
    specific promise and its consumer relies on exactly that promise:
    `evidence_citation_resolves_check` honours it (with
    `UNFOLLOWABLE_ABSOLUTE`) and NOTHING else, because it names a STRUCTURAL
    reason — the publisher's layout does not carry this path. Honouring it
    RETIRES the finding.

    What decided it was the prefix `phase{1,2,3}/stage`. MEASURED on the two
    published cells this landing repairs, that prefix is TRUE of
    `phase3/stage3/pnr/` (0 files shipped) and FALSE of
    `phase2/stage2/synth/` (10 shipped) and
    `phase2/stage2/dft/tdf/` (5). So `synth.log`, `yosys.log` and
    `tdf/sat_run.log` were recorded as "the layout excludes them" while the
    layout demonstrably carries their neighbours; the same path
    `phase2/stage1/sim_full_stack/oracle_run/oracle.log` RESOLVES in a cell
    that force-added it. The prefix was standing in for a fact nobody checked.

    THE SAME FACT IN BOTH MODES, which is why it is answered through
    `_clone_visible` rather than by looking at the disk. At publish time
    `dest` is staged and nothing is tracked yet, so the ignore rules decide;
    on a re-derivation over an already published cell the tracked set decides.
    One definition of carriage, two callers.

    None when git cannot answer — never "nothing is carried", which would
    declare every citation out of scope and silence the gate wholesale.
    """
    if _git_tracked(dest) is None:
        return None
    files = {q.relative_to(dest).as_posix()
             for q in dest.rglob("*") if q.is_file()}
    if not files:
        return None
    return {f.rpartition("/")[0] for f in _clone_visible(dest, files)}


def _layout_excludes(cited: str, carried_dirs: Optional[set]) -> bool:
    """Is `cited` unreachable because the published LAYOUT does not carry it,
    as opposed to because it is a hole in a subtree the layout does carry?

    The prefix test stays as the outer condition — nothing outside
    `phase{N}/stage…` was ever judged this way and this is not the change to
    widen it. What is new is that the prefix no longer DECIDES: the cell is
    asked whether it carries anything at that location.

    Falls back to the prefix alone when git could not be asked, i.e. to
    exactly the rule that shipped before this. So the correction can only ever
    turn OUT_OF_PUBLISHED_SCOPE into DANGLING*, never the reverse: an
    unreachable git cannot manufacture a hole, and cannot silence one either.
    """
    if not any(cited.startswith(f"phase{n}/stage") for n in "123"):
        return False
    if carried_dirs is None:
        return True
    return cited.rpartition("/")[0] not in carried_dirs


def collect_citation_records(dest: Path, *,
                             freshly_staged: bool = False
                             ) -> List[Dict[str, str]]:
    """Every evidence path the STAGED tree's own JSONs cite, and whether it
    resolves inside the published cell.

    Read from the STAGED tree, not the run, because the question is what a
    reader of THIS cell can follow.

    `freshly_staged=True` is what `publish` passes: `dest` was created empty
    (or emptied under `--force`) by THIS publish, so everything on its disk
    is what the cell will ship and the published-tree filter below must not
    run. MEASURED (#2007, re-staging spm x gf180mcuD into a corpus clone):
    the filter keeps only paths git already publishes at HEAD, so every
    document this publish ADDED to an existing cell -- the closure-staged
    `phase3/stage3/postroute_timing_repair/no_repair_summary.json` -- was
    dropped from the record, and `benchmark_evidence_structure_check` then
    found the routing answering for 23 of the cell's 24 citations once the
    file was tracked. A record that the publish itself cannot complete is
    the defect this file exists against.
    """
    out: List[Dict[str, str]] = []
    if not dest.is_dir():
        return out
    seen = set()
    pending: List[Dict[str, object]] = []
    on_disk: set = set()
    # Walk the PUBLISHED tree, not this machine's disk. At publish time `dest`
    # is a freshly staged directory and the two agree; run as an AUDIT over an
    # already-published cell they do not, and a working checkout carries
    # untracked `clean_run_*` leftovers a reader never receives. Measured while
    # building this: the first version attributed citations to a directory that
    # is not in the published tree at all. Same defect this repo fixed in four
    # programs (#447) — reproduced here, in the fix for it.
    docs = sorted(dest.rglob("*.json")) + sorted(dest.rglob("*.md"))
    if not freshly_staged:
        docs = _published_tree.filter_to_published(dest, docs)
    for doc in docs:
        try:
            text = doc.read_text(errors="replace")
        except OSError:
            continue
        rel_doc = doc.relative_to(dest).as_posix()
        asserted = _citations_under_a_pass(text)
        absolute = _absolute_citation_values(text)
        for cited in sorted(set(_CITED_RE.findall(text)) | absolute
                            | _gate_citations(doc)):
            key = (rel_doc, cited)
            if key in seen:
                continue
            seen.add(key)
            if cited.startswith("/"):
                # UNFOLLOWABLE BY CONSTRUCTION. An absolute path under someone's
                # home directory can never resolve for a reader, on any machine
                # but the author's. That is a different fact from "the file is
                # not here", and reporting them the same way sends a reader
                # looking for a missing artefact instead of fixing a pointer.
                #
                # MEASURED over the tracked corpus: 108 CITATION fields carry
                # one, across 7 ICs — including two of the three CONVERGED
                # cells, whose `post_route_signoff_corner.json` cites
                # `/home/<user>/campaign_.../sta_spef_multicorner.rpt`.
                #
                # Narrow on purpose: a blanket "no absolute paths under
                # benchmark-data" rule matches 682 files and 9781 occurrences,
                # nearly all of them logs recording WHERE a run happened, which
                # is legitimate provenance. Only a path something is expected
                # to FOLLOW is a defect.
                decision = "UNFOLLOWABLE_ABSOLUTE"
            else:
                # DEFERRED, all of it. Two facts decide every remaining row and
                # neither is on this machine's disk: does a CLONE carry this
                # path, and — when it does not — does the clone carry anything
                # at all at that location? "On disk" is not the same fact as
                # "the reader gets it", and "absent" is not the same fact as
                # "the publisher's layout excludes it".
                decision = None
                if (dest / cited).exists():
                    on_disk.add(cited)
            pending.append({"doc": rel_doc, "cited": cited,
                            "decision": decision,
                            "asserted": cited in asserted})

    # SECOND PASS — decided against `git`, not against this machine's disk.
    # Only the absolute paths were final above.
    carried = _clone_visible(dest, on_disk)
    carried_dirs = _carried_dirs(dest)
    for row in pending:
        decision = row["decision"]
        if decision is None:
            cited = str(row["cited"])
            if cited in carried:
                decision = "RESOLVES"
            elif _layout_excludes(cited, carried_dirs):
                decision = "OUT_OF_PUBLISHED_SCOPE"
            elif row["asserted"]:
                # A HOLE, NOT A DISCLOSURE: the reader receives this directory
                # and not this file. Saying OUT_OF_PUBLISHED_SCOPE here would
                # retire `evidence_citation_resolves_check`'s finding for a
                # PASS whose proof still ships nowhere — one line in a routing
                # file standing in for the missing artefact.
                decision = "DANGLING_UNDER_PASS"
            else:
                decision = "DANGLING"
        out.append({"doc": str(row["doc"]), "cited": str(row["cited"]),
                    "decision": str(decision)})
    return out


def _absolute_citation_values(text: str) -> set:
    """Absolute paths sitting in a CITATION-shaped KEY.

    Key-based, not text-based, and the difference is the whole point. Matching
    absolute paths in the TEXT finds 914 of them across the tracked corpus —
    nearly all logs recording WHERE a run happened, which is legitimate
    provenance and not a defect. Restricting to keys something is expected to
    FOLLOW gives 108, across 7 ICs, and those are real: two of the three
    CONVERGED cells cite `/home/<user>/campaign_.../sta_spef_multicorner.rpt`
    as the evidence for their sign-off corner.
    """
    out: set = set()
    try:
        doc = json.loads(text)
    except Exception:
        return out

    def is_cite_key(k: str) -> bool:
        k = k.lower()
        return (k in _CITE_KEYS
                or k.endswith(("_report", "_rpt", "_log", "_path", "_file")))

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and v.startswith("/") and is_cite_key(k):
                    out.add(v)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    return out


def _citations_under_a_pass(text: str) -> set:
    """Paths cited inside a record whose own status/verdict is a PASS.

    THE PLAN-VERSUS-CLAIM SPLIT, and the reason the routing file is usable.
    A step that has not run naming the report it WOULD write is a PLAN; a step
    that says PASS while naming a report that is not there is a CLAIM whose
    evidence is absent. Both look identical as a path.

    MEASURED over the published corpus: of the dangling citations,
    35 sit in SKIP/not-run records, 24 in FAIL records, 64 in records with no
    status to judge, and **11 under a PASS**. Only that last group asserts
    anything, so only it is anyone's bug — a 45x reduction in what a reader
    has to look at.
    """
    found: set = set()
    try:
        doc = json.loads(text)
    except Exception:
        return found

    def _has_status(o) -> bool:
        return isinstance(o, dict) and bool(o.get("status") or o.get("verdict"))

    def _own_text(o) -> str:
        """This record's own content, EXCLUDING nested status-bearing records.

        A first version serialised the whole subtree, which over-attributed
        badly: a document with a top-level `verdict: PASS` made EVERY citation
        in the file "asserted", including ones inside nested SKIP steps.
        Measured: 312 across the corpus instead of the real figure. A claim is
        made by the NEAREST enclosing record, not by every ancestor.
        """
        if isinstance(o, dict):
            parts = []
            for k, v in o.items():
                if _has_status(v):
                    continue
                if isinstance(v, list):
                    v = [x for x in v if not _has_status(x)]
                parts.append(json.dumps({k: v}, ensure_ascii=False))
            return " ".join(parts)
        return json.dumps(o, ensure_ascii=False)

    def walk(o):
        if isinstance(o, dict):
            st = str(o.get("status") or o.get("verdict") or "").upper()
            if st.startswith("PASS"):
                found.update(_CITED_RE.findall(_own_text(o)))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    return found


def write_citation_routing(dest: Path, records: List[Dict[str, str]],
                           dry: bool = False) -> None:
    body = _CITATION_HEADER + "".join(
        f"{r['doc']} :: {r['cited']} {r['decision']}\n"
        for r in sorted(records, key=lambda r: (r["doc"], r["cited"])))
    if not dry:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / _CITATION_ROUTING_FILENAME).write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------
# CITATION CLOSURE (#2007) — a staged document's cited proof ships with it.
# See the module docstring section of the same name for the rule and the
# measurement. One decision per (document, citation); only STAGED adds a
# file, and nothing here ever writes into the run.
# --------------------------------------------------------------------------
_CLOSURE_STAGED = "STAGED"
_CLOSURE_IN_CELL = "ALREADY_IN_CELL"
_CLOSURE_ABSENT = "ABSENT_IN_RUN"
_CLOSURE_OVER_CEILING = "OVER_CEILING"
_CLOSURE_LAYOUT = "LAYOUT_POLICY"
_CLOSURE_STEP_VIEW = "STEP_VIEW"
_CLOSURE_ABOVE_CELL = "RESOLVES_ABOVE_CELL"
#: The verdict an amended gate report carries. The gate's own word for a
#: report whose evidence is disclosed absent (vibe-ic#381).
_UNSUBSTANTIATED = "UNSUBSTANTIATED"
_DOC_SUFFIXES = (".json", ".md")


def _closure_rungs(rel_doc: str, cite: str) -> List[str]:
    """Every cell-relative path `cite` can mean when written in `rel_doc`,
    innermost first: the citing document's directory, then each ancestor up
    to the cell root. This is `evidence_citation_resolves_check
    .resolve_citation`'s ladder, bounded at the cell instead of the scan
    root, so a citation the gate would resolve at rung N is staged at rung N
    and nowhere else. A rung that escapes the cell (`..`) is dropped, as the
    gate drops it."""
    import posixpath
    rel_dir = posixpath.dirname(rel_doc)
    out: List[str] = []
    while True:
        cand = posixpath.normpath(
            posixpath.join(rel_dir, cite) if rel_dir else cite)
        if cand not in (".", "") and not cand.startswith("..") \
                and cand not in out:
            out.append(cand)
        if not rel_dir:
            return out
        rel_dir = posixpath.dirname(rel_dir)


def _close_one(run_dir: Path, dest: Path, dry: bool, rel_doc: str, cite: str,
               cell_rels: set, above: List[Path]) -> Tuple[str, str]:
    """Decide -- and, when the answer is STAGED, perform -- the closure of
    ONE citation. Returns `(decision, path)`.

    The first rung that answers wins, in the gate's order. A rung the cell
    already carries is ALREADY_IN_CELL (nothing to do; the routing row will
    say RESOLVES). A rung that is a regular file in the RUN is the proof:
    STAGED at that path unless it is over the commit ceiling, a layout
    artefact (LAYOUT_ROUTING.txt's policy, not this one's), or under the
    `steps/` view (STEP_ROUTING.txt's). A citation with no rung in the run is
    ABSENT_IN_RUN -- unless it resolves ABOVE the cell, where the gate's
    ladder still reaches (`ic/<IC>/…`, `ic/…`) and this program does not
    stage."""
    for rung in _closure_rungs(rel_doc, cite):
        if rung in cell_rels or (not dry and (dest / rung).is_file()):
            return _CLOSURE_IN_CELL, rung
        src = run_dir / rung
        if not src.is_file():
            continue
        if rung.startswith(_STEPS_DIRNAME + "/"):
            return _CLOSURE_STEP_VIEW, rung
        if is_layout_artefact(src):
            return _CLOSURE_LAYOUT, rung
        if over_ceiling(src):
            return _CLOSURE_OVER_CEILING, rung
        if not dry:
            target = dest / rung
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        cell_rels.add(rung)
        return _CLOSURE_STAGED, rung
    import posixpath
    norm = posixpath.normpath(cite)
    if not norm.startswith(".."):
        for base in above:
            if (base / norm).is_file():
                return _CLOSURE_ABOVE_CELL, norm
    return _CLOSURE_ABSENT, cite


def _disclose_absent_evidence(doc: Path, absent: Dict[str, str],
                              run_dir: Path) -> Optional[str]:
    """Amend the STAGED copy of a JSON gate report whose top-level field(s)
    cite an artefact that does not exist in the run -- the honest-absence
    mechanism `evidence_citation_resolves_check._json_artifact_refs` honours
    and the kcite3 precedent (benchmark-data aa8a19b4) applied by hand.

    `absent` maps field -> cited path. The field is nulled and its path kept
    under `evidence_absent`; `verdict` becomes UNSUBSTANTIATED with the run's
    word retained as `verdict_as_run`; every other field is left as the run
    wrote it, because which numbers are conclusions is not this program's to
    decide and erasing them would be a second fabrication. Returns a note on
    failure, None on success. Never touches the run's copy."""
    try:
        data = json.loads(doc.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as exc:
        return f"could not amend {doc.name}: {exc}"
    if not isinstance(data, dict):
        return f"could not amend {doc.name}: not a JSON object"
    prior = data.get("verdict")
    for field in absent:
        data[field] = None
    data["verdict"] = _UNSUBSTANTIATED
    data["verdict_as_run"] = prior
    data["evidence_present"] = False
    data["evidence_absent"] = dict(sorted(absent.items()))
    data["null_because"] = (
        f"benchmark_evidence_publish (#2007) could not close this record's "
        f"citation(s): {', '.join(sorted(set(absent.values())))} do(es) not "
        f"exist anywhere in the run tree at publish time, so the verdict "
        f"{prior!r} the run recorded rests on evidence no reader can open. "
        f"The run's other fields are retained as its assertion, not "
        f"claimed here; no replacement artefact was fabricated.")
    try:
        doc.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    except OSError as exc:
        return f"could not amend {doc.name}: {exc}"
    return None


def close_citations(run_dir: Path, dest: Path,
                    docs: List[Tuple[Path, str]], cell_rels: set, dry: bool,
                    above: Optional[List[Path]] = None) -> Dict[str, object]:
    """Stage every artefact a staged document cites that EXISTS in the run
    (#2007), and disclose every one that does not.

    `docs` is `(source path, path in the cell)` for every document copied
    verbatim into the cell -- the population is decided by the copy walk, not
    re-derived here, and it is the same in a dry run. `cell_rels` is every
    path the publish has already decided to stage; it is EXTENDED by what
    this stages, so one blob cited by several documents is copied once.

    The citation population is the one `collect_citation_records` records
    (`_CITED_RE` plus the gate's own extractor), so the routing record and
    the closure cannot disagree about what a document cites. The AMENDMENT
    population is narrower -- the citations the gate JUDGES -- for the
    reason the docstring gives.

    Returns a summary; every non-STAGED decision is listed, never counted
    alone, because an omission that leaves no trace is the shape this
    program exists to refuse."""
    result: Dict[str, object] = {
        "n_documents": 0, "n_citations": 0, "already_in_cell": 0,
        "staged": [], "absent": [], "over_ceiling": [], "layout_policy": [],
        "step_view": [], "above_cell": [], "amended": [], "unamended": [],
        "errors": [],
    }
    try:
        import evidence_citation_resolves_check as _g       # sibling program
    except Exception:
        _g = None
    seen: set = set()
    above = list(above or [])
    # A WORKLIST, NOT A PASS. A document the closure stages is a staged
    # document, and the rule applies to it too: MEASURED on the spm re-stage,
    # the write ledger cites `phase3/stage3/postroute_timing_repair/
    # no_repair_summary.json`, which itself cites `phase3/stage3/sta/
    # sta_spef_based.rpt`. One pass staged the summary and left its own
    # citation unclosed and unrecorded; the structure gate reported the
    # routing answering for 23 of 24. Every STAGED artefact with a document
    # suffix is appended here, and `seen` bounds the walk.
    worklist: List[Tuple[Path, str]] = sorted(docs, key=lambda d: d[1])
    queued: set = {rel for _s, rel in worklist}
    while worklist:
        src_doc, rel_doc = worklist.pop(0)
        if src_doc.suffix.lower() not in _DOC_SUFFIXES:
            continue
        try:
            text = src_doc.read_text(errors="replace")
        except OSError:
            continue
        result["n_documents"] = int(result["n_documents"]) + 1
        judged = _gate_citations(src_doc)
        absent_fields: Dict[str, str] = {}
        absent_prose: List[str] = []
        for cite in sorted(set(_CITED_RE.findall(text)) | judged):
            if cite.startswith("/"):
                continue          # UNFOLLOWABLE_ABSOLUTE: the routing row says so
            if (rel_doc, cite) in seen:
                continue
            seen.add((rel_doc, cite))
            result["n_citations"] = int(result["n_citations"]) + 1
            decision, path = _close_one(run_dir, dest, dry, rel_doc, cite,
                                        cell_rels, above)
            row = {"doc": rel_doc, "cited": cite, "path": path}
            if decision == _CLOSURE_IN_CELL:
                result["already_in_cell"] = int(result["already_in_cell"]) + 1
                continue
            if decision in (_CLOSURE_STAGED, _CLOSURE_OVER_CEILING,
                            _CLOSURE_LAYOUT, _CLOSURE_STEP_VIEW):
                try:
                    row["bytes"] = (run_dir / path).stat().st_size
                except OSError:
                    row["bytes"] = -1
            bucket = {_CLOSURE_STAGED: "staged", _CLOSURE_ABSENT: "absent",
                      _CLOSURE_OVER_CEILING: "over_ceiling",
                      _CLOSURE_LAYOUT: "layout_policy",
                      _CLOSURE_STEP_VIEW: "step_view",
                      _CLOSURE_ABOVE_CELL: "above_cell"}[decision]
            result[bucket].append(row)          # type: ignore[union-attr]
            if (decision == _CLOSURE_STAGED
                    and path.lower().endswith(_DOC_SUFFIXES)
                    and path not in queued):
                queued.add(path)
                worklist.append((run_dir / path, path))
            if decision == _CLOSURE_ABSENT and cite in judged:
                if src_doc.suffix.lower() == ".json" and _g is not None:
                    for field, tok in _g._json_artifact_refs(src_doc):
                        if tok == cite:
                            absent_fields[str(field)] = cite
                else:
                    absent_prose.append(cite)
        if absent_fields:
            entry = {"doc": rel_doc, "fields": absent_fields,
                     "verdict_as_run": None, "verdict": _UNSUBSTANTIATED}
            try:
                entry["verdict_as_run"] = json.loads(text).get("verdict")
            except (ValueError, AttributeError):
                pass
            if not dry:
                note = _disclose_absent_evidence(dest / rel_doc, absent_fields,
                                                 run_dir)
                if note:
                    result["errors"].append(note)   # type: ignore[union-attr]
                    continue
            result["amended"].append(entry)         # type: ignore[union-attr]
        if absent_prose:
            result["unamended"].append(               # type: ignore[union-attr]
                {"doc": rel_doc, "cited": absent_prose})
    return result


# --------------------------------------------------------------------------
# Per-step evidence — published as a RECORD, never as the symlink view.
# --------------------------------------------------------------------------

_STEPS_DIRNAME = "steps"
_STEP_RECORD_FILENAME = "STEP_RECORD.json"
_STEP_INDEX_FILENAME = "STEP_INDEX.json"
_STEP_ROUTING_FILENAME = "STEP_ROUTING.txt"

# `step_output_collector` writes exactly these two, and both describe the
# SYMLINK VIEW: `outputs.json` carries an `abs` field naming a path on the
# authoring host, and `index.json` is its table of contents. Neither survives
# leaving that host, so both are REPLACED by a derived, self-contained form
# rather than copied. Anything else a step folder holds is a record somebody
# else wrote and is copied verbatim — that is the seam a per-step RECORD
# written by the runner rides through, with no coupling to its schema.
_COLLECTOR_MANIFESTS = frozenset({"outputs.json", "index.json"})

# Only RECORDS are copied out of the steps tree. Everything else in there is
# the view's payload — a link to an artefact whose canonical home is
# elsewhere in the run — and belongs at that canonical path or nowhere.
_STEP_RECORD_EXTS = (".json", ".txt", ".md", ".jsonl")

_STEP_ROUTING_HEADER = (
    "# STEP_ROUTING — every output a flow STEP declared, resolved against the\n"
    "# source run at publish time, and where a reader of THIS cell can find it.\n"
    "#\n"
    "#   <phase>/<stage>/<id>_<slug> :: <run-relative path> <bytes>B\n"
    "#       sha256:<64hex> <DECISION>\n"
    "#\n"
    "#   IN_CELL                 the bytes are in this cell, at that same path.\n"
    "#   OUT_OF_PUBLISHED_SCOPE  the run has it; this cell's copied subtrees do\n"
    "#                           not include it (PnR scratch, etc). The sha256\n"
    "#                           is what makes it recoverable and checkable.\n"
    "#   ZERO_BYTE               the file exists and is empty. 0 bytes is not\n"
    "#                           evidence wherever it sits, so it outranks both\n"
    "#                           of the location decisions above.\n"
    "#   DANGLING_IN_RUN         the path is a broken symlink in the run. Nothing\n"
    "#                           was there to publish and nothing was.\n"
    "#   ABSENT_IN_RUN           the step declared it; it is not in the run. A\n"
    "#                           step whose own status is a PASS and whose output\n"
    "#                           is ABSENT is the residual this record exists for.\n"
    "#\n"
    "# WHY A RECORD AND NOT THE TREE. `<run>/steps/` is a view built from\n"
    "# SYMLINKS into that run directory. Measured on a converged run whose\n"
    "# directory was later renamed: 83 of 83 links dangling. Measured on the\n"
    "# legacy cells that did commit their steps tree: 142 tracked symlinks, 31\n"
    "# of whose targets the index does not carry, so a clean clone receives 31\n"
    "# broken links. Copying the view would publish that; recording it does not.\n"
    "#\n"
    "# SCOPE, stated so it is not over-read: these are the outputs the steps\n"
    "# tree DECLARED, resolved at publish time. It cannot speak for an output no\n"
    "# step declared, and it is not a verdict on the step — only on whether the\n"
    "# artefact the step named can be reached from what you received.\n")


def _step_folder_rel(steps_root: Path, dirpath: Path) -> str:
    """Where this step sits in the tree, as the run itself laid it out.

    MIRRORED, not re-derived. Current runs nest `<phase>/<stage>/<id>_<slug>`
    (the owner's directive); older runs are flat `<id>_<slug>`. Re-deriving a
    nested path for a flat run would invent a structure that run never had,
    and the record's whole value is that it reports what is there.
    """
    try:
        return dirpath.relative_to(steps_root).as_posix()
    except ValueError:
        return dirpath.name


def _declared_output_record(run_dir: Path, rel: str, dest: Path,
                            sha_memo: Dict[Path, str]) -> Dict[str, object]:
    """Resolve ONE declared output against the run, and against this cell.

    Resolution is against `run_dir / rel`, never against the `abs` field the
    collector wrote. `abs` names a path on the authoring host: on the measured
    `_car15_evidence` run every one of them is gone, while 83 of the 90
    run-relative paths still resolve. A record keyed on the machine-absolute
    path would have reported a total loss that did not happen.
    """
    src = run_dir / rel
    is_link = src.is_symlink()
    # lstat, so a DANGLING link is seen as the broken link it is rather than
    # skipped. `Path.glob`/`is_file()` answer False for one, which is how a
    # broken link came to read as a produced artefact elsewhere in this flow.
    try:
        src.lstat()
        present = True
    except OSError:
        present = False

    rec: Dict[str, object] = {"rel": rel, "symlink": is_link}
    if not present:
        rec.update(bytes=-1, sha256="", decision="ABSENT_IN_RUN", in_cell=False)
        return rec
    if is_link and not src.exists():
        rec.update(bytes=-1, sha256="", decision="DANGLING_IN_RUN", in_cell=False)
        return rec
    try:
        size = src.stat().st_size
    except OSError:
        rec.update(bytes=-1, sha256="", decision="ABSENT_IN_RUN", in_cell=False)
        return rec

    real = src.resolve()
    if real not in sha_memo:
        try:
            sha_memo[real] = _sha256(src)
        except OSError:
            sha_memo[real] = ""
    rec["bytes"] = size
    rec["sha256"] = sha_memo[real]
    # Not `is_file()` alone: that follows a link, and "a reader of this cell
    # receives the bytes" is exactly the question a tracked symlink answers
    # falsely (#404 — 31 of 142 such links in this repo's published cells
    # point at something the index does not carry).
    cand = dest / rel
    in_cell = cand.is_file() and not cand.is_symlink()
    rec["in_cell"] = in_cell
    if size == 0:
        rec["decision"] = "ZERO_BYTE"
    else:
        rec["decision"] = "IN_CELL" if in_cell else "OUT_OF_PUBLISHED_SCOPE"
    return rec


def collect_step_records(run_dir: Path, dest: Path) -> Tuple[List[dict], List[dict]]:
    """(step records, verbatim record files) for the run's `steps/` tree.

    Read-only. `os.walk(followlinks=False)`, not `rglob`: the tree is made of
    symlinks and a recursive glob that follows a directory link into an
    ancestor does not terminate.
    """
    steps_root = run_dir / _STEPS_DIRNAME
    steps: List[dict] = []
    verbatim: List[dict] = []
    if not steps_root.is_dir():
        return steps, verbatim

    sha_memo: Dict[Path, str] = {}
    for dirpath, _dirnames, filenames in os.walk(steps_root, followlinks=False):
        d = Path(dirpath)
        names = set(filenames)
        extra = sorted(
            n for n in names
            if n not in _COLLECTOR_MANIFESTS
            and n.lower().endswith(_STEP_RECORD_EXTS)
            and not (d / n).is_symlink()
            # The same commit ceiling everything else obeys. `_excluded` is
            # not the predicate here: it only judges the four LAYOUT
            # extensions, so it would wave through a record too big to commit
            # and the cell would be unpushable for a reason nothing named.
            and not over_ceiling(d / n))
        if "outputs.json" not in names and not extra:
            continue

        folder = _step_folder_rel(steps_root, d)
        for n in extra:
            verbatim.append({"src": str(d / n),
                             "rel": f"{_STEPS_DIRNAME}/{folder}/{n}"
                                    if folder != "." else f"{_STEPS_DIRNAME}/{n}"})

        meta: Dict[str, object] = {}
        declared: List[dict] = []
        if "outputs.json" in names:
            try:
                meta = json.loads((d / "outputs.json").read_text(
                    encoding="utf-8", errors="replace"))
            except (OSError, ValueError):
                meta = {}
            for o in (meta.get("outputs") or []):
                rel = str((o or {}).get("rel") or "")
                if not rel or rel.startswith("/") or ".." in Path(rel).parts:
                    # A declared path that escapes the run is not a path this
                    # record can answer for; say so rather than resolve it.
                    declared.append({"rel": rel, "bytes": -1, "sha256": "",
                                     "symlink": False, "in_cell": False,
                                     "decision": "ABSENT_IN_RUN"})
                    continue
                declared.append(
                    _declared_output_record(run_dir, rel, dest, sha_memo))

        steps.append({
            "id": str(meta.get("id") or ""),
            "name": str(meta.get("name") or ""),
            "status": str(meta.get("status") or ""),
            "phase": str(meta.get("phase") or ""),
            "stage": str(meta.get("stage") or ""),
            "folder": folder,
            "declared_outputs": declared,
            "records": [Path(v["rel"]).name for v in verbatim
                        if Path(v["rel"]).parent.as_posix()
                        == (f"{_STEPS_DIRNAME}/{folder}" if folder != "."
                            else _STEPS_DIRNAME)],
        })

    steps.sort(key=lambda s: s["folder"])
    verbatim.sort(key=lambda v: v["rel"])
    return steps, verbatim


def publish_steps(run_dir: Path, dest: Path, dry: bool) -> Dict[str, object]:
    """Stage the per-step evidence RECORD into the cell.

    Writes `steps/<folder>/STEP_RECORD.json` (self-contained: no host-absolute
    path, every declared output carrying its size, sha256 and where a reader
    can find it), `steps/STEP_INDEX.json`, and the flat `STEP_ROUTING.txt` at
    the cell root. Copies verbatim any OTHER record file a step folder holds.

    NEVER creates a symlink and never copies one — see the module docstring.

    BEST-EFFORT, and legibly so. A malformed steps tree must not cost the cell
    its phase evidence; but a failure that leaves no trace is the shape this
    whole program exists to refuse, so the exception is written into
    STEP_ROUTING.txt and into the summary rather than swallowed.
    """
    result: Dict[str, object] = {
        "present": (run_dir / _STEPS_DIRNAME).is_dir(),
        # WHERE a declared output can be read is decided against the STAGED
        # cell, so on --dry-run there is nothing to decide it against. Say so
        # rather than report the split every entry would fall into by default
        # ("out of scope"), which is the answer an empty directory gives to
        # every question.
        "location_determined": not dry,
        "n_steps": 0, "n_declared": 0, "n_in_cell": 0,
        "n_out_of_scope": 0, "n_zero_byte": 0,
        "n_dangling": 0, "n_absent": 0, "n_records_copied": 0,
        "error": None,
    }
    steps: List[dict] = []
    verbatim: List[dict] = []
    try:
        steps, verbatim = collect_step_records(run_dir, dest)
    except Exception as exc:                       # never fatal to a publish
        result["error"] = f"{type(exc).__name__}: {exc}"

    counts = {"IN_CELL": 0, "OUT_OF_PUBLISHED_SCOPE": 0, "ZERO_BYTE": 0,
              "DANGLING_IN_RUN": 0, "ABSENT_IN_RUN": 0}
    for s in steps:
        for o in s["declared_outputs"]:
            counts[str(o["decision"])] = counts.get(str(o["decision"]), 0) + 1
    result.update(
        n_steps=len(steps),
        n_declared=sum(counts.values()),
        n_in_cell=counts["IN_CELL"] if not dry else -1,
        n_out_of_scope=counts["OUT_OF_PUBLISHED_SCOPE"] if not dry else -1,
        n_zero_byte=counts["ZERO_BYTE"],
        n_dangling=counts["DANGLING_IN_RUN"],
        n_absent=counts["ABSENT_IN_RUN"])

    if dry:
        result["n_records_copied"] = len(verbatim)
        return result

    steps_dest = dest / _STEPS_DIRNAME
    for s in steps:
        sdir = steps_dest / s["folder"] if s["folder"] != "." else steps_dest
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / _STEP_RECORD_FILENAME).write_text(
            json.dumps(s, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
    for v in verbatim:
        target = dest / v["rel"]
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(v["src"]), target)
            result["n_records_copied"] = int(result["n_records_copied"]) + 1
        except OSError:
            continue
    if steps:
        steps_dest.mkdir(parents=True, exist_ok=True)
        (steps_dest / _STEP_INDEX_FILENAME).write_text(
            json.dumps({"source_run_had_steps_tree": bool(result["present"]),
                        "steps": [{k: s[k] for k in
                                   ("id", "name", "status", "phase", "stage",
                                    "folder")}
                                  | {"n_declared": len(s["declared_outputs"]),
                                     "n_in_cell": sum(
                                         1 for o in s["declared_outputs"]
                                         if o["decision"] == "IN_CELL")}
                                  for s in steps]},
                       indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")

    _write_step_routing(dest, steps, result)
    return result


def _write_step_routing(dest: Path, steps: List[dict],
                        result: Dict[str, object]) -> None:
    """The flat, greppable index. ALWAYS emitted — a cell whose run produced no
    steps tree says so in one line, which is a different fact from a cell
    published before this record existed."""
    lines = []
    if result.get("error"):
        lines.append(f"# ERROR building this record: {result['error']}\n"
                     f"# The rows below are incomplete. Treat the absence of a\n"
                     f"# step here as unknown, not as absent.\n")
    if not result.get("present"):
        lines.append("# steps/ tree: ABSENT in the source run — this run was "
                     "driven in a\n#   shape that never materialized one, so "
                     "there is no per-step\n#   evidence to publish. Not the "
                     "same fact as a step having failed.\n")
    for s in steps:
        for o in s["declared_outputs"]:
            lines.append(f"{s['folder']} :: {o['rel']} {o['bytes']}B "
                         f"sha256:{o['sha256']} {o['decision']}\n")
    dest.mkdir(parents=True, exist_ok=True)
    (dest / _STEP_ROUTING_FILENAME).write_text(
        _STEP_ROUTING_HEADER + "".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------
# Publish.
# --------------------------------------------------------------------------

def publish(args: argparse.Namespace) -> dict:
    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        raise Refuse(f"--run-dir {run_dir} is not a directory")

    # --- parameter sanity (structure, not chips) ---
    if not _VERSION_RE.match(args.plugin_version):
        raise Refuse(f"--plugin-version {args.plugin_version!r} is not X.Y.Z")
    for label, val in (("--ic", args.ic), ("--pdk", args.pdk)):
        if not _SAFE_TOKEN_RE.match(val):
            raise Refuse(f"{label} {val!r} is not a safe path token "
                         f"(letters/digits/._- , no separators/spaces)")

    verdir_name = f"v{args.plugin_version}_{args.pdk}"

    # --- convergence guard ---
    verdict_json = Path(args.verdict_json).resolve() if args.verdict_json else None
    verdict, verdict_src = _audit_verdict(run_dir, verdict_json)
    if verdict not in _CONVERGED:
        raise Refuse(
            f"run verdict is {verdict} (from {verdict_src}); only a converged "
            f"run (PASS / PASS_WITH_WAIVERS) may be published as evidence")

    # --- PDK-revision guard (BLOCKING) ---
    # After convergence, because "this run passed" and "this run can be
    # re-derived" are separate questions and the reader is better served by
    # the first refusal naming the first one.
    pdk_rev = _pdk_revision(run_dir)

    # --- RESULT.md (independent audit) required + consistent ---
    result_md = Path(args.result_md).resolve() if args.result_md else (run_dir / "RESULT.md")
    if not result_md.is_file() or result_md.stat().st_size == 0:
        raise Refuse(
            f"independent-audit RESULT.md required but missing/empty at {result_md} "
            f"(write the audit verdict first, or pass --result-md)")
    rmd_verdict = _result_md_verdict(result_md)
    if rmd_verdict == "FAIL":
        raise Refuse(f"RESULT.md at {result_md} states verdict FAIL — inconsistent "
                     f"with a converged publish")

    # --- streamed GDS (for the manifest) ---
    gds_files = _find_gds(run_dir, Path(args.gds).resolve() if args.gds else None)

    # --- destination ---
    dest_root = Path(args.dest_root).resolve()
    ic_root = dest_root / "ic" / args.ic
    dest = ic_root / verdir_name
    if dest.exists() and any(dest.iterdir()) and not args.force:
        raise Refuse(f"destination {dest} already exists and is non-empty "
                     f"(pass --force to overwrite)")

    dry = args.dry_run
    staged: List[str] = []
    route = getattr(args, "oversize_route", "not-retained")
    layout_records: List[dict] = []
    residue: List[dict] = []

    if not dry:
        if dest.exists() and args.force:
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)

    # Every document copied VERBATIM into the cell, and every path the cell
    # will carry -- both fed to the citation closure (#2007) below, decided
    # by the same walks that stage them so a dry run answers identically.
    copied_docs: List[Tuple[Path, str]] = []
    cell_rels: set = set()

    # RESULT.md
    if not dry:
        shutil.copy2(result_md, dest / "RESULT.md")
    staged.append("RESULT.md")
    copied_docs.append((result_md, "RESULT.md"))
    cell_rels.add("RESULT.md")

    # single files
    for fname in _COPY_FILES:
        src = run_dir / fname
        if src.is_file():
            if not dry:
                shutil.copy2(src, dest / fname)
            staged.append(fname)
            copied_docs.append((src, fname))
            cell_rels.add(fname)

    # subtrees
    for sub in _COPY_SUBTREES:
        src = run_dir / sub
        if not src.is_dir():
            continue
        n_residue_before = len(residue)
        copied_here: List[Tuple[Path, str]] = []
        c, recs = _copy_tree(src, dest / sub, dry, rel_base=run_dir, route=route,
                             residue_out=residue, copied_out=copied_here)
        copied_docs.extend(copied_here)
        cell_rels.update(rel for _f, rel in copied_here)
        layout_records.extend(recs)
        n_residue = len(residue) - n_residue_before
        if c:
            staged.append(f"{sub}/ ({c} files"
                          + (f"; {n_residue} build-residue file(s) NOT staged"
                             if n_residue else "") + ")")

    # GDS_MANIFEST — always, whether or not the GDS itself fits.
    gds_dir = dest / "phase3" / "stage4" / "gds"
    manifest_line, hashed = _write_manifest(gds_files, gds_dir, dry)
    staged.append("phase3/stage4/gds/GDS_MANIFEST.txt")
    cell_rels.add("phase3/stage4/gds/GDS_MANIFEST.txt")

    # The signoff GDS itself. `phase3/stage4` is not a copy subtree, so until
    # this existed the GDS was omitted at EVERY size — the size routing could
    # not reach the one artefact the manifest is actually about.
    for g, sha in hashed:
        if over_ceiling(g):
            layout_records.append(
                _record(g, run_dir, "ROUTED_AWAY", route, sha=sha))
            continue
        if not dry:
            gds_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(g, gds_dir / g.name)
        layout_records.append(_record(g, run_dir, "STAGED", route, sha=sha))
        staged.append(f"phase3/stage4/gds/{g.name}")
        cell_rels.add(f"phase3/stage4/gds/{g.name}")

    # The routed DEF. Same shape as the GDS block above and for the same
    # reason: its directory is not a copy subtree, so without this the artefact
    # is omitted at EVERY size. See `_ROUTED_DEF_RELPATH`.
    routed_def = run_dir / _ROUTED_DEF_RELPATH
    if routed_def.is_file():
        if over_ceiling(routed_def):
            layout_records.append(
                _record(routed_def, run_dir, "ROUTED_AWAY", route))
        else:
            if not dry:
                target = dest / _ROUTED_DEF_RELPATH
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(routed_def, target)
            layout_records.append(
                _record(routed_def, run_dir, "STAGED", route))
            staged.append(_ROUTED_DEF_RELPATH.as_posix())
            cell_rels.add(_ROUTED_DEF_RELPATH.as_posix())
    else:
        # NOTHING AT THE CANONICAL PATH, AND THE RUN HAS ONE SOMEWHERE ELSE.
        # Since the block above exists, `_ROUTED_DEF_RELPATH` is IN published
        # scope, so this is a DIFFERENT fact from the policy exclusions the
        # inventory records: the artefact was not declined, it was not found.
        # Recorded NOT_PUBLISHED -- as it was until this branch -- the two are
        # the same word, and a reader of the cell concludes the run had no
        # post-route geometry. `CITATION_ROUTING.txt` already argues this
        # distinction for citations: "a directory that ships its neighbours
        # and not this file is a HOLE ... the wrong word here retires a
        # finding instead of reporting one."
        #
        # MEASURED, and the shape is committed rather than hypothetical: the
        # published corpus carries 52 files under a doubled `phase3/phase3/`
        # prefix -- 28 under `protocol_parity/lpc/`, 24 under
        # `protocol_parity/usb_pd/`, of which 11 sit in
        # `lpc/phase3/phase3/stage3/pnr/` itself. A run tree of that shape
        # publishes rc 0, a cell with zero
        # `.def` files, and -- before this -- no sentence anywhere naming the
        # artefact it dropped.
        #
        # DEDUPED ON THE RESOLVED PATH, for the reason `_inventory_unpublished`
        # gives: converged runs alias their outputs under `steps/`, and the
        # same blob reached twice is the same evidence twice.
        #
        # SEEDED FROM WHAT IS ALREADY RECORDED, and that is not an optimisation.
        # A `routed.def` inside a published subtree -- `reports/phase3/` is the
        # measured case -- has ALREADY been decided about by `_copy_tree`:
        # STAGED under the ceiling, ROUTED_AWAY over it. Emitting a second row
        # for it here breaks this file's own invariant, stated in its header:
        # "ONE LINE PER BLOB, not per path". Caught by
        # test_an_oversized_artefact_is_absent_but_recorded_with_its_hash,
        # which read 2 lines where it requires 1. `OFF_CANONICAL_PATH` is for
        # an artefact the publisher never looked at -- not for one it looked at
        # and decided.
        off_canonical = []
        aliased = {Path(r["src"]).resolve() for r in layout_records}
        for cand in sorted(run_dir.rglob(_ROUTED_DEF_RELPATH.name)):
            if not cand.is_file():
                continue
            real = cand.resolve()
            if real in aliased:
                continue
            aliased.add(real)
            rec = _record(cand, run_dir, "OFF_CANONICAL_PATH", route)
            layout_records.append(rec)
            # The record's OWN path column, not a second derivation of it: a
            # symlink resolving outside the run makes `relative_to` raise, and
            # `_record` already has the fallback for exactly that.
            off_canonical.append(rec["path"])
        if off_canonical:
            # NOT a refusal. The run may be converged and the cell worth
            # publishing; what must not happen is the drop being silent.
            print(
                f"WARNING: this run carries "
                f"{len(off_canonical)} {_ROUTED_DEF_RELPATH.name} file(s), "
                f"none of them at {_ROUTED_DEF_RELPATH.as_posix()}, which is "
                f"the only path the published-corpus population is built "
                f"from. The cell is published WITHOUT a routed DEF and adds "
                f"no member to that corpus. Found: "
                + ", ".join(sorted(off_canonical))
                + f". Recorded OFF_CANONICAL_PATH in {_ROUTING_FILENAME}.",
                file=sys.stderr)

    # shared design input (staged once per IC). BEFORE the routing record is
    # written: these files can live under the run too, and one recorded as
    # NOT_PUBLISHED after having been staged would be a false entry in the
    # one file whose whole value is that it can be trusted.
    shared_input = ic_root / "input"
    input_result, input_recs = _stage_shared_input(run_dir, args, shared_input,
                                                   dry, route, residue_out=residue)
    layout_records.extend(input_recs)

    # Per-step evidence. AFTER the subtrees + the GDS, because each declared
    # output's decision is "can a reader of THIS cell find it", and that is not
    # answerable until the cell is populated. Publishes records only — no
    # symlink is created and none is copied.
    steps_result = publish_steps(run_dir, dest, dry)
    if steps_result["n_steps"]:
        staged.append(f"steps/ ({steps_result['n_steps']} "
                      f"{_STEP_RECORD_FILENAME}"
                      + (f" + {steps_result['n_records_copied']} record file(s)"
                         if steps_result["n_records_copied"] else "") + ")")
    staged.append(_STEP_ROUTING_FILENAME)

    # CITATION CLOSURE (#2007). AFTER every other staging decision, because
    # "is the cited proof already in the cell" is only answerable once the
    # cell is populated; BEFORE the layout inventory and the routing records,
    # which must describe the FINAL tree; and BEFORE the provenance pruning,
    # so a declared output the closure pulls in is no longer disclosed as
    # pruned. `above` is where the gate's ladder keeps resolving past the
    # cell root; this program never stages there and must not call a
    # citation absent that a reader can follow.
    closure = close_citations(run_dir, dest, copied_docs, cell_rels, dry,
                              above=[ic_root, dest_root / "ic"])
    for r in closure["staged"]:                     # type: ignore[union-attr]
        staged.append(f"{r['path']} (citation closure: cited by {r['doc']})")

    # Complete the inventory: layout artefacts the published scope excludes.
    seen = {Path(r["src"]) for r in layout_records}
    layout_records.extend(_inventory_unpublished(run_dir, seen, route))

    # The routing record — emitted even when nothing was routed away.
    _write_routing(layout_records, dest, dry)
    # Same treatment for CITED artefacts as for blobs (#448): a citation the
    # published layout cannot carry is RECORDED as out of scope rather than
    # left to dangle. Read from the STAGED tree, so it answers the reader's
    # question — "can I follow this from what I received?" — not the run's.
    citation_records = collect_citation_records(dest, freshly_staged=True)
    write_citation_routing(dest, citation_records, dry)
    staged.append(_ROUTING_FILENAME)
    staged.append(_CITATION_ROUTING_FILENAME)
    excluded_total = sum(1 for r in layout_records if r["decision"] == "ROUTED_AWAY")

    # Rewrite the (already-copied) provenance.jsonl with pruned-at-publish
    # disclosures for every declared output this program decided not to
    # stage. Must run AFTER every staging decision above (subtrees, GDS,
    # shared input, step evidence) so "is it staged?" reflects the real,
    # final tree.
    provenance_note = _prune_provenance(run_dir, dest, dry)

    summary = {
        "ic": args.ic,
        "pdk": args.pdk,
        # The NAME above is the request; this is what actually ran. Both are
        # kept because they answer different questions and a reader who sees
        # only the first cannot tell that.
        "pdk_revision": pdk_rev.get("revision"),
        "pdk_revision_record": pdk_rev,
        "plugin_version": args.plugin_version,
        "verdict": verdict,
        "verdict_source": str(verdict_src),
        "result_md_verdict": rmd_verdict,
        "dest": str(dest),
        "gds_manifest": manifest_line,
        "gds_source": [str(g) for g in gds_files],
        "staged": staged,
        "excluded_raw_files": excluded_total,
        "layout_routing": layout_records,
        # #2006. Compiler / Verilator intermediates found in a published
        # subtree and left behind. Reported even when empty, for the reason
        # `excluded_raw_files` is.
        "build_residue_skipped": {
            "files": len(residue),
            "bytes": sum(r["bytes"] for r in residue if r["bytes"] > 0),
            "paths": [r["path"] for r in residue],
        },
        "oversize_route": route,
        "shared_input": input_result,
        "step_evidence": steps_result,
        # #2007. Every citation a staged document carries and what the
        # closure did about it. Reported even when nothing was pulled in,
        # for the reason `excluded_raw_files` is.
        "citation_closure": closure,
        "provenance_pruned": provenance_note,
        "dry_run": dry,
    }

    # --- post-stage self-check (structure conformance) ---
    if not dry:
        ok, detail = _self_check(dest)
        summary["self_check"] = detail
        if not ok:
            raise Refuse(
                f"post-stage self-check FAILED — the staged folder is NOT "
                f"conformant:\n{detail}")

    # --- post-stage self-check (the write ledger describes THIS cell) ---
    # Runs after every staging decision, because the question is about the
    # FINAL tree: a ledger is only true of a cell once the cell is complete.
    if not dry:
        stale = stale_write_ledger(dest)
        summary["write_ledger_consistency"] = (
            stale or f"{_LEDGER_REL} agrees with the staged cell "
                     f"(or the run published none)")
        if stale:
            raise Refuse(
                "post-stage self-check FAILED — the write ledger staged into "
                "this cell is REFUTED by the cell itself:\n  "
                + "\n  ".join(stale)
                + f"\nThe record is a snapshot of the run tree at "
                  f"{led_captured(dest)!r} and the run wrote more after it. "
                  f"Re-run `programs/step_write_ledger.py <run-dir>` over the "
                  f"FINISHED run and publish again — do NOT emit it over the "
                  f"staged cell, whose mtimes are a copy's and whose "
                  f"time-derived half is therefore withheld.")

    return summary


_LEDGER_REL = "reports/write_ledger.json"
_LEDGER_D3_RULE = "declared_output_not_produced"


def stale_write_ledger(cell: Path) -> List[str]:
    """Every claim the write ledger STAGED INTO *cell* makes that *cell* itself
    refutes. Empty means the record still describes the tree it ships in.

    WHY A PUBLISHED CELL CAN CARRY A LIE, AND HOW IT DID.
    ``step_write_ledger`` records a SNAPSHOT: what the run tree held at the
    moment it walked, plus the mtimes, provenance windows and D3/D5/D7 residual
    derived from that instant. It is emitted into ``reports/``, and ``reports``
    is a copied subtree, so whichever snapshot happens to be lying in the run
    directory at publish time is staged as though it described the tree being
    staged. Nothing re-checked it, and the record moved into a commit where it
    keeps being read as current.

    MEASURED 2026-08-13 on ``benchmark-data/ic/spm/v1.9.96_gf180mcuD``. Its
    ledger was captured 2026-08-06T19:17:51Z over ``/home/<your-user>/spm3_run/
    gf180mcuD``; the run then wrote ``phase2/stage2/dft/scan_netlist.v`` at
    2026-08-07 08:39:52 (the file's own Fault header) and the publish staged the
    finished tree beside the mid-run record. The committed ledger states that
    four artefacts were never written which the very same commit carries,
    non-empty and tracked at HEAD:

        phase2/stage2/dft/scan_netlist.v          81570 B
        phase2/stage2/dft/atpg_coverage.rpt         421 B
        reports/phase2/dft/coverage.json           3549 B
        phase2/stage2/synth/post_dft_netlist.v    77802 B

    That is not a cosmetic disagreement. ``test_matrix_d3_outputs_produced``
    binds a run root's verdict to that root's ledger and the binding may only
    ever SUBTRACT evidence, so a stale record makes the dimension refuse a real
    artefact at exactly the declared path and quote itself as the authority.

    THE CHECK IS THE LEDGER'S OWN D3 FINDING PUT BACK TO THE CELL: for every
    spec the ledger records as never written, ask whether the staged tree
    carries a usable artefact there, and report every YES. That direction only —
    a ledger that records a spec as produced when the file is missing makes the
    cell look WORSE than it is and needs no guard here.

    The resolver and the usability rule are IMPORTED from
    ``step_write_ledger`` rather than re-implemented, so this guard cannot
    drift away from the semantics of the record it is checking.

    A cell with no ledger returns ``[]``: not publishing one is fine, and is
    what a run that never ran the emitter does.
    """
    led_path = cell / _LEDGER_REL
    if not led_path.is_file():
        return []
    _here = str(Path(__file__).resolve().parent)
    if _here not in sys.path:
        sys.path.insert(0, _here)
    import step_write_ledger as _swl

    try:
        led = json.loads(led_path.read_text())
    except (OSError, ValueError) as exc:
        return [f"{_LEDGER_REL} is staged but unreadable ({exc}); a record "
                f"nobody can parse cannot be published as evidence"]

    # The emitter writes `steps` as a LIST of rows. Accept a mapping too and
    # say so, rather than iterating its keys and quietly finding nothing: a
    # guard that returns a clean answer because it could not read the record is
    # the failure mode this whole check exists to end.
    steps = led.get("steps")
    if isinstance(steps, dict):
        rows = list(steps.values())
    elif isinstance(steps, list):
        rows = steps
    elif steps is None:
        rows = []
    else:
        return [f"{_LEDGER_REL} is staged but its `steps` field is "
                f"{type(steps).__name__}, which this guard cannot read; a "
                f"record that cannot be checked must not be published"]

    problems: List[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for finding in (row.get("findings") or ()):
            if not isinstance(finding, dict):
                continue
            if finding.get("dimension") != "D3" \
                    or finding.get("rule") != _LEDGER_D3_RULE:
                continue
            spec = str(finding.get("spec"))
            for rel in _swl._spec_candidates(cell, spec):
                p = cell / rel
                if p.is_symlink() or not p.is_file():
                    continue
                try:
                    size = p.stat().st_size
                except OSError:
                    continue
                if size <= 0:
                    continue
                problems.append(
                    f"step {row.get('id')} spec {spec!r}: the ledger says NOT "
                    f"WRITTEN ({finding.get('reason')}) but the cell being "
                    f"staged carries {rel} ({size} B)")
                break
    return problems


def led_captured(cell: Path) -> str:
    """``captured_at`` of the ledger staged into *cell*, for the refusal
    message. Unknown rather than raising: a guard must not fail while
    explaining a failure."""
    try:
        return str(json.loads(
            (cell / _LEDGER_REL).read_text()).get("captured_at", "unknown"))
    except (OSError, ValueError):
        return "unknown"


def _stage_shared_input(run_dir: Path, args: argparse.Namespace,
                        shared_input: Path, dry: bool,
                        route: str = "not-retained",
                        residue_out: Optional[List[dict]] = None
                        ) -> Tuple[str, List[dict]]:
    """Copy the design-input docs to ic/<IC>/input/ once. Non-fatal: on a 2nd/3rd
    PDK for the same IC the shared input already exists and is left untouched.

    Returns (message, layout_records). Design docs are not normally layout
    artefacts, but the input dir usually sits UNDER the run — so anything the
    inventory would otherwise sweep up as NOT_PUBLISHED has to be accounted
    for here first, or the record would contradict itself.
    """
    if shared_input.is_dir() and any(shared_input.iterdir()) and not args.force:
        return f"kept existing {shared_input}", []
    src: Optional[Path] = None
    if args.input_docs:
        src = Path(args.input_docs).resolve()
        if not src.is_dir():
            raise Refuse(f"--input-docs {src} is not a directory")
    else:
        for cand in (run_dir / "input" / "docs",
                     run_dir / "input",
                     run_dir / "phase1" / "input_doc"):
            if cand.is_dir() and any(p.is_file() for p in cand.rglob("*")):
                src = cand
                break
    if src is None:
        return "no design-input docs found to stage (shared input unchanged)", []
    dst = shared_input / "docs"
    c, recs = _copy_tree(src, dst, dry, rel_base=run_dir, route=route,
                         residue_out=residue_out)
    for r in recs:
        if r["decision"] == "STAGED":
            r["destination"] = "shared-input"
    return f"staged {c} input doc(s) -> {dst}", recs


def _git_ignored(dest: Path, rels: set) -> set:
    """Which of `rels` (paths relative to `dest`) `.gitignore` excludes.

    One batched `git check-ignore --stdin`, not one subprocess per candidate
    — `rels` is bounded (declared outputs actually present on disk), but a
    per-file subprocess call does not need to be the default shape here.
    Fail-open to "nothing is ignored" on any git/subprocess failure: this
    function only WIDENS what gets pruned, so a failure here means the
    caller's disk-presence check decides alone — the pre-existing, already-
    safe behaviour — never a crash and never a false prune.
    """
    if not rels:
        return set()
    try:
        cp = subprocess.run(
            ["git", "check-ignore", "--stdin"], cwd=str(dest),
            input="\n".join(sorted(rels)), capture_output=True, text=True,
            timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return set()
    # rc 0 = at least one match, 1 = none matched, >1 = a real git error;
    # stdout is authoritative either way except on a real error.
    if cp.returncode not in (0, 1):
        return set()
    return {ln.strip() for ln in cp.stdout.splitlines() if ln.strip()}


_PRUNED_KEY = "outputs_pruned_at_publish"
_PRUNED_REASON_KEY = "outputs_pruned_reason"
_PRUNE_REASON = (
    "declared by the run but outside this cell's published subtrees "
    "(PnR/synthesis/extraction intermediates — see PUBLISHING.md for what "
    "this cell ships); the byte-producing invocation is unaffected, this "
    "output is simply not carried into the published tree")


def _prune_provenance(run_dir: Path, dest: Path, dry: bool) -> str:
    """Annotate `dest/provenance.jsonl` so every declared output NOT staged
    is DISCLOSED as such, not silently missing.

    THE DEFECT THIS CLOSES: `provenance.jsonl` is copied VERBATIM from the
    run (`_COPY_FILES`), unchanged by anything this program decides about
    WHICH subtrees to stage. A step that ran under `phase3/stage3/pnr/` (or
    `extracted/`, or `sta/`) declares its real, produced outputs there —
    and this program has never staged that subtree for any cell. The result:
    `provenance_output_hash_completeness_check` (#434) reads the copied
    ledger, finds declared outputs neither on disk nor accounted for, and
    reports PROVENANCE_OUTPUT_FILE_MISSING / _NOT_SHIPPED_UNDISCLOSED — a
    true finding. MEASURED (spm x sky130A, 2026-08-07): 19 such findings on
    a cell whose own structure/DRC/LVS/STA self-checks were otherwise clean.

    THE FIX, and why it is safe: for each declared output, check the
    STAGED tree first (already verified real, never touched) — then the
    SOURCE run. Only a path that exists in the run but was never staged gets
    pruned; a path absent from the run too is a different fact (the
    declaration's own invocation may have failed, or the run genuinely never
    produced it) and this function leaves it alone rather than guessing.
    Never touches `inputs`, `exit_code`, or any other field — only ever ADDS
    the two disclosure keys `provenance_output_hash_completeness_check`
    already reads (`_publish_disclosures`); it invents no new mechanism.

    "STAGED" MEANS "A CLONE RECEIVES IT", not merely "a file sits at that
    path on THIS disk" — `dest` is not git-added yet when this runs, and a
    repo-wide `.gitignore` rule (e.g. `*.log`) can leave a real, byte-correct
    file copied into `dest` that git will never track. MEASURED: `phase2/
    stage2/synth/synth.log` copied cleanly (phase2/ IS a staged subtree) and
    still failed #434's check, because `git ls-files` — what a clone actually
    receives — never carries it. `git check-ignore` is asked for every
    disk-present candidate for exactly this reason, batched in one call.

    Fail-safe: any read/parse error leaves the verbatim copy `_COPY_FILES`
    already wrote untouched and returns a disclosed skip note — never raises,
    never regresses a publish that would otherwise succeed.
    """
    src = run_dir / "provenance.jsonl"
    dst = dest / "provenance.jsonl"
    if not src.is_file() or dry:
        return "no provenance.jsonl to annotate" if not src.is_file() else "dry-run: not annotated"
    try:
        lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"could not read provenance.jsonl: {exc}"
    parsed: List[object] = []
    disk_present_rels: set = set()
    malformed = False
    for line in lines:
        if not line.strip():
            parsed.append(line)
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            parsed.append(line)         # verbatim — not this function's to fix
            malformed = True
            continue
        parsed.append(entry)
        outputs = entry.get("outputs") if isinstance(entry, dict) else None
        if isinstance(outputs, dict):
            for rel in outputs:
                if isinstance(rel, str) and rel and (dest / rel).is_file():
                    disk_present_rels.add(rel)
    ignored_rels = _git_ignored(dest, disk_present_rels)

    out_lines: List[str] = []
    pruned_total = 0
    for entry in parsed:
        if not isinstance(entry, dict):
            out_lines.append(entry)     # the verbatim malformed line, as-is
            continue
        outputs = entry.get("outputs")
        if not isinstance(outputs, dict) or not outputs:
            out_lines.append(json.dumps(entry))
            continue
        missing_here: List[str] = []
        for rel in outputs:
            if not isinstance(rel, str) or not rel:
                continue
            if rel in disk_present_rels and rel not in ignored_rels:
                continue                # staged AND clone-visible — leave it
            if (run_dir / rel).is_file():
                missing_here.append(rel)  # produced, not in the published tree
            # else: absent even in the source run — a different fact,
            # left alone; see the docstring.
        if missing_here:
            existing = entry.get(_PRUNED_KEY)
            merged = sorted(set(existing) if isinstance(existing, list) else set()
                            | set(missing_here))
            entry[_PRUNED_KEY] = merged
            entry[_PRUNED_REASON_KEY] = _PRUNE_REASON
            pruned_total += len(missing_here)
        out_lines.append(json.dumps(entry))
    if malformed:
        return "provenance.jsonl carries malformed line(s); left verbatim"
    dst.write_text("\n".join(out_lines) + ("\n" if out_lines else ""),
                   encoding="utf-8")
    return (f"{pruned_total} declared output(s) across the ledger disclosed "
            f"as pruned-at-publish (not in this cell's staged subtrees)"
            if pruned_total else "no declared output needed pruning")


def _self_check(dest: Path) -> Tuple[bool, str]:
    """Run the companion structure checker on the freshly staged folder."""
    checker = Path(__file__).resolve().parent / "benchmark_evidence_structure_check.py"
    if not checker.is_file():
        return True, f"structure checker not found at {checker}; skipped self-check"
    out = subprocess.run(
        [sys.executable, str(checker), str(dest)],
        capture_output=True, text=True, check=False)
    return out.returncode == 0, (out.stdout + out.stderr).strip()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Stage a converged (IC × PDK) run's evidence into the "
                    "canonical benchmark-data layout (stages only; never commits).")
    ap.add_argument("--run-dir", required=True, help="completed run directory")
    ap.add_argument("--ic", required=True, help="IC name (a parameter)")
    ap.add_argument("--pdk", required=True, help="PDK tag (a parameter)")
    ap.add_argument("--plugin-version", required=True, help="plugin version X.Y.Z")
    ap.add_argument("--dest-root", default="benchmark-data",
                    help="root under which ic/<IC>/... is staged (default: benchmark-data)")
    ap.add_argument("--result-md", default=None,
                    help="independent-audit RESULT.md (default: <run-dir>/RESULT.md)")
    ap.add_argument("--input-docs", default=None,
                    help="design-input docs dir -> ic/<IC>/input/docs/ (default: auto)")
    ap.add_argument("--gds", default=None,
                    help="explicit streamed .gds for the manifest (default: auto-find)")
    ap.add_argument("--verdict-json", default=None,
                    help="phase23_completion_audit.json "
                         "(default: <run-dir>/reports/audit/phase23_completion_audit.json)")
    ap.add_argument("--oversize-route", default="not-retained",
                    choices=list(_ROUTE_CHOICES),
                    help="where a layout artefact over the commit ceiling went. "
                         "Recorded per-artefact in LAYOUT_ROUTING.txt. Default "
                         "'not-retained' — the honest answer when nobody has "
                         "said otherwise; naming git-lfs / github-release is a "
                         "claim the operator is making.")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing destination / shared input")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute + guard but write nothing")
    ap.add_argument("--json", default=None, help="write a machine-readable summary here")
    args = ap.parse_args(argv)

    try:
        summary = publish(args)
    except Refuse as r:
        print(f"REFUSED: {r}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    verb = "WOULD STAGE" if summary["dry_run"] else "STAGED"
    print(f"[{verb}] {summary['ic']} × {summary['pdk']}  ->  {summary['dest']}")
    print(f"  verdict     : {summary['verdict']} (source: {summary['verdict_source']})")
    print(f"  pdk revision: {summary['pdk_revision']} "
          f"(read from the tree that ran, not from --pdk)")
    print(f"  GDS_MANIFEST: {summary['gds_manifest']}")
    recs = summary["layout_routing"]
    kept = [r for r in recs if r["decision"] == "STAGED"]
    away = [r for r in recs if r["decision"] == "ROUTED_AWAY"]
    unpub = [r for r in recs if r["decision"] == "NOT_PUBLISHED"]
    print(f"  layout      : {len(kept)} staged, {len(away)} routed away "
          f"(-> {summary['oversize_route']}), {len(unpub)} not published, of "
          f"{len(recs)} artefact(s) — all recorded in {_ROUTING_FILENAME}")
    for r in away:
        print(f"      ROUTED_AWAY {r['bytes'] / 1e6:.1f} MB  {r['path']} "
              f"-> {r['destination']}  sha256:{r['sha256'][:12]}…")
    print(f"  shared input: {summary['shared_input']}")
    br = summary["build_residue_skipped"]
    if br["files"]:
        print(f"  build residue: {br['files']} file(s), {br['bytes'] / 1e6:.1f} MB "
              f"NOT staged — compiler/Verilator intermediates, reproduced by "
              f"re-running the build, not evidence (#2006)")
    se = summary["step_evidence"]
    if not se["present"]:
        print(f"  step evidence: source run has NO {_STEPS_DIRNAME}/ tree — "
              f"recorded as absent in {_STEP_ROUTING_FILENAME}")
    elif not se["location_determined"]:
        print(f"  step evidence: {se['n_steps']} step(s), {se['n_declared']} "
              f"declared output(s) — {se['n_zero_byte']} zero-byte, "
              f"{se['n_dangling']} dangling, {se['n_absent']} absent in run. "
              f"The in-cell / out-of-scope split is NOT determined on a dry "
              f"run: nothing was staged for it to be decided against.")
    else:
        print(f"  step evidence: {se['n_steps']} step(s), {se['n_declared']} "
              f"declared output(s) — {se['n_in_cell']} in cell, "
              f"{se['n_out_of_scope']} out of published scope, "
              f"{se['n_zero_byte']} zero-byte, {se['n_dangling']} dangling, "
              f"{se['n_absent']} absent in run "
              f"(recorded in {_STEP_ROUTING_FILENAME}; the view's symlinks are "
              f"NOT published)")
    if se.get("error"):
        print(f"      ! step record INCOMPLETE: {se['error']}")
    cc = summary["citation_closure"]
    print(f"  citations   : {cc['n_citations']} in {cc['n_documents']} staged "
          f"document(s) — {len(cc['staged'])} cited proof(s) pulled into the "
          f"cell by closure (#2007), {cc['already_in_cell']} already in cell, "
          f"{len(cc['absent'])} absent in run, {len(cc['over_ceiling'])} over "
          f"the ceiling, {len(cc['layout_policy'])} under layout policy, "
          f"{len(cc['step_view'])} in the step view, {len(cc['above_cell'])} "
          f"resolving above the cell")
    for r in cc["staged"]:
        print(f"      CLOSED  {r['bytes']} B  {r['path']}  <- {r['doc']} :: "
              f"{r['cited']}")
    for r in cc["over_ceiling"]:
        print(f"      OVER_CEILING {r['bytes'] / 1e6:.1f} MB  {r['path']}  <- "
              f"{r['doc']} :: {r['cited']} (NOT staged; the row stays DANGLING)")
    for a in cc["amended"]:
        print(f"      AMENDED {a['doc']}: {', '.join(sorted(a['fields']))} "
              f"absent in run -> evidence_present=false, verdict "
              f"{a['verdict_as_run']} -> {a['verdict']} (staged copy only)")
    for u in cc["unamended"]:
        print(f"      WARNING {u['doc']} cites {', '.join(u['cited'])}, which "
              f"do(es) not exist in the run. This program does not edit prose: "
              f"amend the document (honest absence) before landing, or "
              f"evidence_citation_resolves_check stays red on it.")
    for e in cc["errors"]:
        print(f"      ! closure INCOMPLETE: {e}")
    for s in summary["staged"]:
        print(f"    + {s}")
    if not summary["dry_run"]:
        print(f"  self-check  : PASS")
        print(f"\nNOT COMMITTED. To land this evidence, review then:")
        print(f"    git add {summary['dest']} "
              f"{Path(summary['dest']).parent / 'input'}")
        print(f"    git commit  # (a deliberate act — this program never commits)")

    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
