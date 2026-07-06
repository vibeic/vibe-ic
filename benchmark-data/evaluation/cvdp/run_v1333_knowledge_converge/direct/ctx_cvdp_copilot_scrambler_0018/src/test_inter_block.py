import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
import random
import harness_library as hrs_lb

@cocotb.test()
async def test_inter_block(dut):
    """Test the DataProcessor module with random inputs."""

    # Start the clock
    cocotb.start_soon(Clock(dut.clk, 10, unit='ns').start())

    # Initialize the DataProcessor model
    model = hrs_lb.DataProcessor(sub_blocks=4, intra_block_class=hrs_lb.IntraBlock)

    # Debug mode
    debug = 1

    # Retrieve parameters from the DUT
    DATA_WIDTH = int(dut.DATA_WIDTH.value)

    # Range for input values
    data_min = 1
    data_max = int(2**DATA_WIDTH - 1)

    for k in range(2):
      # Reset the MODEL
      model.process_data(0, 0, 0)
      model.update_output_data(0)      

      # Reset the DUT
      await hrs_lb.dut_init(dut)

      dut.rst_n.value = 0
      await Timer(10, unit="ns")

      dut_out_inter = int(dut.out_data.value)
      model_dut_inter = model.get_output_data()
      if debug:
        cocotb.log.info(f"[INPUTS] in_data: {0x0}, i_valid: {0}")        
        cocotb.log.info(f"[DUT] output:   {hex(dut_out_inter)}")
        cocotb.log.info(f"[MODEL] output: {hex(model_dut_inter)}")

      dut.rst_n.value = 1
      await Timer(10, unit='ns')      

      await RisingEdge(dut.clk)

      for i in range(12):
          # Generate random input data
          in_data = random.randint(data_min, data_max)
          valid = 1 if i < 4 else 0

          # Apply inputs to DUT
          dut.in_data.value = in_data
          dut.i_valid.value = valid
          
          if debug:
             cocotb.log.info(f"[INPUTS] in_data: {in_data}, i_valid: {valid}")

          # Process data through the model
          model.process_data(dut.rst_n.value, valid, in_data)
          model.update_output_data(dut.rst_n.value)

          # Wait for one clock cycle
          await RisingEdge(dut.clk)

          # Compare model output with DUT output
          model_out_inter = model.out_data_aux
          dut_out_inter = [int(dut.out_data_aux.value[k]) for k in range(4)]
          if debug:
            cocotb.log.info(f"[DUT]   start  :        {int(dut.start_intra.value)}")
            cocotb.log.info(f"[MODEL] start  :        {model.start_intra[4]}")

            cocotb.log.info(f"[DUT]   counter: {int(dut.counter_sub_out.value)}")
            cocotb.log.info(f"[MODEL] counter: {model.counter_sub_out}")

            for i in range(4):
               cocotb.log.info(f"[DUT]     Block inter {i} output: {hex(dut_out_inter[i])}")
               cocotb.log.info(f"[Model]   Block inter {i} output: {hex(model_out_inter[i])}")

          dut_out_inter = int(dut.out_data.value)
          model_dut_inter = model.get_output_data()

          if debug:
            cocotb.log.info(f"[DUT] output:   {hex(dut_out_inter)}")
            cocotb.log.info(f"[MODEL] output: {hex(model_dut_inter)}")

          assert dut_out_inter == model_dut_inter, f"[ERROR] DUT output does not match model output: {hex(dut_out_inter)} != {hex(model_dut_inter)}"
        