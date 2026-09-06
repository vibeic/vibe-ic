"""Source-bound clarification requests through the ordinary spec-review path.

These invented specs exercise structural validation of an explicit review.
Neither the validator nor these controls infer a missing predicate from prose.
The existing CLI discovery test is a behavioral pre-fix negative control: the
unmodified command must expose a supplied request to its ordinary user.
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "spec_review_lint.py"
CONTROL = """# Transfer controller
Assert alarm when a payload differs from the expected value.
Reset during operation clears alarm. Back-to-back transfers are supported.
Overflow saturates and underflow holds the previous result.
"""
TIMING = """# Transfer timing
Transfers are sampled on the rising edge of the clock.
The acknowledgement follows the transfer.
"""
SOURCES = {"input/docs/control.md": CONTROL, "input/docs/timing.md": TIMING}


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _review(sources=None):
    sources = SOURCES if sources is None else sources
    return {
        "schema": "vibeic.spec_clarification.v1",
        "source_sha256": sorted({_sha(text) for text in sources.values()}),
        "requests": [{
            "source_sha256": _sha(sources["input/docs/control.md"]),
            "excerpt": "Assert alarm when a payload differs from the expected value.",
            "missing_information": "The expected payload predicate is not specified.",
            "question": "Which payload values must the receiver accept as valid?",
        }],
    }


def _validate(review, sources=None):
    # Import inside the test path: collection on the pre-fix tree still works,
    # and the CLI negative control never depends on this new API existing.
    import spec_review_lint

    return spec_review_lint.validate_spec_clarification(
        review, SOURCES if sources is None else sources)


def _write_project(tmp_path, sources=None):
    sources = SOURCES if sources is None else sources
    for label, text in sources.items():
        path = tmp_path / label
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (tmp_path / "reports").mkdir(exist_ok=True)
    return sources


def _write_review(project, review, filename="spec_clarification_review.json"):
    path = project / "reports" / filename
    path.write_text(json.dumps(review), encoding="utf-8")
    return path


def _cli(project, *extra):
    report = project / "reports" / "spec_review_lint.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *SOURCES,
         "--json", str(report), *extra],
        cwd=project, capture_output=True, text=True, timeout=20)
    assert report.is_file(), (result.returncode, result.stdout, result.stderr)
    return result, json.loads(report.read_text(encoding="utf-8"))


def test_absent_review_is_not_reviewed_even_when_spec_defines_expected_pattern():
    sources = dict(SOURCES)
    sources["input/docs/control.md"] += (
        "The expected pattern is the exact byte 0x35; all other values assert alarm.\n")
    result = _validate(None, sources)
    assert result == {"status": "NOT_REVIEWED", "requests": [], "errors": []}


def test_two_source_review_accepts_verbatim_and_whitespace_normalized_evidence():
    review = _review()
    review["requests"].append({
        "source_sha256": _sha(TIMING),
        "excerpt": "clock.  \n\tThe acknowledgement follows the transfer.",
        "missing_information": "The acknowledgement delay is not quantified.",
        "question": "How many cycles after a transfer must acknowledgement assert?",
    })
    original = copy.deepcopy(review)
    result = _validate(review)
    assert result["status"] == "SPEC_CLARIFICATION_REQUIRED"
    assert result["errors"] == []
    assert [request["question"] for request in result["requests"]] == [
        request["question"] for request in review["requests"]]
    assert review == original, "validation must not rewrite the supplied review"


def test_identical_sources_under_two_labels_need_one_distinct_hash():
    sources = {"input/docs/control.md": CONTROL, "copy.md": CONTROL}
    result = _validate(_review(sources), sources)
    assert result["status"] == "SPEC_CLARIFICATION_REQUIRED"
    assert result["errors"] == []


@pytest.mark.parametrize("mismatch", ["omitted-source", "extra-source", "stale-text"])
def test_review_must_bind_all_and_only_current_raw_source_texts(mismatch):
    sources = dict(SOURCES)
    review = _review()
    if mismatch == "omitted-source":
        review["source_sha256"] = [_sha(CONTROL)]
    elif mismatch == "extra-source":
        review["source_sha256"].append(_sha("An unrelated source document."))
    else:
        # Semantically identical whitespace is still a different source revision.
        sources["input/docs/timing.md"] = TIMING + "\n"
    result = _validate(review, sources)
    assert result["status"] == "INVALID"
    assert result["errors"]
    assert result["requests"] == []


@pytest.mark.parametrize("forgery", ["unknown-hash", "wrong-source", "invented-excerpt"])
def test_request_evidence_must_belong_to_its_bound_source(forgery):
    review = _review()
    request = review["requests"][0]
    if forgery == "unknown-hash":
        request["source_sha256"] = _sha("An unrelated source document.")
    elif forgery == "wrong-source":
        request["source_sha256"] = _sha(TIMING)
    else:
        request["excerpt"] = "Only payloads divisible by thirteen are permitted."
    result = _validate(review)
    assert result["status"] == "INVALID"
    assert result["errors"]
    assert result["requests"] == []


@pytest.mark.parametrize("defect", [
    "schema", "hash-list", "empty-requests", "request-type",
    "blank-excerpt", "short-missing-information", "short-question",
])
def test_malformed_review_cannot_produce_a_clarification_request(defect):
    review = _review()
    if defect == "schema":
        review["schema"] = "vibeic.spec_clarification.v0"
    elif defect == "hash-list":
        review["source_sha256"] = _sha(CONTROL)
    elif defect == "empty-requests":
        review["requests"] = []
    elif defect == "request-type":
        review["requests"] = ["Please clarify the payload predicate."]
    elif defect == "blank-excerpt":
        review["requests"][0]["excerpt"] = " \n\t"
    elif defect == "short-missing-information":
        review["requests"][0]["missing_information"] = "Missing."
    else:
        review["requests"][0]["question"] = "Which value?"
    result = _validate(review)
    assert result["status"] == "INVALID"
    assert result["errors"]
    assert result["requests"] == []


@pytest.mark.parametrize("strict_warning", [False, True], ids=["advisory", "strict-red"])
def test_existing_cli_automatically_exposes_clarification_without_changing_lint(
        tmp_path, strict_warning):
    """Pre-fix negative control: uses only CLI arguments already supported."""
    sources = dict(SOURCES)
    if strict_warning:
        sources["input/docs/control.md"] += "Wait mode: enter upon enable.\n"
    _write_project(tmp_path, sources)
    extra = ("--strict",) if strict_warning else ()
    before, before_report = _cli(tmp_path, *extra)
    _write_review(tmp_path, _review(sources))
    after, after_report = _cli(tmp_path, *extra)

    # This assertion fails behaviorally on the original program, which runs
    # successfully but silently ignores the conventional review artifact.
    assert "SPEC_CLARIFICATION_REQUIRED" in after.stdout, after.stdout
    assert after.returncode == before.returncode == int(strict_warning)
    for key in ("verdict", "errors", "warnings", "findings"):
        assert after_report[key] == before_report[key], key
    assert before_report["spec_clarification"]["status"] == "NOT_REVIEWED"
    result = after_report["spec_clarification"]
    assert result["status"] == "SPEC_CLARIFICATION_REQUIRED"
    assert result["errors"] == []
    assert result["requests"][0]["question"] == _review()["requests"][0]["question"]


def test_explicit_review_overrides_conventional_sidecar(tmp_path):
    _write_project(tmp_path)
    _write_review(tmp_path, {"schema": "invalid"})
    explicit = _write_review(tmp_path, _review(), "selected_review.json")
    result, report = _cli(tmp_path, "--clarification-review", str(explicit))
    assert result.returncode == 0, result.stdout
    assert report["spec_clarification"]["status"] == "SPEC_CLARIFICATION_REQUIRED"
    assert report["errors"] == 0


@pytest.mark.parametrize("payload", ["{broken json", "null", '{"schema":"invalid"}'])
def test_invalid_conventional_review_is_a_reported_error(tmp_path, payload):
    _write_project(tmp_path)
    (tmp_path / "reports" / "spec_clarification_review.json").write_text(
        payload, encoding="utf-8")
    result, report = _cli(tmp_path)
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert report["verdict"] == "FAIL"
    assert report["spec_clarification"]["status"] == "INVALID"
    assert report["spec_clarification"]["errors"]
    assert report["spec_clarification"]["requests"] == []
    assert any(item["severity"] == "ERROR" for item in report["findings"])
