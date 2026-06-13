module TopModule (
  input        clk,
  input        in,
  input        reset,
  output [7:0] out_byte,
  output       done
);

  localparam IDLE = 3'd0,  // line idle/searching for start bit (0)
             DATA = 3'd1,  // shifting in 8 data bits, LSB first
             STOP = 3'd2,  // checking stop bit (must be 1)
             DONE = 3'd3,  // valid byte received: assert done one cycle
             WAIT = 3'd4;  // stop-bit error: wait for line to return to 1

  reg [2:0] state, next;
  reg [3:0] cnt;            // counts data bits 0..8
  reg [7:0] shift;          // received data, LSB first

  always @(*) begin
    case (state)
      IDLE: next = (in == 1'b0) ? DATA : IDLE;          // start bit
      DATA: next = (cnt == 4'd7) ? STOP : DATA;         // 8 data bits
      STOP: next = (in == 1'b1) ? DONE : WAIT;          // stop bit check
      DONE: next = (in == 1'b0) ? DATA : IDLE;          // back-to-back frames
      WAIT: next = (in == 1'b1) ? IDLE : WAIT;          // resync on idle high
      default: next = IDLE;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state <= IDLE;
      cnt   <= 4'd0;
      shift <= 8'd0;
    end else begin
      state <= next;
      if (state == DATA) begin
        shift <= {in, shift[7:1]};   // LSB first: new bit enters at MSB, shifts right
        cnt   <= cnt + 4'd1;
      end else begin
        cnt   <= 4'd0;
      end
    end
  end

  assign done     = (state == DONE);
  assign out_byte = shift;

endmodule
