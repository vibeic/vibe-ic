module TopModule (
    input  clk,
    input  in,
    input  reset,
    output done
);

    // IDLE : line idle (1); start bit is in==0.
    // DATA : receiving 8 data bits (count 0..7).
    // STOP : check stop bit; 1 -> DONE, 0 -> WAITERR.
    // DONE : Moore output cycle after a valid stop; in may start a new byte.
    // WAITERR : bad stop; wait until line returns to 1 before resyncing.
    localparam IDLE = 3'd0, DATA = 3'd1, STOP = 3'd2, DONE = 3'd3, WAITERR = 3'd4;

    reg [2:0] state, nstate;
    reg [2:0] cnt, ncnt;

    always @(*) begin
        nstate = state;
        ncnt   = cnt;
        case (state)
            IDLE: begin
                ncnt = 3'd0;
                nstate = (in == 1'b0) ? DATA : IDLE;
            end
            DATA: begin
                if (cnt == 3'd7) begin
                    nstate = STOP;
                    ncnt   = 3'd0;
                end else begin
                    nstate = DATA;
                    ncnt   = cnt + 3'd1;
                end
            end
            STOP: begin
                ncnt   = 3'd0;
                nstate = (in == 1'b1) ? DONE : WAITERR;
            end
            DONE: begin
                ncnt   = 3'd0;
                nstate = (in == 1'b0) ? DATA : IDLE;
            end
            WAITERR: begin
                ncnt   = 3'd0;
                nstate = (in == 1'b1) ? IDLE : WAITERR;
            end
            default: begin
                nstate = IDLE;
                ncnt   = 3'd0;
            end
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            cnt   <= 3'd0;
        end else begin
            state <= nstate;
            cnt   <= ncnt;
        end
    end

    assign done = (state == DONE);

endmodule
