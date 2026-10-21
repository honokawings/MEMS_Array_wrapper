# I2S、奇偶补偿与 bank 刷新修复版本记录

核对日期：2026-10-09。本报告记录已主动取消的候选 **`MEMS_Array_i2s_parity_timingfix3_20261009`**，盘古 MINI-200H、PG2L200H / FBB676 / -6。

**状态：首次布线尚未完成时主动取消，无位流、未下载、未进行本版本板级自测。** 取消前本版本已完成新一轮 18/18 功能回归、综合/映射及布局。取消原因为 `CANCELLED_FIR_DATA_ENABLE_PRESSURE_EXPERIMENT`；最终时序结论为 `UNKNOWN_FIRST_ROUTE_INCOMPLETE`。构建包装器返回 FAIL/exit 1，表示此次主动停止的流程没有完成，不能据此报告最终时序失败或通过。[取消记录](../../fpga/build/MEMS_Array_i2s_parity_timingfix3_20261009/cancellation.json)保留停止时间及进程身份。

[构建记录](../../fpga/build/MEMS_Array_i2s_parity_timingfix3_20261009/manifest.json) · [取消前归档](../../log/i2s_parity/timingfix3_archive_before_fir_enable_20261009.json) · [工作状态](../../log/i2s_parity/work_status.json) · [音频操作指南](../audio_monitor.md) · [上板指南](../board_bringup.md)

## 本版本已完成的数字验证

| 项目 | 实际结果 | 证据与范围 |
|---|---|---|
| 本版本完整功能回归 | **新一轮 18/18 PASS**，102 个数字输入与取消前源码一致 | [取消版不可变摘要](../../log/i2s_parity/full_regression_timingfix3_cancelled_20261009.json)；厂商模型重新执行，包含强制 UART 技术网表、host 和 FIR 实际 RAM 层 |
| 发布检查器规则自测 | **既有 214/214 PASS**，校验器未修改 | [原始日志](../../log/i2s_parity/timingfix_fir_ram_strict_rows_checker_tests.log)；这是同一检查器的规则证据，不是本候选最终发布检查 |
| FIR 实际 RAM 专项 | **5,597,580 次核对、四配置 PASS** | 本轮结果、编译与仿真日志保存在[取消前原始日志归档](../../log/i2s_parity/timingfix3_regression_logs_before_fir_enable_20261009.zip)；本轮结果 SHA-256 见下方 |
| 奇偶补偿专项 | **20,614 次核对、18,176 个独立参考样本、269 个完整帧** | 本轮结果及仿真日志保存在[取消前原始日志归档](../../log/i2s_parity/timingfix3_regression_logs_before_fir_enable_20261009.zip)；包括 CHANNELS=1～128 参数用例，269 帧并非全部为 128 路帧 |

本轮不可变 18 层摘要 SHA-256：

`fded79743776c5d79acfdf03e3d83ab27f7b833a9f99cea5ec6e580ed2e537d0`

本轮 FIR RAM 结果 SHA-256：

`39011a3d32a0644cb380a509d9a8b5e9f8e22904e6e707d67ff946b4f2e2bd85`

奇偶补偿 RTL SHA-256：

`611a08f479b5ceaec25d518ecf2300ca249539c74f9c6f30a1b8d775e2f144e4`

本次奇偶 RTL 已更改，不能把 timingfix2 的旧 18 层结果当作本版本功能证据。上述新回归重新核对完整前处理、无网 I2S、配置切换、BIST 旁路与恢复、PHY/ARP/UDP、UART 和主机检查。完整回归的 `steps.fir_ram.evidence` 绑定本轮 RAM 结果路径及 SHA-256，结果再绑定 RTL、TB、runner、两份系数 `.svh`、两份独立参考 `.hex`、工具、原始日志与仿真库配置。取消前已将受测输入、原始日志和向量完整归档；后续工作目录中的同名结果可被新回归更新，本版本应以不可变摘要和归档内容追溯。

## 主动取消与完整归档

2026-10-09 06:23:47（北京时间）停止本任务的原生布线进程，包装器随后自然退出。取消记录明确 `RootCauseProven=false`、`bitstream_generated=false`；[构建记录](../../fpga/build/MEMS_Array_i2s_parity_timingfix3_20261009/manifest.json)确认 `sources_unchanged=true`。此次停止为下一项受控 FIR 数据使能实验保留基线，没有获得本版本完整布线或最终双角时序。

[原始 build.log](../../fpga/build/MEMS_Array_i2s_parity_timingfix3_20261009/build.log)第 23601 行记录第 30 轮：

```text
Unrouted general nets at iteration 30 (MT total route time: 149.760 sec): 9176(overused: 37722)
```

