# DISTIL — what became a program, what did not, and the measurement for each

The capture step produced `recoveries.json`; this file records the DISTIL step
run against it on 2026-08-22, so the next lane starts from a measurement
instead of rediscovering one. Every disposition below is backed by a number
taken on this tree.

Generated from the tree, not typed: a count in this file is derived from
`recoveries.json` and from `programs/` at the moment it was written.


## jcap-chip

Four shipped. Per the 2026-08-22 F13 ruling they are CENSUSES, not gates:
the gate for each of those four names is another lane's implementation, which
refuses over a narrow population with no inventory. A census reports the wide
population and the recorded debt, and must never be wired as a blocking check.

Bucket-A records: **13**

### Shipped as an instrument (4)

* `programs/explicit_argument_outranks_the_environment_pointer_census.py` — census
  with `programs/tests/test_explicit_argument_outranks_the_environment_pointer_census.py`
* `programs/local_clone_does_not_borrow_objects_census.py` — census
  with `programs/tests/test_local_clone_does_not_borrow_objects_census.py`
* `programs/only_the_declaring_step_writes_its_output_census.py` — census
  with `programs/tests/test_only_the_declaring_step_writes_its_output_census.py`
* `programs/provenance_value_is_resolved_not_constant_census.py` — census
  with `programs/tests/test_provenance_value_is_resolved_not_constant_census.py`

### Not shipped (9)

Each carries its measured reason:

* **`declared_basis_matches_the_session_inputs`**  
  HALF IMPLEMENTED. STA population done: `phase3_one_shot_runner.py:31810` refuses a POST_ROUTE basis in a pre-layout step, `_sta_basis.py` is the single reader, and a dedicated test pins the re-run case. POWER population NOT covered — the record's own instance — and needs a runtime check over an emitted power deck.

* **`emitted_script_paths_are_project_relative`**  
  ALREADY IMPLEMENTED as `emitted_script_portability_check.py`, imported by `phase3_one_shot_runner.py:86` as 'the ONE host-path predicate'. Its docstring carries the same measured instance. It is a RUNTIME check over an emitted run tree, which is why two static formulations measured ZERO over 87-102 emitting modules.

* **`every_required_metric_key_has_a_producer`**  
  ALREADY IMPLEMENTED as `_ppa/search_feasibility.py::_axis_names_match_terms()`, whose docstring states the rule almost verbatim. Test-enforced, scoped to the PPA search lane's nine terms. The timing population is not covered and cannot be by a static scan: 13 metric-shaped keys emitted, 1 read through subscripts. That lane can check it because it declares BOTH vocabularies as tuples; the timing population declares neither.

* **`generated_values_state_whether_they_were_read_or_defaulted`**  
  NOT IMPLEMENTED. 118 constraint-emitting modules; read-or-defaulted design quantities found: 4 via `.get(k, DEFAULT)` (all already disclosing), 2 when broadened, neither the class. The record's instance is a table lookup whose fallback is not a literal at the assignment site, so there is no static signature. `declared_clock_period.py` is the value-specific program the record's notes name.

* **`measurement_only_artefact_is_not_a_verdict_source`**  
  ALREADY IMPLEMENTED as `em_peak_current_authority_check.py` — 'the EM peak current must reach a COMPARISON, or the step must name the authority it lacks' — beside `em_current_density_check.py`, the real sign-off producer. Both name `reports/phase3/em.json` with `verdict: MEASURED`, the record's own artefact.

* **`prepared_checkout_states_the_revision_it_holds`**  
  NOT IMPLEMENTED. The record's instance is a clone from a LOCAL repository; scanning every non-test module under programs/ and tools/ finds THREE git clone sites and all three clone from a remote URL — zero from a local path. The defect happens as an ad-hoc operation, not at a source site. Adjacent measurement: of the three, `ip_catalog_upstream_audit.py` proves its revision and the other two do not.

