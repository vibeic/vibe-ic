`timescale 1ns/1ps
`default_nettype none

// Self-checking testbench for the GENERATED spm.
// Golden = (x*y) mod 2^N reassembled LSB-first. Vectors from vectors.hex.
// latency_cycles = 1 (declared): product bit i appears on p one clock after y[i] driven.

module tb_spm;
    localparam integer N = 32;
    localparam integer LAT = 1;   // declared latency_cycles

    reg              clk = 0;
    reg              rst;
    reg  [N-1:0]     x;
    reg              y;
    wire             p;

    spm #(.size(N)) dut (.clk(clk), .rst(rst), .x(x), .y(y), .p(p));

    always #5 clk = ~clk;   // 100 MHz

    // vector storage
    reg [31:0] vx [0:65535];
    reg [31:0] vy [0:65535];
    reg [31:0] vp [0:65535];
    integer nvec;

    integer i, k;
    reg [N-1:0] got;
    integer errors;
    integer fd, r;
    reg [8*64-1:0] line;

    // --- helper: run one multiply, return reassembled product in `got` ---
    task run_multiply(input [N-1:0] xi, input [N-1:0] yi);
        begin
            // synchronous reset for one cycle
            @(negedge clk); rst = 1'b1; x = xi; y = 1'b0;
            @(negedge clk); rst = 1'b0;
            got = {N{1'b0}};
            // Drive y[k] just after a negedge; the intervening posedge registers
            // p <= sum[0] for bit k, so sampling p after the *next* negedge yields
            // product bit k directly (the 1-cycle register latency is absorbed by
            // the negedge-drive / negedge-sample alignment).
            for (k = 0; k < N; k = k + 1) begin
                y = yi[k];
                @(negedge clk);
                got[k] = p;
            end
        end
    endtask

    initial begin
        errors = 0;
        // read vectors: each line "xxxxxxxx yyyyyyyy pppppppp"
        fd = $fopen("vectors.hex", "r");
        if (fd == 0) begin $display("FATAL: cannot open vectors.hex"); $finish; end
        nvec = 0;
        while (!$feof(fd)) begin
            r = $fscanf(fd, "%h %h %h\n", vx[nvec], vy[nvec], vp[nvec]);
            if (r == 3) nvec = nvec + 1;
        end
        $fclose(fd);
        $display("INFO: loaded %0d vectors", nvec);

        for (i = 0; i < nvec; i = i + 1) begin
            run_multiply(vx[i], vy[i]);
            if (got !== vp[i][N-1:0]) begin
                errors = errors + 1;
                if (errors <= 10)
                    $display("MISMATCH vec %0d: x=%h y=%h got=%h exp=%h",
                             i, vx[i], vy[i], got, vp[i]);
            end
        end

        // --- reset-during-computation test: assert rst mid-stream, then redo ---
        begin : midreset
            reg [N-1:0] xt, yt;
            xt = 32'h0001_2345; yt = 32'h6789_ABCD;
            @(negedge clk); rst = 1'b1; x = xt; y = 1'b0;
            @(negedge clk); rst = 1'b0;
            for (k = 0; k < 5; k = k + 1) begin y = yt[k]; @(negedge clk); end
            // mid-computation reset
            @(negedge clk); rst = 1'b1;
            @(negedge clk); rst = 1'b0;
            // now run the multiply cleanly and check it still works
            run_multiply(xt, yt);
            if (got !== ((xt * yt) & ((1<<N)-1))) begin
                errors = errors + 1;
                $display("MISMATCH mid-reset recovery: got=%h exp=%h", got, (xt*yt)&((1<<N)-1));
            end else
                $display("INFO: mid-computation reset recovery PASS");
        end

        if (errors == 0)
            $display("RESULT: PASS  (all %0d vectors + reset tests match golden)", nvec);
        else
            $display("RESULT: FAIL  (%0d mismatches)", errors);
        $finish;
    end
endmodule

`default_nettype wire
