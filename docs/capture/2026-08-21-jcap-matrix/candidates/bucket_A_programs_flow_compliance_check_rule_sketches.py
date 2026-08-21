# Bucket A — program-rule sketches for programs/flow_compliance_check.py
# Corpus-sweep REQUIRED before merging into programs/flow_compliance_check.py.

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.33
# Pattern: A deterministic check loads a tracked registry file and its only finding-emitting loop iterates that registry. Every candidate the check exists to judge is invisible unless somebody first volunteered it, so an empty registry yields a pass with a denominator of zero while the condition it guards is live elsewhere in the tree. The two shapes are told apart by structure alone: a registry that is the iteration target, versus a registry consulted as membership inside a loop over a derived population.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_registry_is_the_iteration_domain(sample_text, ports):
    """An enforcement check whose finding-emitting loop iterates an opt-in registry examines only the entries somebody volunteered. When that registry is empty in the tree, the check reports a clean verdict over a population it never looked at, and that verdict is indistinguishable from one earned by inspection. A registry must be a FILTER applied to an independently derived population, never the population itself: a check that cannot state how many candidates it examined has not examined any."""
    # Expected signal: ERROR
    # Suggested fix action: Walk every program that reads a tracked registry file. Parse it and locate each loop that can append a finding. When the loop's iteration target resolves to the registry rather than to a derived population, refuse, naming the loop line and the registry path. Require the verdict to state two denominators — candidates examined, and registry rows applied — and refuse a verdict that states neither. Apply the same refusal when the registry parses to zero rows while candidates exist, since that is the state in which the check is inert and reads as clean.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.33
# Pattern: A required marker is looked for inside a fixed-size slice of a larger text, and a miss is reported as absence. The verdict then turns on a quantity nobody chose deliberately — the length of the prose above the marker, or the length of a path prefix ahead of it — so the same input flips verdict as unrelated text grows around it. The head-slice and the tail-slice shapes are one class: in both, a bound written to limit SIZE is silently doing the work of a predicate.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_declaration_searched_only_inside_a_truncated_window(sample_text, ports):
    """A predicate deciding whether a required declaration is present must search the whole text. When the search runs over a fixed-size head or tail slice, an identical declaration reads as ABSENT purely because of where it sits, and the finding then names the wrong defect — it reports the author as having declared nothing. Declared outside the window and absent are different states and must stay different: the first is a formatting problem, the second is a governance one."""
    # Expected signal: ERROR
    # Suggested fix action: For every slice of a text that feeds a marker search whose miss is reported as a finding: on a miss, re-run the same search over the full text. When the marker is found there, emit a distinct outcome naming the byte offset and the window size, never the absence outcome. Where the window exists to bound displayed output rather than to bound the search, keep it for display and widen the search to the whole text. Report as WARN any window whose search text can exceed it, so the class closes by construction instead of one instance at a time.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.33
# Pattern: A declared invocation of a checking program is never validated against that program's own argument parser, and a parser refusal shares one exit status with a legitimate not-applicable skip. Any misdeclared invocation therefore lands in a passing tier with nothing examined. The class is systemic wherever a document declares invocations as text and an executor runs them without ever asking whether the program accepts them.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_declared_invocation_accepted_by_its_own_parser(sample_text, ports):
    """An invocation declared in a flow document is a contract with the invoked program's own argument parser. When the declared arguments omit something that parser marks required, the parser refuses before the check ever runs, and that refusal status collides with the status the flow reserves for input-not-applicable. The gate then scores as a pass on every input forever, and the failure points the wrong way: the worse the run, the more certainly it passes."""
    # Expected signal: ERROR
    # Suggested fix action: Extend the existing invocability probe from the umbrella-registry population to the flow-document population, reusing the shared invocation helper so one definition of accepted survives. For each declared clause: resolve the program, resolve any subcommand the declared arguments select, and drive the parser alone with those arguments. Report a parser refusal as a declaration defect in its own tier and never fold it into not-applicable. Resolving subcommands is load-bearing, not a refinement: a static comparison against every required argument in the file reports a false positive on a program whose modes are subcommands, measured at exactly one such false positive over the declared population.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.33
# Pattern: A wiring or consumption audit decides that one module invokes another by searching the caller's raw text. Prose naming the callee — a cross-reference in a docstring, a comment, a help string — counts as a call, so the audit's positive verdicts silently include every mention. The inverse holds too: a text scan cannot see a call assembled at run time, so both directions of such an audit are unsound and its clean verdicts carry no information.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_invocation_proved_by_parse_not_by_text(sample_text, ports):
    """Whether one module invokes another is a question about code, and a text search cannot answer it. About half of a large orchestrating module is prose, and a name that appears there is graded as a call, so the audit certifies wiring that does not exist. The consequence lands on the design: a step whose producer nothing dispatches reports a missing artefact for every input forever, and every reader charges that to the design rather than to the flow."""
    # Expected signal: ERROR
    # Suggested fix action: Parse the caller and decide invocation from the syntax tree: a call node, an element of an argument vector, or an import — never a docstring, a comment, or a help string. Where the caller builds an argument vector from a constant, resolve the constant. Report a name that occurs only in prose as its own outcome so the audit can state how many of its positive verdicts came from prose. Apply the same rule to consumption audits, where the question is whether a status is read rather than whether a name appears.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.33
