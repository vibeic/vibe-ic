module TopModule (
  input            clk,
  input            areset,

  input            predict_valid,
  input      [6:0] predict_pc,
  output           predict_taken,
  output     [6:0] predict_history,

  input            train_valid,
  input            train_taken,
  input            train_mispredicted,
  input      [6:0] train_history,
  input      [6:0] train_pc
);

  // 7-bit global history register and 128-entry PHT of 2-bit saturating counters.
  reg [6:0] ghr;
  reg [1:0] pht [0:127];
  integer i;

  // ---- Prediction (combinational read of pre-training PHT state) ----
  wire [6:0] p_index = predict_pc ^ ghr;
  assign predict_taken   = pht[p_index][1];   // MSB of 2-bit counter
  assign predict_history = ghr;               // history used for this prediction

  // ---- Training index and saturating update ----
  wire [6:0] t_index = train_pc ^ train_history;
  wire [1:0] t_cur   = pht[t_index];
  wire [1:0] t_next  = train_taken ? (t_cur == 2'b11 ? 2'b11 : t_cur + 2'b01)
                                   : (t_cur == 2'b00 ? 2'b00 : t_cur - 2'b01);

  always @(posedge clk or posedge areset) begin
    if (areset) begin
      ghr <= 7'b0;
      for (i = 0; i < 128; i = i + 1)
        pht[i] <= 2'b01;                       // weakly not-taken
    end else begin
      // PHT update on training (takes effect next clock; prediction read above sees old value)
      if (train_valid)
        pht[t_index] <= t_next;

      // GHR update: training (misprediction recovery) takes precedence over prediction
      if (train_valid && train_mispredicted)
        ghr <= {train_history[5:0], train_taken};
      else if (predict_valid)
        ghr <= {ghr[5:0], predict_taken};
    end
  end

endmodule
