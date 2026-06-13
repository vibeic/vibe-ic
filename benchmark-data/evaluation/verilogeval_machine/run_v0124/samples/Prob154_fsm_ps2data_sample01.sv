module TopModule (
  input clk,
  input [7:0] in,
  input reset,
  output [23:0] out_bytes,
  output done
);

  // PS/2 packet FSM.
  // States: BYTE1, BYTE2, BYTE3, DONE.
  //   BYTE1 -> BYTE2 if in[3]==1, else stays in BYTE1
  //   BYTE2 -> BYTE3
  //   BYTE3 -> DONE
  //   DONE  -> BYTE1
  // done is 1 only in the DONE state.
  // A 24-bit shift register collects the bytes: each cycle it shifts left by
  // 8 bits and the new 8-bit input enters the low byte. out_bytes presents the
  // register contents while in DONE.

  localparam [1:0] BYTE1 = 2'd0,
                   BYTE2 = 2'd1,
                   BYTE3 = 2'd2,
                   DONE  = 2'd3;

  reg [1:0] state, next;
  reg [23:0] shift;

  // Next-state logic
  always @(*) begin
    case (state)
      BYTE1: next = in[3] ? BYTE2 : BYTE1;
      BYTE2: next = BYTE3;
      BYTE3: next = DONE;
      DONE:  next = BYTE1;
      default: next = BYTE1;
    endcase
  end

  always @(posedge clk) begin
    if (reset)
      state <= BYTE1;
    else
      state <= next;
  end

  // Shift register: shift left by 8 and bring in the new byte.
  always @(posedge clk) begin
    shift <= {shift[15:0], in};
  end

  assign done = (state == DONE);
  assign out_bytes = done ? shift : 24'd0;

endmodule
