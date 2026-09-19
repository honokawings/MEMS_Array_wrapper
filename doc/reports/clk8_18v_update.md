# 八路同源时钟与 1.8 V 接口发布记录

推荐构建：`fpga/build/MEMS_Array_uart_clk8_18v_spread3_long/`。2026-09-20 01:44 生成位流，01:45 最终发布检查 **PASS**，`release_authorized=true`。本版已完成软件与器件实现验证，尚未下载到开发板，实际 L6/L7 电压尚未确认。

- [下载用 .sbit](../../fpga/build/MEMS_Array_uart_clk8_18v_spread3_long/generate_bitstream/mems_array_pg2l200h.sbit)
- [原始 .bin](../../fpga/build/MEMS_Array_uart_clk8_18v_spread3_long/generate_bitstream/mems_array_pg2l200h.bin)
- [最终发布记录](../../fpga/build/MEMS_Array_uart_clk8_18v_spread3_long/release.json)
- [双角时序报告](../../fpga/build/MEMS_Array_uart_clk8_18v_spread3_long/report_timing/mems_array_pg2l200h.rtr)

`.sbit`：9,188,552 字节，SHA-256：
`0db0d49cef5a2fb361f9b367b1f9c2fd124a638d3bf6c8a2192e32f76b686d34`

`.bin`：9,186,916 字节，SHA-256：
`259964ca24c45958549d4132876e824cccdc6f2c17a6a70e7b05c8c805ff98f5`

## 新的接口分配

| 接口 | 信号 | Bank | 电平 |
|---|---|---|---|
| J10 | CLK0～7 | L6 | 1.8 V |
| J25 | DATA32～63 | L6 | 1.8 V |
| J26 | DATA0～31 | L7 | 1.8 V |

72 个麦克风信号端口全部位于 L6/L7，完整顶层共 99 个端口，无重复封装引脚或缺失端口。Bank 已与 PDS 原厂封装文件核对；麦克风接口不再占用固定 3.3 V 的 L5。

| 信号 | FPGA 引脚 | Bank | 电平 | 驱动 |
|---|---|---|---|---|
| CLK0 | AC26 | L6 | 1.8 V / LVCMOS18 | 16 mA / FAST |
| CLK1 | AB26 | L6 | 1.8 V / LVCMOS18 | 16 mA / FAST |
| CLK2 | U25 | L6 | 1.8 V / LVCMOS18 | 16 mA / FAST |
| CLK3 | AA24 | L6 | 1.8 V / LVCMOS18 | 16 mA / FAST |
| CLK4 | AB25 | L6 | 1.8 V / LVCMOS18 | 16 mA / FAST |
| CLK5 | U26 | L6 | 1.8 V / LVCMOS18 | 16 mA / FAST |
| CLK6 | Y25 | L6 | 1.8 V / LVCMOS18 | 16 mA / FAST |
| CLK7 | AA25 | L6 | 1.8 V / LVCMOS18 | 16 mA / FAST |

## RTL、约束和功能

`mic_clk[7:0]` 由同一个 `pdm_clock` 复制，频率 3.072 MHz，共用相位和复位。慢角、快角实际布线网表均确认八个时钟输出来自同一个物理分频寄存器。DATAk 仍对应逻辑通道 2k、2k+1；UART、PHY/MDIO、ARP、UDP、校准和内部 PDM 自测功能保留。

所有 DATA 与 CLK 为 LVCMOS18。CLK 驱动由 8 mA 提高至 16 mA，摆率 FAST；器件映射和生成的物理约束已逐端口核查电压、驱动、摆率。八路 CLK 均纳入 4 ns 输出路径上限，PDM 输入保持 5 ns 内部路径上限。

完整功能回归 **12/12 PASS**，重新生成参考模型且包含厂商原语；电气配置和发布检查器测试 **146/146 PASS**。板级仿真检查八路时钟的一致性、周期、复位和模式切换。128 个 FIR 乘法器、48 个历史 RAM 的功能身份及 176 个宏位置核对通过。

## 实现结果

| 音频域 122.88 MHz | 建立时间余量 | 保持时间余量 |
|---|---:|---:|
| 慢角 | +0.094 ns | +0.062 ns |
| 快角 | +2.344 ns | +0.020 ns |

全系统建立、保持、恢复、移除和最小脉宽检查无违例。PDM 保守采样预算剩余：慢角 8.170 ns、快角 10.438 ns。预算包含麦克风 100 ns 数据有效延迟、20 ns 外部往返传播、4 ns 时钟输出上限和音频时钟不确定度。RGMII 最大物理发送偏差 0.279 ns，低于 0.300 ns 上限。

器件映射资源：LUT 33,790（22%）、FF 41,284（13%）、APM 130（18%）、DRM 54.5（14%）、IO 99。

发布范围为工程上板联调，采用 PDS 2022.2-SP6.4 的原始 Pre-silicon 模型。实际 TXC 占空比/抖动、PCB 偏斜和麦克风带载波形仍需实测，不能将软件发布 PASS 等同于板级或声学验收。此前四路版本的 157,314,048 样本实测记录属于历史版本。

## 下载前的供电条件

MEMS VDD 为 1.8 V。开发板手册第 12、41 页说明：**断电后按板卡丝印将 J24 选择为 VADJ=1.8 V，通过 J20 选择 VADJ 为 L6/L7 供电，接入阵列前实测确认。** 约束不会改变真实 VCCIO，扩展口 A3V3/A5V0 电源针仍为固定电压。

提高驱动电流不等于完成真实负载验收。麦克风引脚处应确认 3.072 MHz 时钟占空比 48%～52%、上升/下降时间不超过 13 ns，并满足外部传播预算。本次未执行 JTAG 下载或新一轮 UART/网络实板测试。

## 构建及诊断记录

推荐版本使用布局种子 2、布局扩散 3、Center 初始布局，单次 PNR 超时 180 分钟。它从 compile 开始完成常规构建、布局布线、双角报告、SDF 导出及生成前/生成后发布检查，所有源文件哈希保持一致。

```powershell
python sim/verify_all.py
python fpga/scripts/build.py --stage gen_bit_stream --build-name MEMS_Array_uart_clk8_18v_spread3_long --place-seed 2 --placement-decongestion 3 --placement-initial-method Center --pnr-timeout-minutes 180
```

最初两次物理实现因收敛较慢而主动停止；第三次扩散 3 的构建触发 45 分钟时限，均未生成位流。日志和失败状态保留，没有标为时序通过。

扩散 5 的独立候选 `MEMS_Array_uart_clk8_18v_spread5` 也生成了通过发布检查的位流：选择已完成且时序合格的第一次路由，保留原优化日志及源构建记录，重新生成正式报告、双角网表后完成发布。其慢角建立余量 +0.050 ns。本次推荐上方通过常规完整流程、慢角建立余量 +0.094 ns 的扩散 3 版本。

为避免重复等待已合格路由的追加优化，增加 `fpga/scripts/finalize_route_checkpoint.py`。检查点恢复要求完整编译/映射/布局证据、真实路由完成日志、相同源文件和数据库哈希，并保留所有功能、电气、双角时序、接口与位流检查。146 项测试包含未完成路由、改写日志/数据库、错误报告数据库、恢复记录损坏等拒绝用例。首次恢复中遇到独立时序报告参数解析问题，已修正并重做发布检查，原失败记录保留。
