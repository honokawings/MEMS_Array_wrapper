# I2S、奇偶补偿与 FIR 数据暂存修复记录

核对日期：2026-10-09。本报告记录冻结 **`MEMS_Array_i2s_parity_timingfix4_20261009`** 及其布局参数对照的历史终态，目标器件 PG2L200H / FBB676 / -6。原候选、D5、Quad10 和 Quad5 均已退出，布局参数对照已结束；这里的 18/18 功能结果仅属于该冻结输入。

**冻结 timingfix4 的历史结果：18/18 功能回归通过，设备映射和已完成的布局核对通过；原候选及 D5 自然超时，Quad5 主动取消，三者最终时序均未知；Quad10 参数不合法退出。全部对照候选均无新位流。** 后续局部选择、局部写组及固定结果组版本分别取得自己的新输入证据；最新固定结果分组版本已独立通过发布、JTAG 和实板数字自测，见[当前交付报告](i2s_parity_fir_fixed_result_20261009.md)。本页仅记录历史过程，不描述当前板上运行状态，也不将这里的旧 PASS 计作新输入验收。

[工作状态](../../log/i2s_parity/work_status.json) · [本轮不可变回归摘要](../../log/i2s_parity/full_regression_timingfix4_20261009.json) · [音频操作指南](../audio_monitor.md) · [上板指南](../board_bringup.md)

## 本次修改

仅移除 FIR1/FIR2 `write_data` 数据暂存寄存器的共同使能，使其每拍更新。数据选择表达式、暂存寄存器、输入捕获、有效标志、提交地址、末组标志及 RAM 写门控保持原样。RAM 仅在 `rst_n && write_commit_valid` 时提交；有效提交消费上一拍已经暂存的数据，空闲期间的数据变化不会成为有效写入。

奇偶补偿保留此前的 8×16 分组读取和无 busy CE 的银行数据刷新。所有通道标签、增益提交、复位及有效消费规则保留。本次控制负载修改的物理效果需由新的综合、布局布线和时序结果确定，不能从功能仿真推断布线改善。

| 数值与时序契约 | 定义 |
|---|---|
| FIR 局部延迟 | FIR1/FIR2 分别 **546/1058 clk** |
| 奇偶补偿 | 128 路接收至 valid 为 **131 clk** |
| 默认流水开销 | 相比 UART 修复版共增加 **3 clk≈24.414 ns** |
| 输出 | 系数、舍入、饱和、抽取相位、48 kHz 间隔及 frame_id 不变 |
| 协议 | SYS3 不变；I2S1/GAIN1 独立反馈，M128 线协议 1 |

定点链路仍分两次舍入：先将 `FIR_Q30×parity_Q22` 舍入/饱和至 Q2.30，再将 `(补偿后 Q30−offset_Q30)×逐通道 gain_Q22` 舍入/饱和至 Q1.23。内部 PDM BIST 在真实捕获、CIC、两级 FIR 和 PCM 链路中运行，组增益实际按单位增益旁路。

## 冻结 timingfix4 的功能证据

| 项目 | 实际结果 | 证据与范围 |
|---|---|---|
| 完整功能回归 | **18/18 PASS**，102 项冻结输入哈希一致 | [不可变摘要](../../log/i2s_parity/full_regression_timingfix4_20261009.json)；重新运行厂商模型，未复用旧模型结果；不覆盖 local_lane 合入后的新输入 |
| FIR 实际 RAM | **5,597,580 项，四配置 PASS** | 本轮完整回归绑定 [RAM 结果](../../log/fir_ram/result.json) 的 SHA-256、源码、独立系数、工具及原始日志 |
| FIR 算术 | **20,144 乘积及 20,054 舍入值 PASS** | [原始仿真日志](../../log/fir/arithmetic_sim.log) |
| UART 厂商网表 | **PASS** | [厂商 UART 结果](../../log/vendor_uart/result.json)；七个可变通道寄存器及全部 128 通道功能检查 |
| 发布规则自测 | **既有 214/214 PASS**，检查器未修改 | [原始日志](../../log/i2s_parity/timingfix_fir_ram_strict_rows_checker_tests.log)；不等于本候选最终发布通过 |

冻结 timingfix4 完整回归摘要 SHA-256：

`216014b847cc288f8a8fb0b596c202da39d0615475555816071f4a7b831b8085`

冻结 timingfix4 FIR RTL SHA-256：

