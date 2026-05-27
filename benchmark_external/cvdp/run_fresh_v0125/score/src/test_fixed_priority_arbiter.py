import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
import harness_library as hrs_lb  

@cocotb.test()
async def test_fixed_priority_arbiter(dut):
    """Test the fixed_priority_arbiter module."""

    # Start the clock with a period of 10ns
    cocotb.start_soon(Clock(dut.clk, 10, unit='ns').start())

    # Initialize the DUT signals
    await hrs_lb.dut_init(dut)

    # Task: Apply reset (Active High)
    async def reset_dut(active=True, duration_ns=10):
        dut.reset.value = active
        await Timer(duration_ns, unit="ns")
        dut.reset.value = not active
        await RisingEdge(dut.clk)  # Wait for one clock edge after reset is de-asserted

    # Task: Drive request and optional priority override
    async def drive_request(request, priority_override=0):
        dut.req.value = request
        dut.priority_override.value = priority_override
        await RisingEdge(dut.clk)
        await Timer(10, unit="ns")  # Wait to observe the output

    # Monitor the signals
    cocotb.log.info("Starting simulation")

    # Apply a reset to the DUT before starting the test cases
    await reset_dut(active=True, duration_ns=25)

    # ---------------- Test Case 1: Single Request ----------------
    await drive_request(0b00001000)  
    assert dut.grant.value == 0b00001000, f"Test Case 1 Failed: Expected grant=0b00001000, got grant={dut.grant.value}"
    assert dut.grant_index.value == 3, f"Test Case 1 Failed: Expected grant_index=3, got grant_index={dut.grant_index.value}"
    assert dut.valid.value == 1, f"Test Case 1 Failed: Expected valid=1, got valid={dut.valid.value}"
    cocotb.log.info("Test Case 1 Passed: Single request granted correctly.")

    # ---------------- Test Case 2: Multiple Requests (Fixed Priority) ----------------
    await drive_request(0b00111000)  
    assert dut.grant.value == 0b00001000, "Test Case 2 Failed: Incorrect priority handling."
    cocotb.log.info("Test Case 2 Passed: Multiple requests handled with fixed priority.")

    # ---------------- Test Case 3: Priority Override ----------------
    await drive_request(0b00010010, priority_override=0b00010000)  
    assert dut.grant.value == 0b00010000, "Test Case 3 Failed: Priority override did not work."
    cocotb.log.info("Test Case 3 Passed: Priority override successful.")

    # ---------------- Test Case 4: No Requests (Grant Should be Zero) ----------------
    await drive_request(0b00000000)  
    assert dut.grant.value == 0b00000000, "Test Case 4 Failed: Incorrect handling of no requests."
    assert dut.valid.value == 0, "Test Case 4 Failed: Valid signal should be low when no requests."
    cocotb.log.info("Test Case 4 Passed: No requests scenario handled correctly.")

    # ---------------- Test Case 5: Highest Priority Request Wins ----------------
    await drive_request(0b10000001)  
    assert dut.grant.value == 0b00000001, "Test Case 5 Failed: Incorrect priority decision."
    cocotb.log.info("Test Case 5 Passed: Highest priority request wins correctly.")

    # ---------------- Test Case 6: Changing Requests Dynamically ----------------
    await drive_request(0b00000010)  
    assert dut.grant.value == 0b00000010, "Test Case 6 Failed: Grant did not update correctly."
    cocotb.log.info("Test Case 6 Passed: Grant updates dynamically.")

    await drive_request(0b00000100)  
    assert dut.grant.value == 0b00000100, "Test Case 6 Failed: Dynamic request update failed."
    cocotb.log.info("Test Case 6 Passed: Dynamic request update confirmed.")

    # ---------------- Test Case 7: Priority Override While Requests Change ----------------
    await drive_request(0b00000010, priority_override=0b00100000)  
    assert dut.grant.value == 0b00100000, "Test Case 7 Failed: Priority override not applied correctly."
    cocotb.log.info("Test Case 7 Passed: Priority override worked dynamically.")

    await drive_request(0b00010010, priority_override=0b00010000)  
    assert dut.grant.value == 0b00010000, "Test Case 7 Failed: Priority override did not take effect."
    cocotb.log.info("Test Case 7 Passed: Priority override successfully applied during active requests.")

    # ---------------- Test Case 8: Reset During Operation ----------------
    await drive_request(0b00011000)  
    assert dut.grant.value == 0b00001000, "Test Case 8 Failed: Incorrect grant before reset."

    # Apply reset during active requests
    await reset_dut(active=False, duration_ns=25)  
    assert dut.grant.value == 0b00000000, "Test Case 8 Failed: Grant should be zero after reset."
    assert dut.valid.value == 0, "Test Case 8 Failed: Valid should be low after reset."
    cocotb.log.info("Test Case 8 Passed: Reset handled correctly.")

    # Log the successful completion of the simulation
    cocotb.log.info("Simulation completed successfully")
