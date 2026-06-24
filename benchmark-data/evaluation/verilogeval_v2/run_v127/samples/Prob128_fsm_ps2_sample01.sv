module TopModule (
    input        clk,
    input        reset,
    input  [7:0] in,
    output       done
);

    localparam [1:0] BYTE1 = 2'd0,  // hunting for a byte with in[3]=1
                     BYTE2 = 2'd1,
                     BYTE3 = 2'd2,
                     DONE  = 2'd3;  // cycle immediately after byte 3
    reg [1:0] state;

    // done asserted in the cycle the FSM is in DONE (combinational Moore decode).
    assign done = (state == DONE);

    always @(posedge clk) begin
        if (reset)
            state <= BYTE1;
        else begin
            case (state)
                BYTE1: state <= in[3] ? BYTE2 : BYTE1;
                BYTE2: state <= BYTE3;
                BYTE3: state <= DONE;
                // DONE coincides with the next byte-1 slot: re-evaluate in[3].
                DONE:  state <= in[3] ? BYTE2 : BYTE1;
                default: state <= BYTE1;
            endcase
        end
    end

endmodule