`b7637088a3e345232f51f124d89fea795eee67829f8b9c838da5533c35a9a7eb`

冻结 timingfix4 奇偶补偿 RTL SHA-256（local_lane 合入前）：

`611a08f479b5ceaec25d518ecf2300ca249539c74f9c6f30a1b8d775e2f144e4`

[冻结 timingfix4 证据归档](../../log/i2s_parity/timingfix4_archive_20261009.json)已通过 CRC 与成员哈希核对，包含 107 项受测与构建输入、483 份原始日志、24 项参考向量/系数。后续工作目录同名结果即使更新，也可从此归档追溯本版本。

## 位流与板级验收

下表仅填写本版本真实结果。未执行项目保持待验证。

| 阶段 | 当前状态 | 验收内容 |
|---|---|---|
| 临时设备映射 | **技术网表边界及语义更名 PASS** | [独立审计](../../log/i2s_parity/physical_audit_timingfix4_map_final_20261009.json)：256 bank +1024 FIR 数据 FF 无 CE，RAM 提交控制等价；[128 APM 更名审计](../../log/i2s_parity/timingfix4_floorplan_remap_20261009.json)确认全部 176 site/BEL/order 不变，不含正式布局和时序 |
| 完整布局布线 | **布局完成，首轮布线超时 FAIL**；176 项原生位置约束已接受 | [本次构建记录](../../fpga/build/MEMS_Array_i2s_parity_timingfix4_20261009/manifest.json)及[正式构建独立审计](../../log/i2s_parity/physical_audit_timingfix4_20261009.json)；无完整布通数据库或最终时序报告，真实慢/快角 setup/hold、六个配置 CDC 同步 FF 及七个通道 FF 均未完成最终验证 |
| 最终发布与位流 | **全部布局对照候选均未发布、未生成** | 原候选及 D5 首轮未布通；Quad5 主动取消；Quad10 参数拒绝。不能据此认定 setup/hold 失败或通过 |
| JTAG SRAM 下载 | 未执行 | 器件 ID、DONE/INIT/PLL 状态及实际加载 SHA-256 |
| UART 配置 | 未测 | 0～127 请求/期望/实际一致，OFF、非法输入拒绝及复位重放 |
| 实际组零增益 | 未测 | 偶/奇各 64 路零值核对、另一组非零，最后恢复单位增益 |
| PHY / MDIO → ARP → UDP | 未测 | 内部 PDM BIST 与 PC 全 128 路黄金值、连续性、错误及丢包核对 |
| I2S BIST 内容 | 未测 | 全 128 通道非零内容、样本变化、欠载和错误增量；非单位配置下 BIST 旁路 |
| 恢复真实采集 | 未测 | 退出 BIST，恢复单位增益及监听配置，重新核对 DATA1/ch2、3 |

## 布局参数对照

本轮对照已结束。下表的计数来自各自最后一条完整原生日志，表示未布通连接与资源冲突；不同候选的迭代号不能作为完成百分比或预计耗时。

| 候选 | 实际终态 | 首轮最后记录 | 最终时序与位流 |
|---|---|---|---|
| 原候选 | 09:56:49.824 自然达到 180 分钟时限 | 第 45 轮：6,708 / 21,995 | 时序未知，无位流 |
| D5 | 10:57:25.349814 自然达到 180 分钟时限 | 第 58 轮：4,708 / 15,828 | 时序未知，无位流 |
| Quad10 | 10:10:41.082 参数拒绝退出 | 未启动完整路由 | 无最终时序，无位流 |
| Quad5 | 11:05:32.1344351 主动发送预算取消信号 | 第 27 轮：10,471 / 46,073 | 时序未知，无位流 |

以上时间均为 2026-10-09、UTC+08:00。布线未完成的终态统一为 `UNKNOWN_NOT_FULLY_ROUTED`，不是已测得的 setup/hold 违例。

原候选于 **09:56:49.824 +08:00** 自然达到 180 分钟路由时限，原生工具记录 `Flow-0232: Task has been killed as timeout`。最后完整记录为第 45 轮：6,708 条未完成连接、21,995 个资源冲突计数；构建进程退出 1，38 项构建输入仍匹配。没有首轮全布通结果、RTR、两角网表/SDF 或位流。该结果是布线超时，不能标为最终时序违例。

