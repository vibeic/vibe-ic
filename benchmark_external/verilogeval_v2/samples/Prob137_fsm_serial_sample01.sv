module TopModule (
  input  clk,
  input  reset,
  input  in,
  output done
);

  localparam IDLE=0, DATA=1, STOP=2, DONE=3, WAITSTOP=4;
  reg [2:0] state, next;
  reg [3:0] cnt;

  always @(*) begin
    next = state;
    case (state)
      IDLE:     next = (in == 1'b0) ? DATA : IDLE;       // start bit
      DATA:     next = (cnt == 4'd7) ? STOP : DATA;       // 8 data bits
      STOP:     next = (in == 1'b1) ? DONE : WAITSTOP;    // stop bit check
      DONE:     next = (in == 1'b0) ? DATA : IDLE;        // can start next byte
      WAITSTOP: next = (in == 1'b1) ? IDLE : WAITSTOP;    // wait for a stop bit
      default:  next = IDLE;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state <= IDLE;
      cnt   <= 0;
    end else begin
      state <= next;
      if (state == DATA) cnt <= cnt + 4'd1;
      else               cnt <= 0;
    end
  end

  assign done = (state == DONE);

endmodule
