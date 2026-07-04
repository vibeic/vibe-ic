module glitch_free_mux (
    input  wire clk1,
    input  wire clk2,
    input  wire sel,
    input  wire rst_n,   // asynchronous active-low reset
    output wire clkout
);

    // Enable flags for each clock domain. The spec pins the gating to the
    // POSITIVE edge of each clock (not the textbook negedge form): clk1 is
    // disabled on the first posedge of clk1 after sel changes, then clk2 is
    // enabled on the first posedge of clk2 once clk1 is disabled (and vice
    // versa). Each enable is held off while the OTHER clock is still enabled so
    // the two are never enabled simultaneously.
    reg clk1_en;
    reg clk2_en;

    // clk1 domain: enable clk1 only when sel selects it and clk2 is disabled.
    always @(posedge clk1 or negedge rst_n) begin
        if (!rst_n)
            clk1_en <= 1'b0;
        else
            clk1_en <= ~sel & ~clk2_en;
    end

    // clk2 domain: enable clk2 only when sel selects it and clk1 is disabled.
    always @(posedge clk2 or negedge rst_n) begin
        if (!rst_n)
            clk2_en <= 1'b0;
        else
            clk2_en <= sel & ~clk1_en;
    end

    // Gated, glitch-free output clock. On reset clkout is driven low.
    assign clkout = (clk1 & clk1_en) | (clk2 & clk2_en);

endmodule
