module TopModule (
    input  clk,
    input  ar,
    input  d,
    output reg q
);

    // Asynchronous reset 'ar' clears q to 0, positive edge triggered.
    always @(posedge clk or posedge ar) begin
        if (ar)
            q <= 1'b0;
        else
            q <= d;
    end

endmodule
