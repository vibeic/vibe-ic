#!/usr/bin/env python3
"""Enumerate the routed-DEF hygiene corpus from git's index.

The published corpus may live in this checkout or in the repository named by
``VIBE_IC_BENCHMARK_DATA``.  stdout is deliberately only the machine population
(one absolute DEF path per line); every resolution/refusal diagnostic goes to
stderr so ``gate_dispatch_over`` cannot mistake prose for an item.

There is no elapsed-time verdict here.  Git either exits and supplies complete
index evidence, or the caller's progress supervisor owns liveness.  A broken
pointer, a loose directory, or a failed git query is UNDETERMINED (rc 2), never
an empty population.

AN ABSENT CORPUS IS NOT AN EMPTY ONE, AND THEY DO NOT SHARE AN EXIT CODE
(vibe-ic#1764).  The line above promised that every way of failing to READ the
corpus stays out of the population, and one row was left out of it: when
nothing is at ``benchmark-data/`` and ``VIBE_IC_BENCHMARK_DATA`` is unset,
``_corpus_location.refuse(may_be_absent=True)`` answers rc 0 with an empty
stdout -- which is byte-identical to "I read the index and it holds no routed
DEF".  ``gate_dispatch_over`` then printed ONE row for both, and a reader could
not tell a measurement of zero from the absence of a measurement.

    rc 0  the index WAS read and it publishes no routed DEF   -- a measurement
    rc 3  no corpus was resolved, so nothing was opened       -- no measurement
    rc 2  somebody said where the corpus is and was wrong     -- UNDETERMINED

rc 3 is :data:`NO_CORPUS_RC`, matched by ``GATE_DISPATCH_ABSENT_RC`` in
``tools/ci/_gate_dispatch.sh``.  It is deliberately NOT rc 2: an absent corpus
is not a broken configuration, and the considered opt-in in
``_corpus_location.refuse`` -- that a repository which no longer carries the
published tree is not thereby misconfigured -- is left standing.  BOTH states
stay NOT CHECKED and BOTH stay blocking at the dispatcher; only the sentence
each of them gets is different.

A CELL'S IDENTITY IS (design, pdk), AND IT IS SPELLED ONCE (vibe-ic#2011).
A member of this population is ``ic/<design>/v<version>_<pdk>/phase3/stage3/
pnr/routed.def``.  The gate labels the hygiene loop declares over it, and the
gate identities this producer writes into the trusted manifest, used to carry
the DESIGN alone -- so the first design published on two PDKs (spm on sky130A
and on gf180mcuD) would have handed eight gates four labels, two owners per
identity.  This producer refused that whole population rather than declare a
duplicate owner, and the refusal named the repair: migrate the identity.

The identity is now the ``<design>/<pdk>`` pair, derived by
``hygiene_finding_delta.routed_cell_identity`` and by nothing else in Python;
``repo_hygiene_gates.sh::_routed_cell_id`` mirrors the same grammar in bash and
a test pins the two spellings equal.  The version is NOT part of it: a
republish of one design on one PDK is the same owner, so anything keyed by
label keeps its meaning.  Two routed DEFs on the same (design, pdk) are still
a refusal here -- naming the pair -- and so is a cell whose version directory
states no PDK at all: a cell with no identity in this model is not given a
made-up one.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Sequence

_CORPUS_NAME = "published cells carrying a routed DEF"
_ORIGIN = "https://github.com/vibeic/benchmark-data.git"

#: "No corpus was resolved; nothing was opened."  Distinct from rc 0 (an index
#: was read and it holds none) and from rc 2 (a pointer was given and is
#: wrong).  `GATE_DISPATCH_ABSENT_RC` in `tools/ci/_gate_dispatch.sh` is the
#: same number, and `test_the_absent_exit_code_is_one_number_in_two_languages`
#: pins that the two spellings cannot drift apart.
NO_CORPUS_RC = 3


def _programs(repo: Path) -> Path:
    return repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"


def _git(argv: Sequence[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(list(argv), capture_output=True, text=True)
    except OSError as exc:
        print(f"[routed-def corpus] UNDETERMINED: could not execute git: {exc}",
              file=sys.stderr)
        return None


def _index_paths(corpus: Path, identity_of,
                 announce_empty: bool = False) -> tuple[int, list[Path]]:
    """``(rc, routed DEFs)`` read out of git's index under `corpus`.

    `identity_of` is ``hygiene_finding_delta.routed_cell_identity`` -- passed
    in rather than imported here because the callers resolve the plugin's
    program tree first and this function must not guess where it is.  Every
    member's (design, pdk) identity must be formable and unique (vibe-ic#2011).

    `announce_empty` makes a MEASURED empty population say so and NAME the
    index it read (vibe-ic#1764).  Without it, "the index under X publishes no
    routed DEF" reaches a reader as the same silence as "there was no X to
    open", and the whole point of keeping the two apart is that one of them is
    a measurement and the other is the absence of one.
    """
    top_probe = _git(["git", "-C", str(corpus), "rev-parse", "--show-toplevel"])
    if top_probe is None:
        return 2, []
    if top_probe.returncode != 0 or not top_probe.stdout.strip():
        detail = (top_probe.stderr or top_probe.stdout).strip()
        print(
            f"[routed-def corpus] UNDETERMINED: {corpus} exists but is not a "
            "git checkout. This producer reads git's INDEX; treating a loose "
            "directory as zero routed DEFs would be a false empty corpus."
            + (f" git said: {detail}" if detail else ""),
            file=sys.stderr,
        )
        return 2, []

    top = Path(top_probe.stdout.strip()).resolve()
    try:
        prefix = corpus.resolve().relative_to(top)
    except (OSError, ValueError) as exc:
        print(
            f"[routed-def corpus] UNDETERMINED: git reported checkout root "
            f"{top}, but corpus {corpus} is not inside it ({exc}).",
            file=sys.stderr,
        )
        return 2, []

    pathspec = prefix.as_posix() if prefix.parts else "."
    listed = _git([
        "git", "-C", str(top), "ls-files", "--stage", "-z", "--full-name",
        "--", pathspec
    ])
    if listed is None:
        return 2, []
    if listed.returncode != 0:
        detail = (listed.stderr or listed.stdout).strip()
        print(
            f"[routed-def corpus] UNDETERMINED: git could not enumerate the "
            f"index under {corpus} (rc {listed.returncode})."
            + (f" git said: {detail}" if detail else ""),
            file=sys.stderr,
        )
        return 2, []

    routed: list[Path] = []
    cells: dict[str, str] = {}
    prefix_posix = PurePosixPath(prefix.as_posix()) if prefix.parts else None
    for stage_row in listed.stdout.split("\0"):
        if not stage_row:
            continue
        try:
            metadata, raw = stage_row.split("\t", 1)
            mode, _oid, stage = metadata.split()
        except ValueError:
            print(
                "[routed-def corpus] UNDETERMINED: git returned a malformed "
                "index-stage row.", file=sys.stderr)
            return 2, []
        if stage != "0":
            print(
                f"[routed-def corpus] UNDETERMINED: {raw} is not a stage-0 "
                "index entry.", file=sys.stderr)
            return 2, []
        if "\n" in raw or "\r" in raw:
            print(
                "[routed-def corpus] UNDETERMINED: an indexed path contains "
                "a line break, which cannot be represented by the producer's "
                "one-item-per-line protocol.",
                file=sys.stderr,
            )
            return 2, []
        indexed = PurePosixPath(raw)
        try:
            rel = indexed.relative_to(prefix_posix) if prefix_posix else indexed
        except ValueError:
            # Git was asked for this pathspec, but do not let an unexpected
            # out-of-tree row widen the population.
            continue
        parts = rel.parts
        if (len(parts) == 6 and parts[2:] ==
                ("phase3", "stage3", "pnr", "routed.def")):
            design, version = parts[0], parts[1]
            cell = identity_of(design, version)
            if cell is None:
                print(
                    f"[routed-def corpus] UNDETERMINED: {design}/{version} "
                    "publishes a routed DEF but its version directory does "
                    "not state a PDK (expected v<version>_<pdk>). The "
                    "gate-owner identity of a published cell is (design, "
                    "pdk); a cell with no PDK has no identity in that model "
                    "and is not given a made-up one (vibe-ic#2011).",
                    file=sys.stderr,
                )
                return 2, []
            prior = cells.get(cell)
            if prior is not None:
                print(
                    f"[routed-def corpus] UNDETERMINED: design {design!r} "
                    f"publishes two routed-DEF cells on the same PDK "
                    f"({prior!r}, {version!r}), and both would own the gates "
                    f"labelled ({cell}). The corpus publishes one routed DEF "
                    "per (design, pdk); retire one of the two, or extend the "
                    "identity to (design, pdk, version) in "
                    "hygiene_finding_delta.routed_cell_identity before this "
                    "population can carry both (vibe-ic#2011).",
                    file=sys.stderr,
                )
                return 2, []
            cells[cell] = version
            # Keep the indexed pathname itself.  `resolve()` here would follow
            # a tracked symlink and silently change which path the index said
            # belonged to the population.
            candidate = top.joinpath(*indexed.parts)
            try:
                observed = candidate.lstat()
            except OSError:
                observed = None
            if (mode not in ("100644", "100755") or observed is None
                    or not stat.S_ISREG(observed.st_mode)):
                print(
                    f"[routed-def corpus] UNDETERMINED: the index publishes "
                    f"{indexed.as_posix()} as mode {mode}, but its working-tree "
                    "entry is not a materialized regular file. The per-cell "
                    "gates consume exact file bytes; a symlink, sparse, or "
                    "missing checkout is not complete corpus evidence.",
                    file=sys.stderr,
                )
                return 2, []
            routed.append(candidate)
    if not routed and announce_empty:
        print(
            f"[routed-def corpus] MEASURED EMPTY: git's index at {top} was "
            f"read under {pathspec!r} and it publishes no "
            f"*/*/phase3/stage3/pnr/routed.def. This IS a measurement -- the "
            f"corpus was opened and the population is 0 -- and it is NOT the "
            f"same state as a corpus that could not be found (rc "
            f"{NO_CORPUS_RC}).",
            file=sys.stderr,
        )
    return 0, sorted(routed, key=lambda path: path.as_posix())


def _manifest(repo: Path, checkout: Path, subject_repo: Path, sha: str,
              output: Path) -> int:
    """Emit parent-owned population and independent checker receipts."""
    checkout = checkout.resolve()
    subject_repo = subject_repo.resolve()
    if not subject_repo.is_dir():
        print("[routed-def corpus] UNDETERMINED: subject repository for argv "
              "binding is missing.", file=sys.stderr)
        return 2
    head = _git(["git", "-C", str(checkout), "rev-parse", "HEAD"])
    if (head is None or head.returncode != 0
            or head.stdout.strip() != sha):
        print("[routed-def corpus] UNDETERMINED: trusted manifest checkout "
              "does not equal the measured benchmark SHA.", file=sys.stderr)
        return 2
    programs = _programs(repo)
    plugin = programs.parent
    subject_programs = _programs(subject_repo)
    subject_plugin = subject_programs.parent
    if not programs.is_dir() or not subject_programs.is_dir():
        print("[routed-def corpus] UNDETERMINED: trusted or subject plugin "
              "program tree is missing.", file=sys.stderr)
        return 2
    sys.path.insert(0, str(programs))
    import gate_process_attestation as attestation  # noqa: PLC0415
    import hygiene_finding_delta as identity  # noqa: PLC0415
    import repo_hygiene_parallel as owned_runner  # noqa: PLC0415
    from _atomic_artefact import write_json  # noqa: PLC0415

    rc, paths = _index_paths(checkout / "ic", identity.routed_cell_identity)
    if rc != 0:
        return rc

    items = []
    receipts = []
    try:
        operational_grace = float(os.environ.get(
            "GATEKEEPER_OPERATIONAL_STALL_GRACE", "300"))
    except ValueError:
        operational_grace = -1
    if operational_grace <= 0:
        print("[routed-def corpus] UNDETERMINED: operational stall grace "
              "must be positive.", file=sys.stderr)
        return 2
    for ordinal, path in enumerate(paths, 1):
        try:
            rel = path.relative_to(checkout).as_posix()
        except ValueError:
            print("[routed-def corpus] UNDETERMINED: routed DEF escaped the "
                  "attested checkout.", file=sys.stderr)
            return 2
        parts = PurePosixPath(rel).parts
        if (len(parts) != 7 or parts[0] != "ic" or parts[3:] !=
                ("phase3", "stage3", "pnr", "routed.def")):
            print("[routed-def corpus] UNDETERMINED: manifest item has an "
                  f"unexpected identity: {rel}", file=sys.stderr)
            return 2
        # The label identity is (design, pdk) and comes from the same
        # function the landing judge re-derives it with (vibe-ic#2011).
        cell_id = identity.routed_cell_identity(parts[1], parts[2])
        if cell_id is None:
            print("[routed-def corpus] UNDETERMINED: manifest item states no "
                  f"PDK in its version directory: {rel}", file=sys.stderr)
            return 2
        labels = [template.format(cell=cell_id)
                  for template in identity.ROUTED_DEF_GATE_LABELS]
        cell = path.parents[3]
        stage = _git(["git", "-C", str(checkout), "ls-files", "--stage",
                      "--", rel])
        if stage is None or stage.returncode != 0:
            return 2
        try:
            metadata, indexed_rel = stage.stdout.rstrip("\n").split("\t", 1)
            mode, blob, index_stage = metadata.split()
        except ValueError:
            print("[routed-def corpus] UNDETERMINED: manifest index row is "
                  f"malformed for {rel}.", file=sys.stderr)
            return 2
        if (indexed_rel != rel or index_stage != "0"
                or mode not in ("100644", "100755")
                or len(blob) not in (40, 64)
                or any(ch not in "0123456789abcdef" for ch in blob)):
            print("[routed-def corpus] UNDETERMINED: manifest index identity "
                  f"is invalid for {rel}.", file=sys.stderr)
            return 2

        gate_specs = [
            (
                labels[0],
                plugin,
                ["python3", "programs/macro_obs_geometry_intersect_check.py",
                 str(cell)],
                subject_plugin,
                ["python3", "programs/macro_obs_geometry_intersect_check.py",
                 str(cell)],
            ),
            (
                labels[1],
                repo,
                ["python3", str(programs / "drc_vacuous_pass_check.py"),
                 str(cell)],
                subject_repo,
                ["python3", str(subject_programs /
                                "drc_vacuous_pass_check.py"), str(cell)],
            ),
            (
                labels[2],
                repo,
                ["python3", str(programs /
                                "step_internal_fail_bubble_up_check.py"),
                 str(cell)],
                subject_repo,
                ["python3", str(subject_programs /
                                "step_internal_fail_bubble_up_check.py"),
                 str(cell)],
            ),
            (
                labels[3],
                plugin,
                ["python3", "programs/tool_diagnostic_id_gate.py", str(cell)],
                subject_plugin,
                ["python3", "programs/tool_diagnostic_id_gate.py", str(cell)],
            ),
        ]
        manifest_gates = []
        for label, trusted_cwd, trusted_argv, subject_cwd, subject_argv in gate_specs:
            argv_hash = attestation.argv_sha256(
                subject_argv, (subject_repo, subject_cwd, checkout))
            owned = {}
            child_rc, body, problem = owned_runner._run(
                trusted_argv, trusted_cwd, dict(os.environ),
                # No total elapsed limit.  This parent-owned operational lease
                # only classifies a checker that stops producing any bounded
                # diagnostic progress; natural exit and the semantic receipt
                # below remain the correctness evidence.
                stall_grace_s=operational_grace,
                owned_result_sink=owned)
            if problem or not owned:
                print("[routed-def corpus] UNDETERMINED: independent checker "
                      f"receipt for {label!r} is incomplete: {problem}; "
                      f"diagnostic={body[-1000:]}", file=sys.stderr)
                return 2
            manifest_gates.append({
                "label": label,
                "argv_sha256": argv_hash,
            })
            receipts.append({
                "schema": 1,
                "complete": True,
                "label": label,
                "argv_sha256": argv_hash,
                "returncode": child_rc,
                # Derived by the trusted phase-1 attestation implementation
                # over the exact independent checker output.  HDF compares
                # this semantic record byte-for-byte with the candidate gate's
                # process attestation; rc alone cannot hide a `[FAIL]` verdict.
                "semantic": attestation.semantic_record(
                    body, child_rc, (repo, trusted_cwd, checkout)),
                "owned": owned,
            })
        items.append({
            "ordinal": ordinal,
            "path": rel,
            "mode": mode,
            "blob": blob,
            "gates": manifest_gates,
        })

    write_json(output, {
        "schema": 1,
        "complete": True,
        "origin": _ORIGIN,
        "benchmark_data_sha": sha,
        "corpora": [{"name": _CORPUS_NAME, "items": items}],
        "execution_receipts": receipts,
    }, ensure_ascii=False)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--trusted-manifest", type=Path)
    ap.add_argument("--checkout", type=Path)
    ap.add_argument("--subject-repo", type=Path)
    ap.add_argument("--benchmark-sha")
    args = ap.parse_args(argv)
    repo = args.repo.resolve()
    manifest_args = (args.checkout, args.subject_repo, args.benchmark_sha)
    if args.trusted_manifest is not None:
        if any(value is None for value in manifest_args):
            ap.error("--trusted-manifest requires --checkout, --subject-repo, "
                     "and --benchmark-sha")
        return _manifest(
            repo, args.checkout, args.subject_repo, args.benchmark_sha,
            args.trusted_manifest)
    if any(value is not None for value in manifest_args):
        ap.error("manifest-only arguments require --trusted-manifest")
    programs = _programs(repo)
    if not programs.is_dir():
        print(
            f"[routed-def corpus] UNDETERMINED: shared corpus resolver is "
            f"missing at {programs}.",
            file=sys.stderr,
        )
        return 2
    sys.path.insert(0, str(programs))
    import _corpus_location as location  # noqa: PLC0415

    named = repo / "benchmark-data" / "ic"
    corpus, origin = location.resolve(
        named, subdir="ic", gate="routed-def corpus", announce=True)
    if not corpus.is_dir():
        rc = location.refuse(
            "routed-def corpus", named, corpus, origin,
            may_be_absent=True, scanned="routed DEF(s)")
        if rc != 0:
            # A pointer that is set and wrong, or a bound SHA with no checkout.
            # Already UNDETERMINED and already distinct; nothing to add.
            return rc
        # NO_CORPUS. `_corpus_location` answers rc 0 there because for most
        # gates "the corpus is not in this repository" is not a finding
        # against anything, and that considered opt-in is left alone
        # (vibe-ic#1764 argued for reversing it; reversing it would have made
        # an absent corpus borrow the FAILED PRODUCER row instead, which is a
        # second wrong sentence rather than the missing one).
        #
        # This program is a POPULATION PRODUCER, and rc 0 already means
        # something else here: "I read an index and it publishes none". So the
        # NO_CORPUS row leaves with its own code, and the dispatcher gives it
        # its own row. It is still not a pass: rc 3 is a blocking NOT CHECKED.
        print(
            f"[routed-def corpus] NOT FOUND (rc {NO_CORPUS_RC}): no corpus "
            f"was resolved, so no index was opened and 0 routed DEF(s) is the "
            f"ABSENCE of a measurement, not a measurement of zero. The line "
            f"above names what was looked for.",
            file=sys.stderr,
        )
        return NO_CORPUS_RC

    # Imported HERE, after resolution, and not beside `_corpus_location`
    # above: the identity rule is only consulted over members, and a tree
    # that carries no corpus must still reach its own NOT FOUND row.
    try:
        import hygiene_finding_delta as identity  # noqa: PLC0415
    except ImportError as exc:
        print(
            f"[routed-def corpus] UNDETERMINED: the shared cell-identity rule "
            f"(hygiene_finding_delta.routed_cell_identity) is missing at "
            f"{programs}: {exc}",
            file=sys.stderr,
        )
        return 2
    rc, paths = _index_paths(corpus, identity.routed_cell_identity,
                             announce_empty=True)
    if rc != 0:
        return rc
    if not paths:
        # A CORPUS THAT WAS READ AND HOLDS NONE USED TO SAY NOTHING AT ALL.
        # The absent-corpus branch above prints a full sentence with a cause and
        # a remedy; this one -- the state the landing path is actually in, since
        # `gatekeeper_review` binds the corpus before the hygiene set runs --
        # printed only the resolution note and exited. So the LESS informative
        # outcome was loud and the more informative one was silent, and the
        # loudest thing in the run (a blocking dispatcher refusal) was produced
        # by the quietest possible producer.
        #
        # rc is UNCHANGED and so is the population: this is 0 items either way,
        # the dispatcher still records NOT_CHECKED, and it still blocks. Only
        # the reader gains the sentence. stderr, never stdout -- stdout is the
        # machine population and prose there would become an item.
        print(
            f"[routed-def corpus] scanned the {origin} corpus at {corpus} and "
            f"its git index holds 0 routed DEF(s). A member is "
            f"<design>/v<version>_<pdk>/phase3/stage3/pnr/routed.def. This is an "
            f"EMPTY POPULATION, not a clean one: no published cell was "
            f"examined and nothing is claimed about any. The per-cell gates "
            f"go live again on the first cell published with a routed DEF.",
            file=sys.stderr,
        )
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
