module TopModule (
  input  clk,
  input  reset,
  input  data,
  output reg shift_ena,
  output reg counting,
  input  done_counting,
  output reg done,
  input  ack
);

  // Moore timer-control FSM.
  localparam S     = 4'd0;  // searching: nothing matched
  localparam S1    = 4'd1;  // "1"
  localparam S11   = 4'd2;  // "11"
  localparam S110  = 4'd3;  // "110"
  localparam B0    = 4'd4;  // shift_ena, cycle 1
  localparam B1    = 4'd5;  // shift_ena, cycle 2
  localparam B2    = 4'd6;  // shift_ena, cycle 3
  localparam B3    = 4'd7;  // shift_ena, cycle 4
  localparam COUNT = 4'd8;  // counting
  localparam WAIT  = 4'd9;  // done, waiting for ack

  reg [3:0] state, next;

  always @(*) begin
    case (state)
      S:     next = data ? S1   : S;
      S1:    next = data ? S11  : S;
      S11:   next = data ? S11  : S110;   // pattern 1101
      S110:  next = data ? B0   : S;
      B0:    next = B1;
      B1:    next = B2;
      B2:    next = B3;
      B3:    next = COUNT;
      COUNT: next = done_counting ? WAIT : COUNT;
      WAIT:  next = ack ? S : WAIT;
      default: next = S;
    endcase
  end

  always @(posedge clk) begin
    if (reset)
      state <= S;
    else
      state <= next;
  end

  // Moore outputs decoded from the registered state.
  always @(*) begin
    shift_ena = (state == B0) || (state == B1) || (state == B2) || (state == B3);
    counting  = (state == COUNT);
    done      = (state == WAIT);
  end

endmodule
