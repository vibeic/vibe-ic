module TopModule (
  input wire clk,
  input wire reset,
  input wire data,
  output wire [3:0] count,
  output reg counting,
  output reg done,
  input wire ack
);
  localparam S0   = 3'd0;  // looking for 1
  localparam S1   = 3'd1;  // saw 1
  localparam S2   = 3'd2;  // saw 11
  localparam S3   = 3'd3;  // saw 110
  localparam SHFT = 3'd4;  // shifting in 4 delay bits
  localparam CNT  = 3'd5;  // counting
  localparam DN   = 3'd6;  // done

  reg [2:0] state, next;
  reg [3:0] delay;        // delay value, also the displayed remaining count
  reg [1:0] shift_cnt;    // counts the 4 shifted-in bits
  reg [9:0] sub_cnt;      // 0..999 within each 1000-cycle interval

  always @(*) begin
    case (state)
      S0:   next = data ? S1 : S0;
      S1:   next = data ? S2 : S0;
      S2:   next = data ? S2 : S3;
      S3:   next = data ? SHFT : S0;  // 1101 detected
      SHFT: next = (shift_cnt == 2'd3) ? CNT : SHFT;
      CNT:  next = (delay == 4'd0 && sub_cnt == 10'd999) ? DN : CNT;
      DN:   next = ack ? S0 : DN;
      default: next = S0;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      state     <= S0;
      delay     <= 4'd0;
      shift_cnt <= 2'd0;
      sub_cnt   <= 10'd0;
    end else begin
      state <= next;
      case (state)
        S3: if (data) shift_cnt <= 2'd0;   // about to start shifting
        SHFT: begin
          delay     <= {delay[2:0], data}; // MSB first
          shift_cnt <= shift_cnt + 2'd1;
        end
        CNT: begin
          if (sub_cnt == 10'd999) begin
            sub_cnt <= 10'd0;
            if (delay != 4'd0)
              delay <= delay - 4'd1;
          end else begin
            sub_cnt <= sub_cnt + 10'd1;
          end
        end
        default: ;
      endcase
    end
  end

  always @(*) begin
    counting = (state == CNT);
    done     = (state == DN);
  end

  assign count = delay;
endmodule
