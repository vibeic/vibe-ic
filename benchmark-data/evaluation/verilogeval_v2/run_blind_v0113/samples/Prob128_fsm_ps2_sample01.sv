module TopModule (
    input        clk,
    input        reset,
    input  [7:0] in,
    output       done
);
    localparam S1   = 2'd0;  // searching for byte 1 (in[3]==1)
    localparam S2   = 2'd1;  // received byte 1, awaiting byte 2
    localparam S3   = 2'd2;  // received byte 2, awaiting byte 3
    localparam DONE = 2'd3;  // signal done

    reg [1:0] state;

    always @(posedge clk) begin
        if (reset)
            state <= S1;
        else begin
            case (state)
                S1:   state <= in[3] ? S2 : S1;
                S2:   state <= S3;
                S3:   state <= DONE;
                DONE: state <= in[3] ? S2 : S1;
                default: state <= S1;
            endcase
        end
    end

    // Moore output: function of state only
    assign done = (state == DONE);
endmodule
