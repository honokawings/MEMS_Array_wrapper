# 文档索引

核对日期：2026-10-11。当前已发布并下载版本为 **`MEMS_Array_i2s_fir8_auto_20261011`**，包含启动DC、8-lane FIR、八路同源CLK、1.8V MEMS约束、3.3V I2S和独立UART控制。18层功能、唯一一轮原生路由、严格快/慢角时序与16:19:06 JTAG SRAM下载通过；新版本次A–E数字验收通过，联合结果为PASS_WITH_KNOWN_ISSUES；F真实采样连续，DATA1/ch2、3及物理未测边界保留。实际总APM由132降至68（−48.5%），128通道/48kHz不变，共同延迟增加约13.02µs。板上电压、DATA1/ch2、3、DAC模拟和声学配平仍未验收。

[当前FIR8报告](reports/i2s_fir8_auto_20261011.md)汇总实现、严格发布、下载及本次A–F数字结果，并给出[UDP暂存/离线解析用法](reports/i2s_fir8_auto_20261011.md#本次工程采集方式)；[seed3历史基线](reports/i2s_parity_dc_roundsat_seed3_20261011.md)保留A–F数字实测。旧DC负时序、seed2超时等证据见[版本历史](reports/version_history.md)。真实首帧4192、BIST首帧96、补偿131拍及线协议合同见[算法规格](algorithm_spec.md)和[音频运行方式](audio_monitor.md#当前源码新增的启动直流补偿)。

FIR8实际PNR为1850秒，详细布线1528.25秒，严格时序通过；相比前一seed3分别减少78.4%与81.7%。[FIR8报告](reports/i2s_fir8_auto_20261011.md)汇总真实记录、路由入口接续、下载与捕获诊断，资源减少不能单独解释提速。

第一版 UART 常量 0 缺陷、后续时序失败、旧候选超时或取消均保留在[版本历史](reports/version_history.md)。未完成布线版本的最终时序为 UNKNOWN，不与已测得的时序违例混用；它们的局部通过也不计作本版本实测。

## 操作指南

建议阅读顺序：项目概览 → 上板指南 → UART 联调 → 内部自测 → 真实阵列采集。

| 文档 | 用途 |
|---|---|
| [项目 README](../README.md) | 当前状态、系统规格及唯一完整接线表 |
| [上板与采集](board_bringup.md) | 供电、接线、推荐位流、JTAG 下载及重建方法 |
| [UART 联调](system_uart_debug.md) | COM3 控制、SYS3 协议及 PHY/MDIO → ARP → UDP 验收 |
| [I2S 与奇偶补偿](audio_monitor.md) | PCM5102 接线、任意通道监听、独立串口配置和全部 64 对幅值标定 |
| [内部 PDM 自测](selftest.md) | 无麦克风条件下的 FPGA 自测与上位机逐样本校验 |
| [PCM 采集](host_capture.md) | 接收工具、文件格式、连续性与丢包统计 |

## 设计与接口规范

| 文档 | 适用范围 |
|---|---|
| [算法规格 v1.2](algorithm_spec.md) | 滤波器、定点格式、启动直流补偿、奇偶增益、抽取相位与时间轴 |
| [RTL 微架构](rtl_architecture.md) | 调度、存储、跨时钟域及诊断结构 |
| [集成与运行](integration.md) | 可移植前处理接口、依赖及校准 |
| [传输规格 v1.2](transport_spec.md) | FPGA 发送行为、启动等待、数据包和会话定义 |
| [上位机接口参考](host_protocol_reference.md) | 解码、样例、质量标志与接收验收 |
| [PHY 管理器](../sim/net/PHY_MANAGER.md) | MDIO 初始化、状态机及专项验证 |

算法规格 v1.2、传输文档 v1.2、UART `SYS3` 及 `I2S1` / `GAIN1` 是不同接口的版本标识。M128 UDP 头内的线协议版本仍为 **1**；SYS3 保持 34 字、312 字节，word8 新增直流诊断位 12..14。

## 当前验证证据

| 证据 | 已证明的范围 |
|---|---|
| [当前FIR8发布](reports/i2s_fir8_auto_20261011.md) | 8-lane、资源、严格时序、发布及JTAG已通过；本次A–E数字验收通过，联合结果为PASS_WITH_KNOWN_ISSUES；F真实采样连续，DATA1/ch2、3及物理未测边界保留 |
| [FIR8联合实板验收](../log/i2s_parity/fir8_auto_hardware_acceptance_20261011.json) / [F分析](../log/i2s_parity/fir8_auto_unity_spool_20261011/analysis.json) | PASS_WITH_KNOWN_ISSUES；128路选择及I2S内容通过，C+D 504,694,272样本无错无缺包；F143,589帧连续，ch2/3故障保留，full_goal_complete=false |
| [当前工作状态](../log/i2s_parity/work_status.json) | 最新位流、实板结果与未完成的物理项 |
| [正式发布结果](../fpga/build/MEMS_Array_i2s_fir8_auto_20261011/release.json) | FIR8严格快/慢角、数据库与位流身份PASS；工程上板范围，不代表实板电气签核 |
| [JTAG下载记录](../log/i2s_parity/jtag_fir8_auto_20261011/download.json) | 2026-10-11 16:19:06 PG2L200H SRAM下载PASS，ID/status与位流SHA匹配，未写Flash |
| [seed3历史数字验收](../log/i2s_parity/dc_roundsat_seed3_hardware_acceptance_20261011.json) / [原始文件绑定](../log/i2s_parity/dc_roundsat_seed3_hw_20261009_outer_invocation/result.json) | 仅前一seed3的128路配置、组零、网络/I2S BIST、真实unity及DC就绪记录；不代替新版板测 |
| [seed3历史PCM统计](../log/i2s_parity/dc_roundsat_seed3_unity_20261009/analysis.json) | 144,156帧连续；DATA1/ch2、3负满量程、ACRMS0、rail100%，无AC或DAC校准结论 |
| [自动系统功能报告](reports/system_verification.md) / [seed3不可变回归](../log/i2s_parity/full_regression_dc_roundsat_20261009.json) | seed3基线18/18、104项输入；自动/live报告会随后续运行更新，不能代替不可变基线 |
| [FIR8功能回归](../log/i2s_parity/full_regression_fir8_auto_20261011.json) / [实际映射](../log/i2s_parity/fir8_auto_map_actual_20261011.json) | 18层与六配置RAM通过；APM68/FF47,953/LUT28,512，唯一一轮路由和严格发布通过 |
| [旧B技术与布局审计](../log/i2s_parity/physical_audit_fir_fixed_result_technology_index_20261009.json) / [旧B布局快照](../log/i2s_parity/physical_audit_fir_fixed_result_postplace_final_20261009.json) | 仅旧B固定结果写回、RAM及176宏证据，保留历史，不代替seed3或新FIR8验证 |
| [前处理验证](reports/verification.md) | 自动生成，前处理模块及数值比较 |
| [性能仿真](reports/performance.md) | 自动生成，冻结系数与数值模型性能；不是声学实测 |
| [历史发布检查器自测](../log/i2s_parity/uartfix_checker_tests.log) | UART 修复阶段 186/186 通过；后续 188/190 项也属于阶段证据，不代替当前新增 RAM 证据门禁或候选自己的最终发布检查 |
| [发布检查器自测](../log/i2s_parity/timingfix_fir_ram_strict_rows_checker_tests.log) | 既有 214/214 规则自测；当前候选另有自己的正式发布结果，不用规则自测替代发布 |
| [发布检查规则](../fpga/scripts/RELEASE_CHECK.md) · [RGMII 证据说明](../fpga/scripts/TX_SOURCE_CHECK.md) | 工程发布判据、物理时序与未确认的实板边界 |

发布范围为 `engineering_board_bringup`。数字功能、器件模型时序、真实板级电气和声学性能分开记录；前三份自动生成的功能/性能报告不应手工改写测试数据。

## 历史与资料

[版本历史](reports/version_history.md) 集中列出旧位流、旧实板结果和诊断报告。旧版 157,314,048 个样本通过属于四路 CLK 版本，不能作为当前八路/1.8 V 版本的实测验收。

厂商原件保持原名：

- [盘古 MINI 系列开发板硬件指导手册 V1.3](盘古MINI系列开发板硬件指导手册_V1.3.pdf)：板卡、Bank 供电与接线。
- [IM72D128V01 数据手册](IM72D128V01XTMA1.pdf)：麦克风参数与 PDM 电气时序。
- [原始前处理需求](history/original_requirements.md)：最初范围与实现步骤。

维护文档时，完整接线表以根目录 README 为入口，发布数值以对应构建的 `release.json` 为证据；操作文档引用这两处，避免复制旧版本状态。版本变化后同步检查上板、UART、自测及主机协议说明。

2026-09-20 的[历史整理记录](../log/documentation_cleanup_20260920/audit.json)仅对应当时版本，修改前文档保存在 `log/documentation_cleanup_20260920/originals/`。本次 18 层回归与旧 17 层结果分别留档，不复用旧整理或旧发布结果作为新候选验收。
