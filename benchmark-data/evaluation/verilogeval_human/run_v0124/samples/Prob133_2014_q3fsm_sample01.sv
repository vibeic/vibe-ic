module TopModule (
  input clk,
  input reset,
  input s,
  input w,
  output reg z
);

  // State A waits for s=1. After s=1, the FSM enters the counting region and
  // examines w over windows of 3 clock cycles. If exactly two of the three w
  // samples are 1, z is asserted in the cycle following the third sample.
  localparam A = 2'd0,  // wait for s
             P0 = 2'd1, // first w of the window (count starts at this w)
             P1 = 2'd2, // second w
             P2 = 2'd3; // third w

  reg [1:0] state, next;
  reg [1:0] cnt, cnt_next;   // running count of w==1 in current window

  always @(*) begin
    next = state;
    cnt_next = cnt;
    case (state)
      A: begin
        if (s) begin next = P0; cnt_next = 2'd0; end
        else   next = A;
      end
      P0: begin
        cnt_next = {1'b0, w};   // first sample
        next = P1;
      end
      P1: begin
        cnt_next = cnt + w;     // second sample accumulates
        next = P2;
      end
      P2: begin
        cnt_next = cnt + w;     // third sample accumulates (used for z next cycle)
        next = P0;              // start a new window
      end
      default: begin next = A; cnt_next = 2'd0; end
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state <= A;
      cnt   <= 2'd0;
      z     <= 1'b0;
    end else begin
      state <= next;
      cnt   <= cnt_next;
      // z asserted in the cycle right after the third sample (state P2 just done)
      z <= (state == P2) && (cnt_next == 2'd2);
    end
  end

endmodule
