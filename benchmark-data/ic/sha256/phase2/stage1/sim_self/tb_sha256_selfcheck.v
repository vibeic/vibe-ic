// Self-authored clean-room TB: drives the register interface per L4/L5
// and checks against NIST FIPS-180-4 public vectors quoted in L7.
`timescale 1ns/1ps
module tb_sha256_selfcheck;
    reg         clk = 0, reset_n = 0, cs = 0, we = 0;
    reg  [7:0]  address = 0;
    reg  [31:0] write_data = 0;
    wire [31:0] read_data;
    wire        error;
    integer     i, errors = 0;

    sha256 dut(.clk(clk), .reset_n(reset_n), .cs(cs), .we(we),
               .address(address), .write_data(write_data),
               .read_data(read_data), .error(error));

    always #5 clk = ~clk;

    // "abc" padded message block (FIPS-180-4 AppA single block)
    reg [31:0] blk_abc [0:15];

    // expected SHA-256("abc")
    reg [31:0] exp256 [0:7];
    // expected SHA-224("abc")  (first 7 words)
    reg [31:0] exp224 [0:6];

    task wr(input [7:0] addr, input [31:0] d);
        begin
            @(negedge clk); cs=1; we=1; address=addr; write_data=d;
            @(negedge clk); cs=0; we=0;
        end
    endtask

    task rd(input [7:0] addr, output [31:0] q);
        begin
            @(negedge clk); cs=1; we=0; address=addr;
            #1 q = read_data;
            @(negedge clk); cs=0;
        end
    endtask

    reg [31:0] q;
    integer guard;
    task run_block(input mode_sha256);
        begin
            // load 16 block words
            for (i=0;i<16;i=i+1) wr(8'h10+i, blk_abc[i]);
            // CTRL: INIT=1, MODE=mode bit
            wr(8'h08, {29'b0, mode_sha256, 1'b0, 1'b1});
            // poll STATUS.READY
            guard = 0;
            q = 0;
            while (q[0] !== 1'b1 && guard < 500) begin
                rd(8'h09, q); guard = guard + 1;
            end
            if (guard >= 500) begin $display("TIMEOUT waiting READY"); errors=errors+1; end
        end
    endtask

    initial begin
        blk_abc[0]=32'h61626380;
        for (i=1;i<15;i=i+1) blk_abc[i]=32'h0;
        blk_abc[15]=32'h00000018;

        exp256[0]=32'hba7816bf; exp256[1]=32'h8f01cfea; exp256[2]=32'h414140de;
        exp256[3]=32'h5dae2223; exp256[4]=32'hb00361a3; exp256[5]=32'h96177a9c;
        exp256[6]=32'hb410ff61; exp256[7]=32'hf20015ad;

        exp224[0]=32'h23097d22; exp224[1]=32'h3405d822; exp224[2]=32'h8642a477;
        exp224[3]=32'hbda255b3; exp224[4]=32'h2aadbce4; exp224[5]=32'hbda0b3f7;
        exp224[6]=32'he36c9da7;

        // reset (active-low, synchronous)
        reset_n=0; repeat(4) @(negedge clk);
        reset_n=1; @(negedge clk);

        // identity check
        rd(8'h00,q); $display("NAME0 = %08x", q);
        rd(8'h01,q); $display("NAME1 = %08x", q);
        rd(8'h02,q); $display("VERSION = %08x", q);

        // SHA-256 mode
        run_block(1'b1);
        for (i=0;i<8;i=i+1) begin
            rd(8'h20+i, q);
            if (q !== exp256[i]) begin
                $display("SHA256 DIGEST%0d MISMATCH got=%08x exp=%08x", i, q, exp256[i]);
                errors=errors+1;
            end else $display("SHA256 DIGEST%0d OK %08x", i, q);
        end

        // SHA-224 mode
        run_block(1'b0);
        for (i=0;i<7;i=i+1) begin
            rd(8'h20+i, q);
            if (q !== exp224[i]) begin
                $display("SHA224 DIGEST%0d MISMATCH got=%08x exp=%08x", i, q, exp224[i]);
                errors=errors+1;
            end else $display("SHA224 DIGEST%0d OK %08x", i, q);
        end

        if (errors==0) $display("SELFCHECK_RESULT: PASS");
        else           $display("SELFCHECK_RESULT: FAIL (%0d errors)", errors);
        $finish;
    end

    initial begin #200000 $display("GLOBAL TIMEOUT"); $finish; end
endmodule
