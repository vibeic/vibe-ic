# F2 ships with three reds, and one of them was a non-result first

Tree at `2255596ee`, `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` cleared before
each arm, each mutation reverted from a pristine copy taken before the first.

BASELINE: `test_upstream_contract_parity.py` — **22 passed**.

## M1 — revert `_mentions` to the old bare-quoted-literal predicate

    checker rc=1
    FAIL: 1 unaccounted name(s) ...
      - PAD_FAKE_SITES is classified implemented and does not appear in
        programs/_pad_ring.py. The register claims an implementation the
        module does not contain.

This is the load-bearing red. **The predicate fix and the register move are
coupled and neither is green alone:**

* old predicate + old register (`known_gap`) → exit 0, and WRONG — the state
  on main today, passing over its own blind spot;
* new predicate + old register → rc 1, "classified `known_gap` and DOES
  appear";
* old predicate + new register → rc 1, "claims an implementation the module
  does not contain" (this arm);
* new predicate + new register → exit 0, and the 0 now means something.

A register move on its own would have turned the check red. That is why the
change is one change.

## M2 — neutralise the unclassified-name loop

    FAILED ...::test_an_upstream_name_in_no_class_is_a_finding
    1 failed, 21 passed

**THE FIRST ATTEMPT AT THIS MUTATION DID NOT APPLY.** I anchored on the string
`"is in no class"`; the source reads `in no class` split across two f-string
lines, so `str.index` raised, the patch never landed, and the test run that
followed reported **22 passed** — which I could have written down as "the test
survives the mutation" when in fact no mutation had been made. The tell was the
`ValueError` above the pytest output, and nothing else about the run looked
wrong. Recorded because a mutation sweep whose mutations silently fail to apply
reports the tests as passing for the one reason that proves nothing.

## M3 — neutralise the `known_gap`-without-a-reference finding

    FAILED ...::test_a_known_gap_without_a_reference_is_a_finding
    1 failed, 21 passed

## RESTORED

    22 passed
    git status --porcelain: clean — the working tree is byte-identical to the
    commit the sweep started from.

## The two tests were rewritten, and not one assertion was touched

Both borrowed their fixture from the SHIPPED register: they picked
`sorted(known_gap)[0]`. Closing the last gap — which is what this change does —
turned them red with `IndexError`, in tests whose subjects are "a name in no
class" and "a gap with no reference", neither of which has anything to do with
how many gaps the repo currently has.

They now build their own fixture: M2's test drops a name from `implemented`
(populated by construction), M3's INJECTS a gap using a name from
`omitted_by_design` — chosen because those are by definition not consumed by
the module, so the staleness rule cannot also fire and make the assertion pass
for the wrong reason. Same assertions, same messages, same return codes. The
reds above are what say the rewrite did not hollow them out.
