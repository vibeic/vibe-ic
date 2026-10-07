"""Model fixtures use the real Step-7 receipt producer, not typed receipts."""
from _ppa import timing
import phase3_one_shot_runner as runner


def step7_fixture(monkeypatch, project, pdk, sdc, top="neutral"):
    # The model controls its authored text; native acceptance executes the
    # unmocked canonical author on the retained design input separately.
    def author(*_args, **_kwargs):
        return {"text": sdc.read_text(), "design_staged": False,
                "staged_sdc": str(sdc.relative_to(project)),
                "supply_ports": [], "drv_block": None}
    monkeypatch.setattr(timing, "author_asic_sdc", author)
    return timing.emit_step7_asic_sdc(runner, project, top, pdk, "")
