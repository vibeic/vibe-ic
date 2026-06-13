//============================================================================
// tb_sha256.v -- NIST FIPS-180-4 known-answer-vector testbench for sha256
// Drives the L3/L5 memory-mapped register interface through full hash flows.
// GENERATED from FIPS-180-4 + L4 command protocol. Vectors encoded from the
// public NIST standard (golden = NIST oracle).
//============================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_sha256;
    reg         clk = 0, reset_n = 0, cs = 0, we = 0;
    reg  [7:0]  address = 0;
    reg  [31:0] write_data = 0;
    wire [31:0] read_data;
    wire        error;

    integer errors = 0;

    sha256 dut (.clk(clk),.reset_n(reset_n),.cs(cs),.we(we),
                .address(address),.write_data(write_data),
                .read_data(read_data),.error(error));

    always #5 clk = ~clk;   // 100 MHz sim clock

    // ----- bus helpers -----
    task wr; input [7:0] a; input [31:0] d; begin
        @(posedge clk); cs<=1; we<=1; address<=a; write_data<=d;
        @(posedge clk); cs<=0; we<=0;
    end endtask

    task rd; input [7:0] a; output [31:0] d; begin
        @(posedge clk); cs<=1; we<=0; address<=a;
        #1 d = read_data;       // combinational read
        @(posedge clk); cs<=0;
    end endtask

    task wait_ready; integer guard; reg [31:0] st; begin
        guard=0;
        st=0;
        while (st[0]!==1'b1 && guard<200) begin
            rd(8'h09, st); guard=guard+1;
        end
        if (st[0]!==1'b1) begin
            $display("  TIMEOUT waiting READY"); errors=errors+1;
        end
    end endtask

    // load 16 block words from a packed 512-bit value (MSW first into BLOCK0)
    task load_block; input [511:0] blk; integer i; begin
        for (i=0;i<16;i=i+1)
            wr(8'h10+i[7:0], blk[(15-i)*32 +: 32]);
    end endtask

    // run one INIT hash, compare 256-bit digest
    task run_init; input mode; input [511:0] blk; input [255:0] exp;
                   input [255:0] mask; input [127:0] name;
        reg [255:0] got; reg [31:0] w; integer i; begin
            load_block(blk);
            // CTRL: MODE at bit2, INIT bit0
            wr(8'h08, {29'b0, mode, 1'b0, 1'b1});
            wait_ready();
            got=0;
            for (i=0;i<8;i=i+1) begin rd(8'h20+i[7:0], w); got[(7-i)*32 +: 32]=w; end
            if ((got & mask) === (exp & mask))
                $display("  PASS %0s : %h", name, got & mask);
            else begin
                $display("  FAIL %0s\n    exp %h\n    got %h", name, exp&mask, got&mask);
                errors=errors+1;
            end
        end
    endtask

    reg [511:0] b0,b1;
    reg [255:0] got; reg [31:0] w; integer i;

    initial begin
        $dumpfile("tb_sha256.vcd"); $dumpvars(0,tb_sha256);
        // reset (active-LOW)
        reset_n=0; repeat(4) @(posedge clk); reset_n=1; @(posedge clk);

        // ID/version sanity
        rd(8'h00,w); $display("NAME0=%h (\"sha2\")", w);
        rd(8'h01,w); $display("NAME1=%h (\"56  \")", w);
        rd(8'h02,w); $display("VERSION=%h", w);

        $display("--- SHA-256 KAT ---");
        // "abc"
        run_init(1'b1,
          {32'h61626380,32'h0,32'h0,32'h0,32'h0,32'h0,32'h0,32'h0,
           32'h0,32'h0,32'h0,32'h0,32'h0,32'h0,32'h0,32'h00000018},
          256'hba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad,
          {256{1'b1}}, "abc-256");

        // empty message
        run_init(1'b1,
          {32'h80000000,32'h0,32'h0,32'h0,32'h0,32'h0,32'h0,32'h0,
           32'h0,32'h0,32'h0,32'h0,32'h0,32'h0,32'h0,32'h0},
          256'he3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855,
          {256{1'b1}}, "empty-256");

        $display("--- SHA-224 KAT ---");
        // "abc" SHA-224 (compare top 224 bits only)
        run_init(1'b0,
          {32'h61626380,32'h0,32'h0,32'h0,32'h0,32'h0,32'h0,32'h0,
           32'h0,32'h0,32'h0,32'h0,32'h0,32'h0,32'h0,32'h00000018},
          256'h23097d223405d8228642a477bda255b32aadbce4bda0b3f7e36c9da700000000,
          {{224{1'b1}},{32{1'b0}}}, "abc-224");

        $display("--- SHA-256 multi-block (INIT + NEXT) ---");
        // 448-bit "abcdbcde...nopq", 2 blocks
        b0 = {32'h61626364,32'h62636465,32'h63646566,32'h64656667,
              32'h65666768,32'h66676869,32'h6768696a,32'h68696a6b,
              32'h696a6b6c,32'h6a6b6c6d,32'h6b6c6d6e,32'h6c6d6e6f,
              32'h6d6e6f70,32'h6e6f7071,32'h80000000,32'h00000000};
        b1 = {32'h0,32'h0,32'h0,32'h0,32'h0,32'h0,32'h0,32'h0,
              32'h0,32'h0,32'h0,32'h0,32'h0,32'h0,32'h0,32'h000001c0};
        // block 0: INIT
        load_block(b0);
        wr(8'h08, {29'b0, 1'b1, 1'b0, 1'b1});  // MODE=1, INIT
        wait_ready();
        // block 1: NEXT (continue)
        load_block(b1);
        wr(8'h08, {29'b0, 1'b1, 1'b1, 1'b0});  // MODE=1, NEXT
        wait_ready();
        got=0;
        for (i=0;i<8;i=i+1) begin rd(8'h20+i[7:0], w); got[(7-i)*32 +: 32]=w; end
        if (got === 256'h248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1)
            $display("  PASS 2block-256 : %h", got);
        else begin
            $display("  FAIL 2block-256\n    got %h", got); errors=errors+1;
        end

        $display("--- undefined-address error flag ---");
        rd(8'h7f, w);
        if (error===1'b1) $display("  PASS error flag on undefined addr");
        else begin $display("  FAIL error flag not set"); errors=errors+1; end

        $display("==============================");
        if (errors==0) $display("ALL TESTS PASSED");
        else           $display("TESTS FAILED: %0d", errors);
        $finish;
    end

    initial begin #200000; $display("GLOBAL TIMEOUT"); $finish; end
endmodule

`default_nettype wire
