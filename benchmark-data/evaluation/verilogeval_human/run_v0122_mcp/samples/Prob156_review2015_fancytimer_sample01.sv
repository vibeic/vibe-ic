module TopModule (
  input  wire       clk,
  input  wire       reset,
  input  wire       data,
  output wire [3:0] count,
  output reg        counting,
  output reg        done,
  input  wire       ack
);

  // FSM states
  localparam S     = 3'd0,  // search, none matched
             S1    = 3'd1,  // saw 1
             S11   = 3'd2,  // saw 11
             S110  = 3'd3,  // saw 110
             SHIFT = 3'd4,  // shifting in 4 delay bits, MSB first
             COUNT = 3'd5,  // counting down
             DONE  = 3'd6;  // timed out, waiting for ack

  reg  [2:0] state, next;
  reg  [3:0] delay;         // remaining delay value, also the count output during COUNT
  reg  [1:0] sbits;         // number of delay bits shifted so far (0..4)
  reg  [9:0] subcnt;        // 0..999 sub-cycle counter for each 1000-cycle interval

  wire sub_done  = (subcnt == 10'd999);
  wire last_tick = sub_done && (delay == 4'd0);

  always @(*) begin
    case (state)
      S:     next = data ? S1   : S;
      S1:    next = data ? S11  : S;
      S11:   next = data ? S11  : S110;
      S110:  next = data ? SHIFT: S;          // 1101 detected; begin shifting delay
      SHIFT: next = (sbits == 2'd3) ? COUNT : SHIFT;  // 4th bit completes the load
      COUNT: next = last_tick ? DONE : COUNT;
      DONE:  next = ack ? S : DONE;
      default: next = S;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state  <= S;
      delay  <= 4'd0;
      sbits  <= 2'd0;
      subcnt <= 10'd0;
    end else begin
      state <= next;

      // shift in delay bits MSB-first
      if (state == SHIFT) begin
        delay <= {delay[2:0], data};
        sbits <= sbits + 2'd1;
      end else if (state != COUNT) begin
        sbits <= 2'd0;
      end

      // counting: 1000-cycle sub-intervals, decrement delay each interval
      if (state == COUNT) begin
        if (sub_done) begin
          subcnt <= 10'd0;
          if (delay != 4'd0)
            delay <= delay - 4'd1;
        end else begin
          subcnt <= subcnt + 10'd1;
        end
      end else begin
        subcnt <= 10'd0;
      end
    end
  end

  // outputs
  always @(*) begin
    counting = (state == COUNT);
    done     = (state == DONE);
  end

  assign count = delay;     // remaining time; don't-care when not counting

endmodule
