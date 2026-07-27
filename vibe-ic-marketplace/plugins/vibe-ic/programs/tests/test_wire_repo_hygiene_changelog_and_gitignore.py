#!/usr/bin/env python3
"""WIRING GUARD — two working repo-hygiene gates that ran nowhere.

Both programs below existed, both had a real rc=1 path, and neither was
reachable from anything automated:

  changelog_command_reproducibility_check   its ONLY host was
      `tools/ci/run_plugin_self_audit.sh`, a script whose own header calls
      itself "a pre-commit / pre-push CI step" and which NOTHING invokes.
      A whole-repo grep for that script name returns four hits and not one
      is an invocation. Its sibling in the same GATES array,
      `source_chip_agnostic_check`, was lifted out into
      tools/ci/repo_hygiene_gates.sh long ago; this one was left behind.

  gitignore_scratch_guard                   its docstring calls it a
      "Durable CI guard". No CI ran it. Three whole-tree hits: the program,
      the auto-generated programs/INDEX.md row, and its own unit test.

They are now `run` lines in tools/ci/repo_hygiene_gates.sh, which BOTH
workflows call (.github/workflows/ci.yml and gatekeeper-ci.yml — the latter
is the only one that fires on `merge_group`). This file asserts the wiring
EXISTS and that it still BITES, so it cannot silently fall back out.

The existence assertion deliberately goes through
`gate_discloses_denominator_check.parse_gates`, the SAME regex the two
meta-gates use to enumerate the CI battery — a `run` line that a grep can
see but that parser cannot is a line the meta-gates do not cover, and that
is the exact hole the `run_tolerating_uncheckable` wrapper once opened.

chip-AGNOSTIC: shell wiring, exit codes and repo paths only.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import gate_discloses_denominator_check as G  # noqa: E402
import changelog_command_reproducibility_check as C  # noqa: E402

_PLUGIN = _PROGRAMS.parent
_REPO = _PROGRAMS.parents[3]
_CI_SCRIPT = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"

_WIRED = (
    "changelog_command_reproducibility_check",
    "gitignore_scratch_guard",
)


def _gates():
    """(label, cwd-token, command) triples, or skip when the CI script is
    not in this layout (the plugin also ships standalone, without the
    marketplace repo around it)."""
    if not _CI_SCRIPT.is_file():
        pytest.skip(f"CI script not present in this layout: {_CI_SCRIPT}")
    gates = G.parse_gates(_CI_SCRIPT)
    assert gates, (
        f"{_CI_SCRIPT} parsed to ZERO run lines — the whole battery would "
        f"be unwired, not just these two")
    return gates


@pytest.mark.parametrize("program", _WIRED)
def test_the_gate_is_wired_into_the_ci_battery(program):
    """THE LOAD-BEARING ASSERTION: the program is named by a `run` line the
    meta-gates' own parser can see."""
    gates = _gates()
    hits = [(lab, wd, cmd) for lab, wd, cmd in gates if program in cmd]
    assert hits, (
        f"{program}.py is not invoked by any parsed `run` line in "
        f"{_CI_SCRIPT}. It was unwired once; this is the guard against it "
        f"falling out again. Parsed labels: "
        f"{[g[0] for g in gates]}")
    for _lab, wd, _cmd in hits:
        assert wd in ("$ROOT", "$PLUGIN"), (
            f"{program} wired with an unrecognised cwd token {wd!r}; the "
            f"meta-gates only understand $ROOT / $PLUGIN")


def _expand(cmd: str, root: Path) -> list[str]:
    """Expand a CI `run` command exactly as the meta-gates do, but with
    $ROOT / $PLUGIN pointed at a fixture."""
    c = cmd.replace('"$PG/', str(_PROGRAMS) + "/")
    c = c.replace('"$ROOT/', str(root) + "/").replace('"', "")
    c = c.replace("$PLUGIN", str(root / "vibe-ic-marketplace" / "plugins"
                                 / "vibe-ic"))
    c = c.replace("$ROOT", str(root))
    return c.split()


def _wired_cmd(program: str) -> str:
    for _lab, _wd, cmd in _gates():
        if program in cmd:
            return cmd
    raise AssertionError(f"{program} not wired")  # pragma: no cover


