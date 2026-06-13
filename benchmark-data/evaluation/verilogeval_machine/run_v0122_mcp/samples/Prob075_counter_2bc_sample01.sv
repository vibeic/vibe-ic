// Prob075_counter_2bc — 2-bit saturating counter FSM (branch-predictor style).
// Asynchronous reset to state 1. On valid+taken increment (saturate at 3);
// on valid+!taken decrement (saturate at 0); hold otherwise.
module TopModule (
  input clk,
  input areset,
  input train_valid,
  input train_taken,
  output logic [1:0] state
);

  always @(posedge clk or posedge areset) begin
    if (areset)
      state <= 2'd1;
    else if (train_valid) begin
      if (train_taken && state < 2'd3)
        state <= state + 2'd1;
      else if (!train_taken && state > 2'd0)
        state <= state - 2'd1;
      // else hold
    end
    // else hold when !train_valid
  end

endmodule
