module TopModule (
  input clk,
  input reset,
  input data,
  output start_shifting
);
    localparam S0 = 3'd0, // idle
               S1 = 3'd1, // "1"
               S2 = 3'd2, // "11"
               S3 = 3'd3, // "110"
               DONE = 3'd4; // "1101" found
    reg [2:0] state, next;

    always @(*) begin
        case (state)
            S0:   next = data ? S1 : S0;
            S1:   next = data ? S2 : S0;
            S2:   next = data ? S2 : S3;   // overlap: extra 1 stays at "11"
            S3:   next = data ? DONE : S0;
            DONE: next = DONE;
            default: next = S0;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= S0;
        else
            state <= next;
    end

    assign start_shifting = (state == DONE);
endmodule
