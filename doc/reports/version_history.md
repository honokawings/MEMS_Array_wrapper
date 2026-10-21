# 版本与验证历史

本页区分版本、验证范围与原始证据。当前[FIR8](i2s_fir8_auto_20261011.md)已完成唯一一轮路由、严格时序、发布与JTAG SRAM下载，本次A–E数字验收通过，联合结果为PASS_WITH_KNOWN_ISSUES；F真实采样连续，DATA1/ch2、3及物理未测边界保留。前一[seed3基线](i2s_parity_dc_roundsat_seed3_20261011.md)A–F数字结果保留；DATA1/ch2、3、电气、DAC模拟和声学验收仍未完成。

## 完整系统版本

| 日期 | 构建 / 阶段 | 结果与适用范围 |
|---|---|---|
| 2026-10-11 | `MEMS_Array_i2s_parity_dc_roundsat_seed3_20261009` | **前一已下载基线**；18/18、104项输入/22向量，首轮2h23m2s、严格发布和14:55:41 JTAG PASS；A–E数字PASS、F已知问题保留，见[报告](i2s_parity_dc_roundsat_seed3_20261011.md) |
| 2026-10-11 | `MEMS_Array_i2s_fir8_auto_20261011` | **当前已下载版**；18层、实际APM68/FF47,953/LUT28,512；普通route入口Flow-0013[原始归档](../../fpga/build/MEMS_Array_i2s_fir8_auto_20261011/resume_before_route)保留，从相同PLC恢复唯一1轮，64819/64819成功、PNR1850秒；严格发布16:18:08、JTAG16:19:06 PASS，retry1缺包/retry2启动尾片/sync缺包原FAIL保留；本次spool A–E全PASS，联合PASS_WITH_KNOWN_ISSUES，C+D 504,694,272样本无错无缺包；F143,589帧连续、ch2/3故障保留，见[报告](i2s_fir8_auto_20261011.md) |
| 2026-10-09 | `MEMS_Array_i2s_parity_dc_roundsat_20261009`（seed2） | 18/18功能与diag map PASS；首轮iter62剩2919未布/8066过用，原生timeout120自然exit1，[实际FAIL](../../log/i2s_parity/dc_roundsat_seed2_route_timeout_actual_20261009.json)；无RTR/DB/位流，最终时序UNKNOWN |
| 2026-10-09 | `MEMS_Array_i2s_parity_dc_startup_20261009` | 启动逐通道直流估计与冻结；[初版18/18功能回归](../../log/i2s_parity/full_regression_dc_startup_20261009.json)PASS，但正式两轮 setup −0.200 / −0.369 ns，完整构建[实际FAIL](../../log/i2s_parity/dc_startup_full_build_actual_fail_20261009.json)，pre-bit拒绝生成位流，无发布/JTAG/A–F；算法v1.2、M128线协议仍1 |
| 2026-10-09 | `MEMS_Array_i2s_parity_fir_fixed_result_20261009` | 旧B已发布基线；18/18、双角时序、严格发布、JTAG与A–E数字通过，506,273,664 BIST样本相符；DATA1/ch2、3负满量程，原始结果保留 |
| 2026-10-09 | `MEMS_Array_i2s_parity_fir_local_lane_20261009` | 局部写组版本功能/技术/布局通过；首轮未布通后主动取消，最终时序未知，无位流或下载 |
| 2026-10-09 | `MEMS_Array_i2s_parity_local_lane_20261009` | 奇偶局部选择版本首轮未布通后主动取消，最终时序未知，无位流或下载 |
| 2026-10-09 | `MEMS_Array_i2s_parity_timingfix4_20261009` 及参数对照 | 原版和 D5 自然超时，Quad5 主动取消，三者最终时序未知；Quad10 线程参数不合法，未完整布线；全部无位流 |
| 2026-10-09 | UART 通道修复候选 | 功能通过；两轮正式 setup 失败，无新位流或下载 |
| 2026-10-09 | `MEMS_Array_i2s_parity_20261009` | 第一版 I2S/奇偶补偿，发布/JTAG/网络数字测试通过；UART 通道被编译为常量 0，完整实板验收失败 |
| 2026-09-20 | `MEMS_Array_uart_clk8_18v_spread3_long` | 当时推荐；常规完整构建与最终发布 PASS；本版未下载、实际电压未确认，不含新增 I2S/奇偶补偿 |
| 2026-09-20 | `MEMS_Array_uart_clk8_18v_spread5` | 八路/1.8 V 候选；选择已完成的首轮路由检查点后重新导出、检查并发布 PASS；不是本页推荐下载版本 |
| 2026-09-19 下午 | `MEMS_Array_uart_arp_ready_routed` | 旧四路、3.3 V 麦克风接口；修正等待 ARP 溢出，实板 PHY/MDIO、ARP、UDP 及 157,314,048 个 BIST 样本通过；真实输入全通道正饱和 |
| 2026-09-19 上午 | `MEMS_Array_uart_chain8` | UART 集成、PLL 修正；工程发布 PASS；实板发现等待 ARP 时启动/切换丢帧，整体验收未通过 |
| 2026-09-17 | `MEMS_Array_selftest` | 引入内部 PDM 自测与按键/LED；当时实现检查通过，后续发现以太网 PLL 参数问题；不用于当前下载 |
| 2026-09-16 | `MEMS_Array` | 最初完整网络系统；不含按键自测；保留当时发布证据 |
| 2026-09-15 | 前处理 v1.0 | 算法、模型、可移植 RTL 与前处理验证；最初不含以太网 |

