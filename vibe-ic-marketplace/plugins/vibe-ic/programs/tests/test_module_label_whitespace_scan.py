import signal
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase1_doc_one_shot_runner as runner


def test_padded_text_does_not_stall_module_label_lookup():
    def expired(signum, frame):
        raise TimeoutError("module-label lookup stalled on whitespace padding")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.alarm(3)
    try:
        text = (" " * 256 + "\n") * 16 + "Ordinary document text.\n"
        assert runner._doc_module_name_label_or_inline({"spec.txt": text}) is None
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


@pytest.mark.parametrize("heading", [
    "Module Name: widget_core",
    "  ### ** Module Name **: `widget_core`",
    "\t## Module Name\n\t`widget_core`",
    "Top Module Name = widget_core",
])
def test_module_label_forms_remain_supported(heading):
    assert runner._doc_module_name_label_or_inline({"spec.txt": heading + "\n"}) == "widget_core"
