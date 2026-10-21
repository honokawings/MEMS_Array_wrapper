# I2S、奇偶补偿与流水修复版本记录

核对日期：2026-10-09。本报告对应已主动取消的 **`MEMS_Array_i2s_parity_timingfix2_20261009`**，保留其完成阶段与未完成边界。

**状态：首轮布线未完成，已主动取消；构建及本版本板级自测未完成。** 取消原因是 `CANCELLED_ROUTING_PRESSURE_EXPERIMENT`，时序结论为 **`UNKNOWN_FIRST_ROUTE_INCOMPLETE`**。本版本已完成综合、映射、布局和 176 项宏约束接受，但未生成位流、未下载，也未取得最终双角时序或硬件验收结果。这次取消不能写成时序失败或布线成功。

[构建记录](../../fpga/build/MEMS_Array_i2s_parity_timingfix2_20261009/manifest.json) · [主动取消记录](../../fpga/build/MEMS_Array_i2s_parity_timingfix2_20261009/cancellation.json) · [完整归档索引](../../log/i2s_parity/timingfix2_archive_before_bank_enable_20261009.json) · [工作状态](../../log/i2s_parity/work_status.json)

## 已完成的验证

| 项目 | 实际结果 | 原始证据与范围 |
|---|---|---|
| 完整功能回归 | **18/18 PASS**；包含新 `fir_ram`、强制厂商 UART 及新鲜厂商模型 | [不可变摘要](../../log/i2s_parity/full_regression_timingfix_20261009.json)、[取消时快照](../../log/i2s_parity/full_regression_timingfix2_cancelled_20261009.json)；102 个数字输入与本版本构建时源码一致，不表示后续候选也通过 |
| 发布检查器自测 | **214/214 PASS** | [原始日志](../../log/i2s_parity/timingfix_fir_ram_strict_rows_checker_tests.log)；这是检查器自身测试，不是本候选发布许可 |
| 当前 FIR RAM 证据门禁 | **PASS**，绑定 14 项输入、工具及日志证据 | [实际证据核验](../../log/i2s_parity/timingfix_fir_ram_actual_evidence_gate.json)；仍须完成本候选自己的完整发布检查 |
| FIR 实际 RAM 专项 | **5,597,580 次核对、四配置全部 PASS** | 原结果和编译/仿真日志保存于[回归日志归档](../../log/i2s_parity/timingfix2_regression_logs_before_bank_enable_20261009.zip)，路径为 `log/fir_ram/` |
| 奇偶补偿专项 | **20,614 次核对，18,176 个独立参考样本，269 个完整帧** | 原结果和 `log/parity/simulation.log` 保存于[回归日志归档](../../log/i2s_parity/timingfix2_regression_logs_before_bank_enable_20261009.zip)；帧数包含 CHANNELS=1～128 参数用例，269 帧并非全部为 128 路帧 |
| 布局宏原生命令 | **176 个唯一约束全部被 PDS 接受**：128 APM、48 DRM | [本候选审计](../../log/i2s_parity/physical_audit_timingfix2_20261009.json)、[PDS 原始日志](../../fpga/build/MEMS_Array_i2s_parity_timingfix2_20261009/build.log)；宏存在性检查通过，不等于布线时序通过 |
| 本候选技术网表边界 | **新技术网表重新核验通过**，没有继承旧网表的寄存器计数 | [审计](../../log/i2s_parity/physical_audit_timingfix2_20261009.json)；成功 dev_map 后保留的实际综合 GTP 网表，尚非布线后物理 V 网表 |
| 布局阶段 | **完成，原生 place 退出码为 0** | [构建记录](../../fpga/build/MEMS_Array_i2s_parity_timingfix2_20261009/manifest.json)记录 2026-10-09 04:39:54 的布局完成事件；没有最终布线结论 |

18 层摘要 SHA-256：

`0664b18652ea5ad0f519062fec86e72b553ce23f72ae52692e3dae88401a6d93`

FIR RAM 结果 SHA-256：

