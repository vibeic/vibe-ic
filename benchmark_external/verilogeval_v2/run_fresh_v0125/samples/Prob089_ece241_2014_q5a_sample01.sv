module TopModule (
  input  clk,
  input  areset,
  input  x,
  output z
);

  // Moore serial 2's complementer, LSB first.
  // 2's complement rule: copy bits up to and including the first 1,
  // then invert every subsequent bit.
  // State encodes whether a 1 has already been seen AND the bit to emit (Moore).
  // S0: no 1 seen yet, emit 0
  // S1: emitting a copied/processed bit = 1
  // S2: a 1 has been seen, emit 0 (inverted incoming 1)
  localparam [1:0] S0 = 2'd0,  // not yet seen first 1, current output 0
                   S1 = 2'd1,  // current output 1
                   S2 = 2'd2;  // seen first 1, current output 0

  reg [1:0] state, next;

  always @(*) begin
    case (state)
      // Before first 1: output equals input; once a 1 arrives we transition
      // to the "seen" path and from then on output is the inverted input.
      S0: next = x ? S1 : S0;
      S1: next = x ? S2 : S1;  // already seen first 1 -> invert subsequent bits
      S2: next = x ? S2 : S1;
      default: next = S0;
    endcase
  end

  always @(posedge clk or posedge areset) begin
    if (areset)
      state <= S0;
    else
      state <= next;
  end

  // Moore output depends only on state
  assign z = (state == S1);

endmodule
