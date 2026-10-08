# 版本与验证历史

本页区分版本、验证范围和原始证据。当前操作入口是[上板指南](../board_bringup.md)，当前推荐发布是[八路 CLK / 1.8 V 完整系统](clk8_18v_update.md)。下列旧版结果不替代当前实板验收。

## 完整系统版本

| 日期 | 构建 / 阶段 | 结果与适用范围 |
|---|---|---|
| 2026-09-20 | `MEMS_Array_uart_clk8_18v_spread3_long` | **当前推荐**；常规完整构建与最终发布 PASS；本版未下载、实际电压未确认 |
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
| `_spread3_long` | 种子 2、扩散 3、Center、180 分钟时限；常规完整构建 PASS，选为当前推荐 |

检查点工具为 `fpga/scripts/finalize_route_checkpoint.py`。候选发布保留原优化日志与源清单，并重新生成正式时序和双角网表；源文件、数据库、路由完成证据及全部发布检查仍需一致。推荐 `_spread3_long` 没有使用该恢复流程。构建产物和失败日志保留在原目录，未删除或改写为成功。
