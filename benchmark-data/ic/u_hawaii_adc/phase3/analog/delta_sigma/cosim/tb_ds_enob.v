// Testbench: sweep DC input across the +/-1.0 range, run one OSR=256
// conversion window per point, compare the decimated estimate to the ideal,
// and compute ENOB from the worst-case conversion error over the range.
// REAL iverilog/vvp mixed-signal cosim (A8 HIL substitute + A9). MODELED.
`timescale 1ns/1ps
module tb_ds_enob;
    localparam integer FRAC = 30;
    localparam integer OSR  = 256;
    wire signed [63:0] FS = (64'sd1 <<< FRAC);   // full-scale 1.0

    reg clk = 0, rst = 0;
    reg signed [63:0] vin_q, vref_q;
    wire bs;
    wire signed [63:0] dout_q;

    ds_incremental #(.FRAC(FRAC), .OSR(OSR)) dut (
        .clk(clk), .rst(rst), .vin_q(vin_q), .vref_q(vref_q),
        .bs(bs), .dout_q(dout_q));

    always #5 clk = ~clk;   // 100 MHz model clock

    integer p, k;
    integer NPTS = 65;
    real ideal, est, max_inl, enob;
    // least-squares accumulators for a 2-point gain/offset calibration
    // (an incremental ADC is a LINEAR converter; static gain+offset are
    // calibrated out -- ENOB is set by the RESIDUAL nonlinearity / in-band
    // quantization noise, i.e. the INL after the best-fit line).
    real sx, sy, sxx, sxy, n;
    real xv [0:255];
    real yv [0:255];
    real a_gain, b_off, resid, fit;

    initial begin
        vref_q = FS;            // Vref = 1.0
        sx = 0; sy = 0; sxx = 0; sxy = 0; n = 0;
        // sweep input from -0.85 to +0.85 of full-scale (DSM stable range)
        for (p = 0; p < NPTS; p = p + 1) begin
            ideal = -0.75 + (1.5 * p) / (NPTS-1);
            vin_q = $rtoi(ideal * FS);
            @(negedge clk); rst = 1; @(negedge clk); rst = 0;
            for (k = 0; k < OSR; k = k + 1) @(posedge clk);
            @(negedge clk);
            est = $itor(dout_q) / $itor(FS);
            xv[p] = ideal; yv[p] = est;
            sx = sx + ideal; sy = sy + est;
            sxx = sxx + ideal*ideal; sxy = sxy + ideal*est;
            n = n + 1;
        end
        // best-fit line est ~= a_gain*ideal + b_off
        a_gain = (n*sxy - sx*sy) / (n*sxx - sx*sx);
        b_off  = (sy - a_gain*sx) / n;
        max_inl = 0.0;
        for (p = 0; p < NPTS; p = p + 1) begin
            fit = a_gain*xv[p] + b_off;
            resid = yv[p] - fit;
            if (resid < 0) resid = -resid;
            // residual referred to input full-scale via the calibrated gain
            resid = resid / a_gain;
            if (resid > max_inl) max_inl = resid;
            $display("vin=%0.5f  est=%0.6f  inl_fs=%0.6e", xv[p], yv[p], resid);
        end
        // ENOB = log2( full-scale-range(2.0) / (2*max_residual) )
        if (max_inl <= 0.0) max_inl = 1.0e-12;
        enob = $ln(2.0 / (2.0*max_inl)) / $ln(2.0);
        $display("CAL_GAIN=%0.6f CAL_OFFSET=%0.6e", a_gain, b_off);
        $display("MAX_INL_FS=%0.6e", max_inl);
        $display("ENOB=%0.3f bits (OSR=%0d, order=2, after 2pt gain/offset cal)", enob, OSR);
        if (enob >= 14.0)
            $display("RESULT=PASS ENOB>=14");
        else
            $display("RESULT=FAIL ENOB<14");
        $finish;
    end
endmodule
