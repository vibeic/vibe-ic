"""matrix_63x8 — shared substrate for the 63-step x 8-dimension coverage matrix.

See README.md in this directory. Intentionally contains no logic: the three
public modules are ``flowref`` (live accessors over the flow yaml), ``cells``
(the 504-cell ledger) and ``waivers`` (the accepted-gap registry).

Nothing is re-exported here on purpose. Siblings import the modules by name::

    from matrix_63x8 import flowref as F
    from matrix_63x8 import cells as C
    from matrix_63x8 import waivers as W

so that every call site says WHICH layer it is reading — a bare ``step_ids()``
in a dimension module hides whether the answer came from the live yaml or from
the audit history, and that ambiguity is the first step toward asserting on the
wrong one.
"""
