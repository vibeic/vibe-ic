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
  reg [6:0]  ghr;            // global history register
  reg [1:0]  pht [0:127];    // 128-entry 2-bit saturating counters
  integer    i;

  wire [6:0] pidx = predict_pc ^ ghr;
  wire [6:0] tidx = train_pc ^ train_history;

  // Prediction outputs are combinational reads of current state
  assign predict_history = ghr;
  assign predict_taken   = pht[pidx][1];

  // saturating counter update
  function [1:0] sat_update(input [1:0] cur, input taken);
    if (taken) sat_update = (cur == 2'b11) ? 2'b11 : cur + 2'b01;
    else       sat_update = (cur == 2'b00) ? 2'b00 : cur - 2'b01;
  endfunction

  always @(posedge clk or posedge areset) begin
    if (areset) begin
      ghr <= 7'b0;
      for (i = 0; i < 128; i = i + 1)
        pht[i] <= 2'b01;     // weakly not-taken
    end else begin
      // PHT training (occurs at next clock edge)
      if (train_valid)
        pht[tidx] <= sat_update(pht[tidx], train_taken);

      // GHR update: training (misprediction recovery) takes precedence
      if (train_valid && train_mispredicted)
        ghr <= {train_history[5:0], train_taken};
      else if (predict_valid)
        ghr <= {ghr[5:0], predict_taken};
    end
  end
endmodule
