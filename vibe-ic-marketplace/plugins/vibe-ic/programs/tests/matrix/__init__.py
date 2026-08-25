"""matrix — shared substrate for the 63-step x 8-dimension coverage matrix.

See README.md in this directory. Intentionally contains no logic: the four
public modules are ``flowref`` (live accessors over the flow yaml), ``cells``
(the 504-cell ledger), ``waivers`` (the accepted-gap registry) and
``substitution`` (whether an ENFORCED cell was measured against the step's own
mechanism or against a stand-in).

Nothing is re-exported here on purpose. Siblings import the modules by name::

    from matrix import flowref as F
    from matrix import cells as C
    from matrix import waivers as W

so that every call site says WHICH layer it is reading — a bare ``step_ids()``
in a dimension module hides whether the answer came from the live yaml or from
the audit history, and that ambiguity is the first step toward asserting on the
wrong one.
"""