该行显示仍有 9,176 条未布线网络、37,722 项 overused，工具记录的该轮时间字段为 149.760 秒；它不是最终时序报告，也不能用于证明某一 CE 网络造成减速。FIR2 数据暂存使能的 512 个 CE 负载及拥塞观察是下一候选实验的依据，取消记录并未将其判定为已证明的根因。

[取消前归档核对](../../log/i2s_parity/timingfix3_archive_before_fir_enable_20261009.json)状态 **PASS**，保存了 107 个输入文件、483 个原始日志文件及 24 个向量/系数文件，以及独立保留的 18/18 回归摘要。输入包和向量包各另含一份 `snapshot.json` 清单，不计入受测文件数。三个压缩包身份如下：

| 归档 | 文件数 | SHA-256 |
|---|---:|---|
| [输入](../../log/i2s_parity/timingfix3_before_fir_enable_20261009.zip) | 107 | `9d7c28731fa7eeb90df26cd870df5f21b84524bc420b76b9fc428ecb1b211319` |
| [原始日志](../../log/i2s_parity/timingfix3_regression_logs_before_fir_enable_20261009.zip) | 483 | `490f1228af0e8eed647632d83613007025b48f76340cff35d33460de0df11342` |
| [向量与系数](../../log/i2s_parity/timingfix3_vectors_before_fir_enable_20261009.zip) | 24 | `528a2bf85441c0fe3669eae7aefd095d27170e8f545c5d614dc6002860735ac9` |

## 本次修复与不变的数值契约

保留 8×16 分组读取和全部有效位、通道标签、增益及主状态机控制，只移除各 bank_sample 寄存器的 busy CE。`clear_state` 仍具有最高优先级；除此之外，每个音频时钟都刷新 bank 数据。只有 `group_valid` 有效时才消费相应样本，空闲时刷新不会成为有效输出，也不会改变配置提交或旧样本清除规则。

这是一项待实测物理效果的控制负载实验。旧版压力记录显示控制负载与拥塞，但未证明某一 CE 网络就是路由减速根因；不能仅因移除 CE 就宣称本版布线更快或时序通过。

| 保持不变的项目 | 定义 |
|---|---|
| 奇偶补偿帧完成延迟 | 128 路从帧接收到 valid 为 **131 clk** |
| FIR 局部延迟 | FIR1/FIR2 分别 **546/1058 clk**，写暂存和真实提交规则不变 |
| 默认流水开销 | 相比 UART 修复版，两级 FIR 各 +1clk，奇偶读取 +1clk，合计 **3clk≈24.414 ns** |
| 数值与时间轴 | 滤波系数、定点算术、舍入/饱和、抽取相位、48 kHz 输出间隔和 frame_id 不变 |
| 版本 | 算法规格 v1.1、传输文档 v1.1、M128 线协议 1；SYS3 不变，I2S1/GAIN1 仍独立回帧 |

完整运算仍先将 `FIR_Q30×parity_Q22` 舍入/饱和回 Q2.30，再计算 `(补偿后 Q30−offset_Q30)×逐通道 gain_Q22` 并舍入/饱和至 Q1.23；不能合并成一次舍入。内部 PDM BIST 保留已安装组增益，但实际按单位组增益旁路。正常板级真实音频无需 PHY/ARP 就绪，网络仍等待千兆全双工与 ARP；BIST 和可移植默认网络模式保持网络门控。详见[算法规格](../algorithm_spec.md)、[微架构](../rtl_architecture.md)及[集成指南](../integration.md)。

FIR 专项继续从外部接受序号和独立系数构建卷积参考，实际检查 RAM 写入、两次环形回绕、读写并行、输入捕获后变化、末提交同拍接收下一向量、四阶段复位和两类过载。

| case | 通道 / lane / 组数 | taps | 历史深度 | 抽取比 | 输入间隔，clk | 核对次数 |
|---:|---|---:|---:|---:|---:|---:|
| 0，生产 FIR1 | 128 / 16 / 8 | 63 | 128 | 4 | 320 | 721,453 |
| 1，生产 FIR2 | 128 / 16 / 8 | 127 | 256 | 2 | 1280 | 4,794,859 |
| 2，单组 FIR1 | 1 / 1 / 1 | 63 | 128 | 4 | 32 | 10,676 |
| 3，单组 FIR2 | 1 / 1 / 1 | 127 | 256 | 2 | 72 | 70,592 |

## 本版本实现结果与未完成验收

本版本已完成新的[技术网表与宏位置审计](../../log/i2s_parity/physical_audit_timingfix3_20261009.json)：256 个 bank 寄存器全部保留为无 CE 的 `GTP_DFF_R`，清零、时钟、逐位数据输入及后级有效消费关系核验通过；`busy` 的 CE 负载为 30 个，来自标签及增益寄存器。128 个 FIR APM 与 48 个历史 DRM 的 **176 个原位置约束保持不变**，本版本全部原生命令接受，布局阶段 exit 0。这些是本版本自己的综合/映射与布局证据，范围不含最终布线寄存器导出或正式布线后时序。

