module cont_adder #(
    parameter DATA_WIDTH = 32,
    parameter signed THRESHOLD_VALUE_1 = 50,
    parameter signed THRESHOLD_VALUE_2 = 100,
    parameter SIGNED_INPUTS = 1,
    parameter ACCUM_MODE = 0,
    parameter signed WEIGHT = 1
) (
    input  logic                         clk,
    input  logic                         reset,
    input  logic signed [DATA_WIDTH-1:0] data_in,
    input  logic                         data_valid,
    input  logic [15:0]                  window_size,
    output logic signed [DATA_WIDTH-1:0] sum_out,
    output logic signed [DATA_WIDTH-1:0] avg_out,
    output logic                         threshold_1,
    output logic                         threshold_2,
    output logic                         sum_ready
);

    // Accumulator carries two extra guard bits over the data path.
    localparam int ACC_WIDTH = DATA_WIDTH + 2;

    // Sequential Registers
    logic signed [ACC_WIDTH-1:0]  sum_accum;
    logic        [15:0]           sample_count;

    // Combinational Signals
    logic signed [ACC_WIDTH-1:0]  weighted_full;   // full-width product (no truncation warning)
    logic signed [ACC_WIDTH-1:0]  new_sum;         // accumulator-width running sum
    logic signed [DATA_WIDTH-1:0] avg_q;           // output-width quotient (fully used)
    logic signed [DATA_WIDTH-1:0] window_signed;   // window_size as a positive signed value
    logic                         threshold_1_comb;
    logic                         threshold_2_comb;
    logic                         sum_ready_reg;
    logic        [16:0]           next_count;       // sample_count + 1 (extra bit avoids truncation)

    // Combinational Logic
    always @(*) begin
        sum_ready_reg = 1'b0;

        // Respect the SIGNED_INPUTS parameter when forming the weighted input.
        if (SIGNED_INPUTS)
            weighted_full = ACC_WIDTH'(data_in) * ACC_WIDTH'(WEIGHT);
        else
            weighted_full = ACC_WIDTH'($unsigned(data_in)) * ACC_WIDTH'(WEIGHT);

        new_sum = sum_accum + weighted_full;

        threshold_1_comb = (new_sum >= ACC_WIDTH'(THRESHOLD_VALUE_1)) ||
                           (new_sum <= -ACC_WIDTH'(THRESHOLD_VALUE_1));
        threshold_2_comb = (new_sum >= ACC_WIDTH'(THRESHOLD_VALUE_2)) ||
                           (new_sum <= -ACC_WIDTH'(THRESHOLD_VALUE_2));

        next_count = {1'b0, sample_count} + 17'd1;

        // Average computed in the output bit-width: both operands are DATA_WIDTH
        // signed, so the quotient is fully used (no width-expand / unused bits).
        window_signed = $signed({{(DATA_WIDTH-16){1'b0}}, window_size});
        avg_q         = new_sum[DATA_WIDTH-1:0] / window_signed;

        if (data_valid) begin
            if (ACCUM_MODE == 0) begin
                sum_ready_reg = (threshold_1_comb || threshold_2_comb);
            end else if (ACCUM_MODE == 1) begin
                sum_ready_reg = (next_count >= {1'b0, window_size});
            end
        end
    end

    always_ff @(posedge clk or posedge reset) begin
        if (reset) begin
            sum_accum     <= '0;
            sample_count  <= 16'd0;
            sum_ready     <= 1'b0;
            sum_out       <= '0;
            avg_out       <= '0;
            threshold_1   <= 1'b0;
            threshold_2   <= 1'b0;
        end else if (data_valid) begin
            threshold_1 <= threshold_1_comb;
            threshold_2 <= threshold_2_comb;

            if (ACCUM_MODE == 1) begin
                sum_accum    <= new_sum;
                sample_count <= next_count[15:0];
                if (sum_ready_reg) begin
                    sum_out      <= new_sum[DATA_WIDTH-1:0];
                    avg_out      <= avg_q;
                    sum_ready    <= 1'b1;
                    sum_accum    <= '0;
                    sample_count <= 16'd0;
                end else begin
                    sum_ready <= 1'b0;
                    sum_out   <= '0;
                    avg_out   <= '0;
                end
            end else begin
                sum_accum <= new_sum;
                if (sum_ready_reg) begin
                    sum_out   <= new_sum[DATA_WIDTH-1:0];
                    sum_ready <= 1'b1;
                end else begin
                    sum_ready <= 1'b0;
                    sum_out   <= '0;
                end
                avg_out <= '0;
            end
        end else begin
            sum_ready <= 1'b0;
        end
    end

endmodule
