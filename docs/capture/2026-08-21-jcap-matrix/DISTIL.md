# DISTIL — what became a program, what did not, and the measurement for each

The capture step produced `recoveries.json`; this file records the DISTIL step
run against it on 2026-08-22, so the next lane starts from a measurement
instead of rediscovering one. Every disposition below is backed by a number
taken on this tree.

Generated from the tree, not typed: a count in this file is derived from
`recoveries.json` and from `programs/` at the moment it was written.


## jcap-matrix

All ten shipped as blocking gates. This capture was the assigned brief.

Bucket-A records: **10**

### Shipped as an instrument (10)

* `programs/content_pinned_authority_verified_only_at_merge.py` — gate
  with `programs/tests/test_content_pinned_authority_verified_only_at_merge.py`
* `programs/declaration_searched_only_inside_a_truncated_window.py` — gate
  with `programs/tests/test_declaration_searched_only_inside_a_truncated_window.py`
* `programs/declared_invocation_accepted_by_its_own_parser.py` — gate
  with `programs/tests/test_declared_invocation_accepted_by_its_own_parser.py`
* `programs/denial_that_constitutes_the_value_it_appears_to_negate.py` — gate
  with `programs/tests/test_denial_that_constitutes_the_value_it_appears_to_negate.py`
* `programs/invocation_proved_by_parse_not_by_text.py` — gate
  with `programs/tests/test_invocation_proved_by_parse_not_by_text.py`
* `programs/population_pin_without_its_member_set.py` — gate
  with `programs/tests/test_population_pin_without_its_member_set.py`
* `programs/reference_control_resolved_through_a_mutable_ref.py` — gate
  with `programs/tests/test_reference_control_resolved_through_a_mutable_ref.py`
* `programs/registry_is_the_iteration_domain.py` — gate
  with `programs/tests/test_registry_is_the_iteration_domain.py`
* `programs/spawned_gate_whose_status_is_discarded.py` — gate
  with `programs/tests/test_spawned_gate_whose_status_is_discarded.py`
* `programs/wall_clock_bound_standing_in_for_a_verdict.py` — gate
  with `programs/tests/test_wall_clock_bound_standing_in_for_a_verdict.py`

### Not shipped (0)

Each was measured; see `/tmp/jdistmat_done.txt` in the authoring session,
and the reasons summarised here:


A record here that names no program is NOT an oversight: it carries a measured
reason — already implemented elsewhere, half implemented, no static signature,
or a population too thin to earn a gate. Re-deriving those measurements is the
work this file exists to save.
