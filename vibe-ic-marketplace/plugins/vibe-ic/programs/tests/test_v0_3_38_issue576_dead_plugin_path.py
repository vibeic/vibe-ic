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
