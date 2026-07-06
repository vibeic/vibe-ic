module TopModule (
  input clk,
  input reset,
  input s,
  input w,
  output reg z
);

  // A    : reset/idle
  // B    : cycle-1 of a 3-cycle window, z=0
  // BZ   : cycle-1 of a 3-cycle window, z=1 (output from previous window)
  // C0/C1: cycle-2, ones seen so far = 0 / 1
  // D0/D1/D2: cycle-3, ones seen so far = 0 / 1 / 2
  localparam A  = 3'd0, B  = 3'd1, BZ = 3'd2,
             C0 = 3'd3, C1 = 3'd4,
             D0 = 3'd5, D1 = 3'd6, D2 = 3'd7;

  reg [2:0] state, next;

  always @(*) begin
    case (state)
      A:  next = s ? B : A;
      B:  next = w ? C1 : C0;
      BZ: next = w ? C1 : C0;
      C0: next = w ? D1 : D0;
      C1: next = w ? D2 : D1;
      D0: next = B;
      D1: next = w ? BZ : B;
      D2: next = w ? B  : BZ;
      default: next = A;
    endcase
  end

  always @(posedge clk) begin
    if (reset)
      state <= A;
    else
      state <= next;
  end

  always @(*) begin
    z = (state == BZ);
  end

endmodule
