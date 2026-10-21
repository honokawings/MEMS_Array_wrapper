# 位流发布检查

[文档索引](../../doc/README.md) · [构建操作](../../doc/board_bringup.md#构建与发布复现) · [历史八路 CLK 发布报告](../../doc/reports/clk8_18v_update.md)

`check_release.py` 核对实际构建、功能回归及原始时序证据，适配本机 PDS 2022.2-SP6.4。未知格式、缺项或未审阅诊断返回非零状态。发布范围为 `engineering_board_bringup`，供工程上板联调，不表示板级电气或声学验收已完成。测试中合成的报告仅验证检查器，不作为器件时序证据。

## 当前候选与历史证据

核对日期：2026-10-09。当前候选为 **`MEMS_Array_i2s_parity_timingfix4_20261009`**，完整顶层为 **103 个端口**。新鲜 18 层完整回归与独立临时映射审计已通过。正式构建已完成编译、综合、器件映射及176个原生宏位置接受，布局数据库身份已核对，当前首轮布线进行中；最终双角时序及位流尚未产生。补偿 bank_sample 与 FIR write_data 每拍读取，保留 bank 同步清除、valid/tag/gain 以及 RAM 提交控制。新临时网表实际保留256个 bank FF与1024个 FIR 数据暂存 FF，均无CE端口；额外空闲/复位数据仅刷新暂存，不提交 RAM。结构核验不能证明布线减速根因或最终时序改善。

第一版 `MEMS_Array_i2s_parity_20261009` 曾取得物理发布 PASS 并完成 JTAG 下载，但实板 UART 通道命令失败：选择1/127仍为0，128也未被拒绝，实际网表缺少七位 `desired_channel` 寄存器。UART 修复构建通过17层功能回归，正式时序仍失败。首个时序修正版因旧布局宏名称失效而失败；timingfix2 已接受重映射的176个宏位置，但首轮布线因持续减速被主动取消，时序结论为UNKNOWN，不能称为时序FAIL。这些历史结果均不能代替当前候选的完整物理发布证据。

| 验证 | 当前证据与范围 |
|---|---|
| 功能回归 | 当前候选[完整回归快照](../../log/i2s_parity/full_regression_timingfix4_20261009.json)为 18/18 PASS，包含独立 `fir_ram` 与 `vendor_uart`，重新生成数值/厂商模型；[历史 UART 修复版完整回归](../../log/i2s_parity/full_regression_uartfix_20261009.json)为 17/17 PASS，单独保留 |
| UART 技术网表 | 历史 17 层回归中的实际门级结果为 PASS：24.453 秒、128 通道、七位均可翻转、55,197 检查；原结果和输入保存在[失败构建源归档](../../log/i2s_parity/uartfix_before_timing_pipeline_20261009.zip)。无 SDF、未验证小工程布线时序；新候选重新执行 |
| 发布检查器自检 | RAM 实际证据绑定后，214/214 PASS，14.188 秒；[最新完整原始日志](../../log/i2s_parity/timingfix_fir_ram_strict_rows_checker_tests.log)已保存。[190 项步骤门禁日志](../../log/i2s_parity/timingfix_checker_all_tests.log)、[188 项 V_BUF 修正日志](../../log/i2s_parity/uartfix_vbuf_checker_all_tests.log)和[186 项日志](../../log/i2s_parity/uartfix_checker_tests.log)保留为历史证据 |
| 第一版物理发布 | [历史 release.json](../build/MEMS_Array_i2s_parity_20261009/release.json)为工程物理 PASS，实板 UART 为 FAIL；[原检查器快照](../../log/i2s_parity/first_release_audit_scripts/snapshot.json)逐项匹配该发布 SHA，不用新检查器改写历史 |
| 历史 UART 修复版物理检查 | [独立失败构建审计](../../log/i2s_parity/physical_audit_uartfix_20261009.json)：慢快角六 CDC FF 与七通道 FF 均保留且正确连接；正式慢角 audio122 setup −0.067 ns、4 个失败端点，系统时序 FAIL、生成前门禁拒绝、没有位流 |
| 历史首个时序修正版 | [技术网表审计](../../log/i2s_parity/physical_audit_timingfix_20261009.json)逐位核对补偿分组 FF、FIR 写数据 FF、MUX 来源、APM/RAM 消费者和音频 CK；仅证明实际技术网表边界，布局实例名称失配使该构建 FAIL，无布线时序或位流 |
| 历史 timingfix2 取消候选 | [独立审计](../../log/i2s_parity/physical_audit_timingfix2_20261009.json)保留新映射与176原生位置PASS；[取消记录](../build/MEMS_Array_i2s_parity_timingfix2_20261009/cancellation.json)明确首轮未完成、时序UNKNOWN。107输入、483日志、24向量的[归档清单](../../log/i2s_parity/timingfix2_archive_before_bank_enable_20261009.json)已独立核验，没有正式双角或位流 |
| 历史 timingfix3 取消候选 | [独立审计](../../log/i2s_parity/physical_audit_timingfix3_20261009.json)保留新映射边界和176原生位置PASS；[取消归档](../../log/i2s_parity/timingfix3_archive_before_fir_enable_20261009.json)的107输入、483日志、24向量独立核验PASS。首轮未完成即主动取消，时序UNKNOWN；Flow-0189来自该次主动停止，没有正式双角或位流 |
| 当前临时技术网表 | [不可变最终审计](../../log/i2s_parity/physical_audit_timingfix4_map_final_20261009.json)重新逐位核对256个变量 bank FF与1024个 FIR 数据 FF，有效CE均为1；FIR1为272变量+240源证明零位，FIR2为512变量。暂存Q到RAM/APM、提交valid/address/last、实际RAM写门控/地址及新旧跨层capture_input/input_hold均核对PASS。128个APM名称按真实P/X/Y角色重映射、48RAM名保持，全部176位置/BEL/顺序及其余字节不变；[重映射报告](../../log/i2s_parity/timingfix4_floorplan_remap_20261009.json)另行保存。临时dev_map不包含原生place接受或布线时序；正式构建须重新核验 |
| 当前正式技术网表 | [正式4技术与布局不可变快照](../../log/i2s_parity/physical_audit_timingfix4_technology_final_20261009.json)从本次正式VM重新逐位核对256+1024暂存FF、CE=1、复位、数据消费者、capture/input_hold与RAM提交控制；176宏的真实lane/乘法角色与实际PCF精确绑定，原生日志176条唯一位置接受、无错误。器件映射、结构与布局数据库身份通过；首轮完整布线、正式双角时序及位流仍待完成 |
| 当前物理发布 | 待新同次构建完整双角时序、SDF/网表、七个通道 FF、位流及最终发布检查；功能或 FF 结构通过不能代替此项 |

历史构建 `MEMS_Array_uart_clk8_18v_spread3_long` 于 2026-09-20 完成常规完整流程，记录为 `status=PASS`、`release_authorized=true`。它的 **99 端口、12/12 功能回归、146/146 检查器测试**仅描述旧版，不包含本次 I2S/奇偶补偿。来源见[历史发布报告](../../doc/reports/clk8_18v_update.md)和[历史 146 项原始日志](../../log/system_uart/clk8_checker_tests.log)。

## 常规构建流程

`build.py --stage gen_bit_stream` 自动调度以下阶段；推荐参数见[上板指南](../../doc/board_bringup.md#构建与发布复现)。

1. 编译、综合、器件映射成功后，保存原始物理 PCF，追加经审查的 128 个 FIR APM 与 48 个历史 RAM 位置约束。
2. 独立执行 place；复制并记录布局数据库 SHA-256，PNR 从该布局输入开始，随后生成正式双角时序报告。
3. 从同一个布线数据库分别导出慢角和快角 SDF/网表，保存到 `clock_audit/`。
4. 运行生成前检查；退出码为 0 后，才从受审计的同一布线数据库生成位流。
5. 核对原生日志完成状态、数据库和源文件未变，写入最终 manifest，再进行生成后发布检查。

常规构建应有六个独立 PDS 进程记录：compile/map、place、route/timing、slow 导出、fast 导出、bitstream。六个主阶段 `compile/synthesize/dev_map/pnr/report_timing/gen_bit_stream` 之外，显式 place 也有独立完成证据。

PDS 会提前解析 Tcl 内的 `puts`、`file copy` 和 `exec`。完成标记、复制证据和发布检查由外层 Python 在进程结束后执行，避免把排队命令误当作已完成。文件存在或 GUI 显示完成不能单独授权发布。

## 独立复查

以下以当前候选目录为示例，**只在该构建已有完整实际证据后执行**。构建中的候选不能据此提前发布。输出写入新审计目录，保留原始发布记录；命令不负责补齐缺失的实现阶段。

```powershell
$build = 'fpga/build/MEMS_Array_i2s_parity_timingfix4_20261009'
$audit = 'log/release_review_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
New-Item -ItemType Directory -Path $audit | Out-Null
python fpga/scripts/check_release.py --manifest "$build/manifest.json" --regression log/full_regression.json --timing-report "$build/report_timing/mems_array_pg2l200h.rtr" --constraints-report "$build/constraint_check/constraint_check.ccr" --map-report "$build/device_map/mems_array_pg2l200h.dmr" --bitstream "$build/generate_bitstream/mems_array_pg2l200h.sbit" --bin "$build/generate_bitstream/mems_array_pg2l200h.bin" --output "$audit/release.json"
```

生成前检查用 `--pre-bit`，不传位流参数；此阶段允许 RUNNING manifest，`release_authorized` 固定为 false。最终发布要求 manifest 为 PASS、`sources_unchanged=true`、位流阶段成功，且源文件/数据库与生成前一致。

默认读取同构建目录的 `build.log`、RTR 同目录的 `run.log` / `rtr.db`，以及 `clock_audit/` 的双角证据。可显式指定报告/网表路径，但所有输入必须绑定同次构建。检查器重新执行 **PDM、TX、I2S 三项物理时序审计**和 **UART 厂商门级证据/双角寄存器审计**，记录原始输入和执行脚本 SHA-256，不接受外部提供的“预算 PASS” JSON。

## 核对内容

| 类别 | 要求 |
|---|---|
| 功能回归 | 18 项完整模型/RTL/主机/厂商结果通过；`fir_ram` 与 `vendor_uart` 均为独立必检项，不能用 FIR 算术 PASS 替代 RAM 流程；两项实际结果路径与 SHA 绑定完整回归；受测源文件、RAM 参考系数和向量与当前文件一致 |
| PLL | 厂商参数校验通过；旧 PFD=125 MHz/OPTIMIZED 作为负例被拒绝；实际以太网 PLL 为 I=4、M=16、F=2、O=4、OPTIMIZED |
| 构建链 | 从 compile 开始；原生日志成功事件、脚本、完成标记及 map/place/route 数据库身份一致 |
| 宏位置 | 原始 PCF 加精确源模板；176 个宏的位置被实际接受，并核对功能身份；不能用位置数相同替代绑定关系 |
| 引脚与电气 | 103 个端口方向、封装、电压和 I/O 标准一致；8 路 MEMS CLK 为 LVCMOS18、16 mA、FAST，64 根 DATA 为 LVCMOS18；四根 I2S 输出为 L5、3.3 V、LVCMOS33、8 mA、FAST |
| 双角时序 | 慢角/快角 setup、hold、recovery、removal、最小脉宽摘要完整、无违例；关键域和 CDC 路径覆盖齐全 |
| 时钟 | 12 个声明/生成/虚拟时钟的周期、相位及来源匹配；无新增未知时钟；八路 CLK 物理网表同源 |
| RGMII | 六个 TX 端点、双沿、双角、最大/最小路径完整；扣除公共项后的物理偏差 ≤0.300 ns；实际可达边沿名义占空比 45%～55% |
| PDM | 64 根 DATA 输入与8路时钟输出均覆盖；100 ns 器件延迟 +20 ns 外部传播、时钟输出上限 4 ns、实际输入路径及不确定度小于 138.346 ns 采样窗口 |
| I2S | 慢角/快角独立追踪四个真实寄存器到焊盘路径及同源音频时钟；SCK/BCK 路径分别 ≤4 ns，DIN/LRCK 分别 ≤20 ns；独立计算建立、保持和时钟脉宽裕量 |
| 音频配置 CDC | 56 位配置保持总线、请求/确认握手及两级同步器源合同受审；sys27↔audio122 全域双向 7.500 ns 上限与两角实际覆盖必须保留 |
| UART 厂商路径 | 真实 compile/synthesize/dev_map 与未修改 GTP 技术网表仿真；128 通道、128/999 拒绝、非法数字、OFF 与增益边界均通过；最终双角实际七个正沿通道 FF 保留且源于物理 sys27 时钟 |
| 完整性 | 源文件、向量、检查器、报告、数据库及位流 SHA-256 记录并复核；禁止混用不同构建证据 |

## I2S 物理预算

`check_i2s_budget.py` 从同次布线的慢角和快角网表/SDF分别重建输出路径，核对实际正沿寄存器、时钟树和焊盘连接，不依赖作者指定的内部实例名断言同源。四根端口位置必须从 README 的 J10 标签精确解析，缺少标签、重复标签/物理引脚或不属于已审阅 L5 均拒绝。

| 端口 | 引脚 | 电气 | 每角 FF→焊盘路径上限 |
|---|---|---|---|
| `i2s_sck` | R21 | LVCMOS33，3.3 V，8 mA，FAST | 4 ns |
| `i2s_bck` | N19 | LVCMOS33，3.3 V，8 mA，FAST | 4 ns |
| `i2s_din` | M25 | LVCMOS33，3.3 V，8 mA，FAST | 20 ns |
| `i2s_lrck` | T25 | LVCMOS33，3.3 V，8 mA，FAST | 20 ns |

122.88 MHz 音频域采用时钟使能生成输出：SCK 周期 10 个音频周期，BCK 为 40 个，LRCK 为 2560 个。DIN/LRCK 仅在 BCK 下降时改变，20 个音频周期后由 DAC 在 BCK 上升时采样。源码边沿/分频合同、两角物理输出路径和接收裕量分别受检；系统仍为原有 **12 个时钟对象**，没有新增内部 BCK/SCK 时钟或 multicycle 例外。

原版 [TI PCM5102 数据手册](https://www.ti.com/lit/ds/symlink/pcm5102.pdf)第 13 页给出 DIN/LRCK 8 ns 最低建立/保持要求；本项目统一采用更保守的 **20 ns 建立与保持要求**。预算另外扣除 **20 ns 外部相对布线/边沿延迟**、**0.300 ns 不确定度**及报告舍入保护，并核验 SCK/BCK 最小脉宽。任何一个角、端口或裕量缺失、非有限或不合格均拒绝。20 ns 外部预算及 DAC 实际波形仍需实测。

## 56 位配置与同步器证据

`check_audio_config_cdc` 受审内容包括完整 56 位 `held` 数据、等待确认期间保持、请求/确认各两级传递、复位后重发以及实际板级时钟接线。现有 sys27→audio122 和 audio122→sys27 **全域 7.500 ns datapath-only** 预算覆盖全部保持数据和请求/确认首级输入，不增加端点例外，也不放宽为一个音频周期。两方向均要求慢角和快角有成功物理时序覆盖，结果及源文件 SHA-256 写入 `audio_configuration_cdc`。

`alive_meta/alive_sync` 是监督域的两级桥复位释放链。源码声明了 `async_reg` 和 `syn_preserve`；实际 PDS 日志明确忽略 `async_reg`，并将 `syn_preserve` 转为 `PAP_PRESERVE`。因此，源码链路审计不能表述为厂商物理同步器标记已生效。第一版慢/快实际网表已追踪 `request_meta/request_sync`、`ack_meta/ack_sync`、`alive_meta/alive_sync` 六个 FF，均保留两级、正确连接及 CK 来源，见[历史物理审计](../../log/i2s_parity/physical_audit.json)。后续[失败 UART 修复版审计](../../log/i2s_parity/physical_audit_uartfix_20261009.json)也独立核实两角六 FF，但系统时序失败；该结果明确绑定归档源。当前时序修正版仍须用新导出网表复核，不能继承旧实例证据。

## FIR RAM 流程必检

`fir_ram` 是独立于 `fir_arithmetic` 的第 18 项强制功能回归。入口为 `python sim/fir/run_ram_pipeline.py`，[实际结果](../../log/fir_ram/result.json)与[vlog](../../log/fir_ram/vlog.log)、[vsim](../../log/fir_ram/vsim.log)原始日志保存到 `log/fir_ram/`。专项实际四配置已通过 5,597,580 项检查；这不单独表示 18 层完整回归或 FPGA 时序已通过。

完整回归的 `fir_ram.evidence` 必须精确绑定 `log/fir_ram/result.json` 及当前 SHA。结果 scope 固定为 `fir_history_ram_pipeline_functional`。发布检查器另外核对七个输入的当前哈希：FIR RTL、两份 RTL 系数头、RAM TB、runner、两份 `lib/coeff/fir*_q30.hex`；后两项独立参考系数必须与结果的 reference 哈希一致。三份实际 ModelSim 程序、原始 vlog/vsim 和 modelsim.ini 也受哈希检查。全部输入在发布检查末尾再次核对，防止检查途中系数变化。

检查器重新解析原始日志四配置，要求 JSON 计数精确一致、明确完成且无错误/警告；未知字段或缺失原始行拒绝。固定参数为生产 128 通道/16 lanes/8 groups 与单通道/1 lane/1 group，分别使用 FIR1 的 63 taps/128 depth/4 倍抽取及 FIR2 的 127 taps/256 depth/2 倍抽取。每配置须有实际 RAM 读写与完整卷积输出、至少两次回绕、并发读写、四个复位边界、最终提交与新帧同拍、两类调度故障及输入总线变化覆盖。该结果属于 RTL 功能仿真，明确未做 PNR/SDF。缺证据、输入或日志哈希变化、覆盖不足均拒绝；原算术测试、历史 17 层结果和合成夹具不能替代。

## UART 厂商门级与最终寄存器

`python sim/audio/run_vendor_uart.py` 每次从当前 UART 源重新执行 PDS compile/synthesize/dev_map，使用真实生成的 `uart_audio_control_syn.vm` 和安装目录中的 GTP/INT 原语运行 ModelSim。仿真不编译被测 RTL，也不使用自建行为模型代替厂商原语。它逐一检查 0～127、七位零/一翻转、128/999 拒绝、非法数字/legacy 隔离、007、OFF、非单位增益与增益范围。原始工具日志、源、TB、runner、自动生成 Tcl、映射数据库、技术网表、工具可执行文件及递归模型依赖均保留 SHA。

该步骤属于技术网表功能验证，未做小工程 PNR 或 SDF 时序仿真。PDS 拒绝从 MAP 数据库执行 `gen_netlist` 的原始实验日志保留在[失败实验日志](../../log/vendor_uart/pds_export.log)，正常强制 runner 不再请求这一步，也不将拒绝动作记为成功。

`check_uart_vendor.py` 重新验证全部实际证据及哈希，核对完整回归绑定的 `result.json`，并独立读取本次完整板级慢/快网表。七个 `desired_channel` FF 必须独立保留、D 可变、CE 可用、Q 有实际消费者；两角实例/连接相同。它从实际 FF CK 反追未门控 BUF_A、缓冲和 sys_clk_27 输入，拒绝常量折叠、缺位、合并、错时钟及未知极性。第一版缺七 FF 已作为真实拒绝负例核实。此项和三项时序审计共同决定新位流能否发布。

监督 CK 的实际中间原语为 `V_BUF(Z,I)`；输入缓冲为 `V_IBUF(O,I)`。检查器曾把 V_BUF 输出误写为 O，错误也被合成夹具复制；已依据真实网表和厂商模型改为 Z，并增加错误端口/断开输入的拒绝用例。修正没有改变七 FF、物理时钟来源、双角一致性或任何时序上限。原因、修前快照、实际端口与哈希见[检查器修正证据](../../log/i2s_parity/uartfix_vbuf_checker_correction.json)。RTL、约束、构建配方及 17 层回归输入均未改变。

## 时序解释与已审阅提示

- 原始 CCR 不得有错误、普通警告或零匹配对象；配置复用管脚提示仅允许与实际映射一致的条目。
- RTR 的时钟表和双角摘要必须与原始 `rtr.db` 一致。文本 `All Constraints Met` 不能代替 XML 路径检查。
- `report_timing` 不允许裁剪掉必要路径的选项。独立报告可用 `-force_to_run` 和 `-input_db_file`，但输入数据库必须精确绑定当前受审计的路由数据库。
- 27/122.88 MHz 比值 1024/225 超过 PDS 的 1000 周期相位展开范围；只审阅这一已知提示，并检查双向 7.5 ns CDC 物理上界及相应 hold 例外，其他未知时钟对仍拒绝。
- `mic_clk[0]` 是生成时钟定义端口，全部 `mic_clk[*]` 受 4 ns 物理上限约束；PHY0_MDC 另受 7.5 ns 上限约束。不能只检查一个 CLK 引脚而忽略其余七路。
- PDM 零参考输入组含 64 根 DATA 与 KEY1，共 65 个端点；同时独立追踪全部 64 个捕获寄存器，按报告最小裕量计算保守输入上界。
- 当前器件模型对 GPLL RST、LOCK 及专用分频器 CLR_N 产生的已知非数据端点提示，仅在对象、级别、约束路径、行号和原命令完全匹配时审阅；不放行其他空例外、错误或 Internal 异常。
- TX 的 datapath-only 最大延迟替代普通虚拟 setup 关系；最小物理路径由 XML 与专用检查覆盖，不能宣称普通 TX hold 仍在检查。

## 发布范围与恢复流程

原始时序模型如实记录为 Pre-silicon。名义时序、偏斜或名义占空比失败会拒绝工程发布。厂商 180 ps 抖动参数未明确统计口径，按逐沿 ±180 ps 计算的额外敏感性分析仍保留原 FAIL；它不是实测，也不单独阻止工程联调发布。`qualification.unconditional_board_qualification=false`，实际 TXC、PCB 偏斜和麦克风带载波形待测。详细依据见[TX 源端说明](TX_SOURCE_CHECK.md)。

`finalize_route_checkpoint.py` 可选择已完成且证据完整的路由检查点，再重新导出时序、SDF/网表并执行原有检查。它不能把未完成路由或改写日志当成成功。历史 `_spread5` 使用了该流程；历史 `_spread3_long` 为常规完整流程，两者均不代表新候选已发布。历史格式继续受对应证据核查，见[版本历史](../../doc/reports/version_history.md)。

检查器自检命令：`python -m unittest discover -s fpga/scripts/tests -v`。当前 214 项包括原有电气、数据库、路由完成、恢复清单、源文件变化、I2S/CDC 拒绝用例、UART 原始日志/源/网表/工具库哈希、七 FF 常量/合并/极性/时钟、双角一致性、V_BUF 实际接口，以及 RAM 步骤与实际证据拒绝用例。最新完整结果为 214/214 PASS，原始输出见[214 项日志](../../log/i2s_parity/timingfix_fir_ram_strict_rows_checker_tests.log)。RAM 原日志/计数、缺配置、回绕/复位/并发/故障覆盖、参考系数变化、工具/配置哈希及检查中修改均有负例。[190 项版本快照](../../log/i2s_parity/fir_ram_evidence_checker_before/snapshot.json)、历史 188/186 项日志、第一版 166 项实际执行输出（未独立落日志）及历史 146 项日志继续保留，不混用这些计数。
