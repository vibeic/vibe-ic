// sgd_linear_regression
// Stochastic Gradient Descent (SGD) linear-regression trainer.
//
// Literal spec implementation:
//   * y_pred / error / delta_w / delta_b are pure combinational logic of the
//     current weight/bias registers and the current inputs.
//   * w / b are sequential: on each rising edge (when not in reset)
//       w <= trunc(w + delta_w);  b <= trunc(b + delta_b)
//     where the sum is truncated to DATA_WIDTH (its low bits), matching the
//     reference model's apply_bit_limit().
//
// The cocotb test reads dut.w_out / dut.b_out, so the output ports are named
// w_out / b_out.
module sgd_linear_regression #(
    parameter DATA_WIDTH    = 16,
    parameter LEARNING_RATE = 3'd1
) (
    input  logic                          clk,      // Clock
    input  logic                          reset,    // Asynchronous reset (active high)
    input  logic signed [DATA_WIDTH-1:0]  x_in,     // Input data (x)
    input  logic signed [DATA_WIDTH-1:0]  y_true,   // True output (target)
    output logic signed [DATA_WIDTH-1:0]  w_out,    // Trained weight
    output logic signed [DATA_WIDTH-1:0]  b_out     // Trained bias
);

    localparam NBW_PRED  = 2*DATA_WIDTH + 1;
    localparam NBW_ERROR = NBW_PRED + 1;
    localparam NBW_DELTA = 3 + NBW_ERROR + DATA_WIDTH;

    // Signed learning-rate constant (allowed values 0/1/2 -> always positive).
    // Explicitly signed so the delta multiplications are signed.
    localparam signed [3:0] LR_S = LEARNING_RATE;

    // Weight / bias registers
    logic signed [DATA_WIDTH-1:0] w_reg, b_reg;

    // Combinational intermediates
    logic signed [NBW_PRED-1:0]  y_pred;
    logic signed [NBW_ERROR-1:0] error;
    logic signed [NBW_DELTA-1:0] delta_w;
    logic signed [NBW_DELTA-1:0] delta_b;

    // Predicted output: y_pred = w*x_in + b
    always_comb begin
        y_pred = (w_reg * x_in) + b_reg;
    end

    // Error: error = y_true - y_pred
    always_comb begin
        error = y_true - y_pred;
    end

    // Updates: delta_w = LR*error*x_in ; delta_b = LR*error
    always_comb begin
        delta_w = LR_S * error * x_in;
        delta_b = LR_S * error;
    end

    // Sequential weight/bias update (truncates to DATA_WIDTH low bits)
    always_ff @(posedge clk or posedge reset) begin
        if (reset) begin
            w_reg <= '0;
            b_reg <= '0;
        end else begin
            w_reg <= w_reg + delta_w;
            b_reg <= b_reg + delta_b;
        end
    end

    assign w_out = w_reg;
    assign b_out = b_reg;

endmodule
