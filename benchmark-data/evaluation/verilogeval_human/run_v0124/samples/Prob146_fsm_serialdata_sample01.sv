module TopModule (
  input clk,
  input in,
  input reset,
  output [7:0] out_byte,
  output done
);

  localparam IDLE  = 3'd0,  // waiting for start bit (line idle = 1)
             DATA  = 3'd1,  // receiving 8 data bits
             STOP  = 3'd2,  // checking stop bit
             DONE  = 3'd3,  // stop bit good, assert done
             WAIT  = 3'd4;  // bad stop bit: wait for a stop bit (1)
  reg [2:0] state, next;
  reg [3:0] cnt;            // counts data bits received
  reg [7:0] shifter;

  always @(*) begin
    case (state)
      IDLE: next = (in == 1'b0) ? DATA : IDLE;       // detect start bit
      DATA: next = (cnt == 4'd7) ? STOP : DATA;       // after 8 data bits
      STOP: next = (in == 1'b1) ? DONE : WAIT;        // stop bit check
      DONE: next = (in == 1'b0) ? DATA : IDLE;        // immediately can start next
      WAIT: next = (in == 1'b1) ? IDLE : WAIT;        // wait until line returns to 1
      default: next = IDLE;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state   <= IDLE;
      cnt     <= 4'd0;
      shifter <= 8'd0;
    end else begin
      state <= next;
      if (state == DATA) begin
        // shift in LSB first
        shifter <= {in, shifter[7:1]};
        cnt     <= cnt + 4'd1;
      end else begin
        cnt <= 4'd0;
      end
    end
  end

  assign done     = (state == DONE);
  assign out_byte = shifter;

endmodule
