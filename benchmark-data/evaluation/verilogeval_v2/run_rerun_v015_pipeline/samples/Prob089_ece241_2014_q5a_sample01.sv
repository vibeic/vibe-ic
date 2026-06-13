module TopModule (
  input  clk,
  input  areset,
  input  x,
  output z
);
  // Moore serial 2's complementer, LSB first.
  // 2's complement = copy bits up to and including the first 1, then invert the rest.
  // State A: no 1 seen yet (output = input bit). State B: a 1 has been seen (output = inverted input bit).
  // Async positive-edge reset begins a new conversion (state A).
  localparam A = 1'b0, B = 1'b1;
  reg state;

  always @(posedge clk or posedge areset) begin
    if (areset)
      state <= A;
    else begin
      case (state)
        A: state <= x ? B : A;  // once a 1 is passed through, switch to inverting
        B: state <= B;
        default: state <= A;
      endcase
    end
  end

  // Moore-style: output depends on state and current input (output = bit emitted this cycle).
  // In state A: z = x (pass through until first 1). In state B: z = ~x (invert).
  assign z = (state == A) ? x : ~x;
endmodule
