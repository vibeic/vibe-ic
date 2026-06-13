`timescale 1ns/1ps
`default_nettype none

// Cross-check co-simulation: GENERATED spm (spm_gen) vs upstream reference spm
// (spm_ref). Same clk/rst/x/y stimulus drives both; p is compared every cycle.
// Both declare LSB-first, latency=1, sync active-high reset. If the per-cycle p
// streams match for all stimulus, the two are functionally equivalent.

module tb_cosim;
    localparam integer N = 32;
    reg clk = 0, rst, y;
    reg [N-1:0] x;
    wire p_gen, p_ref;

    spm     #(.size(N)) u_gen (.clk(clk), .rst(rst), .x(x), .y(y), .p(p_gen));
    spm_ref #(.size(N)) u_ref (.clk(clk), .rst(rst), .x(x), .y(y), .p(p_ref));

    always #5 clk = ~clk;

    integer i, k, errors, mism_cycles;
    reg [N-1:0] vx [0:65535];
    reg [N-1:0] vy [0:65535];
    integer nvec, fd, r;
    reg [N-1:0] gen_word, ref_word, exp_word;

    initial begin
        errors = 0; mism_cycles = 0;
        fd = $fopen("vectors.hex", "r");
        if (fd == 0) begin $display("FATAL: no vectors.hex"); $finish; end
        nvec = 0;
        while (!$feof(fd)) begin
            r = $fscanf(fd, "%h %h %*h\n", vx[nvec], vy[nvec]);
            if (r == 2) nvec = nvec + 1;
        end
        $fclose(fd);
        $display("INFO: cosim over %0d vectors", nvec);

        for (i = 0; i < nvec; i = i + 1) begin
            // sync reset 1 cycle
            @(negedge clk); rst = 1'b1; x = vx[i]; y = 1'b0;
            @(negedge clk); rst = 1'b0;
            gen_word = 0; ref_word = 0;
            for (k = 0; k < N; k = k + 1) begin
                y = vy[i][k];
                @(negedge clk);
                gen_word[k] = p_gen;
                ref_word[k] = p_ref;
                if (p_gen !== p_ref) mism_cycles = mism_cycles + 1;
            end
            exp_word = (vx[i] * vy[i]) & ((1<<N)-1);
            if (gen_word !== ref_word) begin
                errors = errors + 1;
                if (errors <= 8)
                  $display("WORD MISMATCH vec %0d x=%h y=%h gen=%h ref=%h exp=%h",
                           i, vx[i], vy[i], gen_word, ref_word, exp_word);
            end
        end

        if (errors == 0 && mism_cycles == 0)
            $display("RESULT: EQUIVALENT  (gen==ref for all %0d vectors, 0 per-cycle mismatches)", nvec);
        else
            $display("RESULT: NOT-EQUIVALENT  word_errors=%0d per_cycle_mismatches=%0d", errors, mism_cycles);
        $finish;
    end
endmodule

`default_nettype wire
