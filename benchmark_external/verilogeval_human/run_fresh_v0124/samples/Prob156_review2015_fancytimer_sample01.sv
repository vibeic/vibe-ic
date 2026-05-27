module TopModule (
  input wire clk,
  input wire reset,
  input wire data,
  output wire [3:0] count,
  output reg counting,
  output reg done,
  input wire ack
);

  // Search 1101, shift 4 delay bits (MSB first), count (delay+1)*1000 cycles,
  // then assert done until ack.
  localparam S    = 4'd0;
  localparam S1   = 4'd1;
  localparam S11  = 4'd2;
  localparam S110 = 4'd3;
  localparam D0   = 4'd4;  // shift delay bit 3 (MSB)
  localparam D1   = 4'd5;
  localparam D2   = 4'd6;
  localparam D3   = 4'd7;  // shift delay bit 0 (LSB)
  localparam CNT  = 4'd8;  // counting
  localparam WAIT = 4'd9;  // done, waiting for ack

  reg [3:0]  state, next;
  reg [3:0]  delay;        // captured delay value
  reg [3:0]  rem;          // remaining seconds (counts down)
  reg [9:0]  sub;          // 0..999 sub-counter
  wire sub_last = (sub == 10'd999);

  always @(*) begin
    case (state)
      S:    next = data ? S1   : S;
      S1:   next = data ? S11  : S;
      S11:  next = data ? S11  : S110;
      S110: next = data ? D0   : S;
      D0:   next = D1;
      D1:   next = D2;
      D2:   next = D3;
      D3:   next = CNT;
      CNT:  next = (rem == 4'd0 && sub_last) ? WAIT : CNT;
      WAIT: next = ack ? S : WAIT;
      default: next = S;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state <= S;
    end else begin
      state <= next;

      // Shift in delay bits MSB-first during the 4 shift states D0..D3.
      if (state == D0 || state == D1 || state == D2 || state == D3)
        delay <= {delay[2:0], data};

      // Load counters when entering CNT (delay fully captured after D3).
      if (state == D3) begin
        rem <= {delay[2:0], data};          // include the 4th (LSB) delay bit
        sub <= 10'd0;
      end else if (state == CNT) begin
        if (sub_last) begin
          sub <= 10'd0;
          if (rem != 4'd0)
            rem <= rem - 4'd1;
        end else begin
          sub <= sub + 10'd1;
        end
      end
    end
  end

  // Moore outputs.
  always @(*) begin
    counting = (state == CNT);
    done     = (state == WAIT);
  end

  assign count = rem;

endmodule
