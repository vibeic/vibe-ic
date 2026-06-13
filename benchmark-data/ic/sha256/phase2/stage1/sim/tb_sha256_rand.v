//============================================================================
// tb_sha256_rand.v -- random differential test vs Python hashlib golden.
// Reads rand_vectors.txt: 16 block-words + expected 256-bit digest per line.
// GENERATED. Golden = NIST oracle (hashlib.sha256), used as ORACLE not input.
//============================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_sha256_rand;
    reg         clk=0,reset_n=0,cs=0,we=0;
    reg  [7:0]  address=0;
    reg  [31:0] write_data=0;
    wire [31:0] read_data; wire error;

    sha256 dut(.clk(clk),.reset_n(reset_n),.cs(cs),.we(we),
               .address(address),.write_data(write_data),
               .read_data(read_data),.error(error));
    always #5 clk=~clk;

    task wr; input [7:0] a; input [31:0] d; begin
        @(posedge clk); cs<=1; we<=1; address<=a; write_data<=d;
        @(posedge clk); cs<=0; we<=0;
    end endtask
    task rd; input [7:0] a; output [31:0] d; begin
        @(posedge clk); cs<=1; we<=0; address<=a; #1 d=read_data;
        @(posedge clk); cs<=0;
    end endtask
    task wait_ready; integer g; reg [31:0] s; begin
        g=0; s=0;
        while (s[0]!==1'b1 && g<200) begin rd(8'h09,s); g=g+1; end
    end endtask

    integer NV; parameter MAXV=400;
    reg [31:0] vw [0:MAXV*16-1];
    reg [255:0] vd [0:MAXV-1];

    integer fd, code, i, t, errors;
    reg [31:0] tmpw[0:15]; reg [255:0] exp;
    reg [255:0] got; reg [31:0] w;

    initial begin
        errors=0; NV=0;
        fd=$fopen("rand_vectors.txt","r");
        if (fd==0) begin $display("cannot open rand_vectors.txt"); $finish; end
        // read lines: 16 hex words + 64-hex-digit digest
        while (!$feof(fd) && NV<MAXV) begin
            code=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                tmpw[0],tmpw[1],tmpw[2],tmpw[3],tmpw[4],tmpw[5],tmpw[6],tmpw[7],
                tmpw[8],tmpw[9],tmpw[10],tmpw[11],tmpw[12],tmpw[13],tmpw[14],tmpw[15],
                exp);
            if (code==17) begin
                for (i=0;i<16;i=i+1) vw[NV*16+i]=tmpw[i];
                vd[NV]=exp;
                NV=NV+1;
            end
        end
        $fclose(fd);
        $display("loaded %0d random vectors",NV);

        reset_n=0; repeat(4) @(posedge clk); reset_n=1; @(posedge clk);

        for (t=0;t<NV;t=t+1) begin
            for (i=0;i<16;i=i+1) wr(8'h10+i[7:0], vw[t*16+i]);
            wr(8'h08, {29'b0,1'b1,1'b0,1'b1}); // MODE=256, INIT
            wait_ready();
            got=0;
            for (i=0;i<8;i=i+1) begin rd(8'h20+i[7:0],w); got[(7-i)*32 +: 32]=w; end
            if (got!==vd[t]) begin
                errors=errors+1;
                if (errors<=5) $display("  FAIL vec %0d exp %h got %h",t,vd[t],got);
            end
        end
        $display("==============================");
        if (errors==0) $display("RAND ALL %0d PASSED",NV);
        else           $display("RAND FAILED: %0d / %0d",errors,NV);
        $finish;
    end
    initial begin #50000000; $display("GLOBAL TIMEOUT"); $finish; end
endmodule

`default_nettype wire
