"""Keep observable aliases as match points, with the complete sequential cone.

Yosys name matching can compare an unused public alias that synthesis left at
a different value. Such an internal name is not part of the top interface.
Retain every top output, all logic that can drive it (including state, clock
and reset inputs), and every alias of those wires. Only make the other object
names private before a fresh equivalence model is constructed. This changes
neither a connection nor an initial value, and never edits an existing miter.

Use after flattening and wire splitting. If a word must stay intact for FSM
recoding, the wire-level selection conservatively retains its whole cone.
"""


def observable_matchpoint_names(top: str) -> str:
    """Yosys's own sequential input-cone and alias expansion, preserving ports.

    ``%ci*`` crosses sequential cells as well as combinational cells; ``%a``
    keeps all aliases so two sides cannot pick different public names for a
    live bit. ``rename -hide`` ignores all ports, even unused input ports.
    No design-specific signal name, failed-point list, reset assumption, or
    blacklist selects the proof obligations. A live gold alias whose gate
    alias is an unselected constant need not remain an internal cutpoint;
    the complete downstream output cone remains in both models.
    """
    return (f"select -set vibeic_lec_observable {top}/o:* %ci* %a\n"
            "rename -hide @vibeic_lec_observable %n\n")
