module TopModule (
  input clk,
  input areset,
  input x,
  output z
);

  // Serial 2's complementer (LSB first), MOORE state machine.
  // Algorithm: copy input bits from the LSB up to and INCLUDING the
  // first '1'; invert every input bit AFTER the first '1'.
  //
  // Because this is a MOORE machine, the output z is a function of the
  // CURRENT STATE ONLY (registered). The state is updated at each posedge
  // by consuming the current input bit and computing the output bit that
  // belongs to that consumed bit. Hence z lags the input by ONE cycle.
  //
  // State encodes (seen_a_one, output_bit_to_present):
  //   A : seen=0, z=0  -- copy mode, last copied bit was 0 (also reset state)
  //   P : seen=1, z=1  -- saw the first 1 / inverted a 0  -> present 1
  //   Q : seen=1, z=0  -- inverted a 1                    -> present 0
  localparam A = 2'd0,  // copy, output 0
             P = 2'd1,  // seen, output 1
             Q = 2'd2;  // seen, output 0
  reg [1:0] state;

  always @(posedge clk or posedge areset) begin
    if (areset)
      state <= A;
    else begin
      case (state)
        A: state <= x ? P : A;   // copy: x=1 -> first one (out 1, now seen); x=0 -> stay (out 0)
        P: state <= x ? Q : P;   // invert: x=1 -> 0 (Q); x=0 -> 1 (P)
        Q: state <= x ? Q : P;   // invert: x=1 -> 0 (Q); x=0 -> 1 (P)
        default: state <= A;
      endcase
    end
  end

  // Moore output: strictly a function of state.
  assign z = (state == P);

endmodule
