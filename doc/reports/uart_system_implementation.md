# PLL 修正与完整系统 UART 集成

> 历史记录：2026-09-19 UART / PLL 集成与当日 ARP 修正进展。正文中的“当前/本次/下一步”指当时状态。当前推荐位流与未完成实板项目见[最新发布报告](clk8_18v_update.md)，版本关系见[版本历史](version_history.md)。

2026-09-19 下午历史更新：当时使用 `MEMS_Array_uart_arp_ready_routed`，ARP 启动/切换丢帧修正已完成发布、JTAG 下载及实板数字链路验收，157,314,048 个样本逐位一致且零缺帧。真实输入仍出现全通道正饱和，尚待核对阵列状态。最新位流、时序与测试证据见 [修正报告](arp_ready_fix.md)。以下保留上午 `chain8` 版本的历史实现记录。

2026-09-19 03:47：带 UART 反馈的完整系统已生成工程上板位流，正式构建 `fpga/build/MEMS_Array_uart_chain8` 的最终 `release.json` 为 **PASS**，`release_authorized=true`。功能回归、双角时序和物理接口预算均通过。当天中午已完成 JTAG 下载及 PHY/MDIO、ARP、UDP 实收验证；样本数值正确，但发现启动/模式切换等待 ARP 导致 FPGA 丢帧，**实板整体验收未通过**。见 [实板测试与定位报告](uart_board_test_20260919.md)。

## 已实现

- 将独立实板验证通过的以太网 PLL 参数 I=4、M=16、F=2、O=4、OPTIMIZED 合入 `rtl/board/pango_board_clocks.v`。PFD=31.25 MHz，250 MHz PLL 输出与 125 MHz 网口逻辑时钟不变。
- 在原完整顶层新增 B24/C24 UART，独立 27 MHz 观察器、命令接收和串口发送，全部反馈经 COM3。物理按键功能保留，但本轮诊断不依赖 LED 页表。
- PHY 管理器导出最近 MDIO 事务、ID、PHYSR、配置状态、读无 ACK 数及失败原因；故障原因跨 PHY 自动重试保存。
- MAC 导出 ARP 请求/回复/接收、对端 MAC、UDP 完成数，RX 域导出帧/字节/RX_ER 计数。PCM 域导出采样、校准、自测及错误状态。
- 多位状态用分域握手快照传输。接收时钟停止时标记 RX 快照过期；UART 继续输出其余域状态。
- 修正运行中切换自测的会话边界：旧会话中止产生的 TX 错误在新会话开始时清除；自测发送检查延后一拍启用，避免读到尚未提交清除的旧错误。

状态协议及实板步骤见 [完整系统 UART 联调](../system_uart_debug.md)。前处理系数、声道映射、48 kHz/24 位输出和 M128 UDP 数据格式保持兼容。

## 功能验证证据

`python sim/verify_all.py` 的 **12 项完整回归通过**，包括重新生成 Python/C++ 模型、厂商原语仿真；没有采用跳过模型或跳过厂商检查的发布方式。完整记录：[full_regression.json](../../log/full_regression.json)、[验证报告](system_verification.md)。

| 检查 | 结果 |
|---|---|
| 完整 PDM → UDP → 上位机参考比较 | 99 包、297 帧、38,016 个通道样本逐位一致；包括故意拥塞/丢整帧用例 |
| 原内部 PDM 自测 | 15,360 个通道样本逐位一致；正常段维持 16,000 包/秒 |
| UART 收发单元 | 777 项检查，包括全部 256 字节、波特率偏差、短毛刺与停止位错误 |
| 新完整顶层 UART 集成 | 27 行实际串口字符；PHY/MDIO、ARP、UDP、自测模式运行中切换、RX 停钟、无 ACK 恢复和软件复位通过 |
| 上位机 UART 解析 | 合成字段/畸形输入检查，并逐行解析 RTL 实际串口输出 |
| PLL 厂商参数校验 | 原 I=1/M=4 组合作为负例被拒绝；当前三个 PLL 参数全部接受 |

UART 集成模型将复位、消抖、自测通过阈值及报告间隔缩短，并加速 UART 波特率；GMII 与音频时钟维持生产频率。其频率计数窗口/预分频也缩短，日志不能套用生产 0.1024 MHz 单位来作为板上频率测量。集成测试的物理时钟和 DDR 为数字替身，真实 Pango PLL/DDR 另由全量回归的 vendor 项验证。

