"""The NAMED synthetic-fixture limitations of `test_good_output_passes_all_required` (#2050).

WHY THIS FILE EXISTS. Every skill ships a generated
`skills/<skill>/tests/test_compliance.py` whose
`test_good_output_passes_all_required` builds a synthetic document out of the
skill's own regexes and asserts the compliance driver returns PASS. It never
asserted anything. Before this file, the test read::

    if req_fails:
        pytest.skip("Synthetic good-output did not satisfy all required "
                    "regex patterns; ...")
    assert data["verdict"] == "PASS"

MEASURED on v1.17.79. 70 skills ship `tests/test_compliance.py`; 69 of them
ship the GENERATED `test_good_output_passes_all_required` (phase1-coverage-loop's
file is hand-written and has never had that test). Of those 69, 53 took the
`skip` and 16 reached the assert. Of the 16, zero were red. So the assert ran
on 16 of 69 and the other 53 reported a green run while asserting nothing at
all — which is how #2048's defect survived: the acceptance command in that
issue produced byte-identical node-id sets on both arms, because the one test
that would have caught it skipped before its assert.

A BLANKET SKIP IS REPLACED BY A NAMED LIST, NOT BY ANOTHER BLANKET. The 53 are
enumerated below, per skill, by the exact requirement IDs the synthesiser
cannot satisfy. That turns an invisible 53 into a list a reader can shrink, and
it is checked BOTH WAYS: the generated test asserts the measured set EQUALS the
declared set, so

  * a compliance.yaml that grows a new unsatisfiable pattern reddens (the set
    grew and the list does not say so), and
  * a pattern loosened until the synthesiser CAN satisfy it also reddens, with
    a message telling the reader to delete the entry.

Neither is possible under a skip.

THE CAUSE IS THE SYNTHESISER, NOT THE SKILLS. `_pattern_to_satisfier` in the
generated test rewrites a regex into a literal by hand. Eight distinct
requirement IDs defeat it, in four measured ways — every one verified by
running the satisfier and the pattern against each other:

  NONCAPTURING  `(?:A|B)` — the alternation rule keeps the `?:`, so
                `(##\\s+(?:Output|Findings))` yields the literal `## (?:Output)`,
                and an optional `(?:run\\s+)?` is emitted verbatim.
  METACHAR      `.?` / `.*` survive into the literal, where `.?` is TWO
                characters but matches at most one.
  ESCAPE        the final `re.sub(r'\\', '', s)` turns `\b` into the letter
                `b` and leaves an inline `(?i)` flag as literal text.
  REPETITION    `{7,40}` is copied through instead of being expanded.

Fixing the synthesiser would shrink this list; that is a separate change and
was deliberately NOT bundled with #2050, because it would have moved 53 rows at
once in the same diff that first made them visible.

#2057 IS THAT SEPARATE CHANGE, AND THE LIST IS NOW EMPTY. `_pattern_to_satisfier`
no longer rewrites the pattern's surface text; `_shared/pattern_satisfier.py`
walks the parse tree the `re` module itself produces and verifies its own answer
with `re.fullmatch` under the driver's audit flags before returning it. All four
causes above are structural consequences of reading the surface instead of the
structure, and all four went at once:

    53 skills declared, over 8 requirement IDs   ->   0 skills, 0 IDs
    generated compliance tests                        69 -> 69 (membership
                                                      unchanged; no skill
                                                      added or removed)

The measured membership of the removal is in the #2057 lane evidence
(`limits_measured_FINAL.txt`): every one of the 53 named below was removed, none
survived, and none was newly added. THE FILE IS KEPT, EMPTY. The generated test
still asserts measured == declared, so a required pattern that becomes
unreachable in future reddens immediately and lands here by name — which is the
direction this register was built to catch. Deleting an empty register because
it is momentarily unused is how the next unreachable pattern ships as a skip.

`REASONS` is kept for the same reason: it is the recorded cause of each of the
eight IDs, and `programs/tests/test_pattern_satisfier_2057.py` re-runs every one
of those eight patterns through the new satisfier, so the entries are live
evidence that the four defects are gone rather than history.
"""
from typing import Dict, Tuple

#: Why a given requirement ID defeats the synthetic-fixture generator. Keyed by
#: requirement ID because the cause is a property of the PATTERN, not of the
#: skill; several skills share the same pattern and therefore the same reason.
REASONS: Dict[str, str] = {
    'R_has_output_section':
        'NONCAPTURING: `(?:Output|Findings|...)` yields the literal '
        '`## (?:Output)`, which the pattern does not match.',
    'R_next_step':
        'NONCAPTURING: the optional `(?:run\\s+)?` is emitted verbatim, so '
        'the literal reads `Next: (?:run )?/x`.',
    'R_anti_patterns':
        'METACHAR: `Anti.?patterns` is emitted with a literal `.?`, which is '
        'two characters where the pattern matches at most one.',
    'R_four_modes':
        'METACHAR: the chosen alternative keeps its literal `.?` separators, '
        'so `pulse.?stretched` cannot match `pulse.?stretched`.',
    'R_blocking_declared':
        'ESCAPE: the trailing backslash strip turns `\\b` into the letter `b`, '
        'and the inline `(?i)` flag is left as literal text.',
    'R_no_literals':
        'ESCAPE + NONCAPTURING: nested optional groups collapse into '
        '`(?i)chip-?agnostic?no design-?literals?b)`.',
    'R1_handoff_line':
        'REPETITION: `{7,40}` is copied through instead of expanded, so the '
        'literal carries `0{7,40}` where seven hex digits are required.',
    'R1_closing_comment_cites_a_commit':
        'ESCAPE + REPETITION: `\\b[0-9a-f]{7,40}\\b` becomes `b0{7,40}b`.',
}