本版本在首次布线完成前取消，下表保留已确认阶段及未取得的验收项；没有最终发布、位流或实板结果可填写。

| 阶段 | 当前结论 | 后续须记录的证据 |
|---|---|---|
| 新综合/映射与布局 | 本版本审计 PASS、布局 exit 0 | bank 无 CE、同步清零及有效消费；FIR 写暂存和时钟连接；全部 176 项原生宏约束接受，范围不含最终布线 |
| 正式布线后双角 | 首次布线未完成即取消，最终时序 UNKNOWN | 未取得最终数据库及慢/快角 setup/hold 检查；综合阶段追踪不能替代最终寄存器和 CDC 核验 |
| 最终发布 | 未取得发布许可 | 无本版本最终发布 PASS |
| 位流身份 | 未生成 | 无 `.sbit` 或位流 SHA-256 |
| JTAG 下载 | 本版本未下载 | 时间、器件 ID、原始结果和加载 SHA-256；区分 JTAG SRAM 配置与 Flash 写入 |
| UART 128 路配置 | 本版本未测 | 0～127 请求/期望/实际一致，OFF、非法 128 拒绝及跨域复位重放；SYS3 与独立音频回帧 |
| 偶数 64 路零增益 | 本版本未测 | 实际配置确认、稳态帧数、选中组零值违例、其余组非零、flags 与已知输入异常 |
| 奇数 64 路零增益 | 本版本未测 | 同上，随后恢复单位增益并保存新鲜实际回帧 |
| PHY / MDIO → ARP → UDP BIST | 本版本未测 | PHY ID/地址、链路/ARP、FPGA 本地与发送检查；PC 包/帧/样本数量及 mismatch、flags、连续性、丢包和无效负载 |
| I2S BIST 内容 | 本版本未测 | 全通道非零 PCM/串行内容与独立黄金值；通道切换、样本变化、欠载及错误增量，不能只看静音验证计数 |
| 恢复真实采集 | 本版本未测 | 新鲜状态确认退出 BIST、恢复期望监听和单位组增益；真实网络数据与 DATA1/ch2、3 复核 |

## 历史候选与未验收边界

下一候选暂定 `MEMS_Array_i2s_parity_timingfix4_20261009`，准备仅去除 FIR1/FIR2 `write_data` 各 512 个数据寄存器的 CE，保留暂存寄存器、相同数据选择，以及 valid、提交地址、末组和 RAM 复位门控。奇偶补偿保持本报告的 `611a08f…e2f144e4` 源码不变。此项是下一候选的准备工作；本报告未取得它的新完整回归、实际 CE 映射、布线或时序结论，也不宣称 FIR CE 修改已改善物理实现。本版本 18/18 PASS 不自动适用于下一候选。

| 历史候选 | 已记录的事实 |
|---|---|
| `MEMS_Array_i2s_parity_20261009` | 已发布/JTAG 下载，有网络 BIST 与组零增益历史实测；UART 数字选择被厂商编译成常量 0，系统目标未完成。见[第一版报告](i2s_parity_20261009.md) |
| `MEMS_Array_i2s_parity_uartfix_20261009` | 原 17 层功能通过，正式两轮时序失败；未生成位流、未下载 |
| `MEMS_Array_i2s_parity_timingfix_20261009` | 原 18 层功能通过，旧 APM 名称导致 place FAIL；未生成位流、未下载 |
| `MEMS_Array_i2s_parity_timingfix2_20261009` | 布局完成、176 项宏约束接受；首轮布线未完成，主动取消，时序结论 UNKNOWN；不是时序失败。见[取消版报告](i2s_parity_timingfix2_20261009.md) |

旧版本的发布、下载和实测均不填入本版本未测表。目标范围仍为 `engineering_board_bringup`，以下实际测量尚未验收：

- MEMS VDD 与 L6/L7 VCCIO 实测 **1.8 V**；L5 I2S 使用 **3.3 V** 逻辑并共地，不能把整个 J10 当成 1.8 V。
- 带载 PDM 时钟/有效采样窗口及实际外部路径；八路同源、16 mA 配置并不证明波形合格。
- DATA1 共用路径的 **ch2、ch3 负满量程异常**，需后续获得发布许可的位流实际下载后，以真实单位增益捕获重新复核。
- PCM5102 实际输入与模拟 L/R 输出，以及全部 64 对麦克风的声学幅度、极性和时延配平。

`clipped` / UDP bit0 是粘滞汇总，不表示每个后续样本都再次饱和。零增益归零证明数字乘法生效，内部串行监测证明内部数字一致；它们都不能排除 DATA1 物理异常或替代 DAC、声学验收。本版本停留在主动取消、未发布、未下载的历史状态；后续候选必须保存自己的发布与硬件原始证据。
