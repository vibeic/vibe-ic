module TopModule (
  input  clk,
  input  in,
  input  reset,
  output [7:0] out_byte,
  output done
);

  localparam IDLE=0, DATA=1, STOP=2, DONE=3, WAITSTOP=4;
  reg [2:0] state, next;
  reg [3:0] cnt;
  reg [7:0] shifter;

  always @(*) begin
    next = state;
    case (state)
      IDLE:     next = (in == 1'b0) ? DATA : IDLE;
      DATA:     next = (cnt == 4'd7) ? STOP : DATA;
      STOP:     next = (in == 1'b1) ? DONE : WAITSTOP;
      DONE:     next = (in == 1'b0) ? DATA : IDLE;
      WAITSTOP: next = (in == 1'b1) ? IDLE : WAITSTOP;
      default:  next = IDLE;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state <= IDLE;
      cnt   <= 0;
    end else begin
      state <= next;
      if (state == DATA) begin
        cnt     <= cnt + 4'd1;
        shifter <= {in, shifter[7:1]};  // LSB first
      end else begin
        cnt <= 0;
      end
    end
  end

  assign done     = (state == DONE);
  assign out_byte = shifter;

endmodule
