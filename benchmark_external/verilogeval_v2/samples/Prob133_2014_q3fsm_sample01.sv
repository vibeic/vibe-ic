module TopModule (
  input  clk,
  input  reset,
  input  s,
  input  w,
  output z
);
  // State encoding:
  //   A                 : wait for s
  //   S1               : sampling cycle 1 of window (count=0 so far)
  //   S2_0, S2_1       : sampling cycle 2, count of ones so far
  //   S3_0, S3_1, S3_2 : sampling cycle 3, count of ones so far
  //   DECN, DECY       : decision cycle (z=0 / z=1), this is also sampling
  //                      cycle 1 of the NEXT window.
  localparam A    = 4'd0,
             S1   = 4'd1,
             S2_0 = 4'd2,
             S2_1 = 4'd3,
             S3_0 = 4'd4,
             S3_1 = 4'd5,
             S3_2 = 4'd6,
             DECN = 4'd7,  // decision: not exactly two ones -> z=0
             DECY = 4'd8;  // decision: exactly two ones    -> z=1

  reg [3:0] state, next;

  // counting after each sample (count = ones seen so far in current window)
  always @(*) begin
    case (state)
      A:    next = s ? S1 : A;
      // sample cycle 1 (count starts at 0)
      S1:   next = w ? S2_1 : S2_0;
      // sample cycle 2
      S2_0: next = w ? S3_1 : S3_0;
      S2_1: next = w ? S3_2 : S3_1;
      // sample cycle 3 -> decide
      S3_0: next = w ? DECN : DECN; // 0 or 1 ones total -> not two
      S3_1: next = w ? DECY : DECN; // -> 2 ones if this w=1
      S3_2: next = w ? DECN : DECY; // already 2; one more -> 3 (no), zero more -> 2 (yes)
      // decision cycle is also sample-cycle-1 of next window
      DECN: next = w ? S2_1 : S2_0;
      DECY: next = w ? S2_1 : S2_0;
      default: next = A;
    endcase
  end

  always @(posedge clk) begin
    if (reset) state <= A;
    else       state <= next;
  end

  assign z = (state == DECY);
endmodule
