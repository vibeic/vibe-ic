// ============================================================================
// tb_ahb_apb_gpio.v  —  self-checking testbench for the AHB-Lite -> APB GPIO.
// Drives real AHB-Lite transactions (address phase + data phase pipeline) and
// checks: write a register via AHB, read it back, observe GPIO pads toggle,
// and read the input pads through GPIO_IN.  iverilog -g2012 + vvp.
// ============================================================================
`timescale 1ns/1ps
module tb_ahb_apb_gpio;
    localparam HADDR_WIDTH = 32;
    localparam HDATA_WIDTH = 32;
    localparam PADDR_WIDTH = 12;
    localparam GPIO_WIDTH  = 8;

    // Register byte addresses
    localparam ADDR_DATA = 32'h0000_0000;
    localparam ADDR_DIR  = 32'h0000_0004;
    localparam ADDR_IN   = 32'h0000_0008;
    localparam ADDR_CTRL = 32'h0000_000C;

    // HTRANS encodings
    localparam [1:0] IDLE   = 2'b00;
    localparam [1:0] NONSEQ = 2'b10;

    reg                    clk, rst_n;
    reg                    HSEL, HWRITE, HREADY;
    reg  [HADDR_WIDTH-1:0] HADDR;
    reg  [1:0]             HTRANS;
    reg  [2:0]             HSIZE, HBURST;
    reg  [HDATA_WIDTH-1:0] HWDATA;
    wire [HDATA_WIDTH-1:0] HRDATA;
    wire                   HREADYOUT, HRESP;
    wire [GPIO_WIDTH-1:0]  gpio_out, gpio_oe;
    reg  [GPIO_WIDTH-1:0]  gpio_in;

    integer errors = 0;

    ahb_apb_gpio #(
        .HADDR_WIDTH(HADDR_WIDTH), .HDATA_WIDTH(HDATA_WIDTH),
        .PADDR_WIDTH(PADDR_WIDTH), .GPIO_WIDTH(GPIO_WIDTH)
    ) dut (
        .clk(clk), .rst_n(rst_n),
        .HSEL(HSEL), .HADDR(HADDR), .HTRANS(HTRANS), .HWRITE(HWRITE),
        .HSIZE(HSIZE), .HBURST(HBURST), .HWDATA(HWDATA), .HREADY(HREADY),
        .HRDATA(HRDATA), .HREADYOUT(HREADYOUT), .HRESP(HRESP),
        .gpio_out(gpio_out), .gpio_oe(gpio_oe), .gpio_in(gpio_in)
    );

    // 100 MHz clock
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // HREADY in a single-subordinate AHB-Lite system is just HREADYOUT.
    always @(*) HREADY = HREADYOUT;

    // ------------------------------------------------------------------
    // AHB-Lite single-beat write through the bridge.
    //   Address phase: present HSEL/HADDR/HTRANS=NONSEQ/HWRITE=1 for one cycle.
    //   Data phase   : drive HWDATA, return HTRANS to IDLE.
    //   Then wait for the bridge to drain the multi-cycle APB transfer: it
    //   pulls HREADYOUT LOW while servicing and raises it again on completion.
    //   We wait for the LOW->HIGH completion so a following transaction does
    //   not collide with the in-flight one.
    // ------------------------------------------------------------------
    task ahb_write(input [HADDR_WIDTH-1:0] addr, input [HDATA_WIDTH-1:0] data);
    begin
        // ---- Address phase (sampled by the bridge while HREADYOUT=1) ----
        @(posedge clk);
        HSEL   <= 1'b1;
        HADDR  <= addr;
        HTRANS <= NONSEQ;
        HWRITE <= 1'b1;
        HSIZE  <= 3'b010;   // word
        HBURST <= 3'b000;   // single
        // ---- Data phase: deassert request, present write data ----
        @(posedge clk);
        HSEL   <= 1'b0;
        HTRANS <= IDLE;
        HWDATA <= data;
        // ---- Wait for the bridge to begin (HREADYOUT LOW) then finish ----
        @(posedge clk);
        while (HREADYOUT !== 1'b0) @(posedge clk);  // transfer started
        while (HREADYOUT !== 1'b1) @(posedge clk);  // transfer completed
    end
    endtask

    // ------------------------------------------------------------------
    // AHB-Lite single-beat read through the bridge.  Same address/data phase
    // shape; HRDATA is valid on the cycle the bridge completes (HREADYOUT
    // rising), so we sample it the moment HREADYOUT returns HIGH.
    // ------------------------------------------------------------------
    task ahb_read(input [HADDR_WIDTH-1:0] addr, output [HDATA_WIDTH-1:0] data);
    begin
        @(posedge clk);
        HSEL   <= 1'b1;
        HADDR  <= addr;
        HTRANS <= NONSEQ;
        HWRITE <= 1'b0;
        HSIZE  <= 3'b010;
        HBURST <= 3'b000;
        @(posedge clk);
        HSEL   <= 1'b0;
        HTRANS <= IDLE;
        @(posedge clk);
        while (HREADYOUT !== 1'b0) @(posedge clk);  // transfer started
        while (HREADYOUT !== 1'b1) @(posedge clk);  // completion: HRDATA valid
        data = HRDATA;
    end
    endtask

    task check(input [HDATA_WIDTH-1:0] got, input [HDATA_WIDTH-1:0] exp,
               input [255:0] name);
    begin
        if (got !== exp) begin
            $display("  FAIL: %0s got=0x%08h exp=0x%08h", name, got, exp);
            errors = errors + 1;
        end else begin
            $display("  ok  : %0s = 0x%08h", name, got);
        end
    end
    endtask

    reg [HDATA_WIDTH-1:0] rd;

    initial begin
        // init
        HSEL=0; HADDR=0; HTRANS=IDLE; HWRITE=0; HSIZE=0; HBURST=0;
        HWDATA=0; HREADY=1; gpio_in=8'h00;
        rst_n=0;
        repeat (4) @(posedge clk);
        rst_n=1;
        @(posedge clk);

        $display("=== AHB->APB GPIO self-checking TB ===");

        // 1) Set direction = all outputs
        ahb_write(ADDR_DIR, 32'h0000_00FF);
        ahb_read (ADDR_DIR, rd);
        check(rd, 32'h0000_00FF, "GPIO_DIR readback");
        check({24'b0, gpio_oe}, 32'h0000_00FF, "gpio_oe == DIR");

        // 2) Write DATA = 0xA5, verify readback + pad drive
        ahb_write(ADDR_DATA, 32'h0000_00A5);
        ahb_read (ADDR_DATA, rd);
        check(rd, 32'h0000_00A5, "GPIO_DATA readback");
        check({24'b0, gpio_out}, 32'h0000_00A5, "gpio_out == DATA");

        // 3) Toggle DATA to 0x5A
        ahb_write(ADDR_DATA, 32'h0000_005A);
        ahb_read (ADDR_DATA, rd);
        check(rd, 32'h0000_005A, "GPIO_DATA toggle readback");
        check({24'b0, gpio_out}, 32'h0000_005A, "gpio_out toggled");

        // 4) Drive input pads, read through GPIO_IN (after 2-flop sync settle)
        gpio_in = 8'h3C;
        repeat (4) @(posedge clk);   // let the 2-flop synchronizer settle
        ahb_read(ADDR_IN, rd);
        check(rd, 32'h0000_003C, "GPIO_IN reflects pads");

        // 5) CTRL soft-clear: set CTRL bit0 -> DATA self-clears
        ahb_write(ADDR_CTRL, 32'h0000_0001);
        repeat (2) @(posedge clk);
        ahb_read(ADDR_DATA, rd);
        check(rd, 32'h0000_0000, "GPIO_DATA soft-cleared by CTRL[0]");

        // summary
        if (errors == 0)
            $display("TB PASS  (all checks ok)");
        else
            $display("TB FAIL  (%0d errors)", errors);
        $finish;
    end

    // safety timeout
    initial begin
        #20000;
        $display("TB TIMEOUT");
        $finish;
    end
endmodule
