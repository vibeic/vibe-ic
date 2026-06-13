module TopModule (
    input  clk,
    input  [7:0] in,
    input  reset,
    output done
);

    // S1: hunt for byte1 (in[3]==1). S2/S3: collect bytes 2 and 3.
    // DONE: Moore output cycle after byte3; it also acts as a byte1 boundary.
    localparam S1 = 2'd0, S2 = 2'd1, S3 = 2'd2, DONE = 2'd3;
    reg [1:0] state, nstate;

    always @(*) begin
        case (state)
            S1:   nstate = in[3] ? S2 : S1;
            S2:   nstate = S3;
            S3:   nstate = DONE;
            DONE: nstate = in[3] ? S2 : S1;
            default: nstate = S1;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= S1;
        else
            state <= nstate;
    end

    assign done = (state == DONE);

endmodule
