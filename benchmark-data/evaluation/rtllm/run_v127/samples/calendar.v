// calendar: perpetual clock. Secs/Mins loop 0..59, Hours loops 0..23.
// Async active-high RST, posedge CLK. Three independent always blocks per spec.
module calendar (
    input  wire       CLK,
    input  wire       RST,
    output reg [5:0]  Hours,
    output reg [5:0]  Mins,
    output reg [5:0]  Secs
);

    // Seconds: 0..59
    always @(posedge CLK or posedge RST) begin
        if (RST)
            Secs <= 6'd0;
        else if (Secs == 6'd59)
            Secs <= 6'd0;
        else
            Secs <= Secs + 6'd1;
    end

    // Minutes: increment when Secs==59, wrap at 59
    always @(posedge CLK or posedge RST) begin
        if (RST)
            Mins <= 6'd0;
        else if (Mins == 6'd59 && Secs == 6'd59)
            Mins <= 6'd0;
        else if (Secs == 6'd59)
            Mins <= Mins + 6'd1;
        else
            Mins <= Mins;
    end

    // Hours: increment when Mins==59 && Secs==59, wrap at 23
    always @(posedge CLK or posedge RST) begin
        if (RST)
            Hours <= 6'd0;
        else if (Hours == 6'd23 && Mins == 6'd59 && Secs == 6'd59)
            Hours <= 6'd0;
        else if (Mins == 6'd59 && Secs == 6'd59)
            Hours <= Hours + 6'd1;
        else
            Hours <= Hours;
    end

endmodule
