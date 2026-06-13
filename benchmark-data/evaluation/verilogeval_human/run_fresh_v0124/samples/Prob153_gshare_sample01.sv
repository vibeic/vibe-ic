module TopModule (
  input clk,
  input areset,

  input predict_valid,
  input [6:0] predict_pc,
  output predict_taken,
  output [6:0] predict_history,

  input train_valid,
  input train_taken,
  input train_mispredicted,
  input [6:0] train_history,
  input [6:0] train_pc
);

  reg [6:0] ghr;            // global history register
  reg [1:0] pht [0:127];    // 128-entry 2-bit saturating counters
  integer i;

  wire [6:0] predict_index = predict_pc ^ ghr;
  wire [6:0] train_index   = train_pc ^ train_history;

  // Prediction is combinational: reads PHT before any training update.
  assign predict_taken   = pht[predict_index][1];
  assign predict_history = ghr;

  // 2-bit saturating counter update toward 'taken'.
  function [1:0] sat_update;
    input [1:0] cnt;
    input taken;
    begin
      if (taken)
        sat_update = (cnt == 2'b11) ? 2'b11 : cnt + 2'b01;
      else
        sat_update = (cnt == 2'b00) ? 2'b00 : cnt - 2'b01;
    end
  endfunction

  always @(posedge clk or posedge areset) begin
    if (areset) begin
      ghr <= 7'b0;
      for (i = 0; i < 128; i = i + 1)
        pht[i] <= 2'b01;     // weakly not-taken
    end else begin
      // PHT training update.
      if (train_valid)
        pht[train_index] <= sat_update(pht[train_index], train_taken);

      // GHR update: training (mispredict recovery) takes precedence.
      if (train_valid && train_mispredicted)
        ghr <= {train_history[5:0], train_taken};
      else if (predict_valid)
        ghr <= {ghr[5:0], predict_taken};
    end
  end

endmodule
