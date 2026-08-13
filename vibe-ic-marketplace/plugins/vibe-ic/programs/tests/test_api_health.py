"""Paired guards for api_health (vibe-ic#1319).

Lives in `programs/tests/` and not beside the module, because `pytest.ini` sets
`testpaths = programs/tests` — a test outside that tree is never collected, so
it would gate nothing (measured on vibe-ic#1306, and the general case is #1312).
"""
import importlib.util
import sys
from pathlib import Path


def _load():
    """Locate the module by WALKING UP, never by a parent index (#1308's shape)."""
    for parent in Path(__file__).resolve().parents:
        cand = (parent / "skills" / "core-agent-loop" / "programs" / "api_health.py")
        if cand.is_file():
            spec = importlib.util.spec_from_file_location("api_health", cand)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise AssertionError("api_health.py not found above this test")


H = _load()

_LIMIT = {"message": "API rate limit exceeded for user ID 3784584."}
_HEALTHY_QUOTA = {"resources": {"core": {"remaining": 4862, "limit": 5000}}}
_SPENT_QUOTA = {"resources": {"core": {"remaining": 0, "limit": 5000}}}


# ── the discriminator ─────────────────────────────────────────────────────
def test_a_limit_403_with_quota_REMAINING_is_the_secondary_limit():
    """The measured case: 403 everywhere while rate_limit says 4862/5000 left."""
    assert H.classify(403, _LIMIT, _HEALTHY_QUOTA) == H.SECONDARY_LIMIT


def test_a_limit_403_with_quota_at_zero_is_ordinary_exhaustion():
    assert H.classify(403, _LIMIT, _SPENT_QUOTA) == H.QUOTA_EXHAUSTED


def test_the_two_limits_are_NOT_distinguished_by_wording_alone():
    """Both kinds say 'rate limit exceeded'. Only the counters separate them."""
    assert H.classify(403, _LIMIT, _HEALTHY_QUOTA) != H.classify(403, _LIMIT, _SPENT_QUOTA)


def test_a_403_without_limit_wording_is_a_permissions_problem():
    assert H.classify(403, {"message": "Resource not accessible"}) == H.FORBIDDEN


# ── the refusals ──────────────────────────────────────────────────────────
def test_an_unreadable_quota_is_UNKNOWN_and_never_zero():
    """None is not 0. Folding it to 0 reports exhaustion and sleeps on the
    wrong clock — the reset time is not why a secondary limit is blocking."""
    for junk in (None, {}, {"resources": {}}, "nonsense", {"resources": {"core": {}}}):
        assert H.core_remaining(junk) is None


def test_an_unreadable_quota_classifies_as_SECONDARY_not_exhaustion():
    assert H.classify(403, _LIMIT, None) == H.SECONDARY_LIMIT
    assert H.classify(403, _LIMIT, {"resources": {}}) == H.SECONDARY_LIMIT


def test_a_failed_call_is_NEVER_evidence_about_the_repository():
    """The correctness core: 403 means 'we could not look', never 'nothing is
    there'. Reading it as 'no claims' is what makes a lost claim invisible."""
    assert H.is_evidence(200) is True
    for bad in (0, 403, 429, 500, 502):
        assert H.is_evidence(bad) is False, bad


# ── the operator gets told which clock to trust ───────────────────────────
def test_the_secondary_advice_names_the_limit_and_rejects_the_reset_clock():
    msg = H.advice(H.SECONDARY_LIMIT, _HEALTHY_QUOTA)
    assert "SECONDARY" in msg
    assert "4862" in msg, "the advice must quote the quota that looks healthy"
    assert "wrong clock" in msg


def test_the_exhausted_advice_points_AT_the_reset_clock():
    msg = H.advice(H.QUOTA_EXHAUSTED, _SPENT_QUOTA)
    assert "right clock" in msg and "reset" in msg


def test_a_permissions_403_is_not_described_as_something_waiting_fixes():
    assert "never clear" in H.advice(H.FORBIDDEN)


def test_an_unclassified_failure_still_says_NO_EVIDENCE():
    assert "NO EVIDENCE" in H.advice(H.OTHER)


def test_a_200_is_healthy():
    assert H.classify(200, {"anything": True}) == H.HEALTHY


# ── the wiring: the fleet poller must not swallow a blocked call ──────────
def _poll_source() -> str:
    for parent in Path(__file__).resolve().parents:
        cand = parent / "skills" / "core-agent-loop" / "programs" / "poll.py"
        if cand.is_file():
            return cand.read_text()
    raise AssertionError("poll.py not found above this test")


def test_the_poller_raises_rather_than_reporting_an_empty_repository():
    """`return []` on a failed page would tell the queue 'no open issues'."""
    src = _poll_source()
    assert "raise RuntimeError(" in src
    i = src.index("status != 200 or not isinstance(data, list)")
    tail = src[i:i + 900]
    assert "raise RuntimeError(" in tail, "the failure path stopped raising"


def test_the_poller_names_WHICH_limit_it_hit():
    """Without this the operator sees a raw 403 payload next to a healthy
    quota and concludes the account is fine."""
    src = _poll_source()
    assert "_health.classify(" in src, "poller no longer classifies the failure"
    assert "_health.advice(" in src, "poller no longer reports what to do"
