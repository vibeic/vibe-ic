#!/usr/bin/env python3
"""A report-only gate must not print the token a blocking gate uses.

THE DEFECT, and it cost a top-priority escalation on 2026-08-14.

`repo_hygiene_gates.sh` runs the upstream-currency probe as
`run_tolerating_uncheckable "upstream image currency (report-only)" ...
--report-upstream`. That gate cannot fail the tier: `do_report_upstream`
returns 0 for a divergence on purpose, because what it compares is a MUTABLE
THIRD-PARTY POINTER whose answer flips with no commit in this tree
(vibe-ic#927). Its own summary says so — "This is INFORMATION, not a landing
verdict".

It nevertheless printed:

    [FAIL] `:latest` does NOT point at the anchor version.

That was the ONLY line beginning `[FAIL]` in a 4910-second run of the hygiene
tier over CLEAN main (3d13e2c59), and the tier exited **0** with **71 of 74
passed, 3 NOT CHECKED and zero gates recorded FAIL**. A reader grepping the log
for `^\\[FAIL\\]` — human or otherwise — concludes clean main fails its own
hygiene tier. It does not.

This is the [[unmeasured-reads-as-a-measured-zero]] shape inverted: a REPORT
that reads as a VERDICT. The repair is the token, not the finding: the
observation is real, is worth making, and is unchanged below.

WHY THIS CANNOT WEAKEN THE BLOCKING GATE. `check_latest_points_at_anchor` and
`check_anchor_vs_reality` are called from EXACTLY ONE place each —
`do_report_upstream`. `do_check`, the blocking half, calls neither (measured:
`grep -n 'check_anchor_vs_reality(\\|check_latest_points_at_anchor('` returns
their definitions and the two calls at :753 and :754). So the retokenised
prints are unreachable from the tier's blocking path by construction, and the
last test below pins that.

MEASURED BOTH WAYS on the real registry, md5-verified arms:

    pre-fix  00b557e0   drift injected -> rc 1, "[FAIL] 2 live pointer(s)"
    post-fix 4c95f2a8   drift injected -> rc 1, "[FAIL] 2 live pointer(s)"
    post-fix 4c95f2a8   --report-upstream -> rc 0, zero verdict tokens
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

#: …/<repo>/vibe-ic-marketplace/plugins/vibe-ic/programs/tests/this_file.py
#: parents: 0=tests 1=programs 2=vibe-ic 3=plugins 4=vibe-ic-marketplace 5=repo.
#: Resolved by SEARCH rather than by a hard index, because an index that is one
#: too small makes `_TOOL` absent and every test in this file SKIP — which is
#: green, and says nothing. That is the failure mode this file exists to name.
def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for cand in here.parents:
        if (cand / "tools" / "vibeic-eda" / "sync_image_version.py").is_file():
            return cand
    raise AssertionError(
        f"sync_image_version.py not found above {here} — this test cannot "
        f"silently skip, because a skip here reads as a pass")


_REPO = _find_repo_root()
_TOOL = _REPO / "tools" / "vibeic-eda" / "sync_image_version.py"

#: The tokens a READER treats as the tier's verdict. `[NOT CHECKED]` is
#: deliberately absent: it is the honest answer of a probe that could not look,
#: it is non-fatal by design (`run_tolerating_uncheckable` tolerates rc 2), and
#: the report path is entitled to print it.
_VERDICT_TOKENS = ("[FAIL]", "[PASS]")


def _load():
    spec = importlib.util.spec_from_file_location("_siv_423", _TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def mod():
    return _load()


def _diverging(m, monkeypatch):
    """A registry where `:latest` and the anchor resolve to different manifests.

    Monkeypatched rather than queried: the real `:latest` is mutable, so a test
    that needs it to disagree would pass or fail on someone else's push. The
    condition under test is the TOKEN, which does not depend on the network.
    """
    monkeypatch.delenv(m.PUBLISHED_TAG_ENV, raising=False)
    monkeypatch.setattr(m, "_query_ghcr_digest",
                        lambda repo, tag, timeout=6.0:
                        "sha256:aaa" if tag == m.FLOATING_TAG else "sha256:bbb")


def test_the_divergence_is_reported_without_a_verdict_token(mod, monkeypatch,
                                                            capsys):
    """THE PROPERTY."""
    _diverging(mod, monkeypatch)
    rc = mod.check_latest_points_at_anchor("0.2.89")
    out = capsys.readouterr().out

    offending = [ln for ln in out.splitlines()
                 if ln.startswith(_VERDICT_TOKENS)]
    assert offending == [], (
        "a gate that cannot fail the tier printed the token a blocking gate "
        f"uses; a reader grepping for it concludes main is red:\n{offending}")
    assert rc == 1, (
        "the SEVERITY must survive the retokenisation — `do_report_upstream` "
        "records it as `floating_vs_anchor: disagrees`")


def test_the_finding_itself_is_unchanged(mod, monkeypatch, capsys):
    """PAIRED HALF: not a green bought by deleting the message.

    A fix that silenced the divergence would also satisfy the test above, and
    would be strictly worse than the defect it repairs.
    """
    _diverging(mod, monkeypatch)
    mod.check_latest_points_at_anchor("0.2.89")
    out = capsys.readouterr().out
    assert "does NOT point at the anchor" in out, out
    assert "imagetools create" in out, "the remedy must stay in the message"
    assert "sha256:aaa" in out and "sha256:bbb" in out, (
        "both digests must be quoted — the reader has to be able to verify the "
        "claim without re-querying")
    assert "DIVERGENCE" in out, (
        "the line must still read as a finding, not as routine chatter")


def test_agreement_is_still_silent_and_zero(mod, monkeypatch, capsys):
    """FALSE-POSITIVE CONTROL: the retokenised branch is the DIVERGENT one, so
    an implementation that printed DIVERGENCE unconditionally would pass the
    two tests above."""
    monkeypatch.delenv(mod.PUBLISHED_TAG_ENV, raising=False)
    monkeypatch.setattr(mod, "_query_ghcr_digest",
                        lambda repo, tag, timeout=6.0: "sha256:same")
    rc = mod.check_latest_points_at_anchor("0.2.89")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "DIVERGENCE" not in out, out


def test_unreachable_is_still_NOT_CHECKED_and_rc_2(mod, monkeypatch, capsys):
    """The distinction this repo cares about most, re-pinned here because the
    retokenisation touches the same function.

    `run_tolerating_uncheckable` tolerates rc 2 and ONLY rc 2, so "could not
    look" must not drift into either a pass or a finding.
    """
    monkeypatch.delenv(mod.PUBLISHED_TAG_ENV, raising=False)

    def _boom(repo, tag, timeout=6.0):
        raise TimeoutError("registry unreachable")

    monkeypatch.setattr(mod, "_query_ghcr_digest", _boom)
    rc = mod.check_latest_points_at_anchor("0.2.89", require_remote=True)
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "[NOT CHECKED]" in out, out
    assert "DIVERGENCE" not in out, (
        "an unreachable registry is not a divergence — nothing was compared")


def test_the_blocking_half_never_calls_the_retokenised_functions():
    """THE SCOPE GUARD, and the reason this change cannot weaken the tier.

    Structural, on the source: if a future edit wires either comparison into
    `do_check`, the blocking gate would start printing `[REPORT] DIVERGENCE`
    for a condition that DOES fail the tier — the mirror of the defect fixed
    here — and this test says so before that ships.
    """
    src = _TOOL.read_text(encoding="utf-8")
    start = src.index("def do_check(")
    end = src.index("def do_report_upstream(")
    body = src[start:end]
    for fn in ("check_anchor_vs_reality", "check_latest_points_at_anchor"):
        assert fn not in body, (
            f"do_check now calls {fn}, whose findings print [REPORT] because "
            f"they were report-only. A blocking path must print [FAIL].")


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-v"]))
