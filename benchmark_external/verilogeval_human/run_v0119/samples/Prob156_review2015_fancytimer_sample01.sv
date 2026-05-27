module TopModule (
  input wire clk,
  input wire reset,
  input wire data,
  output wire [3:0] count,
  output reg counting,
  output reg done,
  input wire ack
);
    localparam S    = 4'd0,  // search for 1
               S1   = 4'd1,  // got 1
               S11  = 4'd2,  // got 11
               S110 = 4'd3,  // got 110
               B0   = 4'd4,  // capture delay bit 0 (MSB)
               B1   = 4'd5,
               B2   = 4'd6,
               B3   = 4'd7,
               COUNT= 4'd8,
               DONE = 4'd9;

    reg [3:0] state, next;
    reg [3:0] delay;     // shifted-in delay value
    reg [3:0] rem;       // remaining time (count output)
    reg [9:0] cyc;       // 0..999 within-second counter

    // next-state
    always @(*) begin
        case (state)
            S    : next = data ? S1   : S;
            S1   : next = data ? S11  : S;
            S11  : next = data ? S11  : S110;
            S110 : next = data ? B0   : S;
            B0   : next = B1;
            B1   : next = B2;
            B2   : next = B3;
            B3   : next = COUNT;
            COUNT: next = (cyc == 10'd999 && rem == 4'd0) ? DONE : COUNT;
            DONE : next = ack ? S : DONE;
            default: next = S;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= S;
        end else begin
            state <= next;
        end

        // shift in delay bits MSB-first during the bit-capture states
        case (state)
            B0: delay[3] <= data;
            B1: delay[2] <= data;
            B2: delay[1] <= data;
            B3: delay[0] <= data;
            default: ;
        endcase

        // counting datapath
        if (next == COUNT && state == B3) begin
            // entering COUNT: initialize remaining = delay just captured
            rem <= {delay[3:1], data};  // delay[3:1] already set, B3 sets bit0=data this edge
            cyc <= 10'd0;
        end else if (state == COUNT) begin
            if (cyc == 10'd999) begin
                cyc <= 10'd0;
                if (rem != 4'd0) rem <= rem - 4'd1;
            end else begin
                cyc <= cyc + 10'd1;
            end
        end
    end

    always @(*) begin
        counting = (state == COUNT);
        done     = (state == DONE);
    end

    assign count = rem;
endmodule