def test_the_wired_changelog_command_still_fails_on_a_phantom_command(
        tmp_path):
    """Through the WIRED command line, not just the module: a CHANGELOG that
    quotes a script which does not exist must exit 1."""
    root = tmp_path / "repo"
    plug = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    plug.mkdir(parents=True)
    (plug / "CHANGELOG.md").write_text(
        "# CHANGELOG\n\n```\n"
        "$ bash tools/ci/a_script_that_does_not_exist.sh\n"
        "```\n")
    argv = _expand(_wired_cmd("changelog_command_reproducibility_check"), root)
    r = subprocess.run(argv, cwd=str(root), capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 1, (
        f"expected rc 1 from {argv}\nstdout={r.stdout}\nstderr={r.stderr}")
    assert "MISSING_SCRIPT" in (r.stdout + r.stderr)


def test_the_wired_gitignore_guard_still_fails_without_the_rule(tmp_path):
    """Through the WIRED command line: a repo missing the root-anchored
    `/_*.js` rule must exit 1."""
    root = tmp_path / "repo"
    root.mkdir()
    for args in (["init", "-q", "."], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=str(root), check=True,
                       capture_output=True)
    (root / "seed.txt").write_text("x\n")
    subprocess.run(["git", "add", "seed.txt"], cwd=str(root), check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=str(root),
                   check=True, capture_output=True)
    argv = _expand(_wired_cmd("gitignore_scratch_guard"), root)
    r = subprocess.run(argv, cwd=str(root), capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 1, (
        f"expected rc 1 from {argv}\nstdout={r.stdout}\nstderr={r.stderr}")
    assert '"rule_present": false' in r.stdout


def test_the_gitignore_rule_this_guard_protects_is_still_in_the_repo():
    """The wiring is only worth having while the invariant it guards is
    real — assert the rule itself, so a delete cannot pass by making the
    guard vacuous."""
    gi = _REPO / ".gitignore"
    if not gi.is_file():
        pytest.skip(f"no repo-root .gitignore in this layout: {gi}")
    assert "/_*.js" in gi.read_text().splitlines(), (
        "the root-anchored /_*.js scratch rule (#720) is gone from "
        f"{gi}; the wired guard exists to make that impossible")


def test_the_changelog_gate_pass_discloses_its_denominator(tmp_path):
    """vibe-ic#447 — the reason this gate COULD NOT be wired before.

    `gate_discloses_denominator_check` runs every CI gate against an empty
    tree and fails any that answers PASS without saying how much it looked
    at. This gate's PASS used to read `PASS: every quoted shell command
    references a real target` over 412 documents and over zero alike.
    """
    plug = tmp_path / "mk" / "plugins" / "vibe-ic"
    plug.mkdir(parents=True)
    (plug / "CHANGELOG.md").write_text("# CHANGELOG\n\nno commands here\n")
    r = subprocess.run(
        [sys.executable,
         str(_PROGRAMS / "changelog_command_reproducibility_check.py"),
         str(plug)],
        capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout + r.stderr
    assert "PASS" in out
    assert any(ch.isdigit() for ch in out), (
        "a PASS with no number in it is indistinguishable from a scan of "
        f"nothing: {out!r}")
    assert G._DISCLOSURE_RE.search(out), (
        "the wired PASS line would be flagged PASS_WITHOUT_DENOMINATOR by "
        f"gate_discloses_denominator_check: {out!r}")


def test_the_marketplace_manifest_is_reachable_by_the_changelog_gate():
    """`_audit_files` DECLARES `.claude-plugin/marketplace.json` as an input
    and looked for it one directory too low (`<mk>/plugins/`), so on this
    repo it never opened it — a checker that cannot reach a file it names
    reports clean about that file forever."""
    manifest = _PLUGIN.parent.parent / ".claude-plugin" / "marketplace.json"
    if not manifest.is_file():
        pytest.skip(f"no marketplace manifest in this layout: {manifest}")
    assert manifest in C._audit_files(_PLUGIN), (
        f"{manifest} is not in the gate's scan set — the off-by-one path "
        f"regressed")
