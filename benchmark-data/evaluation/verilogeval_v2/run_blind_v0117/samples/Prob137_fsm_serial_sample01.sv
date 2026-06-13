module TopModule (
    input  clk,
    input  reset,
    input  in,
    output done
);
    // IDLE   : line idle / waiting for a start bit (in==0).
    // D1..D8 : the 8 data-bit cycles (values don't matter for delimiting).
    // STOP   : the stop-bit cycle; if in==1 -> good byte, else -> WAIT.
    // DONE   : one-cycle done pulse; immediately ready to detect the next start bit.
    // WAIT   : stop bit was wrong; wait until a 1 (stop/idle) is seen, then resync.
    localparam IDLE=4'd0, D1=4'd1, D2=4'd2, D3=4'd3, D4=4'd4,
               D5=4'd5, D6=4'd6, D7=4'd7, D8=4'd8,
               STOP=4'd9, DONE=4'd10, WAIT=4'd11;

    reg [3:0] state, nstate;

    always @(*) begin
        case (state)
            IDLE: nstate = in ? IDLE : D1;     // start bit is 0
            D1:   nstate = D2;
            D2:   nstate = D3;
            D3:   nstate = D4;
            D4:   nstate = D5;
            D5:   nstate = D6;
            D6:   nstate = D7;
            D7:   nstate = D8;
            D8:   nstate = STOP;
            STOP: nstate = in ? DONE : WAIT;   // stop bit must be 1
            DONE: nstate = in ? IDLE : D1;     // ready for next byte's start bit
            WAIT: nstate = in ? IDLE : WAIT;   // wait for a 1 before resyncing
            default: nstate = IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= IDLE;
        else
            state <= nstate;
    end

    // Moore output: done high only in DONE state.
    assign done = (state == DONE);
endmodule
