module TopModule (
    input        clk,
    input        reset,
    input        data,
    output [3:0] count,
    output       counting,
    output       done,
    input        ack
);
    localparam S     = 4'd0;  // searching, last bits
    localparam S1    = 4'd1;  // saw 1
    localparam S11   = 4'd2;  // saw 11
    localparam S110  = 4'd3;  // saw 110
    localparam SH0   = 4'd4;  // shift in delay bit 3 (MSB)
    localparam SH1   = 4'd5;  // shift in delay bit 2
    localparam SH2   = 4'd6;  // shift in delay bit 1
    localparam SH3   = 4'd7;  // shift in delay bit 0 (LSB)
    localparam COUNT = 4'd8;  // counting
    localparam DONE  = 4'd9;  // timed out, wait for ack

    reg [3:0]  state, next;
    reg [3:0]  delay;        // shifted-in delay value / current remaining
    reg [9:0]  subcnt;       // 0..999 within each 1000-cycle interval

    wire last_tick = (subcnt == 10'd999);
    wire count_done = last_tick && (delay == 4'd0);

    always @(*) begin
        case (state)
            S:     next = data ? S1   : S;
            S1:    next = data ? S11  : S;
            S11:   next = data ? S11  : S110;   // stay on 1, 110 on 0
            S110:  next = data ? SH0  : S;      // 1101 detected
            SH0:   next = SH1;
            SH1:   next = SH2;
            SH2:   next = SH3;
            SH3:   next = COUNT;
            COUNT: next = count_done ? DONE : COUNT;
            DONE:  next = ack ? S : DONE;
            default: next = S;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state  <= S;
            delay  <= 4'd0;
            subcnt <= 10'd0;
        end else begin
            state <= next;
            // shift in the 4 delay bits MSB-first
            if (state == S110 && data) begin
                delay <= 4'd0;  // clear before shifting (shift happens in SH states)
            end
            if (state == SH0 || state == SH1 || state == SH2 || state == SH3) begin
                delay <= {delay[2:0], data};
            end
            // counting datapath
            if (next == COUNT && state != COUNT) begin
                subcnt <= 10'd0;          // start counting fresh
            end else if (state == COUNT) begin
                if (last_tick) begin
                    subcnt <= 10'd0;
                    if (delay != 4'd0) delay <= delay - 4'd1;  // remaining time decrements
                end else begin
                    subcnt <= subcnt + 10'd1;
                end
            end
        end
    end

    assign counting = (state == COUNT);
    assign done     = (state == DONE);
    assign count    = delay;   // remaining time (don't-care when not counting)
endmodule
