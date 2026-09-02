#!/usr/bin/env python3
"""_sim_results_bridge.py — shared, chip-AGNOSTIC reader for the professional
cocotb testbench result (the NEW TB path emitted by professional_tb_gen under
``phase2/stage1/sim_professional/<top>/results.xml``).

Motivation (2026-07-13): the canonical Step-4 (Simulation) verdict historically
keyed ONLY on the AID reference-TB chain — ``phase2/stage1/sim/results.xml``
(a CONNECTIVITY_PASS bridge written by the WAIVED reference TB for the no-oracle
classes) and ``reports/phase2/coverage/coverage_actual.json`` (SKIPPED-CONDITION
"no reference-TB transcript", #436). For a class whose functional oracle IS
derivable (e.g. a bit-serial multiplier), ``professional_tb_gen`` already RAN a
real cocotb streaming-scoreboard against the real rtl/ and wrote a standard
JUnit ``results.xml`` with ``failures="0"`` — genuine functional evidence that
the reference-TB-only verdict never looked at. This bridge lets the Step-4
aggregator RECOGNISE that real PASS.

It is deliberately a pure, side-effect-free parser:
  * ``parse_junit(path)`` — sum tests/failures/errors/skipped across every
    ``<testsuite>`` in a cocotb/JUnit ``results.xml``. Returns None for a
    non-JUnit document (e.g. the ``<results><verdict>…`` connectivity bridge),
    so it can NEVER mistake the connectivity waiver for a functional PASS.
  * ``find_professional_tb_pass(project)`` — glob the professional-TB result(s)
    and return a summary ONLY when a real functional PASS is present
    (``tests > 0`` AND ``failures == 0`` AND ``errors == 0``). Globs on ``*``
    (the DUT sub-dir) so it is chip-AGNOSTIC — it keys on the JUnit structure
    and the standard path, never on a chip / vendor / SKU literal.

Anti-fabrication (§4.05): this module only ADDS recognition of a REAL passing
transcript. A missing / unparsable / failing / vacuous (zero-test) professional
result yields None, so every caller degrades to EXACTLY its prior behaviour.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

# Standard emission path for professional_tb_gen: sim_professional/<top>/results.xml
_PROFESSIONAL_GLOB = "phase2/stage1/sim_professional/*/results.xml"


def parse_junit(path: Path) -> Optional[Dict[str, Any]]:
    """Parse a cocotb / JUnit ``results.xml`` and aggregate the test counts.

    Returns a dict ``{tests, failures, errors, skipped, passed}`` (ints) or
    ``None`` when the file is absent, unparsable, or is NOT a JUnit document
    (no ``<testsuite>`` / ``<testcase>`` elements — e.g. the ``<results>``
    connectivity bridge, which must never be read as a functional PASS)."""
    try:
        if not path.is_file():
            return None
        root = ET.fromstring(path.read_text(errors="replace"))
    except (OSError, ET.ParseError):
        return None

    # Collect every <testsuite> — the root may itself be <testsuites> (the
    # cocotb wrapper) or a single <testsuite>. Anything else is not JUnit.
    suites: List[ET.Element] = []
    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = list(root.iter("testsuite"))
    else:
        # Not a JUnit document (e.g. the <results><verdict>… bridge).
        return None
    if not suites:
        return None

    def _int(el: ET.Element, attr: str) -> int:
        try:
            return int(el.get(attr, "0") or "0")
        except (TypeError, ValueError):
            return 0

    tests = sum(_int(s, "tests") for s in suites)
    failures = sum(_int(s, "failures") for s in suites)
    errors = sum(_int(s, "errors") for s in suites)
    skipped = sum(_int(s, "skipped") for s in suites)
    # Some emitters omit the tests= attribute; fall back to counting <testcase>.
    if tests == 0:
        tc = sum(1 for s in suites for _ in s.iter("testcase"))
        if tc:
            tests = tc
    passed = max(tests - failures - errors - skipped, 0)
    # #—: WHICH producer wrote this transcript. The slot is a PATH, and more
    # than one producer legitimately writes into it (the cocotb professional TB
    # and the L10 unit-TB executor). A message that names the slot's historical
    # producer for a result another producer wrote is a small lie in the one
    # sentence a reader trusts, so carry the suite's own name.
    names = [s.get("name") or "" for s in suites if (s.get("name") or "")]
    return {
        "suite_names": names,
        "tests": tests,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "passed": passed,
    }


def find_professional_tb_pass(project: Path) -> Optional[Dict[str, Any]]:
    """Return a summary of the professional cocotb TB result IFF it is a real
    functional PASS, else ``None``.

    "Real functional PASS" = a JUnit ``results.xml`` under
    ``phase2/stage1/sim_professional/<top>/`` with ``tests > 0`` AND
    ``failures == 0`` AND ``errors == 0``. A vacuous (zero-test), failing, or
    all-skipped result returns ``None`` — the professional path did not close
    functional verification, so the caller keeps its prior verdict.

    Summary keys: ``rel_path`` (POSIX, project-relative), ``tests``,
    ``failures``, ``errors``, ``skipped``, ``passed``. chip-AGNOSTIC."""
    for cand in sorted(project.glob(_PROFESSIONAL_GLOB)):
        summ = parse_junit(cand)
        if not summ:
            continue
        if (summ["tests"] > 0
                and summ["failures"] == 0
                and summ["errors"] == 0
                and summ["passed"] > 0):
            try:
                rel = cand.relative_to(project).as_posix()
            except ValueError:
                rel = cand.as_posix()
            return {"rel_path": rel, **summ}
    return None


def substantiated_functional_evidence(project: Path,
                                      rel_path: str) -> Optional[Dict[str, Any]]:
    """Validate a record's own ``<functional_evidence>`` pointer.

    A record that CLAIMS ``functional_verified=true`` is a forgery unless it can
    SHOW the transcript. This resolves the pointer against the project and
    applies the same predicate `find_professional_tb_pass` applies — a real
    JUnit document with ``tests > 0``, ``failures == 0``, ``errors == 0`` and
    ``passed > 0``. Anything else (absent, unparsable, non-JUnit, vacuous,
    failing, or escaping the project) returns None, so a caller that refuses on
    None keeps refusing every forgery it refused before.

    chip-AGNOSTIC: a project-relative path and the JUnit structure, nothing else.
    """
    rel = (rel_path or "").strip()
    if not rel:
        return None
    try:
        cand = (project / rel).resolve()
        # A pointer that leaves the project is not this run's evidence.
        cand.relative_to(project.resolve())
    except (OSError, ValueError):
        return None
    summ = parse_junit(cand)
    if not summ:
        return None
    if (summ["tests"] > 0 and summ["failures"] == 0
            and summ["errors"] == 0 and summ["passed"] > 0):
        return {"rel_path": rel, **summ}
    return None
