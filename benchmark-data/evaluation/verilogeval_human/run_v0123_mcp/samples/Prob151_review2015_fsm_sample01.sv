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

  localparam S    = 4'd0,  // searching for 1101
             S1   = 4'd1,  // got 1
             S11  = 4'd2,  // got 11
             S110 = 4'd3,  // got 110
             B0   = 4'd4,  // shift bit 0
             B1   = 4'd5,
             B2   = 4'd6,
             B3   = 4'd7,
             CNT  = 4'd8,  // counting
             WAIT = 4'd9;  // done, wait for ack
  reg [3:0] state, next;

  always @(*) begin
    case (state)
      S:    next = data ? S1   : S;
      S1:   next = data ? S11  : S;
      S11:  next = data ? S11  : S110;
      S110: next = data ? B0   : S;
      B0:   next = B1;
      B1:   next = B2;
      B2:   next = B3;
      B3:   next = CNT;
      CNT:  next = done_counting ? WAIT : CNT;
      WAIT: next = ack ? S : WAIT;
      default: next = S;
    endcase
  end

  always @(posedge clk) begin
    if (reset) state <= S;
    else       state <= next;
  end

  always @(*) begin
    shift_ena = (state == B0) | (state == B1) | (state == B2) | (state == B3);
    counting  = (state == CNT);
    done      = (state == WAIT);
  end

endmodule
