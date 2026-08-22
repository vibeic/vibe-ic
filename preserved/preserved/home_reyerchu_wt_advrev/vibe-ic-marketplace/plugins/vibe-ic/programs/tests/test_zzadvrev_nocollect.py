"""Adversarial-review fixture: a selected file whose tests were all removed.

Realistic cause: a change converts every test in a file into a helper, or
renames them out of the `test_` namespace. The selector still selects the file
because the file changed. pytest then exits rc=5 having collected nothing.
"""


def helper_not_a_test() -> int:
    return 1