`b8ed58282032a0c8cacb4668680a29aceb01a8b4d8da2e0316211aafab92850e`

本版本构建时只更正布局模板的宏实例名，未更改这 102 个数字输入，因此沿用上述实际完成的 18 层回归；没有另行生成或冒称新的功能回归结果。完整回归的 `steps.fir_ram.evidence` 绑定结果路径及 SHA-256，RAM 结果再绑定 RTL、TB、runner、两份系数 `.svh` 与两份独立参考 `.hex` 共七个输入，以及三种仿真工具、原始编译/仿真日志和仿真库配置。后续专项运行可能更新工作目录的同名日志；复核本历史版本应使用下列完整归档。

## 主动取消与证据归档

在核对本任务的构建进程身份后，2026-10-09 05:28:37 主动终止了其原生布线进程，随后原 wrapper 自然以退出码 1 结束。[取消记录](../../fpga/build/MEMS_Array_i2s_parity_timingfix2_20261009/cancellation.json)明确保存了实验取消原因、进程身份、未完成时序结论及未生成位流状态。原 manifest 保留 `FAIL` 和 `PDS process MEMS_Array_route failed`，原始日志末尾出现 `Flow-0189: Internal error occurred`；这些结束状态由本任务原生进程被主动终止产生，不是工具已经完成布线后的时序拒绝。

首轮最后一条已记录的布线进度为 iteration **29**：`unrouted=10131`、`overused=41978`，该次迭代的原生 `MT total route time` 为 **212.757 s**。该耗时字段不是本轮累计墙钟时间，计数也不是正式时序结果。原始记录见[首轮日志](../../fpga/build/MEMS_Array_i2s_parity_timingfix2_20261009/place_route/route_constraint_ite_1/run.log)。

[布线压力复核](../../log/i2s_parity/timingfix2_route_pressure_review_20261009.json)确认新增寄存器边界、控制负载和布局变化等压力因素；但报告只有逐 net 拥塞分数，没有路由器搜索耗时的因果分解。**特定 busy/CE 网络是否造成减速尚未证实**，也不能据此预测最终布线或时序能否通过。下一候选 `MEMS_Array_i2s_parity_timingfix3_20261009` 正在准备，新的完整回归与映射结果仍待取得。

[完整归档索引](../../log/i2s_parity/timingfix2_archive_before_bank_enable_20261009.json)记录下列快照；107 项输入包含数字受测输入及构建相关文件，不应与上文 102 项数字输入混为同一个集合。输入和向量 ZIP 各另附一份 `snapshot.json` 清单，下面的文件数不含该附加清单。

| 归档 | 文件数 | SHA-256 |
|---|---:|---|
| [受测与构建输入](../../log/i2s_parity/timingfix2_before_bank_enable_20261009.zip) | 107 | `ae68e206c3d343b812542a196c593c58d98d5ab3e826d3850d37b4f7ce39a986` |
| [回归原始日志](../../log/i2s_parity/timingfix2_regression_logs_before_bank_enable_20261009.zip) | 483 | `c3e17df5381d69490cbbb4353faacb0b7f5da32eaa50d3ca00569f656d573e42` |
| [参考向量](../../log/i2s_parity/timingfix2_vectors_before_bank_enable_20261009.zip) | 24 | `7d3509b9fd166357ff3d6e990ef27759ba1b5717207892ace7a1055117b1623b` |

## FIR 与奇偶补偿的实现变化

两级 FIR 新增每 lane 写暂存，地址、使能和末组标记同步寄存；最后一次真实 RAM 提交才推进指针、抽取计数和计算任务。奇偶补偿改为 8×16 分组寄存读取后选组，通道标签、增益与有效位同步延迟。

两级 FIR 各增加一拍，奇偶补偿增加一拍，默认生产链路合计增加 **3 个 122.88 MHz 周期，约 24.414 ns**。FIR1/FIR2 局部延迟分别为 546/1058 clk，128 路奇偶补偿为 131 clk。滤波系数、完整定点算术、舍入/饱和、抽取相位、输出间隔和 frame_id 不变，算法规格和传输文档仍为 v1.1，M128 线协议仍为 1。该计算开销不等于 I2S 帧边界或网络到达时刻固定延后相同时间。

