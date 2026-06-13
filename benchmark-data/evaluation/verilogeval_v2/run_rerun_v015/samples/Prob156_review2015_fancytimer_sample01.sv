module TopModule(
    input        clk,
    input        reset,
    input        data,
    output [3:0] count,
    output       counting,
    output       done,
    input        ack
);
    localparam S    = 4'd0;  // searching: looking for 1
    localparam S1   = 4'd1;  // got 1
    localparam S11  = 4'd2;  // got 11
    localparam S110 = 4'd3;  // got 110 (pattern 1101 next bit)
    localparam D0   = 4'd4;  // shift in delay bit 3 (MSB)
    localparam D1   = 4'd5;  // shift in delay bit 2
    localparam D2   = 4'd6;  // shift in delay bit 1
    localparam D3   = 4'd7;  // shift in delay bit 0 (LSB)
    localparam CNT  = 4'd8;  // counting
    localparam WAIT = 4'd9;  // done, wait for ack

    reg [3:0]  state, next;
    reg [3:0]  delay;        // captured delay[3:0]
    reg [9:0]  subcount;     // counts 0..999 within each unit of remaining time
    reg [3:0]  remaining;    // current remaining count value

    wire sub_done   = (subcount == 10'd999);
    wire all_done   = sub_done && (remaining == 4'd0);

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
            CNT:  next = all_done ? WAIT : CNT;
            WAIT: next = ack ? S : WAIT;
            default: next = S;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= S;
        end else begin
            state <= next;
        end

        // Shift the 4 delay bits in MSB-first
        if (!reset) begin
            case (state)
                D0: delay <= {delay[2:0], data};
                D1: delay <= {delay[2:0], data};
                D2: delay <= {delay[2:0], data};
                D3: delay <= {delay[2:0], data};
                default: delay <= delay;
            endcase
        end

        // Counting bookkeeping
        if (reset) begin
            subcount  <= 10'd0;
            remaining <= 4'd0;
        end else if (state == D3) begin
            // entering CNT next: load remaining with full delay, latch last bit
            remaining <= {delay[2:0], data};
            subcount  <= 10'd0;
        end else if (state == CNT) begin
            if (sub_done) begin
                subcount <= 10'd0;
                if (remaining != 4'd0)
                    remaining <= remaining - 4'd1;
            end else begin
                subcount <= subcount + 10'd1;
            end
        end
    end

    assign counting = (state == CNT);
    assign done     = (state == WAIT);
    assign count    = remaining;
endmodule
