"""`_ppa.backends` — one module per tool, and each one only PARSES.

A backend turns the text a tool actually wrote into structured observations.
It holds no threshold, no verdict and no policy, so that adding a second timing
engine later changes no rule: the domain module (`_ppa.timing`, `_ppa.power`,
…) is the only place where an observation becomes a judgement.

The split is not tidiness. A threshold that lives in a parser is a threshold
that has to be re-agreed every time a tool is added, and the two copies drift
in the direction nobody is looking.
"""
