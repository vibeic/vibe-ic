module TopModule (
    input  clk,
    input  reset,
    input  in,
    output done
);

    localparam IDLE = 3'd0,
               DATA = 3'd1,
               STOP = 3'd2,
               DONE = 3'd3,
               WAIT = 3'd4;

    reg [2:0] state, next;
    reg [3:0] cnt, cnt_n;

    always @(*) begin
        next  = state;
        cnt_n = cnt;
        case (state)
            IDLE: begin
                cnt_n = 0;
                if (in == 1'b0) next = DATA;  // start bit
                else            next = IDLE;
            end
            DATA: begin
                if (cnt == 4'd7) begin
                    next  = STOP;
                    cnt_n = 0;
                end else begin
                    cnt_n = cnt + 4'd1;
                    next  = DATA;
                end
            end
            STOP: begin
                if (in == 1'b1) next = DONE;   // valid stop bit
                else            next = WAIT;    // bad stop -> wait for a 1
            end
            DONE: begin
                cnt_n = 0;
                if (in == 1'b0) next = DATA;    // next start bit
                else            next = IDLE;
            end
            WAIT: begin
                if (in == 1'b1) next = IDLE;
                else            next = WAIT;
            end
            default: next = IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            cnt   <= 0;
        end else begin
            state <= next;
            cnt   <= cnt_n;
        end
    end

    assign done = (state == DONE);

endmodule
