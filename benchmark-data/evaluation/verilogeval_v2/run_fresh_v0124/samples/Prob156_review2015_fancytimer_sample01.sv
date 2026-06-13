module TopModule (
    input        clk,
    input        reset,
    input        data,
    output [3:0] count,
    output       counting,
    output       done,
    input        ack
);
    localparam S    = 4'd0;  // looking for 1
    localparam S1   = 4'd1;  // saw 1
    localparam S11  = 4'd2;  // saw 11
    localparam S110 = 4'd3;  // saw 110
    localparam B0   = 4'd4;  // shift delay bit (MSB first)
    localparam B1   = 4'd5;
    localparam B2   = 4'd6;
    localparam B3   = 4'd7;
    localparam CNT  = 4'd8;  // counting
    localparam WAIT = 4'd9;  // done, waiting ack

    reg [3:0]  state, next;
    reg [3:0]  delay;        // captured delay[3:0]
    reg [3:0]  rem;          // remaining seconds (delay..0)
    reg [9:0]  subcnt;       // counts 0..999 within each second

    wire last_in_second = (subcnt == 10'd999);
    wire last_second    = (rem == 4'd0);

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
            CNT:  next = (last_in_second && last_second) ? WAIT : CNT;
            WAIT: next = ack ? S : WAIT;
            default: next = S;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state  <= S;
            delay  <= 4'd0;
            rem    <= 4'd0;
            subcnt <= 10'd0;
        end else begin
            state <= next;
            // shift in delay bits MSB first
            case (state)
                B0: delay <= {delay[2:0], data}; // collect bit 3 (MSB) first overall
                B1: delay <= {delay[2:0], data};
                B2: delay <= {delay[2:0], data};
                B3: begin
                    delay  <= {delay[2:0], data};
                    rem    <= {delay[2:0], data}; // initialize remaining = delay
                    subcnt <= 10'd0;
                end
                CNT: begin
                    if (last_in_second) begin
                        subcnt <= 10'd0;
                        if (!last_second) rem <= rem - 4'd1;
                    end else begin
                        subcnt <= subcnt + 10'd1;
                    end
                end
                default: ;
            endcase
        end
    end

    assign counting = (state == CNT);
    assign done     = (state == WAIT);
    assign count    = rem;
endmodule
