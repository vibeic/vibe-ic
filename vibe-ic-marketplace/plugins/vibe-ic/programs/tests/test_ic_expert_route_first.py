"""The owner chooses one delivery route before either Phase-1 front door runs."""
from pathlib import Path

import pytest



ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT.parent














def test_expert_physical_delivery_rule_names_both_routes():
    page = (PLUGIN / "agents/ic-expert-agent.md").read_text()
    # Reporting instructions may precede delivery admission. Inspect the
    # declared route rule rather than treating the first display heading as it.
    heading = next(line for line in page.splitlines()
                   if line.startswith("## § 0.0"))
    assert "IC path or IP path" in heading
    rule = page.split(heading, 1)[1].split("\n## ", 1)[0]
    assert "physical delivery is in scope" in rule
    assert "bounded RTL" in rule and "task_nature_route.py" in rule
    for phrase in ("DIE", "HARDMACRO", "IC path or IP path?", "before Phase 1",
                   "answer_provenance.deliverable", "15.5ic", "26.5ic",
                   "37.5ic", "37.5ip"):
        assert phrase in rule


@pytest.mark.parametrize("rel", [
    "commands/vibe-ic-all.md", "commands/vibe-ic-phase1.md",
    "commands/vibe-ic-benchmark.md", "skills/phase1/SKILL.md",
])
def test_each_front_door_names_the_first_rule(rel):
    text = (PLUGIN / rel).read_text()
    assert "IC path or IP path?" in text.splitlines()[:25].__str__()
    assert "ic-expert-agent.md" in text


@pytest.mark.parametrize("name", ["ic-expert-identity-session.sh",
                                         "ic-expert-identity-reminder.sh"])
def test_identity_hooks_remind_about_the_first_rule(name):
    text = (PLUGIN / "hooks" / name).read_text()
    assert "FIRST RULE: IC path or IP path?" in text
    assert "agents/ic-expert-agent.md" in text
