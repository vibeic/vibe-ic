"""The owner fixed CHARTER.md on 2026-11-03. Changing it, on purpose, means changing the pin here."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_charter_bytes_are_the_owners():
    digest = hashlib.sha256((ROOT / "CHARTER.md").read_bytes()).hexdigest()
    assert digest == "2c11b0ee836d575b1b8aa4840ab6dc6cc73c05a7309c8754a8e7d6409998e8aa"


def test_every_agent_is_told_at_session_and_prompt():
    for hook in ("ic-expert-identity-session.sh", "ic-expert-identity-reminder.sh"):
        assert "CHARTER.md" in (ROOT / "hooks" / hook).read_text()
