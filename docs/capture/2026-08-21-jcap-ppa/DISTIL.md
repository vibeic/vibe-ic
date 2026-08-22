# DISTIL — what became a program, what did not, and the measurement for each

The capture step produced `recoveries.json`; this file records the DISTIL step
run against it on 2026-08-22, so the next lane starts from a measurement
instead of rediscovering one. Every disposition below is backed by a number
taken on this tree.

Generated from the tree, not typed: a count in this file is derived from
`recoveries.json` and from `programs/` at the moment it was written.


## jcap-ppa

Four shipped as gates. One of them, layer_membership_..., is RED on this tree
deliberately and carries no inventory: a waiver would make the question
disappear.

Bucket-A records: **12**

### Shipped as an instrument (4)

* `programs/layer_membership_is_declared_not_inferred_from_a_filename_prefix.py` — gate
  with `programs/tests/test_layer_membership_is_declared_not_inferred_from_a_filename_prefix.py`
* `programs/population_guard_asserts_equality_not_a_floor.py` — gate
  with `programs/tests/test_population_guard_asserts_equality_not_a_floor.py`
* `programs/published_absence_claim_is_rechecked_against_the_tree.py` — gate
  with `programs/tests/test_published_absence_claim_is_rechecked_against_the_tree.py`
* `programs/two_input_selectors_given_together_must_refuse.py` — gate
  with `programs/tests/test_two_input_selectors_given_together_must_refuse.py`

### Not shipped (8)

Each carries its measured reason:

* **`accepted_value_branch_can_express_its_own_vocabulary`**  
  NOT IMPLEMENTED. Needs the branch-to-vocabulary mapping DECLARED; this tree declares it in one lane only. Running the rule's own method anyway — 77 canonical step ids (6 dotted) through every STEP-named compiled pattern — gives 6 patterns accepting 0 of 77, and all six are FALSE: they are prose extractors ('Timestep: 1e-9 s') with nothing to do with step identifiers.

* **`discovery_selects_on_the_parsed_document_not_the_filename`**  
  NOT IMPLEMENTED. The exact half — a gate whose input glob matches its own output report — is clean: 7 gates discover typed input by a semantic-token glob, 0 self-adjudicate. The valuable half needs a parsed corpus this checkout does not carry: all 7 parse, 3 select on a schema key, and the other 4 may use a structural predicate, which the record permits and a static scan cannot distinguish from its absence.

* **`gate_proof_vocabulary_has_a_producer`**  
  NOT IMPLEMENTED. Same shape and same disposition as the chip capture's `every_required_metric_key_has_a_producer`: the predicate exists as `_axis_names_match_terms()` and works only because that lane declares BOTH vocabularies as tuples. No other population declares either side.

* **`metric_constant_across_differing_arms_is_not_measured`**  
  NOT IMPLEMENTED. Needs the results of MULTIPLE ARMS, a runtime corpus a clean checkout does not carry. A checker could be authored but not verified here, and shipping a gate whose sweep cannot be run is what this lane refused throughout.

* **`optional_import_is_guarded_by_capability_not_exception_type`**  
  NOT IMPLEMENTED, AND THE RECORD AGREES: it states its own screen is 'an UPPER BOUND on candidates and not a defect count ... the screen cannot see the flag'. An independent screen reproduced their numbers — 131 import guards, 77 with attribute use, against their 131/79. 31 of 131 set a capability marker, 100 do not, and it never converges without knowing which attributes are version-gated.

* **`required_scope_keys_are_emitted_by_their_producer`**  
  NOT IMPLEMENTED. As above — the consumer's required keys and the producer's emitted keys must both be declared before they can be cross-referenced, and only the PPA search lane declares either.

* **`runtime_output_path_may_not_resolve_inside_the_installed_tree`**  
  NOT IMPLEMENTED as a scan: 37 functions mkdir a caller-supplied destination's parent and ZERO of the 37 carry a containment check, so a gate flags the whole population and discriminates nothing. That is the record's own point — the fix belongs in the shared writer once. `_atomic_artefact.py:145` mkdirs with no resolution and no refusal, and that file is a PINNED AUTHORITY PATH.

* **`writer_enforces_the_field_shapes_its_consumer_requires`**  
  NOT IMPLEMENTED. Needs the writer-to-validator pairing declared; nothing in `schemas/` declares which writer a validator governs, so which validator's rules a given writer must import is a judgement rather than a lookup.


A record here that names no program is NOT an oversight: it carries a measured
reason — already implemented elsewhere, half implemented, no static signature,
or a population too thin to earn a gate. Re-deriving those measurements is the
work this file exists to save.