[独立布局诊断](../../log/i2s_parity/timingfix4_decong5_place_audit_20261009.json)仅将布局疏散参数从 3 改为 5，种子 2、Center 初始方式、176 个固定宏位置及全部冻结输入保持一致。参数 5 的最终估计连线长度从 1,168,458 降到 1,105,683，减少 5.37%；使用 CLM 增加 504。两者最终估计 slack/TNS 的原始摘要均为 `-376/-1880`，该摘要没有区分单位及慢/快角。

诊断仅运行布局，未运行布线、生成位流或下载；这些几何指标不能证明最终时序、布线速度或硬件验收通过。并行运行的耗时不用于单独归因布局参数。

随后启动了独立完整候选 `MEMS_Array_i2s_parity_timingfix4_d5_20261009`，从 compile 重新运行原构建流程及全部发布检查，不复用诊断设备映射或布局数据库。它与原候选使用相同冻结 RTL、约束、种子及初始方式，仅布局疏散参数为 5。[启动包装器](../../log/i2s_parity/launch_timingfix4_d5_full_build.py)在隔离目录运行原引脚生成逻辑，并逐字节确认与正式约束一致，避免写入原构建输入。

D5 的实际首轮路由于 **10:57:25.349814 +08:00** 自然达到 180 分钟动作时限，原生工具记录 `Flow-0232`；[独立构建记录](../../fpga/build/MEMS_Array_i2s_parity_timingfix4_d5_20261009/manifest.json)终态为 FAIL、输入未变。最后完整记录为第 58 轮：270.938 秒、4,708 条未布通连接及 15,828 个资源冲突。没有 RTR、完整布通 PNR 数据库、慢/快角网表/SDF、位流或发布结果。该候选的终态是 **`UNKNOWN_NOT_FULLY_ROUTED`**，不构成最终时序失败。

[D5 独立终态审计](../../log/i2s_parity/physical_audit_timingfix4_d5_20261009.json)已冻结，SHA-256 为 `db089dd3e412c2f5a45d3d8233513e95c6da39d58ce952c2610417c5597dc9de`。它重新核对 38 项构建输入、102 项回归输入及 9 项附加输入，保留已完成的技术与布局证明；[不可变技术布局快照](../../log/i2s_parity/physical_audit_timingfix4_d5_technology_final_20261009.json)未修改。缺少真实角输出，因此没有执行最终六个配置 CDC 同步 FF（三条双级链）和七个 UART 通道 FF 的物理角审计。

原候选真实失败退出、可用内存约 9 GiB 且进程核对通过后，**10:00:02.056 +08:00** 启动 `MEMS_Array_i2s_parity_timingfix4_quad10_20261009`。它从 compile 完整构建，使用相同已通过 18 项回归的 RTL、引脚和时序要求；布局为 Quad / 疏散 5 / 种子 2，路由请求 10 个线程、动作时限 180 分钟。[Quad10 包装器](../../log/i2s_parity/launch_timingfix4_quad10_full_build.py)保留实际 Tcl 修改及执行记录，全部原发布门禁保留，不复用旧数据库。

Quad10 的设备映射及布局于 **10:10:39.532 +08:00** 通过，176 个宏位置核对一致。随后本机工具报 `Flow-0186`，明确指出多线程路由的合法范围为 **1～5**，并报 `Flow-0075`；构建于 **10:10:41.082 +08:00** 退出 1。它没有启动完整路由，没有 RTR、布通数据库、双角网表/SDF 或位流。[构建记录](../../fpga/build/MEMS_Array_i2s_parity_timingfix4_quad10_20261009/manifest.json)与[独立终态审计](../../log/i2s_parity/physical_audit_timingfix4_quad10_20261009.json)保存真实失败，不能记作时序失败或下载通过。

独立候选 `MEMS_Array_i2s_parity_timingfix4_quad5_20261009` 于 **10:22:34.256 +08:00** 启动，保持 Quad / 疏散 5 / 种子 2，从 compile 完整开始，不添加线程覆盖参数。[启动包装器](../../log/i2s_parity/launch_timingfix4_quad5_full_build.py)已通过独立静态审查，启动时可用内存及两个已失败候选的原生进程退出均已核对。该候选的编译、综合、设备映射与布局均已通过，实际路由日志确认 `Route thread size: 5`；[独立映射审计](../../log/i2s_parity/physical_audit_timingfix4_quad5_map_final_20261009.json)通过。这些已完成阶段不计作最终时序、位流或硬件通过。

