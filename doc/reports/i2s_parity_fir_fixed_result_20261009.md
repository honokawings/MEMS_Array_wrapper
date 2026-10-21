# I2S、奇偶补偿完整系统交付与实板验收

日期：2026-10-09，时间均为北京时间。目标器件：盘古 MINI-200H，PG2L200H / FBB676 / -6。

**当前版本 `MEMS_Array_i2s_parity_fir_fixed_result_20261009` 已生成位流、通过严格发布检查，并通过 JTAG 下载及实板数字自测。** 原 UART 通道号恒为 0 的问题已在 128/128 通道实测中解决。真实输入的 DATA1/ch2、3 仍固定负满量程；板上电压、PCM5102 模拟输出和声学补偿尚未验收。

当前板上状态为真实麦克风采集、奇偶增益均为 1、I2S 通道 0 开启。此次只下载 JTAG SRAM，未写 Flash；断电后不会保留该 SRAM 配置。

## 位流与复查入口

| 项目 | 实际记录 |
|---|---|
| 位流 | [mems_array_pg2l200h.sbit](../../fpga/build/MEMS_Array_i2s_parity_fir_fixed_result_20261009/generate_bitstream/mems_array_pg2l200h.sbit) |
| 文件大小 | 9,188,552 字节 |
| SHA-256 | `0d74a8d706584a86e443b44ec315ac26161dc85a302d4d018aac726d83a38820` |
| 发布检查 | [release.json](../../fpga/build/MEMS_Array_i2s_parity_fir_fixed_result_20261009/release.json)：`PASS`，`release_authorized=true`，范围 `engineering_board_bringup` |
| 下载记录 | [download.json](../../log/i2s_parity/jtag_fir_fixed_result_20261009/download.json)：14:40:49 完成，`PASS` |
| JTAG 读回 | PG2L200H，ID `0x00603899`，状态 `0x081ffca0`；DONE、INIT、PLL 正常，配置错误位为 0 |
| 完整数字验收 | [acceptance.json](../../log/i2s_parity/fir_fixed_result_hw_20261009/acceptance.json)：`PASS_DIGITAL_ONLY` |
| 真实 PCM 统计 | [analysis.json](../../log/i2s_parity/fir_fixed_result_unity_20261009/analysis.json)：`PASS_WITH_KNOWN_ISSUES` |

完整本地路径为 `D:\Workspace\Modelsim\260902_MEMS_Array\fpga\build\MEMS_Array_i2s_parity_fir_fixed_result_20261009\generate_bitstream\mems_array_pg2l200h.sbit`。下载、每项自测及原始数据均绑定这一文件身份；旧位流的通过结果不计入本版本。

## 实现与布线修正

本版本保留奇偶补偿的局部选择计数器和 FIR 的局部写组选择，将 FIR 结果改为固定通道组的 32 位切片写回。每条 lane 共用一份饱和值，以 `final_valid` 和组号使能写入；有效帧、RAM 提交边界、舍入、饱和与复位保持原规则。

FIR1/FIR2 延迟仍为 546/1058 拍，128 通道奇偶补偿仍为 131 拍，相比最初 UART 修正版总增加 3 拍。48 kHz 输出间隔、通道序号、frame_id、SYS3/I2S1/GAIN1 和 UDP 线协议均保持不变。

实际技术映射中 LUT 从上一局部写组版本的 40,821 降为 33,588，减少 7,233（17.7%）；8,192 个结果寄存器的自身 D 反馈被移除，使能和复位条件已核对。176 个固定宏的角色、位置和 BEL 保持，128 个 APM 仅按实际网表更名，48 个 RAM 名称保持。

正式完整构建从 compile 开始，采用 Center、疏散 5、种子 2、实际 5 个路由线程，动作时限 180 分钟。首轮详细布线耗时 621.37 秒，75,601 条连接全部布通且无保持时间违规；包含保存和报告的首轮 PNR 总耗时 13 分 46 秒。这是本次实际结果，不将不同版本或并行环境的耗时当作单变量性能证明。

首轮已完整保存且全部约束通过后，工具启动第二轮可选优化。14:32:46 仅停止该自有优化进程，保留原优化器的 FAIL、原日志和取消原因，再使用既有检查点流程重新导出正式时序、慢/快角网表、执行所有发布检查并生成位流。没有将中断的原优化器改写为正常成功。

| 验证 | 结果 / 证据 |
|---|---|
| 完整功能回归 | [18/18 PASS](../../log/i2s_parity/full_regression_fir_fixed_result_20261009.json)，模型重新运行，102 项验证输入一致；包含真实 FIR RAM、厂商 UART 网表及主机检查 |
| 最终时序 | 全部约束通过；慢角最小 setup 0.021 ns、hold 0.037 ns，快角最小 hold 0.020 ns，失败端点为 0 |
| 实际双角控制 | 7 个独立 UART 通道 FF、6 个配置 CDC FF、连接、时钟与复位检查通过 |
| 正式发布证据 | [最终独立审计索引](../../log/i2s_parity/physical_audit_fir_fixed_result_release_final_index_20261009.json)，绑定本版本数据库、双角输出和位流 |

时序裕量较小；这里的通过是 `Pre-silicon` 器件模型和现行约束下的工程结论，不替代外部带载测量。发布记录仍明确 `unconditional_board_qualification=false`，TXC 占空比/抖动敏感性检查为 `FAIL`，实际 TXC 条件未确认。须在 PHY 处实测占空比、边沿和抖动，核对板级偏斜预算；当前网口实测通过不等于所有电气条件下均已验收。

