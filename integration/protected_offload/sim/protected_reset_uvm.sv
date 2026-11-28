`timescale 1ns/1ps

interface protected_reset_if(input logic clk);
  logic rst_n = 0;
  bit offload_reset_req;
  bit configured, injected, verified;
  int stage, read_delay, write_delay, write_response_delay;
  logic window_ready;
endinterface

package protected_reset_uvm_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"

  class reset_timing;
    rand int hold_cycles;
    rand int reset_cycles;
    rand int stall_cycles;
    constraint timing {
      hold_cycles inside {[0:5]};
      reset_cycles inside {[2:5]};
      stall_cycles inside {[12:18]};
    }
  endclass

  class protected_reset_sequence extends uvm_sequence #(uvm_sequence_item);
    `uvm_object_utils(protected_reset_sequence)
    virtual protected_reset_if bus;

    function new(string name = "protected_reset_sequence");
      super.new(name);
    endfunction

    task body();
      reset_timing timing = new;
      int selected_stage, random_timing;
      if (!$value$plusargs("RESET_STAGE=%d", selected_stage) ||
          selected_stage < 0 || selected_stage > 6)
        `uvm_fatal("RESET_STAGE", "Expected RESET_STAGE in 0..6")
      random_timing = $test$plusargs("RANDOM_TIMING");
      if (random_timing) begin
        if (!timing.randomize())
          `uvm_fatal("TIMING", "Could not randomize recovery timing")
      end else begin
        timing.hold_cycles = 0;
        timing.reset_cycles = 3;
        timing.stall_cycles = 12;
      end
      bus.stage = selected_stage;
      bus.read_delay = selected_stage inside {0, 4, 6} ? timing.stall_cycles : 0;
      bus.write_delay = selected_stage == 1 ? timing.stall_cycles : 0;
      bus.write_response_delay = selected_stage inside {3, 5} ? timing.stall_cycles : 0;
      bus.configured = 1;
      repeat (5) @(negedge bus.clk);
      bus.rst_n = 1;
      wait (bus.window_ready);
      repeat (timing.hold_cycles + 1) @(negedge bus.clk);
      if (!bus.window_ready)
        `uvm_fatal("WINDOW", "Reset window ended before injection")
      $display("RESET_TIMING|stage=%0d|hold=%0d|reset=%0d|stall=%0d",
               selected_stage, timing.hold_cycles, timing.reset_cycles, timing.stall_cycles);
      bus.injected = 1;
      if (selected_stage >= 4) begin
        bus.offload_reset_req = 1;
        @(negedge bus.clk);
        bus.offload_reset_req = 0;
      end else begin
        bus.rst_n = 0;
        repeat (timing.reset_cycles) @(negedge bus.clk);
        bus.rst_n = 1;
      end
      wait (bus.verified);
    endtask
  endclass

  class protected_reset_test extends uvm_test;
    `uvm_component_utils(protected_reset_test)
    virtual protected_reset_if bus;

    function new(string name, uvm_component parent);
      super.new(name, parent);
    endfunction

    task run_phase(uvm_phase phase);
      protected_reset_sequence sequence_handle = protected_reset_sequence::type_id::create("reset");
      if (!uvm_config_db#(virtual protected_reset_if)::get(this, "", "bus", bus))
        `uvm_fatal("RESET_IF", "Reset control interface is missing")
      phase.raise_objection(this);
      sequence_handle.bus = bus;
      sequence_handle.start(null);
      phase.drop_objection(this);
    endtask
  endclass
endpackage
