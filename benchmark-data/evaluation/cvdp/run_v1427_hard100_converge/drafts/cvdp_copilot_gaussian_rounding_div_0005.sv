//////////////////////////////////////////////
// Top-Level Gold-Schmidt Division Module
//////////////////////////////////////////////
module divider (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         start,
    input  logic [17:0]  dividend,
    input  logic [17:0]  divisor,
    output logic [17:0]  dv_out,
    output logic         valid
);

    //////////////////////////////////////////////
    // Local parameters
    //////////////////////////////////////////////
    localparam logic [17:0] TWO  = 18'b000000010_000000000;
    localparam logic [17:0] ZERO = 18'b000000000_000000000;

    //////////////////////////////////////////////
    // Internal signals
    //////////////////////////////////////////////
    logic [17:0] D_0, N_0;
    logic [17:0] D, D2, D4, D6, D8, D10, D12, D14, D16, D18, D20;
    logic [17:0] N, N2, N4, N6, N8, N10, N12, N14, N16, N18, N20, N21;
    logic [17:0] F, F1, F2, F3, F4, F5, F6, F7, F8, F9;
    logic [47:0] D1, N1, D3, N3, D5, N5, D7, N7, D9, N9, D11, N11, D13, N13, D15, N15, D17, N17, D19, N19;

    // Pipeline stage flags
    logic st1, st2, st3, st4, st5, st6, st7, st8, st9, st10, st11, st12;

    // Pre-scaler outputs
    logic [17:0] D_pre, N_pre;

    //////////////////////////////////////////////
    // Stage 0 : register the raw inputs
    // (1 clock cycle to register the input dividend and divisor)
    //////////////////////////////////////////////
    reg18 u_reg_D0 (.clk(clk), .reset(rst_n), .data_in(divisor),  .data_out(D_0));
    reg18 u_reg_N0 (.clk(clk), .reset(rst_n), .data_in(dividend), .data_out(N_0));
    dff1  u_st1    (.clk(clk), .reset(rst_n), .d(start),          .q(st1));

    //////////////////////////////////////////////
    // Pre-scaling : right-shift dividend and divisor together
    // until the divisor has only 0s in its integer bits (D < 1)
    // (1 clock cycle to register the prescaled values)
    //////////////////////////////////////////////
    pre_scaler u_prescale (.a(D_0), .c(N_0), .b(D_pre), .d(N_pre));

    reg18 u_reg_D (.clk(clk), .reset(rst_n), .data_in(D_pre), .data_out(D));
    reg18 u_reg_N (.clk(clk), .reset(rst_n), .data_in(N_pre), .data_out(N));
    dff1  u_st2   (.clk(clk), .reset(rst_n), .d(st1),         .q(st2));

    //////////////////////////////////////////////
    // 10 pipelined Gold-Schmidt iterations
    // Each stage:  F = 2 - D ; D' = (F*D)[26:9] ; N' = (F*N)[26:9]
    //////////////////////////////////////////////

    // ---------------- Iteration 1 ----------------
    assign F  = TWO - D;
    assign D1 = F * D;
    assign N1 = F * N;
    reg18 u_reg_D2 (.clk(clk), .reset(rst_n), .data_in(D1[26:9]), .data_out(D2));
    reg18 u_reg_N2 (.clk(clk), .reset(rst_n), .data_in(N1[26:9]), .data_out(N2));
    dff1  u_st3    (.clk(clk), .reset(rst_n), .d(st2),            .q(st3));

    // ---------------- Iteration 2 ----------------
    assign F1 = TWO - D2;
    assign D3 = F1 * D2;
    assign N3 = F1 * N2;
    reg18 u_reg_D4 (.clk(clk), .reset(rst_n), .data_in(D3[26:9]), .data_out(D4));
    reg18 u_reg_N4 (.clk(clk), .reset(rst_n), .data_in(N3[26:9]), .data_out(N4));
    dff1  u_st4    (.clk(clk), .reset(rst_n), .d(st3),            .q(st4));

    // ---------------- Iteration 3 ----------------
    assign F2 = TWO - D4;
    assign D5 = F2 * D4;
    assign N5 = F2 * N4;
    reg18 u_reg_D6 (.clk(clk), .reset(rst_n), .data_in(D5[26:9]), .data_out(D6));
    reg18 u_reg_N6 (.clk(clk), .reset(rst_n), .data_in(N5[26:9]), .data_out(N6));
    dff1  u_st5    (.clk(clk), .reset(rst_n), .d(st4),            .q(st5));

    // ---------------- Iteration 4 ----------------
    assign F3 = TWO - D6;
    assign D7 = F3 * D6;
    assign N7 = F3 * N6;
    reg18 u_reg_D8 (.clk(clk), .reset(rst_n), .data_in(D7[26:9]), .data_out(D8));
    reg18 u_reg_N8 (.clk(clk), .reset(rst_n), .data_in(N7[26:9]), .data_out(N8));
    dff1  u_st6    (.clk(clk), .reset(rst_n), .d(st5),            .q(st6));

    // ---------------- Iteration 5 ----------------
    assign F4 = TWO - D8;
    assign D9 = F4 * D8;
    assign N9 = F4 * N8;
    reg18 u_reg_D10 (.clk(clk), .reset(rst_n), .data_in(D9[26:9]), .data_out(D10));
    reg18 u_reg_N10 (.clk(clk), .reset(rst_n), .data_in(N9[26:9]), .data_out(N10));
    dff1  u_st7     (.clk(clk), .reset(rst_n), .d(st6),            .q(st7));

    // ---------------- Iteration 6 ----------------
    assign F5  = TWO - D10;
    assign D11 = F5 * D10;
    assign N11 = F5 * N10;
    reg18 u_reg_D12 (.clk(clk), .reset(rst_n), .data_in(D11[26:9]), .data_out(D12));
    reg18 u_reg_N12 (.clk(clk), .reset(rst_n), .data_in(N11[26:9]), .data_out(N12));
    dff1  u_st8     (.clk(clk), .reset(rst_n), .d(st7),             .q(st8));

    // ---------------- Iteration 7 ----------------
    assign F6  = TWO - D12;
    assign D13 = F6 * D12;
    assign N13 = F6 * N12;
    reg18 u_reg_D14 (.clk(clk), .reset(rst_n), .data_in(D13[26:9]), .data_out(D14));
    reg18 u_reg_N14 (.clk(clk), .reset(rst_n), .data_in(N13[26:9]), .data_out(N14));
    dff1  u_st9     (.clk(clk), .reset(rst_n), .d(st8),             .q(st9));

    // ---------------- Iteration 8 ----------------
    assign F7  = TWO - D14;
    assign D15 = F7 * D14;
    assign N15 = F7 * N14;
    reg18 u_reg_D16 (.clk(clk), .reset(rst_n), .data_in(D15[26:9]), .data_out(D16));
    reg18 u_reg_N16 (.clk(clk), .reset(rst_n), .data_in(N15[26:9]), .data_out(N16));
    dff1  u_st10    (.clk(clk), .reset(rst_n), .d(st9),             .q(st10));

    // ---------------- Iteration 9 ----------------
    assign F8  = TWO - D16;
    assign D17 = F8 * D16;
    assign N17 = F8 * N16;
    reg18 u_reg_D18 (.clk(clk), .reset(rst_n), .data_in(D17[26:9]), .data_out(D18));
    reg18 u_reg_N18 (.clk(clk), .reset(rst_n), .data_in(N17[26:9]), .data_out(N18));
    dff1  u_st11    (.clk(clk), .reset(rst_n), .d(st10),            .q(st11));

    // ---------------- Iteration 10 ----------------
    assign F9  = TWO - D18;
    assign D19 = F9 * D18;
    assign N19 = F9 * N18;
    reg18 u_reg_D20 (.clk(clk), .reset(rst_n), .data_in(D19[26:9]), .data_out(D20));
    reg18 u_reg_N20 (.clk(clk), .reset(rst_n), .data_in(N19[26:9]), .data_out(N20));
    dff1  u_st12    (.clk(clk), .reset(rst_n), .d(st11),            .q(st12));

    //////////////////////////////////////////////
    // Output stage : register the result
    // (1 clock cycle to register the output)
    // dv_out is held until the next computation completes.
    //////////////////////////////////////////////
    assign N21 = N20;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            dv_out <= ZERO;
            valid  <= 1'b0;
        end else begin
            valid <= st12;
            if (st12)
                dv_out <= N21;
        end
    end

