module TopModule (
  input clk,
  input reset,
  output shift_ena
);
    // count counts the cycles since reset: shift_ena high for the first 4 cycles.
    reg [2:0] count;
    always @(posedge clk) begin
        if (reset)
            count <= 3'd0;
        else if (count < 3'd4)
            count <= count + 3'd1;
    end
    assign shift_ena = (count < 3'd4);
endmodule
