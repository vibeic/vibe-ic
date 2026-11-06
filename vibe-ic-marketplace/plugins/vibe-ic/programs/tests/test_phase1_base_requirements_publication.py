"""Candidate publication preserves owner approval and the existing metric gate."""


from programs.tests._hostpaths import require_repo


















































def test_authority_documentation_names_owner_role_and_review_stop():
    root = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic')
    flow = (root / 'flow/FLOW109.md').read_text()
    command = (root / 'commands/vibe-ic-all.md').read_text()
    assert 'AI-owned authority remains' not in flow
    assert '`requirements_owner` is a role' in flow
    assert 'named approver' in flow
    assert 'current source hash' in flow
    assert 'Programs never write approvals' in flow
    assert 'D0102_REQUIREMENTS_OWNER_REVIEW_REQUIRED' in command
    assert 'exit 4' in command
    assert 'input/docs/**' in command