endmodule

////////////////////////////////////////////////
// Pre-scaling (Prescaling) Module
////////////////////////////////////////////////
module pre_scaler (
    input  logic [17:0] a,  // unsigned divisor
    input  logic [17:0] c,  // unsigned dividend
    output logic [17:0] b,  // prescaled divisor
    output logic [17:0] d   // prescaled dividend
);

    always_comb begin : SHIFT_LOGIC
        b = a;
        d = c;
        // Right shift both operands together until the divisor has
        // only 0s in its integer bits (i.e. a scaled below 1.0).
        // The integer field is 9 bits wide, so at most 9 shifts.
        for (int i = 0; i < 9; i = i + 1) begin
            // b >= 512 (Q9.9)  <=>  b[17:9] != 0  (integer field non-zero)
            if (b >= 18'd512) begin
                b = b >> 1;
                d = d >> 1;
            end
        end
    end

endmodule

////////////////////////////////////////////////
// Single-bit DFF
////////////////////////////////////////////////
module dff1 (
    input  logic clk,
    input  logic reset,
    input  logic d,
    output logic q
);
    // 1-bit parallel-load register (active-low synchronous reset)
    always_ff @(posedge clk) begin
        if (!reset)
            q <= 1'b0;
        else
            q <= d;
    end
endmodule

////////////////////////////////////////////////
// 18-bit register (parallel load)
////////////////////////////////////////////////
module reg18 (
    input  logic        clk,
    input  logic        reset,
    input  logic [17:0] data_in,
    output logic [17:0] data_out
);
    // 18-bit parallel-load register (active-low synchronous reset)
    always_ff @(posedge clk) begin
        if (!reset)
            data_out <= 18'd0;
        else
            data_out <= data_in;
    end
endmodule
