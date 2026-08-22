# My general guard was fitted to my own sentences, and an independent fix caught it

## Two disclosures first

**My F4 rename is a near-duplicate.** `c56b8e1b1` on
`origin/jpadsite/pad-site` makes the same rename —
`ROTATION_VERTICAL_INERT` -> `ROTATION_VERTICAL_NOT_HONOURED`,
`rotation_vertical_inert` -> `rotation_vertical_not_honoured` — with the same
reasoning, and it is not an ancestor of main. I arrived at it independently and
did not check the sibling branch for it first, which is exactly the failure I
spent this branch documenting in the F2 case. The lander should take
`jpadsite/pad-site` as the vehicle: it is six commits, it carries the NORTH and
CORNER fixes too, and it has the A/B.

**What is NOT a duplicate** is the general guard — theirs fixes the variable,
this enforces the rule. That is the brief's instruction: generalise the RULE,
not the one variable.

## The guard was wrong, and the independent fix is what proved it

First version scanned every string literal for "inert" and excluded the
specific phrases I had written ("not inert", "READ AS INERTNESS"). Run against
three trees:

    origin/main (the defect)              FAIL
    jpadsite/pad-site (independent fix)   FAIL   <-- wrong
    this branch (my fix)                  PASS

It failed the independent fix because that docstring retracts the claim by
QUOTING it:

    THIS SECTION SAID "IS INERT" AND "the placer does not read it" AND BOTH WERE …

**A retraction has to be able to name what it retracts.** A guard whose pass
condition is "contains the sentences the author happened to write" is fitted to
one edit and not to the rule — the precise failure this branch is about, in my
own new code, in the test written to enforce the rule against it.

## Fixed by narrowing to what the rule is actually about

The rule is about IDENTIFIERS: a name, a schema key, a function — things every
consumer keys on and none of them reads a retraction for. Prose is deliberately
not policed. The guard now walks `ast.Name` ids, `def`/`class` names, and
string literals used as DICT KEYS, and nothing else.

    origin/main (the defect)              FAIL  ['name: ROTATION_VERTICAL_INERT',
                                                 "schema key: 'rotation_vertical_inert'"]
    jpadsite/pad-site (independent fix)   PASS
    this branch (my fix)                  PASS

**The guard is satisfied by an implementation it has never seen, and refuses
the tree both implementations were written against.** That is the strongest
evidence available that it enforces the rule rather than the edit — and it was
only obtainable because a second, independent fix existed to test against.
