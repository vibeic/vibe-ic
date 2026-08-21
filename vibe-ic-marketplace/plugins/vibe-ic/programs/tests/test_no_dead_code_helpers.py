"""Tests for v0.1.63 R16 capture: regression test that catches dead-code
helpers — public emit/scrub/extract/skeleton/na_stub-shape entry points
that the runner pipeline never calls.

Motivating history:
  v0.1.51 shipped 4 deterministic helpers (scrub_l_doc, emit_l_doc_skeleton,
  applicable_l_docs/na_stub, extract_l14-l18). None were wired into the
  runner. Their absence surfaced in the v0.1.57 AMBA AXI parity run as 15
  HALLUCINATED findings + over-filled L4/L5/L7/L11/L13 + missing L14-L18
  + missing L19-L23. Wiring them in (R11, R12, R13, R14, R15) closed the
  gap one helper at a time over v0.1.60-v0.1.63.

Doctrine: a helper without a caller is dead code. Future helpers must
land their call-site in the same commit, or fail this test. Adding a new
helper to the SCANNED_MODULES list AND its matching consumer is part of
the regression-test bargain.
"""
import re
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]


# Modules to scan for helper-shape entry points. Each must be a Python file
# under programs/ that defines public functions intended for the runner
# to call (NOT CLI helpers, NOT pure data modules).
SCANNED_HELPER_MODULES = [
    "phase1_post_process.py",
    "phase1_protocol_spec_extract.py",
    "l_doc_taxonomy.py",
]


# Modules where helpers should appear as consumers. Adding a new
# helper-tier without a consumer is the failure this test guards against.
CONSUMER_MODULES = [
    "phase1_doc_one_shot_runner.py",
    "phase1_one_shot_runner.py",
    # If we add catalog-glue-author or analog-one-shot pipelines that
    # consume more L-doc helpers in future, they get added here.
]


# Function-name patterns that mark a "helper" expected to have a caller.
# Intentionally narrow: only function NAMES that match this pattern in a
# SCANNED_HELPER_MODULES file count as captured helpers. This prevents
# the test from over-flagging utility functions.
HELPER_NAME_PATTERNS = [
    re.compile(r"^scrub_l_doc$"),
    re.compile(r"^emit_l_doc_skeleton$"),
    re.compile(r"^extract_l1[4-9]_"),
    re.compile(r"^na_stub$"),
    re.compile(r"^is_applicable$"),
    re.compile(r"^applicable_l_docs$"),
]


# Exemptions: helpers we've decided are NOT meant to be called from a
# runner. Each entry MUST come with a documented reason — anything in
# this set is the test author's promise that the helper is legitimately
# stand-alone (e.g. a CLI-only utility). Empty by default.
EXEMPTED_HELPERS: dict[str, str] = {
    # Format:
    # "module.py::function_name": "why this helper is legitimately uncalled",
    "l_doc_taxonomy.py::applicable_l_docs":
        "Set-returning batch API. The runner uses the singular is_applicable "
        "variant per-doc inside the _write_l_doc chokepoint (R13 wiring). "
        "applicable_l_docs() exists for callers that need the full set "
        "(e.g. a future per-class L-doc summary report); not orphaned, "
        "just not consumed by the current main pipeline.",
}


def _collect_helper_defs(module_path: Path) -> list[str]:
    """Return the names of public functions in `module_path` that match
    any HELPER_NAME_PATTERN. Uses regex over `^def ` lines (good-enough
    for the scan; AST would be more robust but pulls in extra complexity)."""
    src = module_path.read_text()
    names = []
    for m in re.finditer(r"^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", src,
                          re.MULTILINE):
        name = m.group(1)
        if any(p.search(name) for p in HELPER_NAME_PATTERNS):
            names.append(name)
    return sorted(set(names))


