import os
import harness_library as hrs_lb
import random
import pytest

# Fetch environment variables for Verilog source setup
verilog_sources = os.getenv("VERILOG_SOURCES").split()
toplevel_lang   = os.getenv("TOPLEVEL_LANG")
sim             = os.getenv("SIM", "icarus")
toplevel        = os.getenv("TOPLEVEL")
module          = os.getenv("MODULE")
wave            = os.getenv("WAVE")

@pytest.mark.parametrize("test", range(1))
def test_pri_enc(test):
    encoder_in = random.randint(0, 255)
    plusargs=[f'+encoder_in={encoder_in}']
    try:
        args = []
        if sim == "xcelium":
            args=("-coverage all"," -covoverwrite", "-sv", "-covtest test", "-svseed random")
        
        hrs_lb.runner(wave = wave, toplevel = toplevel, plusargs=plusargs, module = module, src=verilog_sources, sim=sim, args=args)
        hrs_lb.coverage_report("assertion")
        hrs_lb.covt_report_check()
    except SystemExit:
        # hrs_lb.save_vcd(wave, toplevel, new_name=f"prioroty_encoder_{tst_seq}_test")
        raise SystemError("simulation failed due to assertion failed in your test")

# if __name__ == "__main__":
#     test_simulate()