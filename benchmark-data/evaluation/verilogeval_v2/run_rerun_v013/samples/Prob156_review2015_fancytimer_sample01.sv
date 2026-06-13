module TopModule (
  input        clk,
  input        reset,
  input        data,
  output [3:0] count,
  output       counting,
  output       done,
  input        ack
);

  localparam S     = 4'd0;
  localparam S1    = 4'd1;
  localparam S11   = 4'd2;
  localparam S110  = 4'd3;
  localparam B0    = 4'd4;  // shift delay bit 1 (MSB)
  localparam B1    = 4'd5;
  localparam B2    = 4'd6;
  localparam B3    = 4'd7;  // shift delay bit 4 (LSB)
  localparam CNT   = 4'd8;
  localparam DONE  = 4'd9;

  reg [3:0]  state, next;
  reg [3:0]  delay;     // shifted-in delay value
  reg [3:0]  cnt_hi;    // remaining time (high), counts down delay..0
  reg [9:0]  cnt_lo;    // 1000-cycle subdivision counter (999..0)

  wire lo_done = (cnt_lo == 10'd0);
  wire hi_done = (cnt_hi == 4'd0);

  always @(*) begin
    case (state)
      S:    next = data ? S1   : S;
      S1:   next = data ? S11  : S;
      S11:  next = data ? S11  : S110;
      S110: next = data ? B0   : S;
      B0:   next = B1;
      B1:   next = B2;
      B2:   next = B3;
      B3:   next = CNT;
      CNT:  next = (lo_done && hi_done) ? DONE : CNT;
      DONE: next = ack ? S : DONE;
      default: next = S;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state  <= S;
      delay  <= 4'd0;
      cnt_hi <= 4'd0;
      cnt_lo <= 10'd0;
    end else begin
      state <= next;

      // Shift in the 4 delay bits, MSB first
      if (state == B0 || state == B1 || state == B2 || state == B3)
        delay <= {delay[2:0], data};

      // Load counters when entering the counting phase (after 4th bit shifted)
      if (state == B3) begin
        cnt_hi <= {delay[2:0], data};   // full delay including the 4th (LSB) bit
        cnt_lo <= 10'd999;
      end else if (state == CNT) begin
        if (lo_done) begin
          if (!hi_done) begin
            cnt_hi <= cnt_hi - 4'd1;
            cnt_lo <= 10'd999;
          end
        end else begin
          cnt_lo <= cnt_lo - 10'd1;
        end
      end
    end
  end

  assign counting = (state == CNT);
  assign done     = (state == DONE);
  assign count    = cnt_hi;

endmodule
