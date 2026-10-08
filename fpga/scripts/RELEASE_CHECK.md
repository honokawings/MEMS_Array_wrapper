# 位流发布检查

[文档索引](../../doc/README.md) · [构建操作](../../doc/board_bringup.md#构建与发布复现) · [当前发布报告](../../doc/reports/clk8_18v_update.md)

`check_release.py` 核对实际构建、功能回归及原始时序证据，适配本机 PDS 2022.2-SP6.4。未知格式、缺项或未审阅诊断返回非零状态。发布范围为 `engineering_board_bringup`，供工程上板联调，不表示板级电气或声学验收已完成。测试中合成的报告仅验证检查器，不作为器件时序证据。

## 当前推荐版本

构建 `MEMS_Array_uart_clk8_18v_spread3_long` 于 2026-09-20 完成常规完整流程，最终 `status=PASS`、`release_authorized=true`。完整顶层为 **99 个端口**，其中 64 根 PDM DATA、8 路 CLK；本次功能回归 12/12、检查器测试 146/146，通过范围见[发布报告](../../doc/reports/clk8_18v_update.md)。

## 常规构建流程

`build.py --stage gen_bit_stream` 自动调度以下阶段；推荐参数见[上板指南](../../doc/board_bringup.md#构建与发布复现)。

1. 编译、综合、器件映射成功后，保存原始物理 PCF，追加经审查的 128 个 FIR APM 与 48 个历史 RAM 位置约束。
2. 独立执行 place；复制并记录布局数据库 SHA-256，PNR 从该布局输入开始，随后生成正式双角时序报告。
3. 从同一个布线数据库分别导出慢角和快角 SDF/网表，保存到 `clock_audit/`。
4. 运行生成前检查；退出码为 0 后，才从受审计的同一布线数据库生成位流。
5. 核对原生日志完成状态、数据库和源文件未变，写入最终 manifest，再进行生成后发布检查。

推荐构建有六个独立 PDS 进程记录：compile/map、place、route/timing、slow 导出、fast 导出、bitstream。六个主阶段 `compile/synthesize/dev_map/pnr/report_timing/gen_bit_stream` 之外，显式 place 也有独立完成证据。

PDS 会提前解析 Tcl 内的 `puts`、`file copy` 和 `exec`。完成标记、复制证据和发布检查由外层 Python 在进程结束后执行，避免把排队命令误当作已完成。文件存在或 GUI 显示完成不能单独授权发布。

## 独立复查

以下只用于已有完整证据的构建。输出写入新审计目录，保留原始发布记录；它不负责补齐缺失的实现阶段。

```powershell
$build = 'fpga/build/MEMS_Array_uart_clk8_18v_spread3_long'
$audit = 'log/release_review_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
New-Item -ItemType Directory -Path $audit | Out-Null
python fpga/scripts/check_release.py --manifest "$build/manifest.json" --regression log/full_regression.json --timing-report "$build/report_timing/mems_array_pg2l200h.rtr" --constraints-report "$build/constraint_check/constraint_check.ccr" --map-report "$build/device_map/mems_array_pg2l200h.dmr" --bitstream "$build/generate_bitstream/mems_array_pg2l200h.sbit" --bin "$build/generate_bitstream/mems_array_pg2l200h.bin" --output "$audit/release.json"
```

生成前检查用 `--pre-bit`，不传位流参数；此阶段允许 RUNNING manifest，`release_authorized` 固定为 false。最终发布要求 manifest 为 PASS、`sources_unchanged=true`、位流阶段成功，且源文件/数据库与生成前一致。

默认读取同构建目录的 `build.log`、RTR 同目录的 `run.log` / `rtr.db`，以及 `clock_audit/` 的双角证据。可显式指定报告/网表路径，但所有输入必须绑定同次构建。检查器会重新运行 PDM 与 TX 物理预算检查，不接受外部提供的“预算 PASS” JSON。

## 核对内容

| 类别 | 要求 |
|---|---|
| 功能回归 | 12 项完整模型/RTL/主机/厂商原语结果通过；受测源文件和向量 SHA-256 与当前文件一致 |
| PLL | 厂商参数校验通过；旧 PFD=125 MHz/OPTIMIZED 作为负例被拒绝；实际以太网 PLL 为 I=4、M=16、F=2、O=4、OPTIMIZED |
| 构建链 | 从 compile 开始；原生日志成功事件、脚本、完成标记及 map/place/route 数据库身份一致 |
| 宏位置 | 原始 PCF 加精确源模板；176 个宏的位置被实际接受，并核对功能身份；不能用位置数相同替代绑定关系 |
| 引脚与电气 | 99 个端口方向、封装、电压和 I/O 标准一致；8 路 CLK 为 LVCMOS18、16 mA、FAST，64 根 DATA 为 LVCMOS18 |
| 双角时序 | 慢角/快角 setup、hold、recovery、removal、最小脉宽摘要完整、无违例；关键域和 CDC 路径覆盖齐全 |
| 时钟 | 12 个声明/生成/虚拟时钟的周期、相位及来源匹配；无新增未知时钟；八路 CLK 物理网表同源 |
| RGMII | 六个 TX 端点、双沿、双角、最大/最小路径完整；扣除公共项后的物理偏差 ≤0.300 ns；实际可达边沿名义占空比 45%～55% |
| PDM | 64 根 DATA 输入与8路时钟输出均覆盖；100 ns 器件延迟 +20 ns 外部传播、时钟输出上限 4 ns、实际输入路径及不确定度小于 138.346 ns 采样窗口 |
| 完整性 | 源文件、向量、检查器、报告、数据库及位流 SHA-256 记录并复核；禁止混用不同构建证据 |

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

`finalize_route_checkpoint.py` 可选择已完成且证据完整的路由检查点，再重新导出时序、SDF/网表并执行原有检查。它不能把未完成路由或改写日志当成成功。候选 `_spread5` 使用了该流程；当前推荐 `_spread3_long` 为常规完整流程。历史格式继续受对应证据核查，见[版本历史](../../doc/reports/version_history.md)。

检查器自检命令：`python -m unittest discover -s fpga/scripts/tests -v`。本次 146 项结果见[原始日志](../../log/system_uart/clk8_checker_tests.log)，包括电气、数据库、路由完成记录、恢复清单及源文件变化的拒绝用例。
