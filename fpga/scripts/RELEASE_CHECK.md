# 位流发布检查

`check_release.py` 只读取实际构建和回归证据。适配 PDS 2022.2-SP6.4 的原始 CCR、DMR、RTR 与运行日志；未知格式、缺项或未审阅诊断均返回非零状态。发布范围固定为 `engineering_board_bringup`，即供上板验证的工程位流，不表示未经实测的整板全 PVT 认证。脚本自检中的合成报告只用于验证解析器，不能作为本工程时序通过的证据。

正常构建由 `python fpga/scripts/build.py --stage gen_bit_stream` 自动完成以下调度：

1. 主 PDS 进程执行 compile、synthesize、dev_map、pnr 和 report_timing。Python 等待进程成功退出并逐项核对原始 `Executing : ... successfully.`，才写入五个完成标记。
2. Python 启动两个独立 PDS 进程，从同一 `place_route/mems_array_pg2l200h_pnr.adf` 分别导出慢角和快角 SDF/网表，记录脚本及布线数据库 SHA，再复制到 `clock_audit`。
3. Python 调用预检查。退出码为 0 后，才启动独立位流生成进程，显式使用同一布线数据库。
4. Python 核对位流阶段真实成功、数据库和硬件源未变，写入最终 manifest，再运行最终发布检查。

PDS 会提前解析 Tcl 中的 `puts`、`file copy` 和 `exec`，因此不能在排队的构建 Tcl 内用这些命令安排完成标记、复制证据或执行门禁。上述工作由外层 Python 在 PDS 进程结束后执行。预检查的独立命令如下，仅用于已有完整本次证据时复查：

```powershell
python fpga/scripts/check_release.py --pre-bit --manifest fpga/build/MEMS_Array/manifest.json --regression log/full_regression.json --timing-report fpga/build/MEMS_Array/report_timing/mems_array_pg2l200h.rtr --constraints-report fpga/build/MEMS_Array/constraint_check/constraint_check.ccr --map-report fpga/build/MEMS_Array/device_map/mems_array_pg2l200h.dmr --output fpga/build/MEMS_Array/pre_bit_check.json
```

预检查允许 `RUNNING` manifest，独立比较起始清单与当前全部 RTL、系数头、约束及构建脚本的 SHA-256，要求本轮前五个阶段依次完成。只有退出码为 0 才继续 `gen_bit_stream`。预检查结果中的 `release_authorized` 固定为 `false`，不能发布位流。

PDS 全流程成功且 manifest 写入 `PASS`、`sources_unchanged=true` 和完成时间后，去掉 `--pre-bit`，增加以下参数再次检查：

```text
--bitstream fpga/build/MEMS_Array/generate_bitstream/mems_array_pg2l200h.sbit
--bin fpga/build/MEMS_Array/generate_bitstream/mems_array_pg2l200h.bin
--output fpga/build/MEMS_Array/release.json
```

`.bin` 为可选产物。PDS 的“Create Bit File”实际生成 `.sbit`。默认读取 RTR 同目录 `run.log`、`rtr.db` 和 manifest 同目录 `build.log`，也可用 `--timing-log`、`--report-db`、`--build-log` 指定。

两种模式都会从原始物理证据重新执行 `check_pdm_budget.py` 和 `check_tx_source.py`。默认要求本次构建目录中的 `clock_audit/slow_sta.sdf`、`slow_sim.v`、`fast_sta.sdf`、`fast_sim.v`；可用 `--slow-sdf`、`--slow-netlist`、`--fast-sdf`、`--fast-netlist` 指定同构建内的文件。它们必须来自布线完成后的两角导出。门禁不接受外部提供的“预算 PASS” JSON；每次用独立临时目录运行检查，核对退出码、结果、输入 SHA 和 helper SHA，结果全文及原始输出 JSON 哈希嵌入最终 `physical` 字段。

检查范围：

