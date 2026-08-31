"""ORGANIC #576 — community-backlog-submit SKILL.md (and, the sweep found,
48 sibling files) still carried compliance-gate sections / comments pointing
at the retired second-plugin path (`plugins/<retired>/...`): dead doctrine
whose guard never fires.  Fixes: all references rewritten against the
unified plugin's paths, and dead_plugin_path_check.py pins the class — no
retired-plugin token may exist under skills/ / programs/ / _shared/.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = PROG.parent
sys.path.insert(0, str(PROG))
import dead_plugin_path_check as DP  # noqa: E402

# Built dynamically so this test file itself never trips the checker.
TOKEN = DP.RETIRED_PLUGIN_TOKEN


def test_checker_flags_dead_compliance_section(tmp_path):
    """The issue's exact shape: a SKILL.md instructing the retired
    plugin's compliance checker path must FAIL."""
    sk = tmp_path / "skills" / "community-backlog-submit"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text(
        "## Compliance gate (" + TOKEN + " - mandatory when deterministic "
        "edition is installed)\n\n"
        "```bash\npython3 plugins/" + TOKEN + "/_shared/skill_compliance_check.py \\\n"
        "    --requirements plugins/" + TOKEN + "/skills/community-backlog-submit/compliance.yaml\n```\n"
    )
    rc = DP.main([str(tmp_path)])
    assert rc == 1


def test_checker_flags_bare_prose_mention(tmp_path):
    prog = tmp_path / "programs"
    prog.mkdir()
    (prog / "x.py").write_text("# exit 2 per the " + TOKEN + " contract\n")
    rc = DP.main([str(tmp_path)])
    assert rc == 1


def test_checker_passes_unified_paths(tmp_path):
    sk = tmp_path / "skills" / "demo"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text(
        "## Compliance gate (mandatory)\n\n"
        "```bash\npython3 plugins/vibe-ic/_shared/skill_compliance_check.py \\\n"
        "    --requirements plugins/vibe-ic/skills/demo/compliance.yaml\n```\n"
    )
    rc = DP.main([str(tmp_path)])
    assert rc == 0


# ── the live pin: shipped bundle carries zero retired-plugin references ─────

def test_shipped_bundle_has_no_retired_plugin_reference():
    hits = DP.audit(str(PLUGIN_ROOT))
    assert hits == [], "\n".join(hits[:20])


def test_community_backlog_submit_uses_unified_checker_path():
    """The named artifact: the rewritten section points at the unified path."""
    md = (PLUGIN_ROOT / "skills" / "community-backlog-submit" / "SKILL.md").read_text()
    assert "plugins/vibe-ic/_shared/skill_compliance_check.py" in md
    assert TOKEN not in md


# ── the 2026-08-31 stamp regression: the token came back as NARRATIVE ───────
#
# `test_shipped_bundle_has_no_retired_plugin_reference` above went red on the
# stamp tree 411c0ac73 (v1.14.43) with exactly one hit:
#
#     programs/tests/test_pytest_ini_paths_exist.py:45
#
# and the hit was not a live path. It was a module docstring EXPLAINING a
# historical defect, which had quoted the broken value verbatim. That is the
# regression door this class comes back through: nobody adds dead doctrine on
# purpose, they cite it while documenting why it was removed. The checker is
# deliberately blind to that distinction (its own docstring: "path forms and
# bare prose mentions alike, since both reintroduce dead doctrine"), because a
# reader who copies the literal out of an explanation is in the same place as
# one who copied it out of an instruction.
#
# So the repair had to keep the explanation and drop the literal — and both
# halves are pinned below, because either one alone is satisfiable by the wrong
# fix: dropping the docstring entirely would satisfy the first, and the second
# alone would be satisfied by never having removed the token.

_NARRATOR = PROG / "tests" / "test_pytest_ini_paths_exist.py"


def test_the_narrating_file_does_not_respell_the_retired_token():
    """Where the stamp's one hit was. Pinned BY FILE, not by count."""
    assert _NARRATOR.is_file(), f"{_NARRATOR} vanished rather than being fixed"
    text = _NARRATOR.read_text(encoding="utf-8")
    hits = [f"{i}: {ln.strip()}" for i, ln in enumerate(text.splitlines(), 1)
            if TOKEN in ln]
    assert not hits, (
        "the retired token is spelled again in the file that narrates why it "
        "was removed:\n" + "\n".join(hits))


def test_the_narrative_survived_the_removal():
    """The fix was a REWRITE, not a deletion of the explanation.

    A docstring is the only place this defect's history is written down. Taking
    the token out by deleting the paragraph would turn this gate green while
    destroying the record of what it is for — and the next author, with no
    explanation to read, re-adds the literal. So the surrounding narrative is
    required to still be here and to still be about the retired plugin.
    """
    text = _NARRATOR.read_text(encoding="utf-8")
    for phrase in ("AND IT PINNED ONE CONFIG WHILE TWO SHIP",
                   "RETIRED", "612b5a94d", "no tests collected"):
        assert phrase in text, (
            f"{phrase!r} is gone from {_NARRATOR.name}: the retired-token "
            f"reference was removed by deleting the explanation rather than "
            f"by rewording it, so nothing tells the next author why")


def test_nothing_LIVE_resolves_to_the_retired_plugin():
    """The removal proof, made executable so it cannot rot into an assumption.

    Deleting a reference is only correct if nothing reached it. Two facts carry
    that, and both are re-measured here rather than asserted once in a commit
    message: the directory is not in the tree, and no shipped pytest config
    names it (that config naming four never-existing testpaths under the
    retired plugin is the defect the narrative above is about, and it is the
    only thing that ever DID reach the path).
    """
    marketplace = PLUGIN_ROOT.parents[1]
    retired = marketplace / "plugins" / TOKEN
    assert not retired.exists(), (
        f"{retired} EXISTS — the path is not dead, and the references to it "
        f"were removed on a false premise")

    import subprocess
    tracked = subprocess.run(
        ["git", "ls-files", f"vibe-ic-marketplace/plugins/{TOKEN}/"],
        cwd=marketplace.parent, capture_output=True, text=True)
    assert tracked.stdout.strip() == "", (
        f"the retired plugin is git-tracked after all:\n{tracked.stdout}")

    cfg = marketplace / "pyproject.toml"
    assert cfg.is_file(), cfg
    assert TOKEN not in cfg.read_text(encoding="utf-8"), (
        "the shipped pytest config names the retired plugin again — this is "
        "the original defect, and it collects NO tests while printing no error")
