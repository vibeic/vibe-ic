//======================================================================
// tb_sha256_nist.v — blind self-verify of sha256.v against the PUBLIC
// NIST FIPS-180-4 test vectors (Appendix B). Drives the register
// interface exactly per L4/L5. Golden digests are the published FIPS
// values (public standard, not the design's hidden oracle).
//======================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_sha256_nist;

    reg         clk = 0;
    reg         reset_n;
    reg         cs, we;
    reg  [7:0]  address;
    reg  [31:0] write_data;
    wire [31:0] read_data;
    wire        error;

    integer     errors = 0;

    sha256 dut (
        .clk(clk), .reset_n(reset_n), .cs(cs), .we(we),
        .address(address), .write_data(write_data),
        .read_data(read_data), .error(error)
    );

    always #5 clk = ~clk;

    localparam [7:0] ADDR_CTRL    = 8'h08;
    localparam [7:0] ADDR_STATUS  = 8'h09;
    localparam [7:0] ADDR_BLOCK0  = 8'h10;
    localparam [7:0] ADDR_DIGEST0 = 8'h20;

    // block storage for the current message block
    reg [31:0] blk [0:15];
    reg [31:0] dig [0:7];
    integer    j;

    task do_reset; begin
        cs=0; we=0; address=0; write_data=0; reset_n=0;
        @(negedge clk); @(negedge clk);
        reset_n=1; @(negedge clk);
    end endtask

    task wr; input [7:0] addr; input [31:0] data; begin
        @(negedge clk); cs=1; we=1; address=addr; write_data=data;
        @(negedge clk); cs=0; we=0;
    end endtask

    task rd; input [7:0] addr; output [31:0] data; begin
        @(negedge clk); cs=1; we=0; address=addr;
        #1 data = read_data;
        @(negedge clk); cs=0;
    end endtask

    task load_block; begin
        for (j=0;j<16;j=j+1) wr(ADDR_BLOCK0+j[7:0], blk[j]);
    end endtask

    task poll_ready; reg [31:0] st; begin
        st = 0;
        while (st[0] !== 1'b1) begin
            rd(ADDR_STATUS, st);
        end
    end endtask

    task read_digest; begin
        for (j=0;j<8;j=j+1) rd(ADDR_DIGEST0+j[7:0], dig[j]);
    end endtask

    // one-block hash: mode 1=SHA256 0=SHA224, INIT
    task hash_init; input mode; begin
        load_block;
        wr(ADDR_CTRL, {29'b0, mode, 2'b01}); // INIT=1, MODE=mode
        poll_ready;
    end endtask

    task hash_next; input mode; begin
        load_block;
        wr(ADDR_CTRL, {28'b0, 1'b0, mode, 2'b10}); // NEXT=1, MODE=mode
        poll_ready;
    end endtask

    task check; input [255:0] expected; input [255:0] tag; integer k; reg [31:0] ev; begin
        read_digest;
        for (k=0;k<8;k=k+1) begin
            ev = expected[255 - k*32 -: 32];
            if (dig[k] !== ev) begin
                errors = errors + 1;
                $display("  MISMATCH %0s word%0d got=%08h exp=%08h", tag, k, dig[k], ev);
            end
        end
        $display("  %0s digest = %08h%08h%08h%08h%08h%08h%08h%08h",
                 tag, dig[0],dig[1],dig[2],dig[3],dig[4],dig[5],dig[6],dig[7]);
    end endtask

    // SHA-224 compare only first 7 words (224 bits)
    task check224; input [223:0] expected; input [255:0] tag; integer k; reg [31:0] ev; begin
        read_digest;
        for (k=0;k<7;k=k+1) begin
            ev = expected[223 - k*32 -: 32];
            if (dig[k] !== ev) begin
                errors = errors + 1;
                $display("  MISMATCH %0s word%0d got=%08h exp=%08h", tag, k, dig[k], ev);
            end
        end
        $display("  %0s digest = %08h%08h%08h%08h%08h%08h%08h",
                 tag, dig[0],dig[1],dig[2],dig[3],dig[4],dig[5],dig[6]);
    end endtask

    initial begin
        do_reset;

        //--------------------------------------------------------------
        // Vector 1: SHA-256("abc")
        //--------------------------------------------------------------
        blk[0]=32'h61626380; for(j=1;j<15;j=j+1) blk[j]=0; blk[15]=32'h00000018;
        hash_init(1'b1);
        check(256'hba7816bf_8f01cfea_414140de_5dae2223_b00361a3_96177a9c_b410ff61_f20015ad,
              "SHA256(abc)     ");

        //--------------------------------------------------------------
        // Vector 2: SHA-224("abc")
        //--------------------------------------------------------------
        blk[0]=32'h61626380; for(j=1;j<15;j=j+1) blk[j]=0; blk[15]=32'h00000018;
        hash_init(1'b0);
        check224(224'h23097d22_3405d822_8642a477_bda255b3_2aadbce4_bda0b3f7_e36c9da7,
              "SHA224(abc)     ");

        //--------------------------------------------------------------
        // Vector 3: SHA-256("") empty
        //--------------------------------------------------------------
        blk[0]=32'h80000000; for(j=1;j<16;j=j+1) blk[j]=0;
        hash_init(1'b1);
        check(256'he3b0c442_98fc1c14_9afbf4c8_996fb924_27ae41e4_649b934c_a495991b_7852b855,
              "SHA256(empty)   ");

        //--------------------------------------------------------------
        // Vector 4: SHA-224("") empty
        //--------------------------------------------------------------
        blk[0]=32'h80000000; for(j=1;j<16;j=j+1) blk[j]=0;
        hash_init(1'b0);
        check224(224'hd14a028c_2a3a2bc9_476102bb_288234c4_15a2b01f_828ea62a_c5b3e42f,
              "SHA224(empty)   ");

        //--------------------------------------------------------------
        // Vector 5: SHA-256 two-block 448-bit message
        // "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"
        //--------------------------------------------------------------
        // block 1
        blk[0]=32'h61626364; blk[1]=32'h62636465; blk[2]=32'h63646566; blk[3]=32'h64656667;
        blk[4]=32'h65666768; blk[5]=32'h66676869; blk[6]=32'h6768696a; blk[7]=32'h68696a6b;
        blk[8]=32'h696a6b6c; blk[9]=32'h6a6b6c6d; blk[10]=32'h6b6c6d6e; blk[11]=32'h6c6d6e6f;
        blk[12]=32'h6d6e6f70; blk[13]=32'h6e6f7071; blk[14]=32'h80000000; blk[15]=32'h00000000;
        hash_init(1'b1);
        // block 2 (continuation via NEXT)
        for(j=0;j<15;j=j+1) blk[j]=0; blk[15]=32'h000001c0;
        hash_next(1'b1);
        check(256'h248d6a61_d20638b8_e5c02693_0c3e6039_a33ce459_64ff2167_f6ecedd4_19db06c1,
              "SHA256(2-block) ");

        //--------------------------------------------------------------
        // Vector 6: SHA-224 two-block 448-bit message (same input)
        //--------------------------------------------------------------
        blk[0]=32'h61626364; blk[1]=32'h62636465; blk[2]=32'h63646566; blk[3]=32'h64656667;
        blk[4]=32'h65666768; blk[5]=32'h66676869; blk[6]=32'h6768696a; blk[7]=32'h68696a6b;
        blk[8]=32'h696a6b6c; blk[9]=32'h6a6b6c6d; blk[10]=32'h6b6c6d6e; blk[11]=32'h6c6d6e6f;
        blk[12]=32'h6d6e6f70; blk[13]=32'h6e6f7071; blk[14]=32'h80000000; blk[15]=32'h00000000;
        hash_init(1'b0);
        for(j=0;j<15;j=j+1) blk[j]=0; blk[15]=32'h000001c0;
        hash_next(1'b0);
        check224(224'h75388b16_512776cc_5dba5da1_fd890150_b0c6455c_b4f58b19_52522525,
              "SHA224(2-block) ");

        //--------------------------------------------------------------
        // error-flag check: read an unallocated address (0x30)
        //--------------------------------------------------------------
        @(negedge clk); cs=1; we=0; address=8'h30; #1;
        if (error !== 1'b1) begin errors=errors+1; $display("  MISMATCH error flag: expected 1 on read 0x30 got %b", error); end
        else $display("  error-flag on unallocated read 0x30 = 1 (OK)");
        @(negedge clk); cs=0; address=8'h20; #1;
        if (error !== 1'b0) begin errors=errors+1; $display("  MISMATCH error flag: expected 0 on read 0x20 got %b", error); end
        else $display("  error-flag on valid read 0x20 = 0 (OK)");

        $display("=====================================================");
        if (errors==0) $display("SELFVERIFY PASS — all NIST FIPS-180-4 vectors match. Mismatches: 0");
        else           $display("SELFVERIFY FAIL — Mismatches: %0d", errors);
        $display("=====================================================");
        $finish;
    end

    // global timeout watchdog
    initial begin
        #500000;
        $display("SELFVERIFY FAIL — TIMEOUT. Mismatches: 999");
        $finish;
    end

endmodule
`default_nettype wire