四个 FIR 实际 RAM 配置如下。输入间隔以音频时钟周期计；每个配置都覆盖两次环形回绕、真实读写并行、输入接收后变化、末提交同拍接收下一向量、四阶段复位和两类真实过载。卷积参考来自外部接受序号与独立冻结系数，不从 DUT 流水生成期望。

| case | 通道 / lane / 组数 | taps | 历史深度 | 抽取比 | 输入间隔 | 核对次数 |
|---:|---|---:|---:|---:|---:|---:|
| 0，生产 FIR1 | 128 / 16 / 8 | 63 | 128 | 4 | 320 | 721,453 |
| 1，生产 FIR2 | 128 / 16 / 8 | 127 | 256 | 2 | 1280 | 4,794,859 |
| 2，单组 FIR1 | 1 / 1 / 1 | 63 | 128 | 4 | 32 | 10,676 |
| 3，单组 FIR2 | 1 / 1 / 1 | 127 | 256 | 2 | 72 | 70,592 |

`GROUPS=1` 的首次读取在末组真实提交之后的下一拍开始，避免依赖 RAM 同地址读写的器件特性。完整公式、配置边界和网络门控区别见[算法规格](../algorithm_spec.md)、[微架构](../rtl_architecture.md)及[集成指南](../integration.md)。

## 布局重匹配与当前映射证据

[重匹配审计](../../log/i2s_parity/timingfix_floorplan_remap_20261009.json)从实际 APM 的 P 输出识别 `fir1/fir2`、lane 和乘积类别，并逐位核验 X/Y 操作数；128 个语义身份均唯一，操作数总线与旧综合一致。48 个历史 RAM 名未变，按本 lane 的写数据、写提交地址和读地址核验。所有 **176 个位置及 site+element 分布保持不变**。

布局模板 SHA-256：

`e5c2272aef05da752977798e5856487715618a0a0412e65a6040655cbf94a051`

重匹配审计当时将映射层完整名称标为待验证。当前完整 PDS 重建已经产生全部 176 个原生 `def_inst_site` 成功记录，新审计证明同一组实例/位置均被接受；这是后续新增的工具证据，没有把原静态审计改写成已通过布局。

本候选重新核验的寄存器边界如下。数字是当前技术网表的实际结果；FIR1 的常量位来自 CIC 左移的源语义，不能将其误算为缺失的可变写寄存器。

| 边界 | 逻辑位数 | 实际可变 FF | 源语义常量位 |
|---|---:|---:|---:|
| 奇偶补偿分组读取 | 256 | 256 | 0 |
| FIR1 lane 写暂存 | 512 | 272 | 240，每 lane 低 15 位 |
| FIR2 lane 写暂存 | 512 | 512 | 0 |

审计同时核对实际连接、消费端和 122.88 MHz 时钟来源，并对新旧相关模块的原语种类、端口和参数重新比较。本版本未取得最终真实慢/快角网表中的流水边界、六组配置 CDC 和七个独立可变 UART 通道位验证；技术网表结果不能替代未完成的布线后证据。

| 本候选构建产物 | 已记录的 SHA-256 |
|---|---|
| [实际综合 GTP 网表](../../fpga/build/MEMS_Array_i2s_parity_timingfix2_20261009/synthesize/mems_array_pg2l200h_syn.vm) | `3b680d6a73e9141cbcc88e92ab92d089a2a6db064e34495a6899589f34fe08ad` |
| [映射数据库](../../fpga/build/MEMS_Array_i2s_parity_timingfix2_20261009/device_map/mems_array_pg2l200h_map.adf) | `c96ac779d3a22b6c73ee39843018ef3c23112a807746f6e5d3eed46dbd3e7fe0` |

## 本版本未完成的发布与实板验证

