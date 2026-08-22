# F4 ships: the identifier no longer asserts the refuted premise

## The reasoning I had to correct first

I declined this in an earlier pass with: "the fix is a rename inside
`pad_ring_gen.py` on main, and this brief forbids pushing to main." That
conflates two different things. **Every fix here reaches main through a branch**
— that is how the F2 checker shipped. Nothing about this fix required touching
main directly. I had over-restricted myself and left a measured, bounded defect
in place on that basis.

## What was wrong, measured on `origin/main` a4caccefe

`git merge-base --is-ancestor c56b8e1b1 origin/main` -> NOT an ancestor. The
rename the source report says landed did not land. Main shipped:

| site | asserted |
|---|---|
| `pad_ring_gen.py`:246 | artefact key `"rotation_vertical_inert"` |
| `pad_ring_gen.py`:185 | constant `ROTATION_VERTICAL_INERT` |
| `pad_ring_gen.py`:67 | heading "`PAD_ROTATION_VERTICAL` IS INERT" |
| `pad_ring_gen.py`:69 | "the placer does not read it" |
| `pad_ring_gen.py`:618 | comment naming the old key |
| `pad_ring_gen.py`:627 / :654 | the rc 2 message, user-visible |
| `_pad_ring.py`:275 | "a CONSTANT of the placer, not a function of the declared rotation" |
| `test_pad_ring.py`:1210, :1227 | two TEST NAMES saying "inert" |
| `test_pad_ring.py`:1219 | a local variable named `inert` |

The variable is not inert. `-rotation_vertical` steers SOUTH and NORTH;
`-rotation_horizontal` steers WEST and EAST. The four-process table is correct
and the inference drawn from it was not.

## What changed, and what deliberately did not

CHANGED: the key, the constant, the heading, the four prose claims, the two
test names, the local variable, and the `reason` string that reaches the user
in the rc 2 refusal — which told them something false about why.

**NOT CHANGED: any geometry, any orientation value, any verdict.**
`VERTICAL_SIDE_ORIENT` still holds the values it held. The rc 2 behaviour is
identical. The finding rule id `PAD_ROTATION_VERTICAL_NOT_HONOURED` was already
correct and was preserved — the mutation below asserts it survives, so a
careless global rename cannot pass as this fix.

The open question is left open, in the comment where a reader meets it: whether
WEST and EAST should be DERIVED from a declared non-default
`PAD_ROTATION_HORIZONTAL` rather than held as constants measured at its
default. That needs one OpenROAD run and must not be acted on before it has
one. I have run no tool.

## The reds

Two new tests:

* `test_the_report_key_does_not_assert_the_refuted_premise` — the report
  carries `rotation_vertical_not_honoured`, not `rotation_vertical_inert`, and
  the reason says "does not implement it", not "the placer does not read it".
* `test_no_identifier_in_the_pad_ring_producer_asserts_inertness` — the
  GENERAL rule, walked over the producer's AST: no `Name` and no emitted string
  literal may assert inertness. Prose may discuss it, and three places now
  explicitly deny it.

Mutation — every spelling reverted, the rule id spared:

    MUTATION APPLIED; tokens gone, rule id preserved
    FAILED ...::test_the_default_vertical_rotation_proceeds_and_is_told_it_is_not_honoured
    FAILED ...::test_the_not_honoured_disclosure_is_in_every_report_including_the_skip
    FAILED ...::test_the_report_key_does_not_assert_the_refuted_premise
    FAILED ...::test_no_identifier_in_the_pad_ring_producer_asserts_inertness
    4 failed, 95 passed

    restored -> 99 passed, `pad_ring_gen.py` byte-identical

Two of those four are PRE-EXISTING tests whose NAMES said "inert". They passed
before the mutation only because I had already renamed them: **a test name is
an identifier, and it asserts the same proposition as a schema key.** That is
the rule finding its own second and third instance in the file it was written
about.

## The fourth mutation-that-was-not, and the guard that caught it

The first attempt reverted only the QUOTED key and the constant, and the token
survived in the unquoted prose mentions. The mutation's own assertion caught it
before any test ran:

    AssertionError: TOKEN SURVIVED — no-op

and the pytest run that followed reported `99 passed`, which would have read as
"the tests survive the mutation" for the fourth time tonight. Every mutation on
this branch now proves the property changed before it reports a result. This is
the only reason that non-result was not written down as evidence.
