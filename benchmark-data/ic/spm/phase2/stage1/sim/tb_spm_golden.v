// Self-authored golden testbench for spm (clean-room, from spec only).
// Golden model: p_stream = (x * y_full) mod 2^size, LSB-first on both serial streams.
// Sweeps candidate latency 0..3 to discover the Plugin-declared latency, then runs
// a large random + corner campaign at the discovered latency.
`timescale 1ns/1ps
module tb_spm_golden;
    parameter size = 32;

    reg              clk = 0, rst = 1, y = 0;
    reg  [size-1:0]  x = 0;
    wire             p;

    spm #(.size(size)) dut (.clk(clk), .rst(rst), .x(x), .y(y), .p(p));

    always #5 clk = ~clk;

    integer errors;
    integer t, lat, chosen_lat;
    reg [size-1:0] yfull, xrand;
    reg [size-1:0] expected, got;

    // Run one multiplication at a given capture latency; returns mismatch via `errors`.
    task run_one(input [size-1:0] xin, input [size-1:0] yin, input integer LAT,
                 output integer mism);
        integer cyc;
        reg [size-1:0] pcap;
        begin
            @(negedge clk); rst = 1; x = xin; y = 0;
            @(negedge clk); rst = 0;
            pcap = 0;
            for (cyc = 0; cyc < size + LAT + 2; cyc = cyc + 1) begin
                y = (cyc < size) ? yin[cyc] : 1'b0;   // feed multiplier LSB-first
                @(posedge clk);
                #1;
                if (cyc >= LAT && (cyc-LAT) < size) pcap[cyc-LAT] = p; // capture p LSB-first
            end
            expected = (xin * yin);
            got = pcap;
            mism = (got !== expected) ? 1 : 0;
        end
    endtask

    integer m;
    initial begin
        // ---- discover latency ----
        chosen_lat = -1;
        for (lat = 0; lat <= 4; lat = lat + 1) begin
            errors = 0;
            run_one(32'hDEADBEEF, 32'h12345678, lat, m); errors = errors + m;
            run_one(1, 1, lat, m); errors = errors + m;
            run_one(32'hFFFFFFFF, 1, lat, m); errors = errors + m;
            run_one(32'h0F0F0F0F, 32'hF0F0F0F0, lat, m); errors = errors + m;
            if (errors == 0 && chosen_lat < 0) begin
                chosen_lat = lat;
                $display("DISCOVERED_LATENCY = %0d", lat);
            end
        end
        if (chosen_lat < 0) begin
            $display("GOLDEN_FAIL: no latency 0..4 makes all probe cases match");
            $finish;
        end

        // ---- full campaign at discovered latency ----
        errors = 0;
        run_one(0, 0, chosen_lat, m); errors = errors + m;
        run_one(32'hFFFFFFFF, 0, chosen_lat, m); errors = errors + m;
        run_one(0, 32'hFFFFFFFF, chosen_lat, m); errors = errors + m;
        run_one(1, 1, chosen_lat, m); errors = errors + m;
        run_one(32'hFFFFFFFF, 1, chosen_lat, m); errors = errors + m;
        run_one(1, 32'hFFFFFFFF, chosen_lat, m); errors = errors + m;
        run_one(32'hFFFFFFFF, 32'hFFFFFFFF, chosen_lat, m); errors = errors + m; // -1*-1=1
        run_one(32'h80000000, 32'h80000000, chosen_lat, m); errors = errors + m;
        run_one(32'h7FFFFFFF, 32'h7FFFFFFF, chosen_lat, m); errors = errors + m;
        for (t = 0; t < 12000; t = t + 1) begin
            xrand = $random; yfull = $random;
            run_one(xrand, yfull, chosen_lat, m);
            errors = errors + m;
            if (m && errors <= 10)
                $display("MISMATCH x=%0d y=%0d exp=%0h got=%0h", xrand, yfull, expected, got);
        end
        if (errors == 0)
            $display("GOLDEN_PASS: all match x*y mod 2^%0d at latency=%0d", size, chosen_lat);
        else
            $display("GOLDEN_FAIL: %0d mismatches at latency=%0d", errors, chosen_lat);
        $finish;
    end
endmodule