# Pattern: A test or a generated document pins the SIZE of a live population and never its MEMBERS. Compensating changes are invisible to it, and so is a restatement applied for a departure but not for the matching arrival — the pin can be arithmetically correct and still describe a different set. Where several pins over one population exist, the coarsest asserts first, so a finer pin that went stale in the same move is never reached.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_population_pin_without_its_member_set(sample_text, ports):
    """A pinned population count is invariant under any change that adds and removes the same number of members. An arrival and a departure landing in one batch leave the number identical, so the pin stays green while the population it names has become a different set, and a raw count read before and after tells the reader nothing. A count pin is a measurement only when the identities producing it are pinned beside it."""
    # Expected signal: ERROR
    # Suggested fix action: For every constant compared against a live re-derivation of a population size, require a member-identity pin in the same module, compared as a set in BOTH directions so a missing member and an extra member are named separately. Where pinning identities is impractical, require the count to be re-derived from the accessor at assertion time and refuse a hand-written literal. Refuse a membership assertion placed inside the branch that filters INTO the population, since that shape can only see a member arriving and never one leaving. Report each count-only pin together with the accessor it is compared against, so the population can be re-derived instead of argued about.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.33
# Pattern: A tracked manifest records content hashes for a set of protected paths and is consulted only by the merge-time tool. Every check that runs before merge is blind to a mismatch, so a branch that legitimately edits a pinned path carries an invisible obligation until a later tool refuses it. The verdict is correct and arrives at the wrong time, which is a different defect from a verdict that is wrong.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_content_pinned_authority_verified_only_at_merge(sample_text, ports):
    """A manifest that pins the content hash of authority files is rendered against one base and verified at one moment. A change that edits a pinned file is legitimate and expected, but between the edit and the re-render the manifest describes no tree that exists, and nothing on the editing side says so. A pin whose only reader runs after the point where it could still be repaired reports the breakage to the one person who cannot act on it."""
    # Expected signal: WARN
    # Suggested fix action: Add a report-only check over the pinned path set: hash each path in the working tree, compare against the manifest, and name every mismatch together with the manifest identifier that must be re-rendered and the tool that renders it. Report rather than block — a mismatch on a branch that edits an authority path is the expected state, and blocking would refuse the very change the manifest exists to record. Run it wherever the repository-wide checks run, so the obligation is visible to the author instead of to the merge.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.33
# Pattern: A test or a gate reads a reference version of a file, or derives the set of subjects it will cover, by resolving a mutable revision name instead of an immutable one. What the code covers then depends on where that name points at run time, so one tree yields different coverage in two clones and the difference surfaces as a changed collection count rather than as a defect. Only an immutable object name can hold a control's reference point still.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_reference_control_resolved_through_a_mutable_ref(sample_text, ports):
    """A negative control must be built from a state that stays legitimately vulnerable. When the reference version is fetched by a branch name, the reference moves the moment the fix lands there, and the control begins asserting that a repaired program is still broken. The failure is silent in the direction that matters: the control stops discriminating and reads as a test that is merely wrong, rather than as coverage that has been withdrawn."""
    # Expected signal: ERROR
    # Suggested fix action: Parse every test and gate for a process call that reads a revision. Refuse when the revision argument is branch-shaped — a remote-tracking name, a bare branch name, or an upstream shorthand — in any position a revision-reading subcommand consumes. Accept a working-tree pointer used against a fixture repository the caller has just created, because there the pointer is immutable in context: the discriminator is the branch shape, not the presence of a revision. Require a full object name and require the reason for choosing that object to be stated beside it.
    return []  # list of findings — TODO implement

# Auto-captured by benchmark-enhancement-capture at plugin v1.11.33
# Pattern: A test kills its subject on a short wall-clock deadline and reports the kill as a substantive finding, with no record of the load the bound was measured under. The same identifier then reads green in one run and red in another off one tree, so a comparison between two arms attributes the difference to the change rather than to the machine — and the direction of that error is not random, because the arm run second inherits the load of the arm run first.
# CORPUS-SWEEP REQUIRED before merging: zero false-positives across
# the open-benchmark corpora used by `score_iverilog_tb.py`.

def rule_wall_clock_bound_standing_in_for_a_verdict(sample_text, ports):
    """A forward-progress deadline of a second or less, applied to a subject that spawns processes, measures the host and not the code. Under load it fires and is reported as a defect in whatever change is in flight; on an idle host it passes and the same red is reported as fixed. A timing bound is a verdict only when the load it was measured under is recorded beside it, and a verdict taken from one sample on each side of a comparison is not a comparison."""
    # Expected signal: WARN
    # Suggested fix action: Find every deadline literal below a stated floor that is compared against a wall clock in a test whose subject spawns a process. Require the verdict message to carry the load average and the elapsed time, and require the bound's own docstring to state the load it was chosen under. Refuse a deadline that is asserted as a substantive finding without those two numbers. Where a candidate red is used to compare two arms, require the arms to be interleaved rather than run in sequence, so neither inherits the other's load.
    return []  # list of findings — TODO implement
