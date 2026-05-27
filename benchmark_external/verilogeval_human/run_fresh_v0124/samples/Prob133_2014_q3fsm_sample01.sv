module TopModule (
  input clk,
  input reset,
  input s,
  input w,
  output reg z
);

  localparam A      = 4'd0;  // wait for s
  localparam W1_Z0  = 4'd1;  // window cycle 1, prior result 0
  localparam W1_Z1  = 4'd2;  // window cycle 1, prior result 1 (z=1)
  localparam W2_C0  = 4'd3;  // window cycle 2, count so far 0
  localparam W2_C1  = 4'd4;  // window cycle 2, count so far 1
  localparam W3_C0  = 4'd5;  // window cycle 3, count so far 0
  localparam W3_C1  = 4'd6;  // window cycle 3, count so far 1
  localparam W3_C2  = 4'd7;  // window cycle 3, count so far 2

  reg [3:0] state;

  always @(posedge clk) begin
    if (reset)
      state <= A;
    else begin
      case (state)
        A:     state <= s ? W1_Z0 : A;
        W1_Z0: state <= w ? W2_C1 : W2_C0;
        W1_Z1: state <= w ? W2_C1 : W2_C0;
        W2_C0: state <= w ? W3_C1 : W3_C0;
        W2_C1: state <= w ? W3_C2 : W3_C1;
        W3_C0: state <= W1_Z0;                  // total 0 or 1 -> not exactly 2
        W3_C1: state <= w ? W1_Z1 : W1_Z0;      // total 2 if w=1
        W3_C2: state <= w ? W1_Z0 : W1_Z1;      // total 2 if w=0
        default: state <= A;
      endcase
    end
  end

  always @(*) begin
    z = (state == W1_Z1);
  end

endmodule
