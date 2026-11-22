import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer


@cocotb.test(timeout_time=20, timeout_unit="us")
async def split_write_channels_and_stalled_responses(dut):
    for name in ("rst_n", "s_axil_awvalid", "s_axil_wvalid", "s_axil_bready",
                 "s_axil_arvalid", "s_axil_rready", "s_axis_tvalid", "m_axis_tready"):
        getattr(dut, name).value = 0
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    async def tick():
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)

    async def send(valid, ready):
        valid.value = 1
        await Timer(1, unit="ns")
        while not int(ready.value):
            await tick()
        await tick()
        valid.value = 0

    async def write(address, value, address_first):
        dut.s_axil_awaddr.value = address
        dut.s_axil_wdata.value = value
        dut.s_axil_wstrb.value = 15
        aw = (dut.s_axil_awvalid, dut.s_axil_awready)
        w = (dut.s_axil_wvalid, dut.s_axil_wready)
        first, second = (aw, w) if address_first else (w, aw)
        await send(*first)
        for _ in range(4):
            await tick()
            assert not int(dut.s_axil_bvalid.value)
        await send(*second)
        while not int(dut.s_axil_bvalid.value):
            await tick()
        for _ in range(4):
            assert int(dut.s_axil_bvalid.value) and int(dut.s_axil_bresp.value) == 0
            await tick()
        dut.s_axil_bready.value = 1
        await tick()
        dut.s_axil_bready.value = 0

    await tick()
    await tick()
    dut.rst_n.value = 1
    await write(0, 1, True)    # Output zero bias select
    await write(4, 23, False)
    await write(8, (0x53 << 8) | (4 << 1), True)
    dut.s_axis_tdata.value = 0x817f0201
    dut.s_axis_tuser.value = 0x53
    await send(dut.s_axis_tvalid, dut.s_axis_tready)
    while not int(dut.m_axis_tvalid.value):
        await tick()
    for _ in range(6):
        assert int(dut.m_axis_tvalid.value)
        assert int(dut.m_axis_tdata.value) == 23  # Zero weights, bias in lane zero
        assert int(dut.m_axis_tuser.value) == 0x53
        await tick()
    dut.m_axis_tready.value = 1
    await tick()
    assert not int(dut.m_axis_tvalid.value)