## 实板数字自测

自测通过 COM3（115200、8N1）和 `以太网 2`（1 Gbit/s，电脑 `192.168.10.1/24`）完成，FPGA 为 `192.168.10.2`、UDP 5000。串口阶段顺序执行，每阶段保存真实开始/结束、命令、退出码、位流身份和产物哈希。

| 阶段 | 实际结果 |
|---|---|
| A：UART 配置 | 137 项检查全部通过；0～127 每路请求/期望/实际一致，反馈新鲜且无 pending；OFF 时数据清零、时钟继续；非法输入拒绝、增益设置及复位重放通过 |
| B：奇偶独立零增益 | 偶组 48,090 个稳定帧、奇组 143,736 个稳定帧；每组 64 路全部精确为 0，另一组 64 路均保持非零，零值违例为 0；最后恢复单位增益。既有满量程问题保留，不算声学标定 |
| C：PHY → ARP → UDP | MDIO 识别 `001CC916`，PHY/link/ARP peer 正常；FPGA 内部 BIST 通过。198,424 包、595,272 帧、76,194,816 样本逐一与黄金数据相符 |
| D：I2S 内容与持续收包 | 每通道 4 个快照，共 512；全部通道非零内容及变化符合对应自测序列，稳态欠载增量为 0；0.5/0.75 配置下 BIST 仍按单位增益旁路。70 秒收包得到 1,119,997 包、3,359,991 帧、430,078,848 个黄金一致样本 |
| E：退出与恢复 | 恢复真实模式、两组单位增益及初始 I2S 通道 0 开启；反馈新鲜、串口/配置队列错误为 0，PHY/ARP 和 UDP 计数继续前进 |

C、D 的数值错误、错误标志、连续性错误、主机队列丢包、无效负载和未保存队列包均为 0，合计 **506,273,664 个 BIST 样本**一致。C 捕获启动及切换前的 25,900 个普通包被明确跳过，比较范围是 BIST 会话；D 无普通包跳过。不能据此声称 C 的全部跨会话数据都属于同一连续自测序列。

[实际执行摘要](../../log/i2s_parity/fir_fixed_result_hw_20261009/orchestration.json) · [C 数值验证](../../log/i2s_parity/fir_fixed_result_hw_20261009/C/pcm_verified.json) · [D 数值验证](../../log/i2s_parity/fir_fixed_result_hw_20261009/D/pcm_verified.json)

[独立实板审证索引](../../log/i2s_parity/fir_fixed_result_hardware_independent_index_20261009.json)和[原始文件哈希清单](../../log/i2s_parity/fir_fixed_result_hardware_raw_hashes_20261009.json)保留下载、执行记录、UART 原始回帧、PCM、元数据及总结的对应关系。

## 真实麦克风数据与下一步排查

完成 E 后独立执行 3 秒真实 PCM 捕获：47,969 包、143,907 帧，所有 128 通道均统计，包/帧连续性正常。全程保留饱和标志，没有将异常帧剔除后宣称音频合格。

| 信号 | 实际统计 |
|---|---|
| DATA1 引脚 | J26 / AC22，对应通道 2（偶）和 3（奇） |
| 通道 2、3 | 每路 143,907 个样本全部为 −8,388,608；最小值=最大值，AC RMS=0，满量程占比 100% |
| 全局状态 | 143,907 帧均带 sticky saturation，统计和原始数据保留该问题 |
| 验收结论 | 数字采样/传输通过；这两路外部采集失败，全部 64 对声学补偿未通过 |

下一步优先检查 DATA1/AC22 的接线、焊接、两只麦克风供电与 LR 接法，并在麦克风端测量 PDM DATA/CLK。也需实测 L6/L7 VCCIO 与 MEMS VDD 为 1.8 V。内部 BIST 已通过相同 FPGA 处理和网络链路，外部输入路径是当前优先排查方向，但现有数据不能单独证明损坏的是线缆、麦克风还是电气条件。

PCM5102 的 SCK/BCK/DIN/LRCK 数字逻辑与内部内容自测通过；外部引脚波形、FMT/XSMT 接法和模拟输出仍待测。奇偶增益当前均为 1，是默认配置，不是完成声学配平；须修复异常并采集满足要求的共同声源，才可标定全部 64 对。

[真实采样执行与原文件绑定](../../log/i2s_parity/fir_fixed_result_unity_20261009/execution_F.json) · [全通道统计](../../log/i2s_parity/fir_fixed_result_unity_20261009/analysis.json) · [音频与补偿操作](../audio_monitor.md)

## 历史范围

[第一版报告](i2s_parity_20261009.md)记录当时网络通过、UART 选通失败及 DATA1 异常。[UART 修复时序失败](i2s_parity_uartfix_timing_20261009.md)、[timingfix4 参数对照](i2s_parity_timingfix4_20261009.md)及局部写组候选的超时/取消原始证据均保留。布线未完成版本的时序结论为未知，不能改写为已测得的时序违例。

操作入口见[上板指南](../board_bringup.md)、[UART 联调](../system_uart_debug.md)与[文档索引](../README.md)。自动回归报告的测试数据保持原始结果；本报告汇总实际构建、下载、数字实测与尚未完成的物理验收范围。
