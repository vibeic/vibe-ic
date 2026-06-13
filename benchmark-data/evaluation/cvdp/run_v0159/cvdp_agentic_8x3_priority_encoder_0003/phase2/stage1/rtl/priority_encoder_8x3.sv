// priority_encoder_8x3
// 8-to-3 priority encoder. MSB-to-LSB priority: the most-significant set bit
// of `in` determines `out` (in[7] highest priority ... in[0] lowest).
// Augmented with an SVA immediate assertion validating that `out` equals the
// index of the highest set bit (the prompt's "Out signal Priority Validation").
module priority_encoder_8x3 (
    input       [7:0] in ,   // 8 input lines
    output reg  [2:0] out    // 3 output lines (index of highest set bit)
);

    // reference: index of the most-significant set bit
    function automatic [2:0] highest_set_index(input [7:0] v);
        integer k;
        begin
            highest_set_index = 3'b000;
            for (k = 0; k < 8; k = k + 1)
                if (v[k]) highest_set_index = k[2:0]; // ascending scan ends on MSB set
        end
    endfunction

    always @(*) begin
        if (in[7])      out = 3'b111;
        else if (in[6]) out = 3'b110;
        else if (in[5]) out = 3'b101;
        else if (in[4]) out = 3'b100;
        else if (in[3]) out = 3'b011;
        else if (in[2]) out = 3'b010;
        else if (in[1]) out = 3'b001;
        else if (in[0]) out = 3'b000;
        else            out = 3'b000; // no active input

        // Out-signal priority validation (immediate assertion).
        // When at least one input is active, `out` must equal the index of the
        // highest set bit. When `in` is zero, `out` defaults to 0.
        // Simulation-only: guarded from synthesis (assertions are not synthesizable).
        // synthesis translate_off
        if (in != 8'b0)
            assert (out == highest_set_index(in))
                else $error("priority_encoder_8x3: in=0x%h expected out=0x%h got out=0x%h",
                            in, highest_set_index(in), out);
        else
            assert (out == 3'b000)
                else $error("priority_encoder_8x3: in=0 expected out=0 got out=0x%h", out);
        // synthesis translate_on
    end

endmodule
