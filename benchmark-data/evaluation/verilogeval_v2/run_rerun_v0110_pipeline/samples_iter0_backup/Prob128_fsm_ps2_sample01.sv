module TopModule (
    input  clk,
    input  reset,
    input  [7:0] in,
    output done
);
    localparam SEARCH = 2'd0, BYTE2 = 2'd1, BYTE3 = 2'd2, DONE = 2'd3;
    reg [1:0] state;

    always @(posedge clk) begin
        if (reset)
            state <= SEARCH;
        else begin
            case (state)
                SEARCH: state <= in[3] ? BYTE2 : SEARCH;
                BYTE2:  state <= BYTE3;
                BYTE3:  state <= DONE;
                DONE:   state <= in[3] ? BYTE2 : SEARCH;
                default: state <= SEARCH;
            endcase
        end
    end

    assign done = (state == DONE);
endmodule
