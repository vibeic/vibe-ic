module TopModule (
  input clk,
  input reset,
  input data,
  output reg shift_ena,
  output reg counting,
  input done_counting,
  output reg done,
  input ack
);

  localparam S0    = 4'd0,  // searching, matched ""
             S1    = 4'd1,  // matched "1"
             S2    = 4'd2,  // matched "11"
             S3    = 4'd3,  // matched "110"
             SH1   = 4'd4,  // shift_ena, cycle 1
             SH2   = 4'd5,  // shift_ena, cycle 2
             SH3   = 4'd6,  // shift_ena, cycle 3
             SH4   = 4'd7,  // shift_ena, cycle 4
             COUNT = 4'd8,  // counting, wait done_counting
             DONE  = 4'd9;  // done, wait ack

  reg [3:0] state, next;

  always @(*) begin
    case (state)
      S0:  next = data ? S1 : S0;
      S1:  next = data ? S2 : S0;
      S2:  next = data ? S2 : S3;      // "11" stays on 1, ->"110" on 0
      S3:  next = data ? SH1 : S0;     // "1101" detected on 1
      SH1: next = SH2;
      SH2: next = SH3;
      SH3: next = SH4;
      SH4: next = COUNT;
      COUNT: next = done_counting ? DONE : COUNT;
      DONE:  next = ack ? S0 : DONE;
      default: next = S0;
    endcase
  end

  always @(posedge clk) begin
    if (reset)
      state <= S0;
    else
      state <= next;
  end

  always @(*) begin
    shift_ena = (state == SH1) || (state == SH2) ||
                (state == SH3) || (state == SH4);
    counting  = (state == COUNT);
    done      = (state == DONE);
  end

endmodule
