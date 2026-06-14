// tb_subservient_func.v
// GENERATED — clean-room functional testbench for the subservient SoC.
//
// Loads a hand-assembled RV32I "blinky" firmware (blinky.hex) into a behavioral
// byte-wide SRAM, releases the synchronous active-high reset, and checks that the
// memory-mapped GPIO output (o_gpio) actually toggles — the L7.1 blinky
// functional intent ("GPIO 輸出規則性 toggle"). Self-checking; no reference
// oracle is read. Emits results.xml (JUnit) + pass.flag on success.

`timescale 1ns/1ps

module tb_subservient_func;
    localparam integer AW = 10;
    localparam integer MEMBYTES = 1024;

    reg  i_clk = 1'b0;
    reg  i_rst = 1'b1;
    wire o_gpio;
    reg  i_gpio = 1'b0;

    wire [9:0] o_sram_addr;
    wire [7:0] o_sram_data;
    wire [7:0] o_sram_wdata;
    wire       o_sram_we;
    wire       o_sram_cyc;
    reg  [7:0] sram_rdata;

    // behavioral byte SRAM (combinational read, synchronous write)
    reg [7:0] mem [0:MEMBYTES-1];

    // DUT
    subservient #(
        .memsize  (1024),
        .RESET_PC (32'h0000_0000),
        .WITH_CSR (1)
    ) dut (
        .i_clk        (i_clk),
        .i_rst        (i_rst),
        .o_gpio       (o_gpio),
        .i_gpio       (i_gpio),
        .o_sram_addr  (o_sram_addr),
        .o_sram_data  (o_sram_data),
        .i_sram_data  (sram_rdata),
        .o_sram_we    (o_sram_we),
        .o_sram_cyc   (o_sram_cyc),
        .o_sram_wdata (o_sram_wdata),
        .i_sram_rdata (sram_rdata)
    );

    // combinational read
    always @(*) sram_rdata = mem[o_sram_addr];

    // synchronous write
    always @(posedge i_clk) begin
        if (o_sram_we && o_sram_cyc)
            mem[o_sram_addr] <= o_sram_data;
    end

    // clock: 100 MHz (10 ns) per L9
    always #5 i_clk = ~i_clk;

    integer cyc;
    integer toggles;
    reg     prev_gpio;
    reg     seen_one;
    reg     seen_zero;

    initial begin
        // preload firmware
        $readmemh("blinky.hex", mem);
        cyc       = 0;
        toggles   = 0;
        prev_gpio = 1'b0;
        seen_one  = 1'b0;
        seen_zero = 1'b1;   // gpio starts at 0 after reset

        // hold reset a few cycles, then release (sync active-high)
        repeat (4) @(posedge i_clk);
        i_rst = 1'b0;

        // run and observe GPIO toggling
        for (cyc = 0; cyc < 4000; cyc = cyc + 1) begin
            @(posedge i_clk);
            if (o_gpio !== prev_gpio) toggles = toggles + 1;
            if (o_gpio === 1'b1) seen_one  = 1'b1;
            if (o_gpio === 1'b0) seen_zero = 1'b1;
            prev_gpio = o_gpio;
        end

        // verdict: blinky must produce both levels AND multiple toggles
        report(seen_one && seen_zero && (toggles >= 2));
    end

    task report;
        input pass;
        integer fx, ff;
        begin
            $display("FUNC-SIM: toggles=%0d seen_one=%0b seen_zero=%0b => %s",
                     toggles, seen_one, seen_zero, pass ? "PASS" : "FAIL");
            // JUnit results.xml
            fx = $fopen("results.xml", "w");
            $fwrite(fx, "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
            $fwrite(fx, "<testsuites>\n");
            $fwrite(fx, "  <testsuite name=\"subservient_func\" tests=\"1\" failures=\"%0d\">\n",
                    pass ? 0 : 1);
            $fwrite(fx, "    <testcase classname=\"subservient\" name=\"blinky_gpio_toggle\">\n");
            if (!pass)
                $fwrite(fx, "      <failure message=\"GPIO did not toggle as expected (toggles=%0d)\"/>\n", toggles);
            $fwrite(fx, "    </testcase>\n");
            $fwrite(fx, "  </testsuite>\n");
            $fwrite(fx, "</testsuites>\n");
            $fclose(fx);
            if (pass) begin
                ff = $fopen("pass.flag", "w");
                $fwrite(ff, "PASS subservient blinky GPIO toggle: toggles=%0d\n", toggles);
                $fclose(ff);
            end
            $finish;
        end
    endtask

    // safety timeout
    initial begin
        #200000;
        $display("FUNC-SIM: TIMEOUT");
        $finish;
    end

endmodule
