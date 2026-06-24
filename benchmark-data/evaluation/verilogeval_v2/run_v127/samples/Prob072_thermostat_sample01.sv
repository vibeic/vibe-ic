module TopModule (
    input  mode,
    input  too_cold,
    input  too_hot,
    input  fan_on,
    output heater,
    output aircon,
    output fan
);

    // Heating mode (mode=1): heater on when too_cold, aircon never.
    // Cooling mode (mode=0): aircon on when too_hot, heater never.
    assign heater = mode & too_cold;
    assign aircon = ~mode & too_hot;
    // Fan runs when heater or aircon is on, or when the user requests it.
    assign fan = heater | aircon | fan_on;

endmodule