def _has_consumer(helper_name: str, consumer_modules: list[Path]) -> bool:
    """True iff `helper_name` is referenced (call, import, or attribute
    access) in any consumer module's source. The reference can be:
      - `from X import helper_name`
      - `import X` followed by `X.helper_name(...)`
      - direct `helper_name(...)` call
    """
    # The reference can be qualified or not; scan for the bare identifier
    # token (boundary on word chars) so `helper_name` matches both
    # `from X import helper_name` and `X.helper_name(...)`.
    pat = re.compile(rf"\b{re.escape(helper_name)}\b")
    for cm in consumer_modules:
        src = cm.read_text()
        # Strip out the def site itself if the consumer module happens to
        # be the helper module too (defensive: the consumer should never
        # be the same as the helper module, but we don't want a helper's
        # own def to count as "consumer found").
        # Match in non-def-line context: any occurrence on a line that
        # isn't `def helper_name(...)`.
        for line in src.split("\n"):
            stripped = line.strip()
            if stripped.startswith(f"def {helper_name}("):
                continue
            if pat.search(line):
                return True
    return False


def test_every_captured_helper_has_a_runner_consumer():
    """Each public emit/scrub/extract/skeleton helper in a SCANNED module
    must be referenced by at least one CONSUMER module. Adding a helper
    without wiring it in (the v0.1.51 dead-code pattern that bit us 4
    times) fails this test."""
    consumer_paths = [PROGRAMS / cm for cm in CONSUMER_MODULES
                       if (PROGRAMS / cm).is_file()]
    assert consumer_paths, (
        f"no consumer modules found from {CONSUMER_MODULES}; "
        f"regression test would always pass — fix the path list.")

    orphans = []
    helpers_seen = []
    for module_name in SCANNED_HELPER_MODULES:
        module_path = PROGRAMS / module_name
        if not module_path.is_file():
            continue
        for name in _collect_helper_defs(module_path):
            full = f"{module_name}::{name}"
            helpers_seen.append(full)
            if full in EXEMPTED_HELPERS:
                continue
            if not _has_consumer(name, consumer_paths):
                orphans.append(full)

    assert helpers_seen, (
        "no helpers were collected from SCANNED_HELPER_MODULES — pattern "
        "set or module list drifted. Fix the regex / module path so the "
        "test stops being a no-op.")
    assert not orphans, (
        "DEAD-CODE HELPERS (no caller in any CONSUMER_MODULES — wire "
        "them in or add to EXEMPTED_HELPERS with a reason):\n"
        + "\n".join(f"  - {h}" for h in orphans))


def test_exemption_format_documented():
    """If EXEMPTED_HELPERS gets populated, every entry must carry a
    non-empty reason string (no silent dead code)."""
    for full, reason in EXEMPTED_HELPERS.items():
        assert isinstance(reason, str) and reason.strip(), (
            f"EXEMPTED_HELPERS[{full!r}] needs a documented reason.")


def test_consumer_modules_all_exist():
    """Catch path drift: every CONSUMER_MODULES entry must be a real file
    in programs/. If we rename a runner, this test catches the stale list."""
    for cm in CONSUMER_MODULES:
        assert (PROGRAMS / cm).is_file(), (
            f"CONSUMER_MODULES path stale: {cm} no longer exists in {PROGRAMS}")


def test_all_v0_1_60_to_v0_1_63_captured_helpers_have_consumers():
    """Belt-and-suspenders: the 4 specific helpers that we know to be
    wired by R11/R13/R14/R15 each appear in a consumer module's text.
    If a future refactor removes the call site, this fails fast."""
    consumer_paths = [PROGRAMS / cm for cm in CONSUMER_MODULES
                       if (PROGRAMS / cm).is_file()]
    for name in ("scrub_l_doc", "is_applicable", "na_stub",
                  "emit_l_doc_skeleton",
                  "extract_l14_versioning", "extract_l15_encoding_tables",
                  "extract_l16_compliance", "extract_l17_channels",
                  "extract_l18_interconnect"):
        assert _has_consumer(name, consumer_paths), (
            f"{name} (wired by R11-R15) lost its consumer — runner "
            f"refactor removed the call site.")
