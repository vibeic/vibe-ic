"""`_ppa.backends` — one module per tool, and each one only PARSES.

`docs/PPA_INTERFACES.md` §4: "A backend module parses one tool's output into
canonical records and does nothing else. No thresholds, no verdicts, no policy
— those live in the domain module, so that adding a tool never changes a rule."

The rule earns its keep at exactly the moment a tool's output is CLOSE to what a
domain wants. A backend that notices a violation count is zero and returns
"clean" has moved a threshold into the parser, and the next tool added will
either duplicate it or contradict it. So a backend's whole job is: this is what
the tool said, this is the scope it said it in, and this is what it did NOT say.
"""