调试中修正了新增端口与旧 `.*` 测试台的接口适配、测试台虚拟按键释放间隔和预期中止帧的检查边界；还修正了 PowerShell 数组表达式的运算优先级。最终回归使用同一冻结源文件集合，记录运行前后哈希一致。

## 最终实现结果

异常耗时与 FIR 宏布局及大扇出控制网络有关。最终采用全局 `fanout_guide=256`、关键 CE/同步清除/WE 的显式 `syn_maxfan=256`、经过功能身份核对的 128 个 APM 与 48 个历史 RAM 位置，以及 `-max_ctrl_chain_length 8`。控制链上限消除了 FIR 结果写使能经过长 CECO 链的 setup 违规；保留原周期行为、RAM 推断、频率及全部时序要求。完整诊断和未采用方案见 [布线耗时诊断](uart_routing_diagnosis.md)。

| 项目 | 实际结果 |
|---|---|
| 下载文件 | [mems_array_pg2l200h.sbit](../../fpga/build/MEMS_Array_uart_chain8/generate_bitstream/mems_array_pg2l200h.sbit) |
| SHA-256 | `f8c38ae04039572f3efec5a593cc4b1089eed69c4975dbfb0e9c2e7a991a03d7` |
| 大小 | 9,188,552 字节 |
| 整体构建 | 03:04:46 至 03:47:31，约 42 分 45 秒 |
| PNR / 详细布线 | 33 分 58 秒 / 1657.39 秒（27 分 37 秒） |
| 最终发布验收 | [release.json](../../fpga/build/MEMS_Array_uart_chain8/release.json)：PASS |
| 功能 / 检查器测试 | 12 项完整功能回归、106 项检查器测试 PASS |
| 双角时序 | All Constraints Met，所有违规端点为 0 |
| 音频域 slow setup / hold | +0.076 / +0.092 ns |
| 音频域 fast setup / hold | +1.667 / +0.020 ns |
| RGMII TX 实际最大偏差 | 0.279 ns，小于 0.300 ns 上限，最小余量 0.021 ns |
| PDM slow / fast 预算余量 | 8.349 / 10.527 ns |
| TXC 名义模型占空比 slow / fast | 48.85% / 51.6125%，满足 45%～55% |
| 管脚 / 构建来源 | 95 个管脚一致；全流程输入哈希未变；176 条位置约束实际接受 |

源文件、map 数据库、原始/追加后 PCF、两角网表及 SDF、最终 routed DB 与位流均由发布检查关联核验。新版最差慢角路径已转移到 FIR1 历史 RAM 写入选择，原长 CECO 链瓶颈消除。此前三个已下载位流的哈希保持不变，见 [保存核对记录](../../log/system_uart/preserved_bitstreams.json)。

## 发布与硬件边界

构建入口使用独立目录，不覆盖此前三种已下载位流。新发布检查要求 95 个物理端口映射一致、双角时序通过、RGMII TX 实际偏差/PDM 输入输出预算通过，并验证厂商 PLL 校验结果与当前 RTL/工具源一致。

新增观察域仍约束 CDC 路径不超过 7.5 ns。27 与 122.88 MHz 比值为 1024/225，超出 PDS 1000 周期的相位展开搜索，因此仅对这一已知 CDC 时钟对作专项审查，并要求双方向、双角实际物理路径通过。PLL 异步 LOCK 状态经多级同步器观察；未用强行释放 LOCK 或放宽数据路径限制代替 PLL 修正。

电脑预检识别到 FPGA 网卡 `6C-1F-F7-1F-1F-BC`，地址仍为 `192.168.10.1`；当前旧独立诊断维持 PHY 复位，网卡显示 Down。未修改系统网络或防火墙。预检：[network_preflight.json](../../log/system_uart/network_preflight.json)。

后续验收必须记录新位流 SHA-256，并结合 COM3、限定网卡二层抓包和 PCM 实际接收逐位比较。UART 的 UDP 计数增长只证明 FPGA 侧完成发送，不等于电脑已经收到。实际麦克风带载时钟、电气质量、声学 SNR 和定位性能仍属于后续实物验收范围。

本次使用 PDS 的 Pre-silicon 双角模型，发布范围为 `engineering_board_bringup`。实际 TXC 占空比/抖动尚需测量；将未定义统计口径的 180 ps 解释为逐沿 ±180 ps 的附加敏感性分析仍为 FAIL，完整保留在发布记录中，没有改写为通过。它不等同于厂商名义模型的结果，也不能据此宣称整板已完成资格验证。
