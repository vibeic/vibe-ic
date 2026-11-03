"""The owner fixed CHARTER.md on 2026-11-03. Changing it, on purpose, means changing the pin here."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_charter_bytes_are_the_owners():
    digest = hashlib.sha256((ROOT / "CHARTER.md").read_bytes()).hexdigest()
    assert digest == "1f98a3581da1a933301f7f08cbd3a1c72e2d4ecc1adc3a1ba1d5b175806eb91c"


def test_every_agent_is_told_at_session_and_prompt():
    for hook in ("ic-expert-identity-session.sh", "ic-expert-identity-reminder.sh"):
        assert "CHARTER.md" in (ROOT / "hooks" / hook).read_text()
