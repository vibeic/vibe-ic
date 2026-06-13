module TopModule (
    input  [15:0] scancode,
    output        left,
    output        down,
    output        right,
    output        up
);
    reg l, dn, r, u;
    always @(*) begin
        l  = 1'b0;
        dn = 1'b0;
        r  = 1'b0;
        u  = 1'b0;
        case (scancode)
            16'he06b: l  = 1'b1;
            16'he072: dn = 1'b1;
            16'he074: r  = 1'b1;
            16'he075: u  = 1'b1;
            default: ;
        endcase
    end
    assign left  = l;
    assign down  = dn;
    assign right = r;
    assign up    = u;
endmodule