Quad5 原生路由于 **10:33:26.143 +08:00** 开始，观察预算设为路由开始后 **30 分钟，即 11:03:26.143 +08:00**；原生 180 分钟参数保持不变。首轮在观察截止后仍未布通，Root 核对实际进程身份后，于 **11:05:32.1344351 +08:00** 主动发送停止信号。[取消记录](../../fpga/build/MEMS_Array_i2s_parity_timingfix4_quad5_20261009/cancellation.json)保留最后第 27 轮：140.806 秒、10,471 条未布通连接及 46,073 个资源冲突。

[Quad5 构建记录](../../fpga/build/MEMS_Array_i2s_parity_timingfix4_quad5_20261009/manifest.json)于 **11:05:32.570878 +08:00** 记录 FAIL，`sources_unchanged=true`；本次退出由主动预算取消造成，不是自然超时或已测得的时序失败。没有 RTR、完整布通 PNR 数据库、两角网表/SDF 或位流，最终时序为 **`UNKNOWN_NOT_FULLY_ROUTED`**。[包装器终态记录](../../log/i2s_parity/timingfix4_quad5_wrapper_20261009/execute_20261009_102234_256419/metadata.json) SHA-256 为 `8326a5b0477ec290d416b57d8cf7d71db723ef0ea7843ff99cc42c2e4341c749`；取消记录 SHA-256 为 `d613b390da5bd7f96a85dc27343059f7a477a97896d43c7569476f028f42bbcf`。

[实际路由耗时对照](../../log/i2s_parity/observed_uartfix_vs_timingfix4_route_cost_20261009.json)显示，旧 UART 修复版首轮 74,341 条网络在 16 分 15 秒全部布通，但最终 setup 仍失败；原候选为 74,643 条网络，却在 180 分钟内未布通。同版本对照中时序、电气要求和主要路由参数一致，输入差异集中在 FIR、奇偶补偿及对应物理约束名称。此记录说明耗时明显变化，尚未证明具体根因，也不是隔离参数性能测试。

## local_lane 后续实现

[局部 lane 隔离测试结果](../../log/i2s_parity/parity_local_lane_candidate_20261009/result.json)通过后，Root 于 **11:08:46.209804 +08:00** 将该实现合入生产 RTL，[合入记录](../../log/i2s_parity/local_lane_merge_20261009/merge.json)确认仅修改 `rtl/pcm_parity_compensation.sv`。它将奇偶补偿的共享低 4 位索引改为每组同步的局部计数器，保留算术、标签、配置提交和 131 拍默认延迟。

合入后生产奇偶补偿 SHA-256 为 `93e929d98b01333d802edaccdb00c7b2c2cc09af8f16c610c3420552a4f8f48c`。新诊断 `MEMS_Array_i2s_parity_local_lane_map_20261009` 于 **11:10:00.143437 +08:00** 从 compile 启动至 dev_map，[实际构建记录](../../fpga/build/MEMS_Array_i2s_parity_local_lane_map_20261009/manifest.json)已生成。该诊断范围不含完整布局布线、位流或发布。

黄金测试 20,614 项通过，覆盖通道数 1～128；独立逐拍等价检查 2,054,959 项通过，覆盖 9 种通道数以及 792 次复位/禁用中断。独立只读审查通过。结果限于 RTL 功能，不是穷尽形式证明；32 个局部 FF 的实际独立保留、增加的控制负载及总体布线收益仍待厂商结果。

布局参数对照已经终止，local_lane 合入已经完成。新生产输入须重新取得实际设备映射、新鲜 18 项完整功能回归及独立发布证据；上述隔离测试和本报告历史 18/18 结果不能替代新输入的验证。

## 历史记录与物理边界

[timingfix3 报告](i2s_parity_timingfix3_20261009.md)记录前一候选的主动取消：首轮布线未完成，最终时序未知，无位流。[timingfix2 报告](i2s_parity_timingfix2_20261009.md)同样为主动取消；[第一版报告](i2s_parity_20261009.md)保留旧位流的实际下载和网络证据。

目标发布范围为 `engineering_board_bringup`。下列项目仍需实际测量：

- MEMS VDD 与 L6/L7 VCCIO 为 1.8 V；L5 I2S 为 3.3 V。
- 带载 PDM 时钟及真实采样窗口。
- DATA1 共用路径的 ch2、ch3 负满量程异常。
- PCM5102 实际模拟输出，以及全部 64 对麦克风的声学幅度、极性和时延。

数字零增益和内部 BIST 通过不能替代上述物理验收。当前没有安装基于已知共同声场测得的奇偶补偿系数。
