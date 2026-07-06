"""Regression: the IC Expert DB carries GENERAL cache-replacement-policy craft
for ALL the canonical representations (recency-bit / NMRU, age-COUNTER LRU+MRU,
saturating FREQUENCY LFU, tree-PLRU, FIFO/round-robin eviction pointer), and the
digest retrieval surfaces the RIGHT representation's lesson for each.

Motivation: a blind cache-replacement author was getting NO cache lesson for the
counter/frequency/FIFO representations because the retrieval matcher had no
design-family stem separating them from generic clocked-sequential vocabulary
(the recency-bit + tree lessons matched only recency/tree prompts). Adding the
`recency`/`nmru`/`mru`/`lfu` family stems + the three representation lessons
closes that WITHOUT leaking into foreign (non-cache) designs.

All prompts here are GENERIC prose (no benchmark identifier) — chip-AGNOSTIC.
"""
import sys
from pathlib import Path

import ic_expert_db_query as Q

PLUGIN = Path(__file__).resolve().parent.parent.parent


def _classes(prompt, k=5):
    return [h["ic_class"] for h in Q.query(prompt, k=k)]


# ── each representation retrieves its OWN craft ─────────────────────

def test_counter_age_lru_retrieves_counter_policy():
    p = ("Complete a counter-based set-associative cache replacement policy. Each "
         "way holds a recency counter; on a cache hit set the accessed way's counter "
         "to the maximum and decrement the others; the LRU way with the minimum "
         "counter is selected for replacement (way_replace).")
    assert "cache-replacement-counter-policy" in _classes(p)


def test_counter_age_mru_retrieves_counter_policy():
    p = ("Implement an MRU counter-based cache replacement policy for a "
         "set-associative cache: the way holding the maximum recency counter is the "
         "MRU way chosen for way_replace; hits promote the way_select counter to the "
         "maximum and decrement counters above its previous value.")
    assert "cache-replacement-counter-policy" in _classes(p)


def test_lfu_retrieves_lfu_policy():
    p = ("Design a least-frequently-used LFU cache replacement policy: keep a "
         "saturating frequency counter per way, increment on a cache hit, and pick "
         "the way with the minimum frequency for way_replace on a miss.")
    cls = _classes(p)
    assert "cache-replacement-lfu-policy" in cls


def test_fifo_retrieves_fifo_policy():
    p = ("A FIFO cache replacement policy tracks the next way_replace per index. On "
         "a cache hit way_replace must stay unchanged; only on a miss/eviction does "
         "the round-robin victim pointer advance.")
    assert "cache-replacement-fifo-policy" in _classes(p)


def test_recency_bit_still_retrieves_nmru_lesson():
    # the pre-existing recency-bit / NMRU lesson must NOT be displaced by the new
    # counter/lfu lessons for a genuine recency-bit design.
    p = ("A pseudo-LRU / NMRU replacement policy uses a per-way recency bit array; "
         "on a hit set the used bit, and select the smallest-index way whose recency "
         "bit is zero as way_replace.")
    cls = _classes(p)
    assert any(c in ("cache-replacement-policy", "cache") for c in cls)


# ── §4.05 NO-LEAK: the family stems must not surface a cache lesson for a
#    FOREIGN (non-cache) design that merely shares generic sequential words ──

def test_no_foreign_displacement_clock_divider():
    p = ("Design an integer clock divider: a counter counts clock edges and the "
         "divided clock toggles on the rising edge when the count reaches the limit.")
    cls = _classes(p, k=3)
    assert not any(c.startswith("cache-replacement") for c in cls), cls


def test_no_foreign_displacement_generic_counter():
    p = ("An MMIO timer counter increments each clock and raises an interrupt when "
         "it matches a threshold register; reads are combinational off the address.")
    cls = _classes(p, k=3)
    assert not any(c.startswith("cache-replacement") for c in cls), cls
