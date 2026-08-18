"""Canonical helpers for Phase-1 protocol-class detectors (captured v0.1.95).

This module CODIFIES the recurring `is_<proto>(blob)` detector-authoring patterns
that the Tier-D/E/F/G protocol sweeps (v0.1.90–v0.1.94) re-derived — and re-bugged —
by hand, one protocol at a time. It is the Bucket-A ("write the fix into the tool, not
the prompt") counterpart to the Bucket-B prose doctrine in agents/ic-expert-agent.md.

The doctrine, learned across ~80 protocol classes and ~15 detector cross-fires that the
universal no-misfire guard caught (force-overwrite-to-0 hides them from parity per
R28/R32 — the v0.1.89 KEY LESSON):

  1. NEVER fire on a name-token alone. The runner enumerates a generic bus/interface
     vocabulary (and L9 interface_types) that injects protocol NAMES into foreign docs'
     generated L-docs. Every True path must require a STRUCTURAL signal. → use
     `word_boundary` for the structural signal-name tokens; never `name in blob` alone.

  2. A comparison/migration section makes a sibling's detector fire on the full multi-doc
     blob (a spec describes "unlike X" / "migration from X"). → `foreign_exclusive_defer`:
     defer when a token the FOREIGN protocol always has and the OWN never has is present.

  3. A positive structural signature must WIN over an incidental sibling mention — a
     name-anywhere mutex wrongly suppresses the own-doc (e.g. an Automotive-Ethernet spec
     contrasting itself against "800GBASE"). Compute the own conjunction first; gate any
     name-anywhere defer behind its absence.

  4. Separate same-family members (DDR3/4/5/LPDDR5/HBM3/GDDR6) by SUBJECT-DOMINANCE, not
     feature presence — every member's spec enumerates the others' features. → `subject_dominates`.

  5. A true DERIVED sibling (eDP←DisplayPort, I3C←I2C, NVMe←PCIe, SMBus←I2C, QSPI←SPI):
     the base detector firing on the derived doc is CORRECT base-class detection, handled
     by force-overwrite ordering — NOT a false positive. Do not force the base detector to
     defer (it breaks the derived doc's validated base). → allowlist the (base, derived)
     pair in `DERIVED_SIBLING_CROSS_FIRES`; the no-misfire guards consult it.

These helpers are FORWARD-LOOKING: the ~80 existing detectors are validated and left as-is;
new protocol detectors should import from here so the patterns are battle-tested once.
"""
from __future__ import annotations

import re
from typing import Iterable


# --------------------------------------------------------------------------- #
# Single canonical derived-sibling allowlist.
#
# (base_stem, derived_stem): the base detector legitimately fires on the derived
# benchmark because the derived protocol EXTENDS the base; the derived synth runs
# last and force-overwrites. The universal no-misfire guard
# (tests/test_protocol_detector_no_misfire.py) and the Tier-E guard both import this
# ONE source — do not duplicate it.
#
# NOTE: only pairs where BOTH detectors are module-level `is_<stem>` need listing
# (those are what the guards discover). Base-on-derived pairs whose base detector is
# inline in the runner (is_i2c→i3c, is_spi→qspi_ospi, is_pcie→nvme, is_i2c→smbus_pmbus)
# are not module-level and so never surface in the guards.
# --------------------------------------------------------------------------- #
DERIVED_SIBLING_CROSS_FIRES = {
    ("displayport", "edp"),   # Embedded DisplayPort extends DisplayPort (v0.1.94)
    # MIPI D-PHY base ⟶ its packet-layer / display-layer derivatives. CSI-2 and
    # DSI BOTH ride on the MIPI D-PHY physical layer, so the generic D-PHY
    # `is_mipi` detector legitimately fires on the mipi_csi2 / mipi_dsi
    # benchmarks; the runner resolves it by running the dedicated
    # mipi_csi2 / mipi_dsi synths LAST and force-overwriting (the same
    # cross-protocol force-overwrite doctrine as NVMe-on-PCIe). Made visible to
    # the no-misfire guards when `is_mipi` became a module-level detector
    # (ORGANIC-20260531-incidental-csi2-mentions-in-pcie-ufs-ldocs).
    ("mipi", "mipi_csi2"),    # CSI-2 packet layer rides on MIPI D-PHY
    ("mipi", "mipi_dsi"),     # DSI display layer rides on MIPI D-PHY
}


def word_boundary(token: str, blob: str) -> bool:
    """True iff `token` occurs in `blob` on word boundaries (case-sensitive).

    The `_wb` helper that ~9 detectors re-implemented. Use for short or
    digit/identifier-adjacent tokens (FS/FE/VC/CCI/SD1/8-bit/ddr/...) so they match
    only as standalone words — "ddr" must not match inside "command-address", "8-bit"
    must not match inside "48-bit". For multi-word phrases this is a normal boundary
    search; for tokens containing regex metacharacters it escapes them.
    """
    if not token or not blob:
        return False
    return re.search(r"\b" + re.escape(token) + r"\b", blob) is not None


def any_word_boundary(tokens: Iterable[str], blob: str) -> bool:
    """True iff ANY of `tokens` matches `blob` on a word boundary."""
    return any(word_boundary(t, blob) for t in tokens)


def foreign_exclusive_defer(blob: str,
                            foreign_signatures: Iterable[Iterable[str]]) -> bool:
    """True (=> the caller should `return False`) iff the doc carries a FOREIGN-EXCLUSIVE
    signature — a conjunction of tokens the foreign protocol always has and the own
    protocol never has.

    `foreign_signatures` is a list of token-groups; each group is a conjunction (ALL of
    its tokens must be present, case-insensitive substring) and the groups are OR'd. This
    is the fix for comparison/migration-section contamination (rule 2): e.g. for an SAS
    detector deferring to Fibre-Channel-primary docs, pass
    `[("n_port", "flogi", "r_ctl")]`. Returns True if any group fully matches.
    """
    low = blob.lower()
    for group in foreign_signatures:
        toks = list(group)
        if toks and all(t.lower() in low for t in toks):
            return True
    return False


def subject_dominates(blob: str,
                      own_tokens: Iterable[str],
                      sibling_token_sets: Iterable[Iterable[str]],
                      *,
                      subtract: Iterable[tuple[str, str]] = ()) -> bool:
    """True iff the OWN protocol is the dominant SUBJECT of the doc by token count.

    For crowded families (rule 4) where every member's spec enumerates the others'
    features, feature presence cannot separate them — but the OWN name/spec-id appears
    far more often than a sibling's incidental mention. Returns True iff
    sum(count(own_tokens)) strictly exceeds sum(count(tokens)) of EVERY sibling set.

    `subtract` handles the substring near-tie: pass (superset, subset) pairs so the
    subset's net count subtracts the superset's occurrences — e.g. for DDR5 vs LPDDR5,
    "lpddr5" contains "ddr5", so pass subtract=[("lpddr5", "ddr5")] to get the true
    DDR5-only count. All counting is case-insensitive.
    """
    low = blob.lower()

    def _count(tokens):
        return sum(low.count(t.lower()) for t in tokens)

    own = _count(own_tokens)
    for sup, sub in subtract:
        # remove the superset's contribution from the subset's raw count
        own -= low.count(sup.lower()) if sub.lower() in (t.lower() for t in own_tokens) else 0
    if own <= 0:
        return False
    for sib in sibling_token_sets:
        if own <= _count(sib):
            return False
    return True
