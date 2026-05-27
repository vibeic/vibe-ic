module TopModule (
    input        clk,
    input        reset,
    input  [7:0] in,
    output       done
);
    localparam BYTE1 = 2'd0;  // searching for first byte (in[3]==1)
    localparam BYTE2 = 2'd1;  // got byte1, waiting byte2
    localparam BYTE3 = 2'd2;  // got byte2, waiting byte3
    localparam DONE  = 2'd3;  // signal done (cycle after byte3)

    reg [1:0] state;

    always @(posedge clk) begin
        if (reset)
            state <= BYTE1;
        else begin
            case (state)
                BYTE1: state <= in[3] ? BYTE2 : BYTE1;
                BYTE2: state <= BYTE3;
                BYTE3: state <= DONE;
                DONE:  state <= in[3] ? BYTE2 : BYTE1;  // current byte is byte1 of next msg if in[3]=1
                default: state <= BYTE1;
            endcase
        end
    end

    // Moore output
    assign done = (state == DONE);
endmodule
