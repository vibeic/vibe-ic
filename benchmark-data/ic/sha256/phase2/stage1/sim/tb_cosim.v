//============================================================================
// tb_cosim.v -- VERIFY-stage co-simulation: MY generated sha256 vs the
// upstream secworks reference sha256 (ORACLE only, allowed at VERIFY stage).
// Both DUTs share the identical L3/L5 register interface. Drives the same
// stimulus to both, polls each DUT's own STATUS.READY, compares all 8 DIGEST
// words. Reports per-vector PASS/FAIL + the digests.
//============================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_cosim;
    reg         clk=0, reset_n=0;
    reg         cs_a=0, we_a=0; reg [7:0] addr_a=0; reg [31:0] wd_a=0;
    wire [31:0] rd_a; wire err_a;
    reg         cs_b=0, we_b=0; reg [7:0] addr_b=0; reg [31:0] wd_b=0;
    wire [31:0] rd_b; wire err_b;

    // MY design
    sha256 dut_mine (.clk(clk),.reset_n(reset_n),.cs(cs_a),.we(we_a),
        .address(addr_a),.write_data(wd_a),.read_data(rd_a),.error(err_a));
    // upstream secworks reference (oracle)
    ref_sha256 dut_ref (.clk(clk),.reset_n(reset_n),.cs(cs_b),.we(we_b),
        .address(addr_b),.write_data(wd_b),.read_data(rd_b),.error(err_b));

    always #5 clk=~clk;
    integer errors=0;

    // drive BOTH buses identically
    task wr; input [7:0] a; input [31:0] d; begin
        @(posedge clk); cs_a<=1;we_a<=1;addr_a<=a;wd_a<=d;
                        cs_b<=1;we_b<=1;addr_b<=a;wd_b<=d;
        @(posedge clk); cs_a<=0;we_a<=0; cs_b<=0;we_b<=0;
    end endtask
    task rd_mine; input [7:0] a; output [31:0] d; begin
        @(posedge clk); cs_a<=1;we_a<=0;addr_a<=a; #1 d=rd_a; @(posedge clk); cs_a<=0;
    end endtask
    // reference has a REGISTERED read (1-cycle read latency) vs my combinational
    // read — account for the declared-interface latency difference.
    task rd_ref; input [7:0] a; output [31:0] d; begin
        @(posedge clk); cs_b<=1;we_b<=0;addr_b<=a;
        @(posedge clk); #1 d=rd_b; cs_b<=0;
    end endtask
    task wait_both; integer g; reg [31:0] sa,sb; begin
        g=0; sa=0; sb=0;
        while ((sa[0]!==1'b1 || sb[0]!==1'b1) && g<400) begin
            rd_mine(8'h09,sa); rd_ref(8'h09,sb); g=g+1;
        end
    end endtask

    task load_block; input [511:0] blk; integer i; begin
        for (i=0;i<16;i=i+1) wr(8'h10+i[7:0], blk[(15-i)*32 +: 32]);
    end endtask

    task run_one; input mode; input [511:0] blk; input continue_h; input [127:0] nm;
        reg [255:0] gm,gr; reg [31:0] wm,wr_; integer i; begin
            load_block(blk);
            if (continue_h) wr(8'h08,{29'b0,mode,1'b1,1'b0});  // NEXT
            else            wr(8'h08,{29'b0,mode,1'b0,1'b1});  // INIT
            wait_both();
            gm=0; gr=0;
            for (i=0;i<8;i=i+1) begin rd_mine(8'h20+i[7:0],wm); gm[(7-i)*32 +:32]=wm; end
            for (i=0;i<8;i=i+1) begin rd_ref (8'h20+i[7:0],wr_); gr[(7-i)*32 +:32]=wr_; end
            if (gm===gr) $display("  PASS %0s  mine==ref : %h", nm, gm);
            else begin
                $display("  FAIL %0s\n    mine %h\n    ref  %h", nm, gm, gr);
                errors=errors+1;
            end
        end
    endtask

    reg [511:0] b0,b1; integer t;
    reg [31:0] vw[0:16*400-1]; reg [255:0] dummy; integer NV,code,fd,i;
    reg [31:0] tw[0:15];

    initial begin
        reset_n=0; repeat(4) @(posedge clk); reset_n=1; @(posedge clk);

        $display("--- co-sim: MY sha256 vs secworks reference (oracle) ---");
        // abc SHA-256
        run_one(1'b1,{32'h61626380,{14{32'h0}},32'h00000018},1'b0,"abc-256");
        // empty SHA-256
        run_one(1'b1,{32'h80000000,{15{32'h0}}},1'b0,"empty-256");
        // abc SHA-224
        run_one(1'b0,{32'h61626380,{14{32'h0}},32'h00000018},1'b0,"abc-224");
        // 2-block message (INIT then NEXT)
        b0={32'h61626364,32'h62636465,32'h63646566,32'h64656667,
            32'h65666768,32'h66676869,32'h6768696a,32'h68696a6b,
            32'h696a6b6c,32'h6a6b6c6d,32'h6b6c6d6e,32'h6c6d6e6f,
            32'h6d6e6f70,32'h6e6f7071,32'h80000000,32'h00000000};
        b1={ {15{32'h0}},32'h000001c0};
        run_one(1'b1,b0,1'b0,"2blk-A-256");
        run_one(1'b1,b1,1'b1,"2blk-B-256");

        // random differential co-sim (200 single-block vectors)
        fd=$fopen("rand_vectors.txt","r"); NV=0;
        while(!$feof(fd) && NV<200) begin
            code=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                tw[0],tw[1],tw[2],tw[3],tw[4],tw[5],tw[6],tw[7],
                tw[8],tw[9],tw[10],tw[11],tw[12],tw[13],tw[14],tw[15],dummy);
            if (code==17) begin
                for(i=0;i<16;i=i+1) vw[NV*16+i]=tw[i];
                NV=NV+1;
            end
        end
        $fclose(fd);
        $display("--- %0d random differential co-sim vectors ---",NV);
        for (t=0;t<NV;t=t+1) begin
            b0={vw[t*16+0],vw[t*16+1],vw[t*16+2],vw[t*16+3],
                vw[t*16+4],vw[t*16+5],vw[t*16+6],vw[t*16+7],
                vw[t*16+8],vw[t*16+9],vw[t*16+10],vw[t*16+11],
                vw[t*16+12],vw[t*16+13],vw[t*16+14],vw[t*16+15]};
            run_one_quiet(1'b1,b0,1'b0,t);
        end

        $display("==============================");
        if (errors==0) $display("CO-SIM ALL PASSED (mine bit-exact == secworks reference)");
        else           $display("CO-SIM FAILED: %0d", errors);
        $finish;
    end

    task run_one_quiet; input mode; input [511:0] blk; input continue_h; input integer idx;
        reg [255:0] gm,gr; reg [31:0] wm,wr_; integer i; begin
            load_block(blk);
            wr(8'h08,{29'b0,mode,1'b0,1'b1});
            wait_both();
            gm=0; gr=0;
            for (i=0;i<8;i=i+1) begin rd_mine(8'h20+i[7:0],wm); gm[(7-i)*32 +:32]=wm; end
            for (i=0;i<8;i=i+1) begin rd_ref (8'h20+i[7:0],wr_); gr[(7-i)*32 +:32]=wr_; end
            if (gm!==gr) begin
                errors=errors+1;
                if (errors<=5) $display("  FAIL rand %0d mine %h ref %h",idx,gm,gr);
            end
        end
    endtask

    initial begin #100000000; $display("GLOBAL TIMEOUT"); $finish; end
endmodule

`default_nettype wire
