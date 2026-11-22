create_clock -name core_clock -period 10 [get_ports clk]
set_input_delay 1 -clock core_clock [all_inputs -no_clocks]
set_output_delay 1 -clock core_clock [all_outputs]
