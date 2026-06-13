module TopModule (
    input  clk,
    input  reset,
    input  in,
    output done
);

    localparam IDLE  = 3'd0,
               DATA  = 3'd1,
               STOP  = 3'd2,
               DONE  = 3'd3,
               WAITS = 3'd4;   // error: wait for stop (line==1)

    reg [2:0] state, next;
    reg [3:0] cnt, cnt_next;

    always @(*) begin
        next = state;
        cnt_next = cnt;
        case (state)
            IDLE: begin
                if (in == 1'b0) begin    // start bit
                    next = DATA;
                    cnt_next = 4'd0;
                end
            end
            DATA: begin
                if (cnt == 4'd7) begin
                    next = STOP;
                end else begin
                    cnt_next = cnt + 4'd1;
                end
            end
            STOP: begin
                if (in == 1'b1)          // valid stop bit
                    next = DONE;
                else
                    next = WAITS;        // missing stop -> wait
            end
            DONE: begin
                // done asserted this cycle; sample next bit as possible start
                if (in == 1'b0) begin
                    next = DATA;
                    cnt_next = 4'd0;
                end else
                    next = IDLE;
            end
            WAITS: begin
                if (in == 1'b1)
                    next = IDLE;
            end
            default: next = IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            cnt   <= 4'd0;
        end else begin
            state <= next;
            cnt   <= cnt_next;
        end
    end

    assign done = (state == DONE);

endmodule
