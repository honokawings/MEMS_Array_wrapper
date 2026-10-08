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

[完整功能回归](system_verification.md) **12/12 PASS**，重新生成参考模型且包含厂商原语；[电气配置和发布检查器测试](../../log/system_uart/clk8_checker_tests.log) **146/146 PASS**。板级仿真检查八路时钟的一致性、周期、复位和模式切换。128 个 FIR 乘法器、48 个历史 RAM 的功能身份及 176 个宏位置核对通过。

## 实现结果

| 音频域 122.88 MHz | 建立时间余量 | 保持时间余量 |
|---|---:|---:|
| 慢角 | +0.094 ns | +0.062 ns |
| 快角 | +2.344 ns | +0.020 ns |

全系统建立、保持、恢复、移除和最小脉宽检查无违例。PDM 保守采样预算剩余：慢角 8.170 ns、快角 10.438 ns。预算包含麦克风 100 ns 数据有效延迟、20 ns 外部往返传播、4 ns 时钟输出上限和音频时钟不确定度。RGMII 最大物理发送偏差 0.279 ns，低于 0.300 ns 上限。

器件映射资源：LUT 33,790（22%）、FF 41,284（13%）、APM 130（18%）、DRM 54.5（14%）、IO 99。

发布范围为工程上板联调，采用 PDS 2022.2-SP6.4 的原始 Pre-silicon 模型。实际 TXC 占空比/抖动、PCB 偏斜和麦克风带载波形仍需实测，不能将软件发布 PASS 等同于板级或声学验收。此前四路版本的 157,314,048 样本实测记录属于[历史版本](version_history.md)。

最终 `qualification` 仍记录：`unconditional_board_qualification=false`、`txc_duty_and_jitter=UNCONFIRMED`。名义 TXC 占空比通过，但按逐沿 ±180 ps 附加假设计算的保守敏感性分析为 FAIL；该假设不能替代厂商抖动统计定义或实测。推荐版本允许的额外边沿对误差上限为 0.271 ns，必须保留这一发布范围边界。

## 下载前的供电条件

MEMS VDD 为 1.8 V。开发板手册第 12、41 页说明：**断电后按板卡丝印将 J24 选择为 VADJ=1.8 V，通过 J20 选择 VADJ 为 L6/L7 供电，接入阵列前实测确认。** 约束不会改变真实 VCCIO，扩展口 A3V3/A5V0 电源针仍为固定电压。

提高驱动电流不等于完成真实负载验收。麦克风引脚处应确认 3.072 MHz 时钟占空比 48%～52%、上升/下降时间不超过 13 ns，并满足外部传播预算。本次未执行 JTAG 下载或新一轮 UART/网络实板测试。

## 构建复现与历史

推荐版本使用种子 2、布局扩散 3、Center 初始布局、PNR 超时 180 分钟，从 compile 开始完成常规完整构建。源码与约束在构建前后保持一致；本版本没有使用路由检查点恢复。

重建命令集中在[上板指南](../board_bringup.md#构建与发布复现)，使用新构建目录避免覆盖发布证据。其他候选、失败尝试及检查点流程见[版本历史](version_history.md)。当前验收入口是[UART 联调](../system_uart_debug.md)与[内部自测](../selftest.md)。
