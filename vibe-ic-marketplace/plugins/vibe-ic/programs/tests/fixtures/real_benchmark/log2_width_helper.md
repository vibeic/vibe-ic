# Configurable pulse counter: elaboration width

The ratio input width is determined by bits_for(LIMIT), with LIMIT a positive
elaboration parameter. Each accepted input pulse advances the counter. This
document describes a dimension helper, not a configurable arithmetic rounding
mode. The following is a neutralized real completion-document shape.

```systemverilog
module pulse_counter #(parameter LIMIT = 10)(
    input wire clk,
    input wire [bits_for(LIMIT)-1:0] ratio
);
    // Function to calculate the ceiling of log2
    function integer bits_for;
        input integer value;
        integer i;
        begin
            bits_for = 1;
            for (i = 0; (2 ** i) < value; i = i + 1)
                bits_for = i + 1;
        end
    endfunction
endmodule
```
