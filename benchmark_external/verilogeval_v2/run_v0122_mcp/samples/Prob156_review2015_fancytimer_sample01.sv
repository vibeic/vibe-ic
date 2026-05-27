module TopModule (
    input        clk,
    input        reset,
    input        data,
    output [3:0] count,
    output       counting,
    output       done,
    input        ack
);
    localparam IDLE  = 4'd0;  // searching: need '1'
    localparam D1    = 4'd1;  // got 1
    localparam D11   = 4'd2;  // got 11
    localparam D110  = 4'd3;  // got 110
    localparam SH0   = 4'd4;  // shift delay bit 3 (MSB)
    localparam SH1   = 4'd5;
    localparam SH2   = 4'd6;
    localparam SH3   = 4'd7;  // shift delay bit 0 (LSB)
    localparam CNT   = 4'd8;  // counting
    localparam DONE  = 4'd9;  // wait ack

    reg [3:0]  state, next;
    reg [3:0]  delay;        // remaining delay value (count output)
    reg [9:0]  subcnt;       // counts 0..999 within each unit

    wire sub_last  = (subcnt == 10'd999);
    wire delay_last = (delay == 4'd0);

    always @(*) begin
        case (state)
            IDLE: next = data ? D1 : IDLE;
            D1:   next = data ? D11 : IDLE;
            D11:  next = data ? D11 : D110;       // need a 0 next
            D110: next = data ? SH0 : IDLE;       // '1101' complete -> shift
            SH0:  next = SH1;
            SH1:  next = SH2;
            SH2:  next = SH3;
            SH3:  next = CNT;
            CNT:  next = (sub_last && delay_last) ? DONE : CNT;
            DONE: next = ack ? IDLE : DONE;
            default: next = IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state  <= IDLE;
            delay  <= 4'd0;
            subcnt <= 10'd0;
        end else begin
            state <= next;
            // shift the 4 delay bits MSB-first
            case (state)
                SH0: delay <= {delay[2:0], data};
                SH1: delay <= {delay[2:0], data};
                SH2: delay <= {delay[2:0], data};
                SH3: begin delay <= {delay[2:0], data}; subcnt <= 10'd0; end
                CNT: begin
                    if (sub_last) begin
                        subcnt <= 10'd0;
                        if (!delay_last) delay <= delay - 4'd1;
                    end else begin
                        subcnt <= subcnt + 10'd1;
                    end
                end
                default: ;
            endcase
        end
    end

    assign count    = delay;
    assign counting = (state == CNT);
    assign done     = (state == DONE);

endmodule
