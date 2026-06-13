module TopModule (
  input        clk,
  input        areset,

  input        predict_valid,
  input  [6:0] predict_pc,
  output       predict_taken,
  output [6:0] predict_history,

  input        train_valid,
  input        train_taken,
  input        train_mispredicted,
  input  [6:0] train_history,
  input  [6:0] train_pc
);

  reg [6:0] history;
  reg [1:0] pht [0:127];

  integer i;

  wire [6:0] predict_index = predict_pc ^ history;
  wire [6:0] train_index   = train_pc ^ train_history;

  // Prediction outputs (combinational, sees PHT state before this cycle's training)
  assign predict_taken   = pht[predict_index][1];
  assign predict_history = history;

  // saturating-counter update
  function [1:0] sat_update;
    input [1:0] cur;
    input       taken;
    begin
      if (taken)
        sat_update = (cur == 2'b11) ? 2'b11 : cur + 2'b01;
      else
        sat_update = (cur == 2'b00) ? 2'b00 : cur - 2'b01;
    end
  endfunction

  always @(posedge clk or posedge areset) begin
    if (areset) begin
      history <= 7'b0;
      for (i = 0; i < 128; i = i + 1)
        pht[i] <= 2'b01;   // weakly not-taken
    end else begin
      // PHT training update
      if (train_valid)
        pht[train_index] <= sat_update(pht[train_index], train_taken);

      // Global history register update; training misprediction takes precedence
      if (train_valid && train_mispredicted)
        history <= {train_history[5:0], train_taken};
      else if (predict_valid)
        history <= {history[5:0], predict_taken};
    end
  end

endmodule
