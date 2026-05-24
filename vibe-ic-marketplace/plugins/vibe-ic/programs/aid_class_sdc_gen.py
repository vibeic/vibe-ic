#!/usr/bin/env python3
"""Backwards-compat shim — to be removed in v0.130.

Wave 73 (v0.128) S3 renamed aid_class_sdc_gen.py to sdc_gen.py because
the generator is class-AGNOSTIC (it works for any chip whose L8/L9
declares clock + top-module pins, not just EXAMPLE_PROTOCOL-class).

Existing in-tree callers were migrated to the new name. This shim
forwards both library imports (`from aid_class_sdc_gen import ...`)
and CLI invocations (`python3 aid_class_sdc_gen.py ...`) so any
out-of-tree caller still works for one release.
"""
import sys
import warnings

warnings.warn(
    "aid_class_sdc_gen.py is renamed to sdc_gen.py (removal in v0.130)",
    DeprecationWarning,
    stacklevel=2,
)

from sdc_gen import *  # noqa: F401,F403,E402

if __name__ == "__main__":
    from sdc_gen import main as _m  # noqa: E402
    sys.exit(_m())