旧四路 3.3 V 位流不适用于当前 1.8 V 麦克风直接连接。历史报告中“本次”“当前”和“下一步”均指该报告日期，不是本项目最新状态。

## 历史报告与实板记录

| 记录 | 内容 |
|---|---|
| [启动DC seed3交付与实测](i2s_parity_dc_roundsat_seed3_20261011.md) | 前一16-lane位流、严格时序、A–F数字验收及DC/物理边界 |
| [旧B固定结果分组交付与实测](i2s_parity_fir_fixed_result_20261009.md) | 历史位流、JTAG、全通道UART/I2S、网络BIST及DATA1问题 |
| [I2S/奇偶补偿第一版](i2s_parity_20261009.md) | 当时网络通过、UART 选通失败，保留原始证据 |
| [UART 修复时序失败](i2s_parity_uartfix_timing_20261009.md) | 原两轮负 setup，不能选负裕量检查点发布 |
| [timingfix4 与参数对照](i2s_parity_timingfix4_20261009.md) | 自然超时、非法参数及主动取消的不同历史终态 |
| [ARP 就绪修正](arp_ready_fix.md) | 2026-09-19 修正、发布与两轮内部自测实测 |
| [修正前 UART 实板测试](uart_board_test_20260919.md) | PHY/ARP/UDP 可通，但发现启动/切换缺帧 |
| [PLL 与 UART 集成](uart_system_implementation.md) | `chain8` 实现及后续 ARP 修正说明 |
| [UART 布线诊断](uart_routing_diagnosis.md) | 旧布局收敛与拥塞分析，不代表当前构建仍在运行 |
| [按键自测实现](selftest_implementation.md) | 2026-09-17 自测版实现证据 |
| [首次上板诊断](board_debug_20260917.md) | 当时网络/启动问题；后续五键五灯映射已实测对应 |
| [最初 FPGA 实现](fpga_implementation.md) | 2026-09-16 位流发布证据 |
| [独立 UART 时钟诊断](../../fpga/diagnostics/uart_clock/README.md) | `CLK2`，PHY 保持复位，不提供网络收发 |
| [IO 映射诊断](../../fpga/diagnostics/io_map/README.md) · [时钟/复位页表诊断](../../fpga/diagnostics/clock_reset/README.md) | 历史专项工具；现行完整系统使用 UART `SYS3` |

## 八路 / 1.8 V 构建过程

| 构建后缀（前缀 `MEMS_Array_uart_clk8_18v`） | 结果 |
|---|---|
| `_preflight` | 综合预检查通过，核对 176 个宏身份 |
| 无后缀、`_seed2` | 因路由收敛较慢主动停止；未生成位流 |
| `_spread` | 扩散 3、45 分钟时限；PNR 超时，未生成位流 |
| `_spread5` | 扩散 5；首轮路由已完成且时序通过，停止追加优化后经检查点流程发布 |
| `_spread3_long` | 种子 2、扩散 3、Center、180 分钟时限；常规完整构建 PASS，当时选为推荐 |

检查点工具为 `fpga/scripts/finalize_route_checkpoint.py`。候选发布保留原优化日志与源清单，并重新生成正式时序和双角网表；源文件、数据库、路由完成证据及全部发布检查仍需一致。历史 `_spread3_long` 没有使用该恢复流程。2026-10-09 当前版本使用已保存且全部时序通过的首轮结果继续严格发布；中断的第二优化原始 FAIL 仍保留。构建产物和失败日志未删除或改写为成功。
