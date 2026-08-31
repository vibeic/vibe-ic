"""A quotation is not an invocation — and an invocation is still refused.

The guard blocked a landing whose PROSE documented (in inline code) the
forbidden form its fix removed. The discriminator: backtick spans are
quotation; bare text is command.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import git_prohibition_guard as g


def test_backtick_quoted_mention_is_not_a_violation():
    r = g.scan_commands(
        ["* it restored protected paths with `git checkout -- <path>`, which takes the INDEX copy"])
    assert r.passed, r.violations


def test_bare_command_is_still_refused():
    r = g.scan_commands(["git checkout -- some/file.py"])
    assert not r.passed
    assert r.violations[0].rule_id == "checkout_discard"


def test_other_rules_survive_the_blanking():
    r = g.scan_commands(["git push --force origin main"])
    assert not r.passed and r.violations[0].rule_id == "push_force"
    r2 = g.scan_commands(["docs say `git push --force` is forbidden"])
    assert r2.passed, r2.violations
