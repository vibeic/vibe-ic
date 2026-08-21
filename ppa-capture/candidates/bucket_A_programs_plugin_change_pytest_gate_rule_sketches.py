# Bucket A — program-rule sketches for programs/plugin_change_pytest_gate.py
# Corpus-sweep REQUIRED before merging into programs/plugin_change_pytest_gate.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A suite parametrises over a population it DISCOVERS (a glob, a registry walk) but drives each member with an invocation it DECLARES (a hand-maintained table). The guard against an empty population is written as a floor — at least N — with N frozen at the count on the day the two numbers happened to agree. The floor then passes forever while the two sets drift apart, so a member added later is silently uncovered, and an entry left behind for a member since deleted is invisible in the other direction. The guard's own message keeps quoting the old count.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_population_guard_asserts_equality_not_a_floor(sample_text, ports):
    """A population guard over a discovered set must assert EQUALITY against the declared set and print the symmetric difference, never a lower bound. A lower bound answers a question nobody asked — is the population non-empty — while the question that matters is whether every discovered member is declared and every declared member still exists. A floor cannot see either drift, and it reads as coverage while holding neither."""
    # Expected signal: ERROR
    # Suggested fix action: Replace the floor assertion with a set-equality assertion between the discovered population and the declared table, whose message prints both counts and both directions of the difference. Emit it ONCE for the whole population rather than once per member, so the reader gets the list instead of N single names. THE OBVIOUS WRONG GUARD, and one is already in the tree: asserting the declared table against ITS OWN length. That is self-consistency; it passes for any table and can never see the population. Assert against the POPULATION. Where several declared tables cover one discovered population, assert each against it and assert the tables agree with one another — the defect is not confined to invocation tables: the same shape sits on the present-but-empty input table and on the hand-listed producer set, whose discovered counterpart is an importable package.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A suite that enforces a LAYER-wide property selects its population with a filename-prefix glob, because in the layer's first week the prefix and the layer were the same set. They stop being the same set as soon as the layer gains a module inside its own package, or a program that imports the layer under a different name. Every such executable is outside the population, so the layer property is unenforced on it — and the defect the suite exists to catch survives there untouched, with the suite green.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_layer_membership_is_declared_not_inferred_from_a_filename_prefix(sample_text, ports):
    """Membership of a layer is a RELATION — the executable imports the layer's package, or cites the layer's interface document — and it must be computed from that relation, never from how the file happens to be named. A naming convention standing in for a boundary silently shrinks the population every time the layer grows in a direction the convention did not anticipate, and the shrinkage is invisible because the members that fell out were never counted."""
    # Expected signal: ERROR
    # Suggested fix action: Define the population as every executable that imports the layer's package or cites the layer's interface document, and take the prefix glob as one contributor rather than as the definition. Assert that the relation-derived population is a superset of the glob-derived one, and drive every arm of the layer property over the relation-derived set.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: One tool WRITES a document and a second tool VALIDATES it. The writer's own schema documents a field as free text; the validator requires that field to match a fixed prefixed form. Each side is self-consistent and each side's tests pass. The writer accepts and emits the malformed document with no complaint, so the refusal arrives later, from a different tool, in a different run, and only if somebody thinks to run it — by which time the document has been filed and the author has moved on.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_a_writer_enforces_the_field_shapes_its_declared_consumer_requires(sample_text, ports):
    """A writer that produces a document for a declared validator must apply that validator's field-shape rules AT WRITE TIME, not leave them to be discovered downstream. The two rule sets must come from one place: a shape restated in a second file is a shape that will disagree with the first. Measured cost of the split: the writer's own documentation gave no hint the field was constrained at all, so the natural reading produced a document its sibling refused."""
    # Expected signal: ERROR
    # Suggested fix action: Import the validator's field-shape rules into the writer and apply them to every field the validator constrains, before the file is written; refuse with the validator's own message so the two tools cannot disagree about what is wrong. State the constrained shape in the writer's schema documentation as well, since an author reads the writer's contract and never the validator's. Add a two-directional test: a well-shaped field writes and validates, and a free-text field is refused BY THE WRITER rather than only by the validator.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: A validator accepts a prefixed value and names, per prefix, the vocabulary the suffix is drawn from. One branch's suffix pattern cannot express any member of the vocabulary it names — every member carries a character the pattern excludes. The branch is therefore dead: it matches nothing, it has never matched anything, and it never will. Nothing detects this, because a branch that refuses everything looks exactly like a branch nobody has used yet, and the error message lists it among the supported forms.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_an_accepted_value_branch_must_be_able_to_express_its_own_vocabulary(sample_text, ports):
    """Where a validator's accepted form names a vocabulary that exists in the tree, at least one member of that vocabulary must satisfy the form; a branch satisfied by no member is dead and must fail the suite rather than sit in the help text. The check is the vocabulary itself run through the pattern — a single pass over a list that is already machine-readable — so it stays true as either side changes, which is the only way it catches the case where the vocabulary gains its separator later."""
    # Expected signal: ERROR
    # Suggested fix action: For every branch of an accepted-value pattern that names an enumerable in-tree vocabulary, run every member of that vocabulary through the branch and assert at least one is accepted. Report the branch, the vocabulary size, and the accepted count. Measured on this tree: the branch naming the flow's canonical steps accepts 0 of 42 of them, because every canonical step identifier is dotted and the branch's suffix admits only word characters and hyphens. Widen the suffix to the vocabulary's real character set, and add the census so the next divergence fails at the suite rather than at a filing.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.66
# Pattern: An optional dependency is imported inside a handler that catches the import failure, and the fallback is correct for the case where the package is missing entirely. The package is then used through an attribute that only exists from a later release. On a host carrying an older release the import SUCCEEDS, the handler never runs, and the attribute access raises — inside a program whose exit codes reserve one value for a finding about the subject under test, so a crash publishes itself as a verdict. The test-side guard has the same hole from the other side: skipping on whether the import works covers one of the two ways the dependency can be out of reach.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_an_optional_import_is_guarded_by_capability_not_by_exception_type(sample_text, ports):
    """Guard an optional dependency on the CAPABILITY the code uses, never on whether the import raised. Present-but-too-old and absent are different states and only one of them is an import failure; the guard that conflates them fails on the state that is harder to notice, because everything up to the attribute access behaves normally. The same rule binds the test side: a skip predicated on importability reports NOT-RUN for the absent case and a red for the too-old one, and neither is the honest answer, which is that the verification did not run and here is the command that would let it."""
    # Expected signal: ERROR
    # Suggested fix action: For every handler catching an import failure and binding a name, require a capability check on each attribute of that name used outside the handler, and make the fallback path set an explicit capability flag the use sites read. Route the test-side skip through the not-verified tier rather than a bare skip, carrying the remedy command, so the roll-up sees an unanswered question instead of a green tick. Measured cost of the version-gated case: the gate crashed and returned the exit code reserved for a finding about the subject, and 33 test identifiers were red on a stock host for that one attribute. A broad static screen over this tree finds 79 of 131 handler sites using an attribute of the guarded name outside the handler; that is an UPPER BOUND on candidates and not a defect count, because a site whose use is already behind a capability flag satisfies the rule and the screen cannot see the flag.
    return []  # list of findings — TODO implement