本版本已主动取消，下表没有对应的发布或实板结果。保留字段便于后续版本另行记录；旧版本下载、网络或零增益结果不能填入本表作为本版本 PASS。

| 阶段 | 当前结论 | 后续须记录的内容 |
|---|---|---|
| 正式双角与发布 | 未完成，首轮主动取消 | 选用的布线数据库；慢/快角 setup/hold 等完整检查；真实寄存器/CDC/时钟追踪；最终 release 状态及许可 |
| 位流身份 | 未生成 | `.sbit` 路径、大小、SHA-256；必须与最终 release 中的位流证据一致 |
| JTAG 下载 | 本版本未下载 | 时间、器件 ID、下载工具原始结果、加载文件 SHA-256；区分易失 JTAG SRAM 配置与 Flash 写入 |
| UART 128 路配置 | 本版本未测 | 0～127 全部请求/期望/实际通道一致；OFF、非法 128 拒绝、跨域复位重放；SYS3 与 I2S1/GAIN1 独立回帧 |
| 偶数 64 路零增益 | 本版本未测 | 实际配置确认、稳态帧数、选中 64 路零值违例、其余组非零情况、flags 与已知输入异常 |
| 奇数 64 路零增益 | 本版本未测 | 同上；随后恢复单位增益并保存真实回帧 |
| PHY / MDIO → ARP → UDP BIST | 本版本未测 | PHY ID/地址、链路/ARP 状态；FPGA 本地与发送检查；PC 包/帧/样本数及 mismatch、flags、连续性、丢包、无效负载 |
| I2S BIST 内容 | 本版本未测 | 全部通道的非零 PCM/串行内容与独立黄金值核对；通道切换、样本变化、欠载及错误增量，不能只看静音帧验证计数 |
| 恢复真实采集 | 本版本未测 | 新鲜状态确认退出 BIST，恢复期望监听与单位组增益；真实网络捕获及 DATA1/ch2、3 复核 |

## 电气与声学边界

本次全部数字检查都不能代替真实板级测量，以下项目仍未验收：

- **MEMS VDD 与 L6/L7 VCCIO 实测 1.8 V**；L5 上 I2S 为 3.3 V 逻辑，不能把整个 J10 当成 1.8 V。接线和供电以[上板指南](../board_bringup.md)为准。
- 实际阵列带载 PDM 时钟、DATA 有效窗口、驱动负载和往返路径。八路同源及 16 mA 配置不是带载波形验收。
- **DATA1 共用路径的 ch2、ch3 负满量程异常**。需后续已发布版本恢复真实单位增益后重新捕获，不能用补偿或 BIST 绕过故障定位。
- PCM5102 实际输入时序及模拟 L/R 输出、全部 64 对麦克风的声学幅度/极性/时延配平。

`clipped` / UDP bit0 是粘滞汇总，不表示每个后续样本都重新发生饱和。零增益归零只能证明数字乘法生效；内部串行数值一致只能证明内部数字数据，均不能证明麦克风输入、DAC 模拟输出或声学性能合格。

## 旧候选记录

| 候选 | 已知失败及边界 |
|---|---|
| `MEMS_Array_i2s_parity_20261009` | 已发布和 JTAG 下载，网络/BIST 与组零增益有历史实测；但 UART 数字选择在厂商编译后成为常量 0，系统目标未完成。详见[第一版报告](i2s_parity_20261009.md) |
| `MEMS_Array_i2s_parity_uartfix_20261009` | UART 解析修复与原 17 层功能检查通过，但两轮正式时序失败；未生成位流、未下载 |
| `MEMS_Array_i2s_parity_timingfix_20261009` | 18 层数字功能通过、综合/映射完成，但旧 APM 编号导致 place FAIL；未生成位流、未下载 |

本报告覆盖已主动取消并归档的工程联调候选，未形成发布许可；目标范围仍为 `engineering_board_bringup`。下一 timingfix3 的新回归、实现和实板结论须独立记录，本报告的完成阶段不能替代后续版本验收。