#: skill -> the requirement IDs its synthetic good-output cannot satisfy.
#: MEASURED, never estimated. Shrink an entry when you fix the pattern or the
#: synthesiser; delete the entry when it becomes empty. Do NOT add an entry to
#: silence a red — a new red here means a real requirement stopped being
#: reachable, and the generated test says which.
#:
#: EMPTY since #2057. It is not a dead register: the generated test asserts
#: measured == declared in BOTH directions, so the first pattern that becomes
#: unreachable for `_shared/pattern_satisfier.py` reddens 69 tests at once and
#: is written here by name, with its cause in REASONS above.
SYNTHETIC_FIXTURE_LIMITATIONS: Dict[str, Tuple[str, ...]] = {}

#: THE 53 THAT WERE HERE, kept as the record of what #2057 removed — so the
#: claim "all 53 went" is a membership a reader can check rather than a count
#: to be trusted. Nothing reads this at audit time; it is asserted against the
#: live measurement in programs/tests/test_pattern_satisfier_2057.py, which
#: re-runs every one of these skills' patterns through the new satisfier.
REMOVED_BY_2057: Dict[str, Tuple[str, ...]] = {
    'ams-sim': ('R_has_output_section', 'R_next_step'),
    'analog-extraction-resim': ('R_has_output_section', 'R_next_step'),
    'analog-flow-orchestrate': ('R_has_output_section', 'R_next_step'),
    'analog-hardmacro-gen': ('R_has_output_section', 'R_next_step'),
    'analog-hw-measure': ('R_has_output_section', 'R_next_step'),
    'analog-hw-testbench-gen': ('R_has_output_section', 'R_next_step'),
    'analog-hw-tuning-loop': ('R_has_output_section', 'R_next_step'),
    'analog-layout': ('R_has_output_section', 'R_next_step'),
    'analog-netlist-gen': ('R_has_output_section', 'R_next_step'),
    'analog-output-verify': ('R_has_output_section', 'R_next_step'),
    'analog-sizing': ('R_has_output_section', 'R_next_step'),
    'analog-sizing-loop': ('R_has_output_section', 'R_next_step'),
    'analog-spec-extract': ('R_has_output_section', 'R_next_step'),
    'analog-topology-select': ('R_has_output_section', 'R_next_step'),
    'architecture-explore': ('R_has_output_section', 'R_next_step'),
    'benchmark-verify': ('R_next_step',),
    'catalog-glue-author': ('R_next_step',),
    'checkpoint-gate': ('R_next_step',),
    'community-backlog-submit': ('R_next_step',),
    'compliance-gate-spot-check': ('R_has_output_section', 'R_next_step'),
    'core-agent-loop': ('R1_handoff_line',),
    'design-for-eco': ('R_next_step',),
    'drc-fix': ('R_has_output_section', 'R_next_step'),
    'eco-plan': ('R_has_output_section', 'R_next_step'),
    'equivalence-check': ('R_has_output_section', 'R_next_step'),
    'flow-change-acceptance': ('R_blocking_declared', 'R_no_literals'),
    'fork-gatekeeper-loop': ('R1_closing_comment_cites_a_commit',),
    'formal-verify': ('R_has_output_section', 'R_next_step'),
    'fpga-hps-bridge': ('R_next_step',),
    'fpga-led-probe-allocation': ('R_four_modes', 'R_anti_patterns'),
    'fpga-signaltap': ('R_next_step',),
    'hls-c2rtl': ('R_has_output_section', 'R_next_step'),
    'hold-fix': ('R_has_output_section', 'R_next_step'),
    'hw-debug-loop': ('R_next_step',),
    'ir-drop-triage': ('R_has_output_section', 'R_next_step'),
    'lvs-triage': ('R_has_output_section', 'R_next_step'),
    'mixed-signal-cosim': ('R_has_output_section', 'R_next_step'),
    'phase1-completeness-deep-review': ('R_has_output_section', 'R_next_step'),
    'phase1-output-verify': ('R_has_output_section', 'R_next_step'),
    'phase2-rtl-verify': ('R_has_output_section', 'R_next_step'),
    'phase3-backend-verify': ('R_has_output_section', 'R_next_step'),
    'ppa-predict': ('R_has_output_section', 'R_next_step'),
    'regression-issue-fix': ('R_next_step',),
    'regression-manage': ('R_has_output_section', 'R_next_step'),
    'rtl-repair': ('R_has_output_section', 'R_next_step'),
    'rtl-review': ('R_has_output_section', 'R_next_step'),
    'spec-review': ('R_has_output_section', 'R_next_step'),
    'spec-validator': ('R_has_output_section', 'R_next_step'),
    'sta-review': ('R_has_output_section', 'R_next_step'),
    'synth-doctor': ('R_has_output_section', 'R_next_step'),
    'tapeout-checklist': ('R_has_output_section', 'R_next_step'),
    'testbench-gen': ('R_has_output_section', 'R_next_step'),
    'yield-diagnostic': ('R_has_output_section', 'R_next_step'),
}


def reason_for(skill: str) -> str:
    """One sentence per skill, composed from the per-requirement causes."""
    ids = SYNTHETIC_FIXTURE_LIMITATIONS.get(skill)
    if not ids:
        return ''
    return (f"synthetic good-output cannot satisfy {list(ids)} — "
            + ' '.join(REASONS.get(i, 'no cause recorded.') for i in ids))
