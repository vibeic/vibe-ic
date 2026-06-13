module TopModule (
  input clk,
  input in,
  input reset,
  output done
);

  // Serial framing: idle/stop line is 1; start bit is 0; then 8 data bits;
  // then 1 stop bit (must be 1). done asserts the cycle after a correct stop.
  localparam IDLE  = 3'd0,  // waiting for start bit (in==0)
             DATA  = 3'd1,  // receiving 8 data bits
             STOP  = 3'd2,  // checking stop bit
             DONE  = 3'd3,  // byte received correctly; done=1
             WAITE = 3'd4;  // bad stop bit: wait for line to return to 1

  reg [2:0] state, next;
  reg [3:0] cnt, cnt_next;   // counts data bits 0..7

  always @(*) begin
    next = state;
    cnt_next = cnt;
    case (state)
      IDLE: begin
        if (in == 1'b0) begin next = DATA; cnt_next = 4'd0; end
        else next = IDLE;
      end
      DATA: begin
        if (cnt == 4'd7) begin next = STOP; end
        else begin cnt_next = cnt + 4'd1; next = DATA; end
      end
      STOP: begin
        if (in == 1'b1) next = DONE;    // valid stop bit
        else            next = WAITE;   // framing error -> recover
      end
      DONE: begin
        // After done, look for the next start bit.
        if (in == 1'b0) begin next = DATA; cnt_next = 4'd0; end
        else next = IDLE;
      end
      WAITE: begin
        if (in == 1'b1) next = IDLE;    // line back to idle; ready for next
        else            next = WAITE;
      end
      default: next = IDLE;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state <= IDLE;
      cnt   <= 4'd0;
    end else begin
      state <= next;
      cnt   <= cnt_next;
    end
  end

  assign done = (state == DONE);

endmodule
