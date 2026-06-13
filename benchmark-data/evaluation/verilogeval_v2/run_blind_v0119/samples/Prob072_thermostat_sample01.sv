module TopModule(
    input  mode,
    input  too_cold,
    input  too_hot,
    input  fan_on,
    output heater,
    output aircon,
    output fan
);
    assign heater = mode & too_cold;        // heating mode only
    assign aircon = ~mode & too_hot;        // cooling mode only
    assign fan    = heater | aircon | fan_on;
endmodule
