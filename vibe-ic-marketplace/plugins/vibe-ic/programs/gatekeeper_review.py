#!/usr/bin/env python3
"""gatekeeper_review.py — the DETERMINISTIC half of the single PR gatekeeper.

PURPOSE (Q2)
============
This program is the machine half of the one gatekeeper that decides whether a
PR may land on ``main``. It does NOT re-implement any governance rule — it
AGGREGATES the existing governance programs against a PR's change-set and emits
a single verdict. The existing programs it COMPOSES (import or subprocess —
never re-implemented):

  * source_chip_agnostic_check.py      — chip-AGNOSTIC plugin source guard
  * shipped_path_portability_check.py  — no personal absolute path may
    ship as a value (the phantom-directory / wrong-machine-default guard)
  * commit_msg_nda_check.py            — the MESSAGE-side twin of that guard:
                                         no NDA foundry / SKU / process token in
                                         any commit MESSAGE in base..head
  * nda_diff_scan_check.py             — the DIFF-CONTENT twin: no NDA foundry /
                                         SKU / process / IP-vendor token in any
                                         line the PR ADDS or any added/renamed
                                         PATH, anywhere in the repo (not just the
                                         plugin source tree)
  * gatekeeper_stale_branch_check.py   — the LANDING-METHOD guard: a PR forked
                                         from an older base that also touches a
                                         file landed since would phantom-revert
                                         it under a blind checkout — land via
                                         cherry-pick of the PR's own delta
  * landing_collateral_revert_check.py — the same guard AFTER the fact: no
                                         commit in `base..head` may erase the
                                         contribution an EARLIER commit of the
                                         same range made to a file (the shape a
                                         blind checkout land actually produces)
  * loop_watchdog_compliance_check.py  — every long sub-process is watchdog-
                                         supervised + every risky loop is
                                         bounded (no fixed-timeout kill of a
                                         live job; no loop can spin forever)
  * git_prohibition_guard.py           — forbidden destructive git ops in the
                                         PR's commit command strings
  * version_bump_monotonic_check.py    — strict monotonic version bump
                                         (current > previous) + the
                                         marketplace equality re-assert
  * marketplace_version_sync_check.py  — plugin.json == marketplace.json
  * agent_checkin_scope_guard.py       — role-based check-in path scope
  * plugin_full_audit.py               — D1 (every program tested) + D2 (every
                                         step has a compliance checker)
  * full_suite_run_check.py            — the cadence-appropriate pytest command
                                         was actually issued
  * blindness_audit.py                 — (optional, only when transcripts are
                                         supplied) prompt-only blindness audit
  * control_substance_check.py         — (only when the control evidence is
                                         supplied) how many of the change's
                                         pre-fix control tests OBSERVED A
                                         VALUE, as opposed to only noticing
                                         that something was absent. A control
                                         whose every failure is "the module the
                                         fix introduces does not exist yet"
                                         BLOCKS: "the tests fail pre-fix" is
                                         true of every new file ever written
  * tools/ci/repo_hygiene_gates.sh     — (#538) the ENTIRE repo-hygiene set CI
                                         runs, INVOKED rather than re-listed,
                                         so a gate added to CI is covered here
                                         with no edit to this file. Before it
                                         was wired, this program's own list
                                         overlapped CI's in FIVE of 34 and
                                         MERGE_OK was answered without
                                         consulting the other 29 — twice
                                         wrongly in one day (v1.7.89 landed
                                         red; v1.7.92 was caught only by a
                                         manual habit). See `repo_hygiene_gate`
                                         for why the list is INVOKED and not
                                         derived from the gate names.

THE §4.05 / GENERAL / NO-CHEAT BOUNDARY  (read this — it is load-bearing)
========================================================================
This program is DETERMINISTIC ONLY. The AGENT-JUDGMENT gate — does a relaxation
mask a real defect (§4.05 no-leak)? is the change GENERAL rather than
keyword/overfit? is the root cause fixed without a bypass (no-cheat)? — is
**deliberately NOT in this program**. That gate is the loop's Step-2.7
adversarial review (codex-adversarial-review / the human-or-LLM reviewer), an
irreducibly semantic judgment that no machine gate can stand in for. A green
verdict here means "every MACHINE gate is green"; it is a NECESSARY but NOT a
SUFFICIENT condition to land. The caller MUST still run Step-2.7 before merge.
Folding §4.05 into this program would be the very leak it warns against:
a machine PASS would silently certify a semantic property it cannot measure.

TEST CADENCE (2026-06-17 policy)
================================
The required test cadence is DERIVED from the version bump in the diff, via
``version_bump_monotonic_check`` semver parsing:

  * a PATCH bump  x.y.Z (Z > 0)  requires only a TARGETED regression run.
  * an x.y.0 MINOR milestone     requires the FULL both-tree suite
                                  (``full_suite_run_check`` must see a
                                  full-suite invocation).

If a ``--pytest-cmd`` is supplied, the cadence selector validates it against
the required cadence (a FULL milestone cannot be satisfied by a subset run).

CLI
===
    gatekeeper_review.py --base <ref> --head <ref>
                         [--role <author-role>]
                         [--pytest-cmd "<cmd>"]
                         [--commit-cmds-file <f>]   # PR commit command strings
                         [--transcripts <dir/file> --dataset <root>]  # blindness
                         [--control-junit <f>] [--control-text <f>]  # the
                                                    # pre-fix control's own
                                                    # pytest report
                         [--repo <dir>] [--plugin-root <dir>]
                         [--changed-file <f>]       # override diff (one path/line)
                         [--json OUT]

VERDICT
=======
  MERGE_OK         — all applicable machine gates green.
  REQUEST_CHANGES  — >=1 fixable gate red (each listed in ``blocking``).
  REJECT           — an out-of-scope-by-role, unsalvageable change (e.g. a
                     non-core role touching MCP / plugin secrets). The diff
                     does not belong to this author at all; it must be re-filed
                     as a backlog item, not patched.

5-SECTION JSON
==============
    {verdict, gates:[{name,rc,summary}], cadence, version_bump, blocking[]}

Exit codes
----------
    0  MERGE_OK
    1  REQUEST_CHANGES
    2  REJECT  (also: a usage / git error that prevents a meaningful verdict)

chip-AGNOSTIC: reasons over repo paths, role names, semver tuples, and the
exit codes of the composed governance programs only — no IC / vendor / SKU
literal appears as logic.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import _watchdog as _wd


_PROGRAMS_DIR = Path(__file__).resolve().parent
# repo root = .../vibe-ic-marketplace/plugins/vibe-ic/programs -> up 4
_PLUGIN_ROOT_DEFAULT = _PROGRAMS_DIR.parent  # .../vibe-ic
_PLUGIN_JSON_REL = "vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json"
_MARKETPLACE_JSON_REL = "vibe-ic-marketplace/.claude-plugin/marketplace.json"


# --------------------------------------------------------------------------
# Compose helpers: import the pure-logic neighbours by path so we never have a
# second copy of their rules. subprocess is reserved for the gates whose unit
# of work is "walk the filesystem and exit 0/1" (those have no clean importable
# verdict function or have filesystem side effects).
# --------------------------------------------------------------------------
def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(
        name, _PROGRAMS_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_vbm = _load_module("version_bump_monotonic_check")
_gpg = _load_module("git_prohibition_guard")
_acs = _load_module("agent_checkin_scope_guard")
_roc = _load_module("run_output_completeness_check")


# --------------------------------------------------------------------------
# Data model: one machine gate result.
# --------------------------------------------------------------------------
@dataclass
class GateResult:
    name: str
    rc: int            # 0 PASS / 1 FAIL / 2 ERROR / -1 SKIP(not-applicable)
    summary: str

    @property
    def green(self) -> bool:
        # rc 0 = pass; rc -1 = not applicable (counts as green / non-blocking).
        return self.rc in (0, -1)


@dataclass
class Verdict:
    verdict: str
    gates: List[GateResult] = field(default_factory=list)
    cadence: str = ""
    version_bump: str = ""
    blocking: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Git plumbing.
# --------------------------------------------------------------------------
def _git(repo: Path, *args: str) -> Tuple[int, str, str]:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def changed_files(repo: Path, base: str, head: str) -> List[str]:
    """`git diff --name-only base..head`. Honest error → RuntimeError."""
    rc, out, err = _git(repo, "diff", "--name-only", f"{base}..{head}")
    if rc != 0:
        raise RuntimeError(
            f"git diff --name-only {base}..{head} failed: "
            f"{err.strip() or 'non-zero exit'}")
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _git_show_json_version(repo: Path, ref: str, rel: str) -> Optional[str]:
    rc, out, _ = _git(repo, "show", f"{ref}:{rel}")
    if rc != 0:
        return None
    try:
        return json.loads(out).get("version")
    except Exception:
        return None


def commit_messages(repo: Path, base: str, head: str) -> List[str]:
    """Subject+body of every commit in base..head (the PR's commit command
    strings live there if they were recorded; used by git_prohibition_guard).
    Best-effort: empty list if the range cannot be walked."""
    rc, out, _ = _git(repo, "log", "--format=%B", f"{base}..{head}")
    if rc != 0:
        return []
    return [ln for ln in out.splitlines()]


# --------------------------------------------------------------------------
# Cadence derivation from the version bump (2026-06-17 policy).
# --------------------------------------------------------------------------
def derive_cadence(cur: Optional[str], prev: Optional[str]) -> Tuple[str, str]:
    """Return (cadence, version_bump_label).

    cadence ∈ {"FULL", "TARGETED", "NONE"}; FULL for an x.y.0 milestone,
    TARGETED for an x.y.Z patch (Z>0). NONE when there is no parseable bump
    (no version change in the diff)."""
    cur_t = _vbm.parse_semver(cur) if cur else None
    prev_t = _vbm.parse_semver(prev) if prev else None
    if cur_t is None:
        return "NONE", f"unparseable/none (current={cur!r})"
    label = f"{prev}->{cur}" if prev else f"-> {cur}"
    # An x.y.0 patch component is a MINOR/major milestone -> FULL suite.
    if cur_t[2] == 0:
        return "FULL", label
    return "TARGETED", label


# --------------------------------------------------------------------------
# Role / out-of-scope-by-role -> REJECT classification.
# Uses agent_checkin_scope_guard.evaluate(); a violation that lands in the MCP
# or plugin protected zone for a NON-core role is unsalvageable-by-patch and
# yields REJECT, distinct from a fixable gate red.
# --------------------------------------------------------------------------
_REJECT_ZONES = ("MCP (mcp-eda)", "plugin")


def role_scope_gate(role: Optional[str],
                    files: List[str]) -> Tuple[GateResult, bool]:
    """Return (gate_result, is_reject). When role is None we skip (the PR has
    no declared author role to enforce). A core-agent is unrestricted."""
    if role is None:
        return GateResult("agent_checkin_scope_guard", -1,
                          "skipped — no --role supplied"), False
    if role not in _acs.ROLE_ALLOW:
        return GateResult("agent_checkin_scope_guard", 2,
                          f"unknown role {role!r}"), False
    violations = _acs.evaluate(role, files)
    if not violations:
        return GateResult("agent_checkin_scope_guard", 0,
                          f"role '{role}' — all {len(files)} path(s) in scope"), False
    # Any violation landing in a REJECT zone is unsalvageable-by-patch. A NO-MIX
    # violation (a measure-and-author role bundling benchmark results WITH a
    # plugin/MCP edit — the anti-gaming vector) is likewise unsalvageable: it
    # cannot be patched, only SPLIT into a pure result commit + a pure plugin-fix
    # PR, so it is a REJECT too.
    reject = any(v["zone"] in _REJECT_ZONES or v["zone"].startswith("NO-MIX")
                 for v in violations)
    zones = sorted({v["zone"] for v in violations})
    paths = [v["path"] for v in violations]
    summary = (f"role '{role}' may NOT check in {len(violations)} path(s) "
               f"in zone(s) {zones}: {paths[:6]}"
               + (" …" if len(paths) > 6 else ""))
    return GateResult("agent_checkin_scope_guard", 1, summary), reject


# --------------------------------------------------------------------------
# Version bump + marketplace equality, via version_bump_monotonic_check.evaluate.
# --------------------------------------------------------------------------
# Paths whose contents are SHIPPED to users by `/plugin update` (or that declare
# the shipped version). A change confined outside these ships nothing, so demanding
# a version bump for it is meaningless.
_SHIPPED_PREFIXES = ("vibe-ic-marketplace/plugins/", "mcp/")
_MANIFEST_SUFFIX = ".claude-plugin/marketplace.json"


def ships_to_users(files: List[str]) -> bool:
    """True when the change-set touches anything `/plugin update` delivers."""
    return any(f.startswith(_SHIPPED_PREFIXES) or f.endswith(_MANIFEST_SUFFIX)
               for f in files)


def version_bump_gate(cur: Optional[str], prev: Optional[str],
                      market: Optional[str],
                      version_by_gatekeeper: bool = False,
                      files: Optional[List[str]] = None) -> GateResult:
    if cur is None and prev is None:
        return GateResult("version_bump_monotonic_check", -1,
                          "skipped — no version change in diff")
    # DATA-ONLY change-set (benchmark-data/, docs/, tools/, CI): ships nothing via
    # `/plugin update`, so a bump would only push a spurious cache invalidation to
    # every user for a change that cannot affect them — and main's own convention
    # lands these as unversioned `docs(benchmark-data): …` commits. Without this,
    # a benchmark-data-only PR could NEVER pass this gate, which pressures the
    # maintainer into either bypassing the gate or inflating the version. Both are
    # worse than scoping the rule to what it is actually about.
    if files is not None and not ships_to_users(files):
        return GateResult("version_bump_monotonic_check", -1,
                          "skipped — change-set ships nothing to users "
                          "(no plugin/ or mcp/ or manifest path); version bump N/A")
    # AUTHORING PR under the gatekeeper-assigns-versions doctrine (2026-06-17):
    # field/core PRs carry NO version bump (cur==prev) — two PRs in flight that
    # each self-bumped would COLLIDE; only the serialized gatekeeper, landing
    # PRs one at a time onto an advancing main, can assign a monotonic version.
    # DEFER the version gate here; the gatekeeper assigns the version at merge
    # (gatekeeper_assign_version.py) and RE-RUNS this review WITHOUT the flag on
    # the bumped tree, where the monotonic+equality check is fully ENFORCED.
    if version_by_gatekeeper and cur == prev:
        return GateResult("version_bump_monotonic_check", -1,
                          f"deferred — version assigned by gatekeeper at merge "
                          f"(authoring PR at {cur})")
    equality_checked = market is not None
    report, rc = _vbm.evaluate(cur, prev, market, equality_checked)
    return GateResult("version_bump_monotonic_check", rc, report.reason)


# --------------------------------------------------------------------------
# marketplace_version_sync_check — run as subprocess (it walks the tree).
# --------------------------------------------------------------------------
def marketplace_sync_gate(plugin_or_repo: Path) -> GateResult:
    prog = _PROGRAMS_DIR / "marketplace_version_sync_check.py"
    # The program walks UP from --marketplace-dir to find marketplace.json.
    rc, out, err = _run_program(prog, ["--marketplace-dir", str(plugin_or_repo)])
    summary = (out.strip().splitlines() or [err.strip()] or [""])[-1][:240]
    return GateResult("marketplace_version_sync_check", rc, summary or "(no output)")


# --------------------------------------------------------------------------
# source_chip_agnostic_check — subprocess against the plugin root.
# --------------------------------------------------------------------------
def chip_agnostic_gate(plugin_root: Path) -> GateResult:
    prog = _PROGRAMS_DIR / "source_chip_agnostic_check.py"
    rc, out, err = _run_program(prog, [str(plugin_root)])
    summary = (out.strip().splitlines() or [err.strip()] or [""])[0][:240]
    return GateResult("source_chip_agnostic_check", rc, summary or "(no output)")


# --------------------------------------------------------------------------
# shipped_path_portability_check — the PORTABILITY twin of the source guard.
# chip_agnostic_gate bans chip/vendor identity in shipped source; this bans
# MACHINE identity: a personal absolute home path where it could be used as a
# value. The defect it locks out shipped one developer's home directory as a
# runtime default, which (worst case) got mkdir-ed into existence and grew a
# phantom workspace directory on a clean install.
# --------------------------------------------------------------------------
def path_portability_gate(plugin_root: Path) -> GateResult:
    prog = _PROGRAMS_DIR / "shipped_path_portability_check.py"
    rc, out, err = _run_program(prog, [str(plugin_root)])
    summary = (out.strip().splitlines() or [err.strip()] or [""])[0][:240]
    return GateResult("shipped_path_portability_check", rc,
                      summary or "(no output)")


# --------------------------------------------------------------------------
# commit_msg_nda_check — the MESSAGE-side twin of the source guard.
#
# chip_agnostic_gate above scans FILES. A commit whose MESSAGE names the
# commercial foundry / SKU / process therefore passed every gate here — and one
# really did land on origin/main AFTER the full-history NDA rewrite. A commit
# message is a permanent, publicly mirrored artifact, so this scans the exact
# range being landed. Output is MASKED (role, not literal), so it is safe in a
# CI log or a PR comment.
# --------------------------------------------------------------------------
def commit_msg_nda_gate(repo: Path, base: str, head: str) -> GateResult:
    prog = _PROGRAMS_DIR / "commit_msg_nda_check.py"
    if not prog.is_file():
        return GateResult("commit_msg_nda_check", 2,
                          f"checker missing at {prog}")
    rc, out, err = _run_program(prog, ["--repo", str(repo),
                                       "--rev-range", f"{base}..{head}"])
    # rc 2 == the range could not be walked (synthetic refs in a unit test, a
    # shallow CI clone). That is NOT a leak finding, so it must not block —
    # but it IS reported as a skip so a silently-unwalked range is visible.
    if rc == 2:
        return GateResult("commit_msg_nda_check", -1,
                          f"skipped — range {base}..{head} not walkable")
    body = err.strip() or out.strip()
    summary = (body.splitlines() or [""])[0][:240]
    return GateResult("commit_msg_nda_check", rc, summary or "(no output)")


# --------------------------------------------------------------------------
# nda_diff_scan_check — the DIFF-CONTENT twin of the two guards above.
#
# chip_agnostic_gate scans the plugin SOURCE TREE only (nothing outside it);
# commit_msg_nda_gate scans MESSAGES only. Neither sees a leak that a PR ADDS
# in a repo-root config file, a doc, a template, or a fixture FILENAME. This
# scans the exact CONTENT the PR adds — every `+` line and every added/renamed
# path in base..head — anywhere in the repo. Output is MASKED (role, not
# literal), safe in a CI log or PR comment. (Closes the #247 gap: SKU + IP part
# in a test fixture's content AND filename passed every prior gate.)
# --------------------------------------------------------------------------
def nda_diff_scan_gate(repo: Path, base: str, head: str) -> GateResult:
    prog = _PROGRAMS_DIR / "nda_diff_scan_check.py"
    if not prog.is_file():
        return GateResult("nda_diff_scan_check", 2,
                          f"checker missing at {prog}")
    rc, out, err = _run_program(prog, ["--repo", str(repo),
                                       "--rev-range", f"{base}..{head}"])
    # rc 2 == the range could not be diffed (synthetic refs in a unit test, a
    # shallow CI clone). NOT a leak finding, so it must not block — but it is
    # reported as a skip so a silently-undiffed range is visible.
    if rc == 2:
        return GateResult("nda_diff_scan_check", -1,
                          f"skipped — range {base}..{head} not diffable")
    body = err.strip() or out.strip()
    summary = (body.splitlines() or [""])[0][:240]
    return GateResult("nda_diff_scan_check", rc, summary or "(no output)")


# --------------------------------------------------------------------------
# acceptance_control_check (#401) — ADVISORY.
#
# A fix's evidence must be measured against the state BEFORE the feature.
# Validating round N against round N-1 measures the branch against itself:
# measured on a real branch, 231 lines "recovered" four cases that the
# merge-base already had, and the same tests showed 11 of 20 failing against
# the predecessor while the corpus was byte-identical on 795 of 795 documents.
#
# The wrong control PROPAGATES: two rounds of adversarial verification both
# used the SHA the commit body named. Recomputing it from git does not inherit
# that. NEVER BLOCKING — a stacked-PR workflow can legitimately have a control
# not yet on the integration branch.
# --------------------------------------------------------------------------
def acceptance_control_gate(repo: Path, base: str, head: str) -> GateResult:
    prog = _PROGRAMS_DIR / "acceptance_control_check.py"
    if not prog.is_file():
        return GateResult("acceptance_control_check", -1,
                          f"checker missing at {prog}")
    rc, out, err = _run_program(prog, ["--repo", str(repo),
                                       "--base", base, "--head", head])
    if rc == 2:
        return GateResult("acceptance_control_check", -1,
                          f"skipped — merge-base({base}, {head}) unresolvable")
    body = (out.strip() or err.strip()).splitlines()
    bad = [ln for ln in body if "NOT valid" in ln]
    summary = (bad[0] if bad else (body[0] if body else "(no output)"))[:240]
    return GateResult("acceptance_control_check", 0, f"ADVISORY — {summary}")


# --------------------------------------------------------------------------
# real_artefact_test_backing_check (#400) — ADVISORY.
#
# A change whose tests are ALL synthetic fixtures authored alongside it cannot
# distinguish itself from its own absence. Measured on a real withdrawn
# branch: mutating the guard killed 10 of 31 tests — every one of them a
# hand-typed fixture from the same commits, while all 4 real-artefact tests
# still passed. This surfaces the split at review time instead of after a
# third adversarial round.
#
# NEVER BLOCKING (rc is forced to 0): the classifier is static, and a
# misclassification must cost one line of reading, not a rejected PR. It also
# cannot prove a real-artefact test is non-vacuous — only a mutation run can.
# --------------------------------------------------------------------------
def real_artefact_backing_gate(repo: Path, base: str, head: str) -> GateResult:
    prog = _PROGRAMS_DIR / "real_artefact_test_backing_check.py"
    if not prog.is_file():
        return GateResult("real_artefact_test_backing_check", -1,
                          f"checker missing at {prog}")
    rc, out, err = _run_program(prog, ["--repo", str(repo),
                                       "--base", base, "--head", head])
    if rc == 2:
        return GateResult("real_artefact_test_backing_check", -1,
                          "skipped — no test module added or modified")
    body = (out.strip() or err.strip()).splitlines()
    summary = (body[0] if body else "(no output)")[:240]
    return GateResult("real_artefact_test_backing_check", 0,
                      f"ADVISORY — {summary}")


# --------------------------------------------------------------------------
# gatekeeper_stale_branch_check — the LANDING-METHOD guard.
#
# A PR branch cut from an OLDER base than the current origin/main tip makes a
# naive `origin/main..HEAD` diff show a PHANTOM REVERT of every commit landed
# since the fork; a blind `git checkout HEAD -- <files>` land would silently
# revert that work. This flags the risk so the land is a CHERRY-PICK of the
# PR's own delta. rc 0 FRESH / stale-no-overlap; rc 1 stale WITH file overlap
# (the real phantom-revert surface); rc 2 unresolvable ref. Unlike the other
# gates this does not judge the CHANGE — only the safe way to LAND it.
#
# 2026-08-05 — its FRESH verdict now has to be EARNED. FRESH was decided by
# ANCESTRY alone and then asserted a property about CONTENT ("an ordinary
# squash-merge cannot phantom-revert anything"). A commit that named origin/main
# as its parent while carrying the PREVIOUS version's TREE satisfied the
# ancestry test exactly, and would have reverted 13 commits — 81 files, 9258
# deletions, 15 files removed, plugin.json walked back a version. This roster
# was green on it, because the two revert guards each disclaim that case IN
# WRITING and hand it to the other: the collateral check's window is "this push"
# (0 pairs on a one-commit branch) and this gate answered FRESH. Only a human
# read caught it. The gate now checks, inside the FRESH branch, that no path the
# head modifies holds a blob the base's own history has already superseded; that
# rc 1 blocks here exactly as STALE_OVERLAP does.
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# landing_is_one_commit_check — the OTHER landing-method guard.
#
# A landing is ONE commit. Three landings left TWO on main (vibe-ic#459): the
# authoring commit plus a version commit carrying only the manifests, because
# `git commit --amend` after a rebase touches only the top commit. Nothing
# failed and nothing warned, and GitHub runs CI on the LAST commit of a push,
# so the intermediate one has no CI record of its own.
#
# rc 0 one commit / rc 1 two or more, or zero (nothing landed). rc 2 means the
# range could not be counted, which is reported as a skip rather than a pass —
# an uncountable range has told us nothing.
#
# v1.7.64 — BATCH mode. The owner's standing directive is to land several PRs
# under ONE version bump and ONE CI run, and this review had no way to say so:
# every batch was blocked by a rule that does not apply to it, on a line whose
# own remedy text named a `--batch` flag the review could not forward. A
# reviewer who learns to read past one blocking line learns to read past
# blocking lines, so the flag is plumbed through instead.
#
# `--batch` does NOT relax the check. The underlying program's batch mode
# asserts a strictly stronger property than the single-landing rule: no
# manifest-only commit anywhere in the range, exactly one version bump, and it
# must be the tip — because CI runs on the pushed tip, so a version buried
# mid-batch would mean green CI referring to a tree nobody released. It stays
# OPT-IN: without the flag the single-landing rule is unchanged, so a real
# `commit --amend` slip still fails exactly as before.
# --------------------------------------------------------------------------
def one_commit_gate(repo: Path, base: str, head: str = "HEAD",
                    batch: bool = False) -> GateResult:
    prog = _PROGRAMS_DIR / "landing_is_one_commit_check.py"
    if not prog.is_file():
        return GateResult("landing_is_one_commit_check", 2,
                          f"checker missing at {prog}")
    argv = ([str(repo), "--base", base, "--head", head]
            + (["--batch"] if batch else []))
    rc, out, err = _run_program(prog, argv)
    detail = (err or out).strip().splitlines()
    reason = detail[-1] if detail else "no output"
    if rc == 2:
        return GateResult("landing_is_one_commit_check", -1,
                          f"skipped — range not countable: {reason}")
    return GateResult("landing_is_one_commit_check", rc, reason)


def stale_branch_gate(repo: Path, base: str, head: str) -> GateResult:
    prog = _PROGRAMS_DIR / "gatekeeper_stale_branch_check.py"
    if not prog.is_file():
        return GateResult("gatekeeper_stale_branch_check", 2,
                          f"checker missing at {prog}")
    rc, out, err = _run_program(prog, ["--repo", str(repo),
                                       "--base", base, "--head", head])
    # rc 2 == a ref could not be resolved (synthetic refs in a unit test, a
    # shallow CI clone). NOT a phantom-revert finding, so it must not block —
    # reported as a skip so a silently-unresolved range is visible.
    if rc == 2:
        return GateResult("gatekeeper_stale_branch_check", -1,
                          f"skipped — {base}/{head} not resolvable")
    body = err.strip() or out.strip()
    summary = (body.splitlines() or [""])[0][:240]
    return GateResult("gatekeeper_stale_branch_check", rc,
                      summary or "(no output)")


# --------------------------------------------------------------------------
# landing_collateral_revert_check — the landing-method guard AFTER the fact.
#
# `stale_branch_gate` above is a PRE-land guard: it reasons about a branch that
# has not been landed yet. It said rc 1 STALE_OVERLAP on all five PRs of the
# 2026-08-03 batch and named the exact overlap files, and the batch landed
# anyway with three of its eleven commits erasing the other two.
#
# It could not have said otherwise once the land had happened. Its verdict is
# `merge-base(base, head) == base tip -> FRESH`, and after a cherry-pick the
# landed commit IS a fast-forward descendant of the base, so FRESH is
# structurally guaranteed and says nothing about the content that now exists.
# This gate reads that content: it takes the same `base..head` the review is
# already scoped to and asks whether any commit in it erases an earlier one's
# contribution to a file. rc 2 (unresolvable or empty range) is NOT CHECKED,
# never a pass — same contract as every other range-shaped gate here.
# --------------------------------------------------------------------------
def collateral_revert_gate(repo: Path, base: str, head: str) -> GateResult:
    prog = _PROGRAMS_DIR / "landing_collateral_revert_check.py"
    if not prog.is_file():
        return GateResult("landing_collateral_revert_check", 2,
                          f"checker missing at {prog}")
    rc, out, err = _run_program(prog, ["--repo", str(repo),
                                       "--rev-range", f"{base}..{head}"])
    body = (err.strip() or out.strip()).splitlines()
    reason = body[-1] if body else "(no output)"
    if rc == 2:
        return GateResult("landing_collateral_revert_check", -1,
                          f"skipped — {base}..{head} not walkable: {reason[:160]}")
    return GateResult("landing_collateral_revert_check", rc, reason[:400])


# --------------------------------------------------------------------------
# loop_watchdog_compliance_check — subprocess against the plugin root. FAILs
# when any programs/*.py launches a long EDA tool without the watchdog or has
# an unbounded risky loop. rc 0 clean / 1 offender(s) / 2 usage error.
# --------------------------------------------------------------------------
def loop_watchdog_gate(plugin_root: Path) -> GateResult:
    prog = _PROGRAMS_DIR / "loop_watchdog_compliance_check.py"
    rc, out, err = _run_program(prog, [str(plugin_root)])
    if rc == 0:
        summary = (out.strip().splitlines() or [""])[0][:240]
    else:
        # the offender list is on stderr; surface the header + first offenders
        errlines = [ln for ln in err.splitlines() if ln.strip()
                    and "SyntaxWarning" not in ln and "invalid escape" not in ln]
        summary = " | ".join(errlines[:4])[:240]
    return GateResult("loop_watchdog_compliance_check", rc,
                      summary or "(no output)")


# --------------------------------------------------------------------------
# plugin_full_audit (D1 + D2) — subprocess against the plugin root.
# --------------------------------------------------------------------------
def plugin_audit_gate(plugin_root: Path) -> GateResult:
    prog = _PROGRAMS_DIR / "plugin_full_audit.py"
    rc, out, err = _run_program(prog, [str(plugin_root)])
    last = (out.strip().splitlines() or [err.strip()] or [""])[-1][:240]
    return GateResult("plugin_full_audit", rc, last or "(no output)")


# --------------------------------------------------------------------------
# git_prohibition_guard — scan the PR's commit command strings (import).
# --------------------------------------------------------------------------
def git_prohibition_gate(commit_cmds: List[str]) -> GateResult:
    if not commit_cmds:
        return GateResult("git_prohibition_guard", -1,
                          "skipped — no commit command strings supplied")
    rep = _gpg.scan_commands(commit_cmds)
    if rep.vacuous:
        return GateResult("git_prohibition_guard", -1,
                          "no command lines scanned (vacuous)")
    if rep.violations:
        descs = "; ".join(f"line {v.line_no} {v.rule_id}" for v in rep.violations)
        return GateResult("git_prohibition_guard", 1,
                          f"{len(rep.violations)} forbidden git op(s): {descs}")
    return GateResult("git_prohibition_guard", 0,
                      f"{rep.scanned} command(s) clean")


# --------------------------------------------------------------------------
# full_suite_run_check — validate the supplied --pytest-cmd against cadence.
# FULL milestone => full-suite invocation REQUIRED.
# TARGETED patch  => a (any) pytest invocation suffices; subset is fine.
# --------------------------------------------------------------------------
def test_cadence_gate(pytest_cmd: Optional[str], cadence: str) -> GateResult:
    if pytest_cmd is None:
        # No command to validate. We do not fabricate a PASS — but absence of a
        # supplied command is an honest SKIP (the caller may run tests out of
        # band); the loop's Step-2.7 still requires evidence. For a FULL
        # milestone we make this a hard FAIL because the policy demands proof.
        if cadence == "FULL":
            return GateResult("full_suite_run_check", 1,
                              "FULL milestone requires a full-suite pytest "
                              "command (none supplied via --pytest-cmd)")
        return GateResult("full_suite_run_check", -1,
                          f"skipped — no --pytest-cmd (cadence={cadence})")
    rep = _fsr_scan([pytest_cmd])
    if cadence == "FULL":
        if rep.full_suite_found:
            return GateResult("full_suite_run_check", 0,
                              "FULL cadence satisfied — full-suite invocation present")
        return GateResult("full_suite_run_check", 1,
                          "FULL cadence required but pytest cmd is a SUBSET "
                          "(integration/regression gates skipped)")
    # TARGETED / NONE: any real pytest invocation satisfies the regression gate.
    if rep.pytest_invocations >= 1:
        return GateResult("full_suite_run_check", 0,
                          f"TARGETED cadence satisfied — {rep.pytest_invocations} "
                          f"pytest invocation(s)")
    return GateResult("full_suite_run_check", 1,
                      "no pytest invocation found in --pytest-cmd")


_fsr = None


def _fsr_scan(cmds: List[str]):
    global _fsr
    if _fsr is None:
        _fsr = _load_module("full_suite_run_check")
    return _fsr.scan_commands(cmds)


# --------------------------------------------------------------------------
# blindness_audit — only when transcripts + dataset are supplied (subprocess).
# --------------------------------------------------------------------------
def blindness_gate(transcripts: Optional[str],
                   dataset: Optional[str]) -> GateResult:
    if not transcripts:
        return GateResult("blindness_audit", -1,
                          "skipped — no transcripts supplied")
    if not dataset:
        return GateResult("blindness_audit", 2,
                          "transcripts supplied but --dataset missing")
    prog = _PROGRAMS_DIR / "blindness_audit.py"
    rc, out, err = _run_program(prog, [transcripts, "--dataset", dataset])
    # blindness_audit rc: 0 clean / 1 violation / 2 nothing / 3 AUDIT_ERROR.
    # rc 2 (nothing to audit) and rc 3 (tool error) are NOT blindness FAILs —
    # map them to ERROR(2)/SKIP so a tool hiccup never blocks a clean PR.
    last = (out.strip().splitlines() or [err.strip()] or [""])[-1][:200]
    if rc == 0:
        return GateResult("blindness_audit", 0, last or "no blindness violation")
    if rc == 1:
        return GateResult("blindness_audit", 1, last or "blindness violation")
    if rc == 2:
        return GateResult("blindness_audit", -1, "nothing to audit")
    return GateResult("blindness_audit", 2, f"audit tool error: {last}")


# --------------------------------------------------------------------------
# control_substance_check — the PRE-FIX CONTROL, GRADED (vibe-ic#381).
#
# The standard control in this repo is "copy the change's new test file onto
# clean main, run it, show it FAILS", and it is reported in a PR body as "the
# tests fail pre-fix". Measured on two live PRs, that sentence covered a run
# that collected NOTHING (551 lines of new test, one ModuleNotFoundError, zero
# assertions executed — true of every new file ever written) and a run whose
# 4-of-4 "behavioural" failures were 3-of-4 absence of a field the fix adds.
# `control_substance_check` reads the control's own pytest report and counts
# how many failures actually observed a VALUE.
#
# It shipped with nothing but its own unit test running it, which is the exact
# shape it exists to name — a fixture proving the logic, never the artefacts —
# and it is composed here because this program is the only place in the repo
# that judges a base..head CHANGE rather than the tree.
#
# THE POLICY, stated rather than buried, and it follows `ci_ran_at_all_check`
# twenty lines down:
#   * evidence supplied + tautological  -> rc 1, BLOCKING. This is the gate.
#   * evidence supplied + substantive   -> rc 0 with the count.
#   * NO evidence + the diff changes test files -> rc -1, a LOUD non-blocking
#     disclosure naming the count of test files whose control was not graded.
#     Blocking here would refuse every landing from day one over evidence the
#     workflow does not yet produce, and a gate that must be bypassed to work
#     is a gate that gets bypassed for real reasons too.
#   * NO evidence + no test file changed -> rc -1, not applicable.
# The disclosure is never silent: the summary reaches the review record either
# way, which is the difference between a decision and an oversight.
# --------------------------------------------------------------------------
def control_substance_gate(control_junit: Optional[str],
                           control_text: Optional[str],
                           files: List[str]) -> GateResult:
    prog = _PROGRAMS_DIR / "control_substance_check.py"
    if not prog.is_file():
        return GateResult("control_substance_check", -1, "checker not present")
    changed_tests = [f for f in files
                     if f.endswith(".py") and ("/tests/" in f
                                               or "/test_" in f)]
    if not control_junit and not control_text:
        if changed_tests:
            return GateResult(
                "control_substance_check", -1,
                f"NO CONTROL EVIDENCE SUPPLIED and the diff changes "
                f"{len(changed_tests)} test file(s) — nothing graded whether "
                f"the pre-fix control observed a value or only noticed an "
                f"absence. Re-run with --control-junit <the control run's "
                f"pytest --junitxml>")
        return GateResult("control_substance_check", -1,
                          "not applicable — the diff changes 0 test file(s) "
                          "and no control evidence was supplied")
    argv: List[str] = []
    if control_junit:
        argv += ["--junit", control_junit]
    if control_text:
        argv += ["--text", control_text]
    rc, out, err = _run_program(prog, argv)
    blob = ((out or "") + (err or "")).strip()
    first = (blob.splitlines() or [""])[0][:240]
    if rc == 0:
        return GateResult("control_substance_check", 0,
                          first or "the control observed a value")
    if rc == 1:
        return GateResult("control_substance_check", 1,
                          f"TAUTOLOGICAL CONTROL — {first}")
    return GateResult("control_substance_check", 2,
                      f"control evidence could not be read: {first}")


# --------------------------------------------------------------------------
# run_output_completeness — a benchmark/IC run under review whose RESULT.md is
# EMPTY / MISSING / STUB must NOT land (v1.3.51). When the PR's change-set adds
# or edits a run deliverable (a RESULT.md), self-check that run_dir's deliverable
# is genuinely complete. A legitimately in-progress run (live process/lock) is
# NON-blocking (distinct RUN_STILL_IN_PROGRESS state) so this never false-flags a
# run that simply hasn't reached its write step. Imports the pure classifier —
# no re-implementation.
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# ci_ran_at_all_check — #550. Nothing in this roster asked whether the CI that
# was supposed to run the tests EXISTS. Actions was disabled account-wide and
# 561 commits landed with none, while every question about CI came back clean:
# an empty run listing reads identically to "nothing new since the last green".
#
# POLICY, and it is a choice worth stating rather than burying. NEVER_RAN is
# rc 1 from the checker, but this gate DOWNGRADES it to a loud non-blocking
# disclosure for ordinary landings and keeps it BLOCKING for a milestone
# (x.y.0). Reasons, in order:
#   * a hard refusal everywhere makes the local-only workflow — which is the
#     situation this repo is in RIGHT NOW, and legitimately so while the
#     account is blocked — impossible, and a gate people must bypass to work
#     is a gate that gets bypassed for real reasons too;
#   * a milestone is the one landing that must not rest on one machine's word.
# The disclosure is never silent in either case: the summary says NO CI RUN in
# both, so `git log` and the review record carry it.
# --------------------------------------------------------------------------
def ci_ran_gate(repo: Path, head: str, cadence: str) -> GateResult:
    prog = _PROGRAMS_DIR / "ci_ran_at_all_check.py"
    if not prog.is_file():
        return GateResult("ci_ran_at_all_check", -1, "checker not present")
    rc, out, err = _run_program(prog, [str(repo), "--rev", head,
                                       "--min-total", "50"])
    summary = ((out + err).strip().splitlines() or [""])[0][:240]
    if rc == 1 and "NO CI RUN EXISTS" in (out + err):
        # vibe-ic#570 — the MILESTONE BLOCK is retired; the disclosure is not.
        #
        # It used to block at FULL cadence, reasoning that "a milestone is the one
        # landing that must not rest on one machine's word". That reasoning is
        # still right. What changed is that the evidence it named is evidence we
        # have decided not to produce — owner directive 2026-08-01: GitHub is repo
        # storage only, CI is ours. The clause therefore blocked every future
        # x.y.0 on a run that is never coming, and a gate that must be bypassed to
        # work is a gate that gets bypassed for real reasons too.
        #
        # WHY NOT simply re-point it at our own gate. `gatekeeper-land.sh` DOES
        # write a per-SHA record — `.git/gatekeeper-stamp`, enforced by the
        # pre-push hook, invalidated by an amend, so it is neither forgeable by
        # accident nor reusable. But it lives in `.git/`, which is not
        # version-controlled and does not travel with a push: it IS one machine's
        # word. Pointing the milestone clause at it would turn every milestone
        # green while satisfying none of the clause's stated reason — the #550
        # shape again, our own empty record standing in for GitHub's empty
        # listing. A gate asserting a property it no longer checks is worse than
        # one that admits the property is unmet.
        #
        # So: disclose at EVERY cadence, block at none, and name the unmet
        # property in the milestone summary so it reaches the review record. When
        # a durable, shareable record exists the block can return and point at
        # something that means what it says.
        #
        # UNCHANGED: a CI run that EXISTS and FAILED still blocks everywhere — rc
        # 1 without NO CI RUN EXISTS falls through to the return at the bottom.
        # This downgrade is scoped to NEVER_RAN, which is the whole point.
        scope = ("patch landing" if cadence != "FULL"
                 else "MILESTONE — independent-evidence property NOT met (#570)")
        return GateResult("ci_ran_at_all_check", -1,
                          f"DISCLOSED (non-blocking for a {scope}): " + summary)
    if rc == 2:
        # NOT CHECKED must not BLOCK. rc 2 is non-blocking everywhere else in
        # this repo (`run_tolerating_uncheckable` in _gate_dispatch.sh), but
        # `GateResult.green` counts only 0 and -1, so returning 2 here would
        # refuse a merge for an offline maintainer, a rate limit, or a review
        # run over a directory that is not a git repo — which is how the
        # existing gatekeeper_review tests drive this function, and they caught
        # it. Mapped to -1 with the reason kept IN THE TEXT: a reader still sees
        # "could not look", which is the whole point of the state.
        return GateResult("ci_ran_at_all_check", -1,
                          "NOT CHECKED (non-blocking): " + summary)
    return GateResult("ci_ran_at_all_check", rc, summary or "(no output)")


def run_deliverable_gate(repo: Path, files: List[str]) -> GateResult:
    results = [f for f in files if Path(f).name == "RESULT.md"]
    if not results:
        return GateResult("run_output_completeness_check", -1,
                          "skipped — no run deliverable (RESULT.md) in change-set")
    checked = 0
    failures: List[str] = []
    in_progress = 0
    for rel in results:
        run_dir = (repo / rel).parent
        if not run_dir.is_dir():
            continue          # deleted in the PR — nothing to judge
        checked += 1
        rep = _roc.check(run_dir)
        if rep.verdict == "FAIL":
            failures.append(f"{rel}: {rep.state}")
        elif rep.verdict == "IN_PROGRESS":
            in_progress += 1
    if checked == 0:
        return GateResult("run_output_completeness_check", -1,
                          "skipped — RESULT.md path(s) not present on disk")
    if failures:
        return GateResult("run_output_completeness_check", 1,
                          f"{len(failures)} empty/missing/stub deliverable(s): "
                          + "; ".join(failures[:6])
                          + (" …" if len(failures) > 6 else ""))
    note = f"{checked} run deliverable(s) complete"
    if in_progress:
        note += f" ({in_progress} in-progress — non-blocking)"
    return GateResult("run_output_completeness_check", 0, note)


# --------------------------------------------------------------------------
# repo_hygiene_gates — the CI hygiene set, INVOKED rather than re-listed (#538).
#
# WHAT WAS WRONG
# --------------
# This program is what a maintainer runs before every push, and MERGE_OK reads
# as "this will land green". Measured at v1.7.92: `tools/ci/repo_hygiene_gates.sh`
# wired 34 gate invocations, this review ran 17 of its own, and the two sets
# OVERLAPPED IN FIVE — so MERGE_OK was answered without consulting 29 of the
# checks CI would go on to run. Twice in one day the verdict was wrong:
#
#   v1.7.89  MERGE_OK, then main went RED on `published_record_staleness_check`.
#   v1.7.92  MERGE_OK while INDEX.md was stale; refused only because the
#            maintainer had by then taken to running the script BY HAND.
#
# One of the two was caught by a habit rather than by the tool, and that habit
# appears in no skill, runbook or agent file — `grep -rn repo_hygiene skills/
# docs/` was empty. A gate that depends on remembering is the thing this gate
# exists to replace.
#
# WHY IT INVOKES THE SCRIPT INSTEAD OF DERIVING THE GATE LIST
# ----------------------------------------------------------
# Two alternatives were rejected on evidence, not taste:
#
#   * RE-LISTING the gate names here. A second hand-maintained list of 34 names
#     is the exact drift shape #527, #530 and #534 each spent a version
#     removing, and a drifted copy would restore the hole while looking fixed.
#
#   * PARSING the script for its program names and running `prog .`. The script
#     is not a list of names: it passes `--recent 60`, `--corpus <path>`,
#     `--check`, `--require-remote`, `audit-corpus --root`, `"$PLUGIN"`; it runs
#     eight gates from the PLUGIN directory and the rest from the repo root; and
#     its two wrappers interpret exit codes DIFFERENTLY (`run_tolerating_
#     uncheckable` treats rc 2 as "could not check", `run` as a defect). A
#     bare-name reproduction loses every one of those, and it would lose them
#     SILENTLY and in the lenient direction. Six of the 34 do not even end in
#     `_check`/`_audit` — including the two INDEX.md freshness gates, one of
#     which is the v1.7.92 incident — so a filename-shaped derivation also
#     under-counts the population it is meant to cover.
#
#   * A THIRD FORM, a shared machine-readable gate table both files read, was
#     rejected because the argument setup and the rc interpretation still have
#     to live somewhere, so they would be encoded twice — and the script's ~150
#     lines of per-gate WHY comments, which are the record of what each gate
#     cost to learn, have nowhere to go in a data file.
#
# Invoking the script keeps ONE definition, and it is the one that actually
# runs in CI. A gate added to CI is covered here the moment it is added, with
# no edit to this file.
#
# HOW IT REPORTS
# --------------
# `--summary-json` is produced BY THE SCRIPT, at the single place each gate is
# declared, and carries the DENOMINATOR (`declared`) alongside what happened to
# each gate. Reconstructing that caller-side would be the second list again.
# The verdict line always states declared/ran/not-checked, so "all gates
# passed" can never be read over a set that silently shrank — and NOT_CHECKED
# (a gate that refused, e.g. host-independence on a dirty tree) is reported
# separately from PASS, never folded into it, which is the `_vacuous_exit`
# convention applied one level up.
# --------------------------------------------------------------------------
_HYGIENE_SCRIPT_REL = "tools/ci/repo_hygiene_gates.sh"
_HYGIENE_PARALLEL_REL = (
    "vibe-ic-marketplace/plugins/vibe-ic/programs/repo_hygiene_parallel.py")

#: No runtime estimate.  This is the maximum interval with neither captured
#: output nor a completed gate record before the shared progress watchdog calls
#: the coordinator stalled.  Any forward progress resets it, however long the
#: complete hygiene run legitimately needs.
_HYGIENE_STALL_GRACE_S = 1800


# --------------------------------------------------------------------------
# THE PUBLISHED CORPUS IS AN INPUT TO THIS GATE, SO THIS GATE RESOLVES IT.
#
# WHAT WAS WRONG
# --------------
# v1.10.56 moved the published cells into their own repository
# (https://github.com/vibeic/benchmark-data.git).  `tools/ci/routed_def_corpus.py`
# enumerates the corpus "published cells carrying a routed DEF" from the tree
# `$VIBE_IC_BENCHMARK_DATA` names, and `repo_hygiene_gates.sh:591` wires that
# producer with `GATE_DISPATCH_ATTEST_POPULATION=1`, so a population of zero is
# a BLOCKING dispatcher-owned refusal (`_gate_dispatch.sh:1270`) that cannot be
# excused (`_dispatch` mode 2, ll. 637-641/667-670).  That refusal is CORRECT.
#
# What was wrong is that this program — the one a maintainer runs before every
# push — never resolved the corpus at all.  It inherited whatever the operator
# happened to have exported, so on an ordinary checkout the set spent four
# minutes and then certified nothing, and no line in the run named the cause or
# the remedy.
#
# MEASURED (2026-08-20, clean origin/main 3199e9b3, this host):
#     pointer UNSET -> 75 of 80 decided, 71 passed, 4 failed, 5 NOT CHECKED,
#                      the routed-DEF corpus EMPTY and BLOCKING, 239s wasted.
#     pointer SET   -> 77 of 83 decided, 73 passed, 4 failed, 6 NOT CHECKED, 241s,
#                      and `published-evidence index honest` FAILS — a real,
#                      committed-INDEX-is-stale defect the empty corpus hid
#                      outright.
#
# WHY RESOLVE-AND-REFUSE AND NOT "LET AN EMPTY CORPUS BE A STATED NOT_CHECKED"
# ---------------------------------------------------------------------------
# The second option is one line and it is the wrong line, on this repository's
# own recorded evidence:
#
#   * `_corpus_location.py:41-46,63-66` — "nothing anywhere + the CALL SITE
#     opted in -> NO_CORPUS (rc 0) ... an rc 0 for a scan that did not happen is
#     the false certificate this whole gate suite exists to remove, and the only
#     thing keeping it from becoming the general answer is that somebody has to
#     type it."
#   * `_gate_dispatch.sh:637-641` — mode 2 is private precisely so an empty
#     population "must never acquire the non-fatal tolerance that a human may
#     buy with `uncheckable_until`"; ll. 667-670 make attaching one a WIRING
#     ERROR.  Softening the empty corpus means deleting a guard whose comment
#     records the measured reason it exists.
#   * `repo_hygiene_gates.sh:539-547` — the last time this exact corpus read as
#     CHECKED while nothing in it was opened (the `$ROOT/$ABSOLUTE` prefix bug),
#     four gates were absorbed under exemptions whose stated reasons were FALSE.
#     The comment ends: "the empty-population refusal above cannot see this,
#     because the population is 1, not 0."  At 0 the blocking refusal is the
#     only thing left that can notice.
#   * The LANDING arm already resolves it and already dies loudly when it
#     cannot (`tools/gatekeeper-verify-merge.sh:617-640`).  A review that is
#     PERMISSIVE where landing is STRICT is the "MERGE_OK, then main went RED"
#     shape this whole gate was written to end (see the block at line 928).
#
# So the corpus is resolved HERE, with the SAME precedence the landing arm uses
# — one order, not two — and a corpus that cannot be resolved is rc 2 with the
# cause and the remedy named, BEFORE the four-minute set is spent.
#
# WHY THE BOUND SHA IS EXPORTED TOO
# ---------------------------------
# `_corpus_location.resolve()` prefers a NAMED root over the pointer, and some
# gates compute that named root by walking `Path(__file__).parents` (e.g.
# `l_doc_field_producer_check.py:299-302`), which climbs out of the repository.
# MEASURED on this host: those gates adopted `$HOME/benchmark-data` and printed
# "VIBE_IC_BENCHMARK_DATA=… is set and NOT followed".  A pointer that can be
# shadowed by whatever happens to sit above the checkout is not a binding.
# `GATEKEEPER_BENCHMARK_DATA_SHA` is the mechanism this repo already built for
# exactly that (`_corpus_location.py:137-156`): with it set, the pointer wins
# unconditionally and every candidate-local shadow is refused.  It also reaches
# the record as `corpus_inputs.benchmark_data_sha`, which the landing arm's
# `hygiene_record_binds_benchmark()` already validates.
#
# WHAT THIS DELIBERATELY DOES NOT DO
# ----------------------------------
# It does not fetch and it does not judge CURRENCY.  Binding the checkout's HEAD
# says WHICH tree was scanned, which is the property a review needs; proving the
# tree equals the canonical `origin/main` is the landing arm's job and it owns a
# whole program for it (`tools/ci/benchmark_data_landing_checkout.py measure`).
# A review gate that reached the network would be a review gate that fails when
# the network does.
# --------------------------------------------------------------------------
_CORPUS_ENV = "VIBE_IC_BENCHMARK_DATA"
_CORPUS_CHECKOUT_ENV = "VIBEIC_BENCHMARK_DATA_CHECKOUT"
_CORPUS_BOUND_SHA_ENV = "GATEKEEPER_BENCHMARK_DATA_SHA"
_CORPUS_DEFAULT_DIRNAME = "_matrix_benchmark_data"
_CORPUS_SUBDIR = "ic"
_CORPUS_ORIGIN = "https://github.com/vibeic/benchmark-data.git"
_OID_CHARS = set("0123456789abcdef")


def _corpus_remedy() -> str:
    return (f"Remedy: clone the published corpus and name it — "
            f"`git clone {_CORPUS_ORIGIN} ~/{_CORPUS_DEFAULT_DIRNAME}`, or "
            f"export {_CORPUS_ENV}=<path to that clone>.")


def _published_corpus_binding() -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """`(env additions, refusal)` for the published-corpus checkout.

    Exactly one of the two is None.  The refusal is a complete sentence naming
    the slot that supplied the path, what was wrong with it, and the remedy —
    it is the whole verdict a reader gets, so it may not be a bare word.
    """
    slots = (
        (_CORPUS_ENV, os.environ.get(_CORPUS_ENV) or None),
        (_CORPUS_CHECKOUT_ENV, os.environ.get(_CORPUS_CHECKOUT_ENV) or None),
    )
    named: Optional[Path] = None
    slot = ""
    for key, value in slots:
        if value:
            named, slot = Path(value), key
            break
    if named is None:
        home = os.environ.get("HOME") or ""
        if not home:
            return None, (f"ERROR — the published corpus could not be located: "
                          f"neither {_CORPUS_ENV} nor {_CORPUS_CHECKOUT_ENV} is "
                          f"set and HOME is unset, so there is no default "
                          f"checkout to fall back on. NOTHING WAS SCANNED and "
                          f"the hygiene set was NOT run. " + _corpus_remedy())
        named = Path(home) / _CORPUS_DEFAULT_DIRNAME
        slot = ""

    if not named.is_dir():
        # SET AND WRONG IS NOT ABSENT (`_corpus_location.py:26-29`), and NOTHING
        # ANYWHERE is not a pass either. The two are different states with
        # different remedies, so they get different sentences; neither is rc 0.
        if slot:
            return None, (f"ERROR — the published corpus at {named} (from "
                          f"{slot}) is not a readable directory, so the "
                          f"per-cell gates had nothing to examine. A pointer "
                          f"that is set and wrong is a broken configuration, "
                          f"not an absent corpus. NOTHING WAS SCANNED and the "
                          f"hygiene set was NOT run. " + _corpus_remedy())
        return None, (f"ERROR — no published-corpus checkout: {_CORPUS_ENV} and "
                      f"{_CORPUS_CHECKOUT_ENV} are both unset and the default "
                      f"{named} does not exist. The published cells moved to "
                      f"their own repository in v1.10.56, so this tree carries "
                      f"none and the per-cell gates would examine 0 of them. "
                      f"NOTHING WAS SCANNED and the hygiene set was NOT run. "
                      + _corpus_remedy())

    resolved = named.resolve()
    # The producer reads git's INDEX (`tools/ci/routed_def_corpus.py:42-83`), so
    # a loose directory enumerates zero cells and that zero is "I could not
    # look", not "there are none" — the one substitution this whole module
    # exists to refuse.
    top = _git_text(resolved, ["rev-parse", "--show-toplevel"])
    if top is None or Path(top).resolve() != resolved:
        return None, (f"ERROR — the published corpus at {resolved} (from {slot}) "
                      f"is not the ROOT of a git checkout"
                      + (f" (git reports its root as {top})" if top else "")
                      + f". The corpus producer reads git's INDEX; over a "
                      f"tarball fetch, an archive export or a dead clone it "
                      f"would enumerate zero cells and that is 'I could not "
                      f"look', not 'there are none'. NOTHING WAS SCANNED and "
                      f"the hygiene set was NOT run. " + _corpus_remedy())

    if not (resolved / _CORPUS_SUBDIR).is_dir():
        return None, (f"ERROR — the published corpus at {resolved} (from {slot}) "
                      f"is a git checkout but carries no {_CORPUS_SUBDIR}/ "
                      f"directory, so it is not the published-cell repository "
                      f"this gate needs. NOTHING WAS SCANNED and the hygiene "
                      f"set was NOT run. " + _corpus_remedy())

    sha = _git_text(resolved, ["rev-parse", "HEAD"])
    if (sha is None or len(sha) not in (40, 64)
            or any(ch not in _OID_CHARS for ch in sha)):
        return None, (f"ERROR — the published corpus at {resolved} (from {slot}) "
                      f"has no readable HEAD commit, so the verdicts could not "
                      f"be bound to the tree that produced them. NOTHING WAS "
                      f"SCANNED and the hygiene set was NOT run. "
                      + _corpus_remedy())

    return {_CORPUS_ENV: str(resolved), _CORPUS_BOUND_SHA_ENV: sha}, None


def _git_text(cwd: Path, argv: List[str]) -> Optional[str]:
    """One line of git output, or None when git could not answer."""
    try:
        proc = subprocess.run(["git", "-C", str(cwd), *argv],
                              capture_output=True, text=True)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    return out or None


def repo_hygiene_gate(repo: Path,
                      script: Optional[Path] = None,
                      stall_grace: int = _HYGIENE_STALL_GRACE_S,
                      summary_out: Optional[Path] = None,
                      progress_out: Optional[Path] = None) -> GateResult:
    """Run `tools/ci/repo_hygiene_gates.sh` and report its own coverage record.

    `script` is a test seam in the same spirit as `override_files` — it lets a
    unit test point at a cheap fixture script instead of the real multi-minute
    set. There is deliberately NO CLI flag for it: a command-line way to skip
    the hygiene set would be a skip button on the gate whose whole purpose is
    that it cannot be forgotten.
    """
    name = "repo_hygiene_gates"
    if script is not None:
        path = Path(script)
        command = ["bash", str(path)]
    else:
        parallel = repo / _HYGIENE_PARALLEL_REL
        path = parallel if parallel.is_file() else (repo / _HYGIENE_SCRIPT_REL)
        command = ([sys.executable, str(path)] if path == parallel
                   else ["bash", str(path)])
    if not path.is_file():
        # An honest SKIP that states its denominator: this tree wires no
        # hygiene set, so 0 gates were consulted. Never dressed up as a pass
        # over gates that do not exist.
        return GateResult(name, -1,
                          f"skipped — 0 gate(s) consulted: {_HYGIENE_SCRIPT_REL} "
                          f"not present under {repo}")

    # BEFORE the four-minute set, not after it. A corpus that cannot be
    # resolved makes every per-cell verdict impossible, so spending the set to
    # discover that costs four minutes and reports the consequence instead of
    # the cause. `script is not None` is the unit-test seam (see the docstring):
    # a fixture script wires no corpus and must not be made to need one.
    corpus_env: Dict[str, str] = {}
    if script is None:
        corpus_env_or_none, corpus_refusal = _published_corpus_binding()
        if corpus_refusal is not None:
            return GateResult(name, 2, corpus_refusal)
        corpus_env = corpus_env_or_none or {}

    with tempfile.TemporaryDirectory(prefix="hygiene_summary_") as td:
        summary_path = Path(td) / "summary.json"
        progress = None
        try:
            env = os.environ.copy()
            env.update(corpus_env)
            if progress_out is not None:
                progress = Path(progress_out).resolve()
                progress.parent.mkdir(parents=True, exist_ok=True)
                try:
                    progress.unlink()
                except FileNotFoundError:
                    pass
                env["GATE_DISPATCH_ATTESTATION_FILE"] = str(progress)
            def _popen(argv, **kwargs):
                return subprocess.Popen(
                    argv, cwd=str(repo), start_new_session=True, **kwargs)

            def _kill_group(proc, _reason):
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    return
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                # The coordinator may exit on TERM while one of its workers
                # ignores it.  Kill the remaining process group either way.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

            supervised = _wd.run_supervised(
                [*command, "--summary-json", str(summary_path)],
                env=env, log_path=progress,
                stall_grace_s=stall_grace, poll_s=5,
                hard_ceiling_s=float("inf"), popen_factory=_popen,
                kill=_kill_group)
        except OSError as exc:
            return GateResult(name, 2, f"ERROR — could not run {path}: {exc}")

        if supervised.outcome != "natural":
            return GateResult(
                name, 2,
                "ERROR — hygiene progress watchdog reported "
                f"{supervised.outcome} after no output or completed-gate "
                f"record advanced for {stall_grace}s; nothing was concluded")

        if not summary_path.is_file():
            # The script ran but produced no record, so we cannot say what it
            # covered. "I do not know what ran" is its own state and must not
            # reach a reader as a pass.
            tail = ((supervised.err or supervised.out or "").strip().splitlines()
                    or ["(no output)"])[-1][:180]
            return GateResult(name, 2,
                              f"ERROR — {_HYGIENE_SCRIPT_REL} exited "
                              f"{supervised.rc} without writing its coverage "
                              f"record; coverage unknown. Last line: {tail}")
        try:
            doc = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return GateResult(name, 2,
                              f"ERROR — unreadable coverage record: {exc}")

        # vibe-ic#1025 — hand the record on to a caller that has a second
        # question about it. Before this, the ONLY production copy of the
        # dispatcher's record was this temp file, destroyed on the next line,
        # so no consumer could ask anything a single run cannot answer — which
        # is why `a permanently red gate is a gate that gets skipped` had no
        # machinery under it. Copied rather than relocated: the temp dir stays
        # the owner, so a caller that passes nothing is byte-for-byte
        # unaffected.
        if summary_out is not None:
            try:
                summary_out.write_text(json.dumps(doc, indent=2,
                                                  ensure_ascii=False) + "\n",
                                       encoding="utf-8")
            except OSError as exc:
                return GateResult(name, 2,
                                  f"ERROR — could not hand on the coverage "
                                  f"record: {exc}")

    return _hygiene_verdict(doc, supervised.rc)


def gate_red_since_gate(repo: Path, record: Path) -> GateResult:
    """Adjudicate this run's reds against the acknowledgement ledger (#1025).

    A SEPARATE gate rather than a clause folded into `repo_hygiene_gates`,
    because the two answer different questions and a reader has to be able to
    tell them apart: the hygiene gate says WHICH gates are red, this one says
    which of those reds is NEW and which acknowledgement has run out of time.
    Folding them would report an expired deadline under the headline
    "repo_hygiene_gates FAILED", pointing the reader at the gate rather than at
    the row that came due.

    It is also deliberately NOT wired into `_gate_dispatch.sh`. The dispatcher's
    rc is pinned by vibe-ic#1025's own guard (`run` blocks on rc 2,
    `run_tolerating_uncheckable` does not), and a ledger that could move that rc
    would be a ledger that can buy a green.
    """
    name = "gate_red_since"
    prog = Path(__file__).resolve().parent / "gate_red_since_check.py"
    if not prog.is_file():                      # pragma: no cover - packaging
        return GateResult(name, -1, "skipped — checker not present")
    if not record.is_file():
        # The hygiene gate errored before writing a record. It has already
        # reported that; saying "no red is overdue" over a record that does not
        # exist would be this program committing the defect it audits for.
        return GateResult(name, -1,
                          "skipped — 0 gate state(s) examined: the hygiene set "
                          "produced no record to adjudicate")
    rc, out, err = _run_program(prog, ["--record", str(record),
                                       "--repo", str(repo)])
    line = (out.strip().splitlines() or [""])[-1]
    if rc == 2:
        return GateResult(name, -1, f"skipped — {line}")
    return GateResult(name, rc, line or (err.strip()[:200] or "no output"))


def _declared_labels(repo: Path, script: Optional[Path] = None) -> Optional[list]:
    """The labels THIS tree declares, from a `--list` run. 0.12 s, measured."""
    path = Path(script) if script is not None else (repo / _HYGIENE_SCRIPT_REL)
    if not path.is_file():
        return None
    with tempfile.TemporaryDirectory(prefix="hygiene_list_") as td:
        out = Path(td) / "list.json"
        try:
            subprocess.run(["bash", str(path), "--list",
                            "--summary-json", str(out)],
                           cwd=str(repo), capture_output=True, timeout=120)
            doc = json.loads(out.read_text(encoding="utf-8"))
        except Exception:
            return None
    return [str(g.get("label")) for g in (doc.get("gates") or [])]


def hygiene_gate_from_record(repo: Path, record: Path,
                             record_rc: Optional[int],
                             script: Optional[Path] = None) -> GateResult:
    """Adjudicate a hygiene record the CALLER already produced.

    WHY THIS IS NOT THE SKIP BUTTON `repo_hygiene_gate` REFUSES TO GROW.
    That function's docstring says there is deliberately no CLI flag for
    `script`, because a command-line way to point the gate at a cheap fixture
    would be a skip button on the gate whose whole purpose is that it cannot be
    forgotten. That reasoning is right and it is why this is a different thing:
    `--hygiene-script` substitutes a CHEAPER SUBJECT, while this substitutes
    the RUNNER of the same subject. The set still runs, in full, over this
    tree — it runs in the lander's own hygiene lane, which refuses the landing
    on its own account, and this reads that run's record instead of paying for
    a second one.

    MEASURED, which is why it exists: the owner's ruling gives a landing four
    minutes for this review. With the published corpus bound the review's own
    hygiene run exceeds that on its own, so wiring the program as-is would make
    every landing time out — the check would be unavoidable and would never
    once decide, which is the opposite of the ruling's intent. With the corpus
    UNBOUND it takes 45 s, because the hygiene gate refuses early and
    `gate_red_since` then reports `skipped — 0 gate state(s) examined`. Both
    ends of that range are a deadline that never adjudicates.

    THE RECORD IS CHECKED, NOT TRUSTED. A caller could hand over anything, so:
    the record must exist and parse; it must carry the exit status of the run
    that produced it, supplied separately by the caller that watched it; and
    the gates it names must be exactly the set this tree declares, obtained
    from a `--list` run costing 0.12 s. A record forged to be green must
    therefore also be forged to name all 85 declared labels, which is no longer
    "a flag that skips the gate" but a fabricated measurement — a different act
    with a different name, and one the landing record and this gate's own
    output both preserve the evidence of.

    Every failure to establish those is rc 2 UNDETERMINED and BLOCKING. Never
    rc 0: "I could not check the record" must not reach a verdict as "the
    record was clean", which is this repo's `_vacuous_exit` convention applied
    to the handover itself.
    """
    name = "repo_hygiene_gates"
    record = Path(record)
    if not record.is_file():
        return GateResult(name, 2,
                          f"UNDETERMINED — no hygiene record at {record}: the "
                          f"caller named a record it did not produce, so 0 "
                          f"gate state(s) could be adjudicated")
    try:
        doc = json.loads(record.read_text(encoding="utf-8"))
    except Exception as exc:
        return GateResult(name, 2,
                          f"UNDETERMINED — the hygiene record at {record} does "
                          f"not parse: {exc}")
    if record_rc is None:
        return GateResult(name, 2,
                          "UNDETERMINED — a hygiene record was supplied with no "
                          "exit status. The record says WHICH gates were red; "
                          "only the run's rc says whether the set completed, "
                          "and a killed run leaves a record that looks finished")
    declared = _declared_labels(repo, script)
    if declared is None:
        return GateResult(name, 2,
                          "UNDETERMINED — could not ask this tree which gates it "
                          "declares, so a supplied record cannot be checked "
                          "against it")
    named = sorted(str(g.get("label")) for g in (doc.get("gates") or []))
    if named != sorted(declared):
        missing = sorted(set(declared) - set(named))
        extra = sorted(set(named) - set(declared))
        return GateResult(name, 2,
                          f"UNDETERMINED — the supplied record names "
                          f"{len(named)} gate(s) and this tree declares "
                          f"{len(declared)}: {len(missing)} not in the record "
                          f"({', '.join(missing[:4])}), {len(extra)} not "
                          f"declared ({', '.join(extra[:4])})")
    result = _hygiene_verdict(doc, int(record_rc))
    return GateResult(result.name, result.rc,
                      f"{result.summary} [adjudicated from the caller's record "
                      f"of a run that exited {int(record_rc)}, "
                      f"{len(declared)} declared gate(s) matched]")


def _hygiene_verdict(doc: dict, script_rc: int) -> GateResult:
    """Turn the script's own coverage record into a gate result.

    Split out from the subprocess plumbing so a test can drive every verdict
    branch from a record document without a multi-minute run.
    """
    name = "repo_hygiene_gates"
    declared = int(doc.get("declared") or 0)
    gates = doc.get("gates") or []
    by_state = lambda s: [str(g.get("label")) for g in gates
                          if g.get("state") == s]
    failed, not_checked = by_state("FAIL"), by_state("NOT_CHECKED")
    deferred = by_state("LISTED")
    # 2026-08-04 — a gate that WROTE into benchmark-data while auditing it.
    # Its own state, and read here rather than left to the fallback branch:
    # the script exits 1 for it while naming no FAIL, which would otherwise be
    # reported as "exited 1 while naming no failing gate" — an inconsistency
    # message about a record that is perfectly consistent, pointing a reader
    # away from the one thing that happened.
    wrote = by_state("WROTE_CORPUS")

    # vibe-ic#584 — the three keys that make NOT_CHECKED load-bearing HERE and
    # not only in the script's exit code. Before this, `not_checked` reached the
    # summary STRING and nothing else: the sweep printed "3 NOT CHECKED — this
    # is NOT a pass" and this function returned rc 0, i.e. MERGE_OK.
    #
    # Derived from the per-gate records when the top-level key is absent, and
    # derived FAIL-SAFE: a record written by a script predating the exemption
    # mechanism carries no `exempt_until` on any gate, so every NOT_CHECKED in
    # it reads as UNEXEMPTED and refuses. The opposite default would make "hand
    # a record in the old format" the way to buy silence for the whole
    # mechanism.
    wiring = [str(w) for w in (doc.get("wiring_errors") or [])]
    unexempted = doc.get("not_checked_unexempted")
    if unexempted is None:
        unexempted = [str(g.get("label")) for g in gates
                      if g.get("state") == "NOT_CHECKED"
                      and not g.get("exempt_until")]
    expired = doc.get("exemptions_expired")
    if expired is None:
        expired = [str(g.get("label")) for g in gates
                   if g.get("exemption_expired")]

    ran = declared - len(deferred)
    secs = doc.get("seconds")
    where = f"{ran}/{declared} gate(s) ran"
    if secs is not None:
        where += f" in {secs}s"
    if not_checked:
        where += (f"; {len(not_checked)} NOT CHECKED (not a pass): "
                  + ", ".join(sorted(not_checked)[:4]))
    if deferred:
        where += (f"; {len(deferred)} DEFERRED, NOT run here: "
                  + ", ".join(sorted(deferred)[:6]))

    if wrote:
        where += (f"; {len(wrote)} WROTE INTO the corpus: "
                  + ", ".join(sorted(wrote)[:4]))

    if declared == 0:
        # A hygiene script that wires nothing cannot certify anything.
        return GateResult(name, 2,
                          "ERROR — the hygiene script declared 0 gates; "
                          "nothing was checked and this is NOT a pass")
    if wiring:
        # The set's own DECLARATION is wrong, so no count it reports means what
        # it says. ERROR rather than FAIL: nothing was concluded about the tree.
        return GateResult(name, 2,
                          f"ERROR — {len(wiring)} wiring error(s) in the "
                          f"hygiene gate declarations, so the set certifies "
                          f"nothing: " + "; ".join(wiring[:3])
                          + (" …" if len(wiring) > 3 else "") + f" [{where}]")
    if wrote:
        # BEFORE the FAIL branch. Every gate that ran after a corpus write read
        # a tree this run modified, so any accompanying failure may be about
        # the leftovers rather than about the change — which is the
        # misattribution that cost hours and nearly produced a REQUEST_CHANGES
        # on an innocent PR. The writer has to be the headline.
        return GateResult(name, 1,
                          f"{len(wrote)} hygiene gate(s) WROTE INTO the corpus "
                          f"while auditing it: " + ", ".join(sorted(wrote)[:6])
                          + (" …" if len(wrote) > 6 else "")
                          + f". Verdicts taken after them are over a tree this "
                            f"run changed"
                          + (f"; {len(failed)} gate(s) also FAILED: "
                             + ", ".join(sorted(failed)[:4]) if failed else "")
                          + f" [{where}]")
    if failed:
        return GateResult(name, 1,
                          f"{len(failed)} hygiene gate(s) FAILED: "
                          + ", ".join(sorted(failed)[:6])
                          + (" …" if len(failed) > 6 else "")
                          + f" [{where}]")
    # AFTER the FAIL branch, and both are rc 1, so the ordering decides only
    # which sentence a maintainer reads first — a gate that RAN and found
    # something is the one to act on. Neither is lost: both are named in
    # `where`.
    if unexempted:
        # The lie-shape this whole change is about: the sweep NAMED a gate it
        # could not run and this function answered MERGE_OK over it. A gate
        # allowed to go unchecked must have said so in advance, with a date and
        # a reason, at the line that wires it.
        return GateResult(name, 1,
                          f"{len(unexempted)} gate(s) NOT CHECKED with no "
                          f"declared exemption — the hygiene set is smaller "
                          f"than it reports: "
                          + ", ".join(sorted(unexempted)[:6])
                          + (" …" if len(unexempted) > 6 else "")
                          + f" [{where}]")
    if expired:
        return GateResult(name, 1,
                          f"{len(expired)} uncheckable exemption(s) are PAST "
                          f"their review date; re-review the gate and either "
                          f"restate the date with a reason that is still true "
                          f"or remove the tolerance: "
                          + ", ".join(sorted(expired)[:6])
                          + (" …" if len(expired) > 6 else "") + f" [{where}]")
    # vibe-ic#1025 — a sweep that reached NO verdict is not a pass, and this
    # branch is what makes that true HERE and not only in the script's exit
    # code. Before it, an all-refusing sweep fell past every branch above to
    # the final `GateResult(name, 0, where)` — a GREEN gate — carrying
    # "6 NOT CHECKED (not a pass)" inside `where`, i.e. as prose beside a
    # passing verdict. That is #584's lie shape one level up: #584 made each
    # individual refusal buy a dated exemption, and never asked what happens
    # when the exempted set is ALL of them.
    #
    # BEFORE the `script_rc != 0` branch, for the reason the `wrote` branch is
    # before the FAIL branch: that branch's sentence is about an INCONSISTENCY
    # between the record and the exit code, and here the record and the exit
    # code agree perfectly — every gate ran and none of them concluded
    # anything. Reported through it, a wholly vacuous sweep reads as "the
    # script and its own summary disagree", pointing a reader away from the one
    # thing that happened.
    #
    # Derived from `gates` — the same source `failed` / `not_checked` /
    # `wrote` above come from — and NOT from the top-level `passed` counter. A
    # record may legitimately carry `gates` without the roll-up counters
    # (several of this repo's fixtures do), and reading an absent counter as 0
    # would make an all-PASS record look like it decided nothing: the very
    # failure this branch reports, manufactured by the branch itself.
    #
    # `executed` excludes LISTED and OTHER_SHARD for the same reasons the
    # script does: a `--list` run decided nothing BY REQUEST and already says
    # so, and a shard that owns no gate was never asked the question.
    executed = [g for g in gates
                if g.get("state") in ("PASS", "FAIL", "NOT_CHECKED",
                                      "WROTE_CORPUS")]
    decided = len(by_state("PASS")) + len(failed)
    if executed and decided == 0:
        return GateResult(name, 2,
                          f"ERROR — the hygiene set DECIDED NOTHING: 0 of "
                          f"{len(executed)} gate(s) that ran reached a "
                          f"verdict, {len(not_checked)} NOT CHECKED. Nothing "
                          f"was concluded about this tree, and that is not a "
                          f"pass [{where}]")
    if script_rc != 0:
        # Red script, no failing gate named: a setup/summary inconsistency we
        # must not paper over.
        return GateResult(name, 2,
                          f"ERROR — {_HYGIENE_SCRIPT_REL} exited {script_rc} "
                          f"while naming no failing gate [{where}]")
    return GateResult(name, 0, where)


# --------------------------------------------------------------------------
# subprocess runner for the file-walking gates.
# --------------------------------------------------------------------------
#: What ONE driven program may spend before this gate stops waiting for it.
#: vibe-ic#1208.
#:
#: MUST BE TIGHTER THAN THE HARNESS TIMEOUT ABOVE IT, and the first version of
#: this fix was not. At 300s under the suite's `--timeout=180`, pytest's own
#: timeout fires FIRST, and because it is thread-based it cannot interrupt a
#: subprocess wait — so the invocation still produced no summary and the bound
#: never got a chance to act. MEASURED: wall=181.63s, no summary, unchanged.
#: A bound only helps if whatever is waiting on it is prepared to wait longer.
_PROGRAM_TIMEOUT_S = 90.0


def _run_program(prog: Path, args: List[str],
                 timeout: float = _PROGRAM_TIMEOUT_S) -> Tuple[int, str, str]:
    """Drive `prog` as a subprocess. Returns `(rc, stdout, stderr)`.

    BOUNDED (vibe-ic#1208). This had no `timeout=` at all, and it is the one
    chokepoint all 15 gate drivers go through — `plugin_audit_gate` puts
    `plugin_full_audit.py` over the entire plugin root through it.

    An unbounded wait here is not "a slow gate". The wait lands in
    `subprocess.communicate` -> `selector.poll`, which pytest's
    `--timeout-method=thread` CANNOT interrupt: the timeout fires, prints its
    stack, and the invocation still never returns. What the operator sees is
    not "one test timed out" but a run with NO SUMMARY LINE — which greps as
    neither a pass nor a failure. Three of this program's own test modules
    could not be run in a pinned selection on clean `a38902d1` because of it,
    and this is the program that decides whether a batch may land.

    A TIMEOUT RETURNS 124, NEVER 0. Every caller here treats non-zero as a
    failing gate, so "I could not determine this" lands on the safe side of
    the verdict. A bounded wait that returned 0 would be a worse defect than
    the hang: it would convert "never finished" into "clean".
    """
    try:
        proc = subprocess.run([sys.executable, str(prog), *args],
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        def _txt(v) -> str:
            if v is None:
                return ""
            return v.decode("utf-8", "replace") if isinstance(v, bytes) else v
        return 124, _txt(exc.stdout), (
            f"{prog.name}: exceeded the {timeout:g}s bound and was stopped "
            f"(#1208) — this gate is UNDETERMINED, which is reported as a "
            f"failure because it is not a clean result\n" + _txt(exc.stderr))
    return proc.returncode, proc.stdout, proc.stderr


# --------------------------------------------------------------------------
# The aggregation: run every applicable gate, derive the verdict.
# --------------------------------------------------------------------------
def review(base: str, head: str, *,
           repo: Path,
           plugin_root: Path,
           role: Optional[str] = None,
           pytest_cmd: Optional[str] = None,
           commit_cmds: Optional[List[str]] = None,
           transcripts: Optional[str] = None,
           dataset: Optional[str] = None,
           control_junit: Optional[str] = None,
           control_text: Optional[str] = None,
           version_by_gatekeeper: bool = False,
           override_files: Optional[List[str]] = None,
           override_cur: Optional[str] = None,
           override_prev: Optional[str] = None,
           batch: bool = False,
           hygiene_script: Optional[Path] = None,
           hygiene_report: Optional[Path] = None,
           hygiene_progress: Optional[Path] = None,
           hygiene_record_in: Optional[Path] = None,
           hygiene_record_rc: Optional[int] = None) -> Verdict:
    """Run the deterministic gatekeeper and return a Verdict.

    `version_by_gatekeeper=True` is the AUTHORING-side review of a version-less
    PR (field/core PRs carry no bump; the gatekeeper assigns the version at
    merge): the version gate DEFERS when cur==prev and the authoring-time
    cadence floor is TARGETED. The gatekeeper's FINAL review (after
    gatekeeper_assign_version.py writes the real version) is run WITHOUT the
    flag, fully enforcing the monotonic+equality bump on the assigned version.

    `override_*` let tests inject a synthetic change-set / version pair without
    a real git history; production callers pass none of them. `hygiene_script`
    is the same kind of seam for the #538 hygiene gate — see `repo_hygiene_gate`
    for why it is deliberately not reachable from the CLI.
    """
    # 1. change-set.
    if override_files is not None:
        files = list(override_files)
    else:
        files = changed_files(repo, base, head)

    # 2. version bump (current=head, previous=base) + marketplace eq.
    if override_cur is not None or override_prev is not None:
        cur, prev = override_cur, override_prev
    else:
        cur = _git_show_json_version(repo, head, _PLUGIN_JSON_REL)
        prev = _git_show_json_version(repo, base, _PLUGIN_JSON_REL)
    market = _git_show_marketplace_version(repo, head) \
        if override_cur is None else override_cur

    # 3. cadence from the bump. A version-less authoring PR (cur==prev) under
    #    --version-by-gatekeeper can't know its merge-time version, so its
    #    authoring cadence floor is TARGETED; the gatekeeper re-derives the real
    #    cadence (FULL on an x.y.0 milestone) from the version it assigns.
    if version_by_gatekeeper and cur is not None and cur == prev:
        cadence = "TARGETED"
        version_bump = f"deferred — gatekeeper assigns at merge (authoring at {cur})"
    else:
        cadence, version_bump = derive_cadence(cur, prev)

    # 4. run gates.
    gates: List[GateResult] = []

    scope_gate, is_reject = role_scope_gate(role, files)
    gates.append(scope_gate)

    vb = version_bump_gate(cur, prev, market, version_by_gatekeeper, files)
    gates.append(vb)

    gates.append(marketplace_sync_gate(plugin_root))
    gates.append(chip_agnostic_gate(plugin_root))
    gates.append(path_portability_gate(plugin_root))
    gates.append(commit_msg_nda_gate(repo, base, head))
    gates.append(nda_diff_scan_gate(repo, base, head))
    gates.append(stale_branch_gate(repo, base, head))
    # The same landing method, seen from the other side. `stale_branch_gate`
    # judges a branch BEFORE it lands; once it has landed, its FRESH verdict is
    # structurally guaranteed and content-blind. This one reads the commits.
    gates.append(collateral_revert_gate(repo, base, head))
    # #459 — the landing SHAPE, alongside the landing METHOD above.
    #
    # v1.7.65: this used to omit `head`, and the comment that stood here
    # claimed a synthetic head ref would make the range uncountable so the
    # gate would skip. It did no such thing — `head` was simply never passed,
    # and the checker counted the REVIEWER'S working HEAD. Reviewing a PR from
    # a checkout parked on a clean one-commit landing returned PASS over an
    # unsquashed branch. An unresolvable ref is rc 2 / NOT CHECKED, which is
    # what the old comment promised and the code now delivers.
    gates.append(one_commit_gate(repo, base, head, batch=batch))
    gates.append(real_artefact_backing_gate(repo, base, head))
    gates.append(acceptance_control_gate(repo, base, head))
    gates.append(loop_watchdog_gate(plugin_root))
    gates.append(plugin_audit_gate(plugin_root))
    gates.append(git_prohibition_gate(commit_cmds or []))
    gates.append(test_cadence_gate(pytest_cmd, cadence))
    gates.append(ci_ran_gate(repo, head, cadence))
    gates.append(run_deliverable_gate(repo, files))
    gates.append(blindness_gate(transcripts, dataset))
    gates.append(control_substance_gate(control_junit, control_text, files))
    # #538 — LAST because it is by far the longest, so every cheap machine gate
    # has already printed by the time this starts. It is the whole CI hygiene
    # set, invoked (not re-listed) so that MERGE_OK means what it reads as.
    # #1025 — the hygiene record is adjudicated a second time, for a question
    # one run cannot answer: is any of this red OLD, and has any of it outlived
    # the deadline its acknowledgement set? The record is handed over rather
    # than the set re-run.
    with tempfile.TemporaryDirectory(prefix="gate_red_since_") as _td:
        _record = (Path(hygiene_report).resolve() if hygiene_report is not None
                   else Path(_td) / "hygiene.json")
        _record.parent.mkdir(parents=True, exist_ok=True)
        if hygiene_record_in is not None:
            _record = Path(hygiene_record_in).resolve()
            gates.append(hygiene_gate_from_record(
                repo, _record, hygiene_record_rc, script=hygiene_script))
        else:
            gates.append(repo_hygiene_gate(repo, script=hygiene_script,
                                           summary_out=_record,
                                           progress_out=hygiene_progress))
        gates.append(gate_red_since_gate(repo, _record))

    # 5. verdict.
    blocking = [f"{g.name}: {g.summary}" for g in gates if not g.green]
    if is_reject:
        verdict = "REJECT"
    elif blocking:
        verdict = "REQUEST_CHANGES"
    else:
        verdict = "MERGE_OK"

    return Verdict(verdict=verdict, gates=gates, cadence=cadence,
                   version_bump=version_bump, blocking=blocking)


def _git_show_marketplace_version(repo: Path, ref: str) -> Optional[str]:
    rc, out, _ = _git(repo, "show", f"{ref}:{_MARKETPLACE_JSON_REL}")
    if rc != 0:
        return None
    try:
        d = json.loads(out)
    except Exception:
        return None
    for entry in d.get("plugins", []) or []:
        if isinstance(entry, dict) and entry.get("version") is not None:
            return entry.get("version")
    return None


# --------------------------------------------------------------------------
# CLI.
# --------------------------------------------------------------------------
def _verdict_to_dict(v: Verdict) -> dict:
    return {
        "verdict": v.verdict,
        "gates": [{"name": g.name, "rc": g.rc, "summary": g.summary}
                  for g in v.gates],
        "cadence": v.cadence,
        "version_bump": v.version_bump,
        "blocking": v.blocking,
    }


_RC_BY_VERDICT = {"MERGE_OK": 0, "REQUEST_CHANGES": 1, "REJECT": 2}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Deterministic PR gatekeeper — aggregate the governance "
                    "programs against a PR diff and emit a verdict.")
    ap.add_argument("--base", required=True, help="base git ref")
    ap.add_argument("--head", required=True, help="head git ref")
    ap.add_argument("--role", default=None, help="PR author agent role")
    ap.add_argument("--pytest-cmd", default=None,
                    help="the pytest command string the PR ran")
    ap.add_argument("--commit-cmds-file", default=None,
                    help="file of the PR's git/gh command strings (one per line)")
    ap.add_argument("--transcripts", default=None,
                    help="blindness-audit transcript dir/file (optional)")
    ap.add_argument("--dataset", default=None,
                    help="blindness-audit dataset root (required with --transcripts)")
    ap.add_argument("--control-junit", default=None,
                    help="the PRE-FIX control run's pytest --junitxml report; "
                         "graded by control_substance_check, which BLOCKS on a "
                         "control whose every failure is an absence")
    ap.add_argument("--control-text", default=None,
                    help="the same control as a pasted pytest console log "
                         "(weaker than --junit; the checker measures the gap)")
    ap.add_argument("--repo", default=None,
                    help="repo root for git ops (default: cwd's repo)")
    ap.add_argument("--plugin-root", default=None,
                    help="plugin root for the file-walking gates "
                         "(default: this program's plugin)")
    ap.add_argument("--changed-file", default=None,
                    help="override the diff with a file of changed paths "
                         "(one per line; for CI/test without a real range)")
    ap.add_argument("--batch", action="store_true",
                    help="this push lands SEVERAL PRs under one version bump "
                         "and one CI run; check the batch's shape (no "
                         "manifest-only commit, exactly one version bump, "
                         "carried by the tip) instead of demanding one commit")
    ap.add_argument("--version-by-gatekeeper", action="store_true",
                    help="AUTHORING-side review of a version-less PR: DEFER the "
                         "version-bump gate when cur==prev (the gatekeeper "
                         "assigns the version at merge via "
                         "gatekeeper_assign_version.py and re-runs this review "
                         "WITHOUT the flag on the bumped tree)")
    ap.add_argument("--json", default=None, help="write the verdict JSON here")
    ap.add_argument(
        "--gate-record", dest="hygiene_report", default=None,
        help=("persist the complete repo-hygiene summary/attestation JSON at "
              "this path instead of keeping it only for the in-process "
              "gate-red-since adjudication"))
    ap.add_argument(
        "--hygiene-record-in", dest="hygiene_record_in", default=None,
        help=("adjudicate a repo-hygiene summary JSON the CALLER already "
              "produced instead of running the set a second time. Requires "
              "--hygiene-record-rc. The record is checked against this tree's "
              "declared gate set, not trusted; anything unestablished is rc 2 "
              "UNDETERMINED and blocking"))
    ap.add_argument(
        "--hygiene-record-rc", dest="hygiene_record_rc", type=int, default=None,
        help=("the exit status of the run that produced --hygiene-record-in. "
              "Separate because the record says WHICH gates were red and only "
              "the rc says whether the set completed"))
    ap.add_argument(
        "--gate-progress", dest="hygiene_progress", default=None,
        help=("append one owner-only JSONL process attestation after each "
              "completed hygiene gate; intended for sparse monitoring of a "
              "long run without polling its full stdout"))
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve() if args.repo else _find_repo_root()
    plugin_root = Path(args.plugin_root).resolve() if args.plugin_root \
        else _PLUGIN_ROOT_DEFAULT

    commit_cmds: List[str] = []
    if args.commit_cmds_file:
        p = Path(args.commit_cmds_file)
        if not p.is_file():
            print(f"ERROR: --commit-cmds-file not found: {p}", file=sys.stderr)
            return 2
        commit_cmds = p.read_text(encoding="utf-8").splitlines()

    override_files: Optional[List[str]] = None
    if args.changed_file:
        p = Path(args.changed_file)
        if not p.is_file():
            print(f"ERROR: --changed-file not found: {p}", file=sys.stderr)
            return 2
        override_files = [ln.strip() for ln in
                          p.read_text(encoding="utf-8").splitlines() if ln.strip()]

    try:
        v = review(args.base, args.head,
                   repo=repo, plugin_root=plugin_root,
                   role=args.role, pytest_cmd=args.pytest_cmd,
                   commit_cmds=commit_cmds,
                   transcripts=args.transcripts, dataset=args.dataset,
                   control_junit=args.control_junit,
                   control_text=args.control_text,
                   version_by_gatekeeper=args.version_by_gatekeeper,
                   override_files=override_files,
                   batch=args.batch,
                   hygiene_report=(Path(args.hygiene_report)
                                   if args.hygiene_report else None),
                   hygiene_progress=(Path(args.hygiene_progress)
                                     if args.hygiene_progress else None),
                   hygiene_record_in=(Path(args.hygiene_record_in)
                                      if args.hygiene_record_in else None),
                   hygiene_record_rc=args.hygiene_record_rc)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    out_dict = _verdict_to_dict(v)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(out_dict, indent=2,
                                              ensure_ascii=False) + "\n")

    print(f"VERDICT: {v.verdict}   (cadence={v.cadence}, bump={v.version_bump})")
    for g in v.gates:
        tag = {0: "PASS", 1: "FAIL", 2: "ERROR", -1: "SKIP"}.get(g.rc, "?")
        print(f"  [{tag}] {g.name}: {g.summary}")
    if v.blocking:
        print("BLOCKING:")
        for b in v.blocking:
            print(f"  - {b}")
    print("NOTE: §4.05/General/no-cheat AGENT-JUDGMENT gate is NOT here — "
          "it is the loop's Step-2.7 adversarial review (run it before merge).")
    return _RC_BY_VERDICT[v.verdict]


def _find_repo_root() -> Path:
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True)
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    # fall back to walking up from the plugin to a .git
    cur = _PLUGIN_ROOT_DEFAULT
    for _ in range(10):
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return _PLUGIN_ROOT_DEFAULT


if __name__ == "__main__":
    sys.exit(main())