- 完整模型及厂商原语回归的十项结果全部 PASS；当前 RTL、测试、模型、脚本及参考向量与回归 SHA-256 一致。
- 构建从 compile 开始，最终六阶段按序完成。原生日志的真实成功记录及完成标记均须各出现一次，且每个成功记录先于对应标记。所有产物的修改时间和原始报告日期属于本次构建，禁止拿旧报告或旧位流冒充结果。
- `flow_evidence` 记录主进程、慢角导出、快角导出和最终位流进程的脚本、SHA、退出码及完成时间；预检查只允许前三项。两次导出和位流的脚本及原始成功命令都必须显式指向同一个已核对 SHA 的布线数据库。审计结束前再次复核所有脚本和数据库。
- CCR 无错误、普通警告或零匹配对象；通配表达式覆盖当前 FDC，列出的对象数量一致。仅允许与实际管脚映射一致的 `ConstraintEditor-2002` 配置复用管脚提示。
- DMR 内的时序约束与当前 FDC 完全一致；87 个端口的方向、封装管脚、电压和 I/O 标准完全匹配。
- RTR 明确为 multi corner 且 All Constraints Met；慢、快角各五类摘要均有真实数值，裕量非负、失败端点为零。关键时钟路径、四个方向的 CDC 上界以及 RGMII 数据和控制端点必须存在。
- `timing.timing_models` 如实记录原始报告的 `Pre-silicon` 或 `Production` 标签；本安装的 PG2L200H 报告使用 `Pre-silicon`，门禁不会改称 Production。`report_timing` 仅允许已核验的 `-delay_type min_max`、`-report_io_datasheet`、`-report_max_skew`、`-report_exception TRUE`、正整数 `-max_path`/`-nworst`；具体命令与选项同时记入结果。标签或命令选项不替代双角数值覆盖检查。
- 预期 12 个时钟的周期、相位、来源及生成关系逐项匹配；包括 `ref125 → eth250 → eth125` 的 PLL 倍频及单上升沿二分频。外部参考虚拟时钟允许无物理源，其余关键时钟必须有负载。新增时钟必须根据实际实现更新明确清单，未知时钟不会自动放行。仅对 PDS 已观察到的级联生成时钟边沿量化设置 2 ps / 50 ps 容差，时序裕量不放宽。
- 原始 `rtr.db` 的时钟表、双角五类摘要必须与文本 RTR 完全一致。`check_timing_summary` 必须完整，无未审阅非零问题。零参考 min=max I/O 等值提示必须从当前 FDC 机械确认，反向边界仍拒绝。PDS 对三只虚拟参考时钟报告“未引用”时，检查器逐个要求真实虚拟时钟声明、min/max I/O 约束及两个角上对应 5/6/64/1 个真实成功端点，不能只按时钟名称忽略提示。两个生成时钟输出 `mic_clk[0]`、`PHY0_MDC` 不设置普通 output delay，须分别具有准确的生成时钟来源及 4.000/7.500 ns 物理路径上限；任何其它缺少 output delay 的端口均拒绝。上述原始提示与逐项审阅结果写入发布清单。
- TX 预算要求六个物理端点包括 TXC、双沿、双角和 min/max 原始路径；原始 MaxSkew 0.400 ns 不能单独授权，helper 必须核对共同抖动项并证实物理偏斜 ≤0.300 ns。两角 SDF 和网表还须证明实际可达边沿的名义占空比为 45%～55%。TX 的 datapath-only 最大延迟只在 Setup 摘要中出现，其最小路径由同次 XML 独立检查；其它普通功能时序不允许负裕量。
- 厂商 TOUTJIT 180 ps 未说明统计口径，不能自行等同于峰值、峰峰值或 RMS。把它解释为逐沿 ±180 ps 的额外敏感性分析完整保存在 `physical.results.tx.duty.conservative_jitter_sensitivity`，其中原有 FAIL 和各场景不改写；该附加假设不替代厂商模型，也不单独阻止工程上板位流。名义模型失败、已知时序/偏斜违规仍拒绝发布。`qualification` 明确记录板级资格未确认、实际 TXC 占空比/抖动待测，以及基于该次名义 DCD 的最大允许边沿对抖动预算。
- PDM 预算必须包含两角布线 SDF 的共享时钟分支、全部 64 根输入、报告中的实际输入裕量和保守不利时钟分支。外部 120 ns、时钟输出 4 ns、输入路径和报告中的不确定度相加，须严格小于有效采样区间 138.346 ns。检查器同时核对实际 RTL 的 CLOCK_DIV=40、SAMPLE_TICK=19、两级输入寄存器及实例未覆盖参数，防止预算和代码漂移。
- 时序运行日志不得存在未审阅 E/C/W 诊断。当前 PG2L200H 模型不把三个 GPLL 的 RST 和专用分频器 CLR_N 当作数据时序端点，会对一条冗余复位例外报告四个 STA-3006 和一个 STA-3015；只允许完整、唯一的这组提示，并逐项验证实际对象、严重级别、FDC 绝对路径、行号及该行精确命令。功能 FF 的清零端点和其它空例外不在豁免范围。原始提示保存在 `timing.reviewed_clock_reset_diagnostics`；任何 E 诊断和 `Internal-*` 异常仍拒绝。
- 最终记录源文件、报告、回归清单、检查器、`.sbit` 和可选 `.bin` 的 SHA-256；检查结束前复核，阻止并行修改造成证据混用。`audit_scripts` 独立记录实际执行的主检查器和两个 helper 在审计开始时的 SHA，并在结束时再次核对。构建清单固定记录硬件源、约束和 `build.py`；审计程序可在长构建后完成，但其被执行版本必须明确且执行期间不变。

运行门禁自检：`python -m unittest discover -s fpga/scripts/tests -v`。

PASS 表示本地构建证据一致且通过上述工程模型范围的功能和时序检查。`unconditional_board_qualification` 始终为 `false`；板卡电压、麦克风负载、PHY 实际边沿/抖动和长期采集仍须实测验收，敏感性分析失败不能在交付时隐藏。
