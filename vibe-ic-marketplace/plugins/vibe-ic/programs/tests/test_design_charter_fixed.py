"""The owner fixed CHARTER.md on 2026-11-03. Changing it, on purpose, means changing the pin here."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_charter_bytes_are_the_owners():
    digest = hashlib.sha256((ROOT / "CHARTER.md").read_bytes()).hexdigest()
    assert digest == "9afee992348420b542220f128f2bc8ce3dd2de0706ed8e1c4d232a225f05c067"


def test_every_agent_is_told_at_session_and_prompt():
    for hook in ("ic-expert-identity-session.sh", "ic-expert-identity-reminder.sh"):
        assert "CHARTER.md" in (ROOT / "hooks" / hook).read_text()