* **`printed_remedy_runs_as_printed`**  
  DROPPED. Measured at both ends: broad form 35 hits (mostly prose and <placeholder> help text), narrow form 1 hit and that one a FALSE POSITIVE (`git commit --amend` offered as advice for the reader's own repo). No middle setting has a true positive; the property is a construction discipline and this tree has no shared-builder convention to key on.

* **`signoff_report_states_its_stage`**  
  DEFERRED, population 2. The flow declares exactly two STA sign-off reports and the module writing them stamps STA_BASIS 41 times; the reader's docstring records the instance as repaired. A gate would be population 2, findings 0.

* **`test_aggregate_carries_its_runtime_identity`**  
  HALF IMPLEMENTED. Producer side done: `trusted_pytest_entry.py:268` stamps the identity — `schema`, `python` (the interpreter), `entry`, `plugin` and `modules` — and exports it as `VIBEIC_PYTEST_RUNTIME_IDENTITY`; `_pytest_progress_plugin.py:144` forwards it onto the `session_start` record and `pytest_per_file_junit.py:438` (`_runtime_identity`) VALIDATES it, returning None on any ambiguity. (Corrected 2026-08-22: this line previously cited `pytest_per_file_junit.py:438` as the stamp. That function is the CONSUMER-side validator, not the producer — it takes a value and returns the identity or None. The disposition is unchanged, since a producer does exist; the citation named the wrong end of the chain.) Consumer side missing and it is the half that matters: `landing_merge_verdict.py` does not compare the two arms' runtime stamps before subtracting. The remedy is a guard inside the program that decides whether a branch lands.


A record here that names no program is NOT an oversight: it carries a measured
reason — already implemented elsewhere, half implemented, no static signature,
or a population too thin to earn a gate. Re-deriving those measurements is the
work this file exists to save.

## OUT OF SCOPE: the records that are not Bucket A (4 of 17)

The DISTIL brief covered the Bucket-A records only. These were NOT
examined, and are listed so a reader of a capture with 17 records and 13 dispositions can tell
*considered and excluded* from *missed*. The reason on each line is the
record's own `why_not_bucket_a` field, not a judgement added here.

- **[T]** A fatal condition downgraded to a warning leaves no machine-readable statement that the stage did not complete
  > A plugin-side rule can only enumerate the identifiers the fork has
  > ALREADY downgraded — which is what it does today, with a list of error
  > markers plus a separately added scan for the one identifier most
  > recently downgraded to a warning. That list can never include the next
  > downgrade, because the downgrade exists precisely to stop the tool from
  > erroring, so a downstream rule is guaranteed to be one release behind
  > and to fail in the passing direction. The completion statement has to
  > come from the tool that knows it did not complete.

- **[C]** An artefact index that matches whole-path literals cannot tell a reader from a writer, nor see a reader that resolves the path at run time
  > A deterministic rule is the right answer and the input is a program's
  > source text; what a program cannot decide from a bare basename
  > occurrence is whether that occurrence is a read, a write, or a name in a
  > mapping table or a comment. The measured population is eight undeclared
  > step-designated outputs mentioned by basename elsewhere, and several of
  > those mentions are not reads — so the widened pattern shipped as-is
  > produces false findings, which this module's own doctrine treats as a
  > defect to kill rather than a cost to accept. Deciding it needs source-
  > level data-flow analysis plus an individual verdict on each of the
  > eight, which is a new program and a fixture corpus, not a wider regular
  > expression.

- **[C]** A published run carries the reports it produced but not the inputs those reports name
  > The check itself IS deterministic and belongs in Bucket A — a published
  > run either carries the inputs its own reports name or it does not, and
  > that is a file-existence test over paths the reports themselves state.
  > What is large is everything the check needs before it can be turned on:
  > the contract for which inputs a published run must carry has to be
  > written, every already-published run has to be measured against it, and
  > runs have to be re-published from a flow carrying the identity stamps,
  > because switching the check on today fails the entire corpus for a
  > reason that predates the rule.

- **[D]** ?
  > (the record states no reason)

