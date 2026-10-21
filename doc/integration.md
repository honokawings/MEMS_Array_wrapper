# 集成与运行指南

本文保留可移植前处理的完整接口说明。PG2L200H整机顶层为 `rtl/board/mems_array_pg2l200h.sv`；数据包格式见 [transport_spec.md](transport_spec.md)，上位机接收见 [host_capture.md](host_capture.md)，I2S 及奇偶增益控制见[音频监听指南](audio_monitor.md)。

前一seed3基线的18层回归、严格时序和A–F数字记录保留在[seed3报告](reports/i2s_parity_dc_roundsat_seed3_20261011.md)。其DATA1/ch2、3故障没有被软件消除；板上电压、DAC模拟和声学配平仍未验收。

FIR8每级以8条乘加流水处理16组，128通道和48kHz不变；相对16-lane增加约13.02µs共同延迟。[完整18层回归](../log/i2s_parity/full_regression_fir8_auto_20261011.json)、[实际资源](../log/i2s_parity/fir8_auto_map_actual_20261011.json)、严格发布与JTAG均已通过。本次A–E数字验收通过，联合结果为PASS_WITH_KNOWN_ISSUES；F真实采样连续，DATA1/ch2、3及物理未测边界保留，详情见[FIR8报告](reports/i2s_fir8_auto_20261011.md)。

## 首次运行

需要 ModelSim/Questa（支持 SystemVerilog/SVA）、C++17 的 g++、Python 及 `lib/model/requirements.txt` 中的依赖。仿真器和编译器应在 PATH 中。完整回归还需要本机 PDS 2022.2-SP6.4 与有效许可证，用于强制 UART 厂商编译/综合/映射及门级功能验证。

在工程根目录执行：

```powershell
python -m pip install -r lib/model/requirements.txt
python sim/verify_all.py
```

如果数值库装在另一个 Python 环境，用 `MEMS_PYTHON` 指定那个解释器的完整路径。脚本会优先使用指定解释器，再检查当前解释器；在本机 Codex 环境还可识别已有的数值运行时。`lib/.deps/` 为本机依赖缓存，不属于 RTL 源码。

完整回归入口含 **18层强制检查**：数值模型、前处理、FIR算术/真实RAM、奇偶/DC、I2S、UART/host、板级音频、PHY/网络及厂商PLL/DDR。成功显示`[RUN_PASS]`，失败返回非零。已下载seed3的[不可变18/18记录](../log/i2s_parity/full_regression_dc_roundsat_20261009.json)只绑定该基线104项输入及22份向量；FIR舍入/饱和定向核对866,460项、20,630组输入及40,216次写回，见[快照](../log/i2s_parity/dc_round_sat_directed_20261009_203011/snapshot.json)。当前另已应用FIR8，六配置RAM定向PASS、[FIR8完整回归](../log/i2s_parity/full_regression_fir8_auto_20261011.json)已PASS（104项输入、22份向量）；旧基线回归不覆盖新源码。旧DC时序失败见[历史](reports/version_history.md)。

新 DC 的[定向记录](../log/i2s_parity/dc_estimator_targeted_20261009/design_and_verification.json)含 790,040 项新检查和 20,614 项既有检查；功能通过不签核器件时序或硬件。实时摘要为 [log/full_regression.json](../log/full_regression.json)；[旧 B 18/18 不可变摘要](../log/i2s_parity/full_regression_fir_fixed_result_20261009.json)只绑定旧 B 的 102 项输入，不覆盖新增 DC。可读结果见[功能验证报告](reports/system_verification.md)。原 `sim/sim.bat` 和以下命令专用于前处理，各层使用独立工作库。

```powershell
python sim/run_all.py --models-only
python sim/run_all.py --rtl-only
python sim/run_all.py --rtl-only --test tb_array
```

专项验证的独立入口如下；修改受测源码后应重新运行完整回归，再构建发布位流。

```powershell
python sim/run_parity.py
python sim/fir/run_ram_pipeline.py
python sim/audio/run_i2s.py
python sim/audio/run_audio_uart.py
python sim/audio/run_vendor_uart.py
python sim/audio/run_board_audio.py
```

`vendor_uart` 每次重新执行 PDS compile/synthesize/dev_map，使用实际技术网表和厂商模型核验全部 128 个通道、拒绝非法输入、OFF 与组增益。证据见 [log/vendor_uart/result.json](../log/vendor_uart/result.json)，并通过 SHA-256 绑定完整回归。该层没有 SDF 标注或布局布线；`--skip-vendor` 只跳过 PLL/DDR 层，不能跳过 UART 厂商层或 `fir_ram`。

`fir_ram` 当前覆盖两级16-lane基线、两种单通道`GROUPS=1`及两级8-lane新配置，共六案例；核验真实RAM写入、回绕、读写并行、末提交同拍接收、复位中断及过载，参考来自外部事务和独立系数。[FIR8定向记录](../log/i2s_parity/fir8_directed_ram_20261011.json)实际11,435,616项PASS，8-lane两级输入至valid精确1090/2114拍；其[FIR8完整回归](../log/i2s_parity/full_regression_fir8_auto_20261011.json)已PASS（104项输入、22份向量）。已下载seed3的四配置5,597,580项是基线范围，不能代替新配置回归或物理结果。`steps.fir_ram.evidence`按路径/SHA绑定实际结果、七个输入、工具及原始日志；214项既有检查器自测也不签核新候选时序。

`--rtl-only` 需要已经生成 `tb/vectors/`。批处理使用 `vsim -batch`，避免旧版 ModelSim 交互进程在 IPv6 本机 RPC 初始化时的兼容问题。GUI 查看波形可在 ModelSim 中 `do <工程完整路径>/sim/modelsim_sim.do`；部分旧版 GUI 仍取决于其本机通信配置。

## 顶层接口

实例化 `mems_array_top`，向 `clk` 提供精确 122.88 MHz。所有输入控制和 PCM 接收端均在此时钟域。若来自其他时钟域，应在顶层之外完成 CDC。

| 端口 | 方向 | 语义 |
|---|---|---|
| clk / rst_n | 输入 | 系统时钟 / 同步低有效复位，至少保持 2 个系统时钟 |
| enable | 输入 | 1：启动/持续采集；0：停止并清空数据状态 |
| pdm_data[63:0] | 输入 | 64 根共享数据线，每线两只麦克风 |
| mic_clk | 输出 | 送往全部麦克风的公共时钟源 |
| started | 输出 | 麦克风 50 ms 等待结束；不表示滤波稳态/DC训练已完成 |
| cfg_valid / cfg_ready | 输入/输出 | 仅 enable=0 时握手写校准；valid 必须保持到 ready |
| cfg_channel[6:0] | 输入 | 0～127 逻辑通道号 |
| cfg_gain[23:0] | 输入 | 有符号 Q2.22，单位增益 4194304 |
| cfg_offset[31:0] | 输入 | 奇偶补偿后的有符号 Q2.30 偏置，默认 0 |
| parity_cfg_valid / parity_cfg_ready | 输入/输出 | 奇偶增益配置握手；运行中可排队，valid 和数据须保持至 ready |
| parity_even_gain / parity_odd_gain[23:0] | 输入 | 非负 Q2.22，合法值 0x000000～0x7FFFFF；1 为 0x400000 |
| parity_active_even_gain / parity_active_odd_gain[23:0] | 输出 | 已提交的奇偶增益，不表示输出 FIFO 内旧帧已经排空 |
| parity_bypass | 输入 | 1：整帧不扣DC、使用单位奇偶增益、不推进训练；保留增益配置，板级 BIST 使用 |
| dc_ready | 输出 | DC禁用时恒1；启用时完整训练窗已审核，不表示全部通道接受 |
| dc_rejected[127:0] | 输出 | 被拒绝的通道置1，其学习偏置为0、原始异常保留 |
| pcm_valid / pcm_ready | 输出/输入 | 当两者同时为 1 时传输一个样本 |
| pcm_data[23:0] | 输出 | 有符号 Q1.23 PCM |
| pcm_channel[6:0] | 输出 | 当前样本通道，按 0～127 递增 |
| pcm_frame_id[63:0] | 输出 | 同一 128 路采样时刻的公共帧号，重新启动归零计数 |
| pcm_first / pcm_last | 输出 | 当前有效样本为该帧通道 0 / 127 |
| overflow / dropped_frames[31:0] | 输出 | 输出队列满的粘滞标志 / 饱和计数器 |
| processing_error | 输出 | 内部调度过载；停止并重新启动本轮采集 |
| clipped | 输出 | 运行期间 FIR、奇偶补偿或逐通道校准饱和的粘滞标志 |

当 `pcm_valid=1 && pcm_ready=0` 时，数据和全部标签保持不变。`pcm_ready` 不会停止 PDM 时钟。应根据帧号识别丢帧，不能把两个不连续帧直接拼成连续录音后进行 PHAT。disable/reset 可中止一个正在发送的帧，接收端也应同步清空该半帧。

逐通道 `cfg_ready` 与 `parity_cfg_ready` 是两套握手。逐通道增益/ROM偏置仅在 `enable=0` 时接受；奇偶补偿有一个待提交槽，运行中下一完整 FIR2 帧边界生效。仅在复位释放后提交，握手不表示旧 PCM 已排空，也不表示 DC 已完成。不使用奇偶配置时将 `parity_cfg_valid/parity_bypass` 接0；默认增益均为1。`dc_ready` 是训练状态，与两种 cfg_ready 不同。

可移植 `mems_array_top` 与 `mems_ethernet_core` 默认 `DC_ESTIMATE_LOG2=0`，保留 DC、首帧96。物理板级 `mems_array_pg2l200h` 默认12；跳过96帧，再训练4096帧，真实首帧4192。合法非零窗口参数为2～20；更改参数需重新检查首帧门控、状态存储与验证。降低测试窗口不能带入生产配置。

完整板级把 I2S 连接到网络内核的 `monitor_pcm_valid/channel/data`。这些信号位于音频域，`monitor_pcm_valid` 表示前端已接受的 PCM 传递事件，不是可反压接口，也不是 FIR2 原始值。I2S 串行器端口与查询方法见[音频监听指南](audio_monitor.md)。

## 推荐启动顺序

1. 确保电源和 122.88 MHz 时钟稳定，`enable=0`，复位至少两个系统时钟。
2. 在 `enable=0` 时，先确定并提交奇偶增益，再逐通道写入以该补偿为基准的增益/偏置。逐通道配置不能在采集时修改；运行期间 `cfg_ready=0`。奇偶配置可运行中整帧切换，但更改后应重新评估已有校准。
3. 接收端准备好后拉高 enable，保持安静。等待预热及96帧滤波瞬态；启用DC时再训练4096帧，核对 `dc_ready` 和拒绝mask。板级真实首帧4192，DC禁用/BIST首帧96；网络首帧还取决于ARP释放时刻。
4. 按 frame_id/channel 组装 128 路同步 PCM。每 128 个成功握手构成一帧；不要把串行总线上的到达时刻当成各麦克风的不同采样时刻。

## 校准流程

先确认输入/供电正常，记录位流、DC策略及拒绝状态；安静启动后等待训练完成。奇偶增益默认1，不代表个体 AC 已配平。保持两组增益不变、逐通道ROM增益/偏置为1/0，获取安静和共同已知声场的稳态录音，排除启停、拒绝、饱和及间断。保存为 `(样本数,128)` 的 int32 NPY，元素为有符号24位PCM编码。启用DC时，这些数据已经扣启动冻结值；恢复unity不会得到未扣DC的raw FIR数据。

```powershell
python lib/model/calibration.py --silence quiet.npy --tone common_tone.npy --frequency 1000 --reference 0 --output doc/calibration/measured
```

生成 `.txt` 的每行分别为逐通道 gain_q22 和 offset_q30，可在 `enable=0` 时写入。完整计算先将 `(FIR_Q30−learned_DC_Q30)×parity_Q22` 舍入/饱和回 Q2.30，再计算 `(补偿后 Q30−ROM_offset_Q30)×channel_gain_Q22` 并舍入/饱和为 Q1.23，见[算法公式](algorithm_spec.md#数学及定点契约)。旧ROM偏置仍是post-parity残差，不能写入pregain学习DC重复扣除。更改奇偶增益或DC策略后应重新评估ROM校准；重启后的学习窗也须记录。`.json` 保存通道、DATA、LR和单音相位；单音相位仅作诊断，不能唯一标定宽带延迟。SRP-PHAT 幅相测量仍需要已知声源、几何和多频带条件。

不应使用不同位置的未知声源直接估计各麦克风“器件增益/相位差”，否则会把真实的传播时延和声压差错误地校正掉。阵元坐标和麦克风接线对应关系应由板级工程提供，并与 channel_id 固定关联。

## 板级接入前

板级工程包含 PG2L200H 时钟/DDR 原语及 J10/J25/J26/PHY0 约束，完整顶层为 **103 个约束端口**。八路同源 MEMS CLK 与 64 根 DATA 使用 LVCMOS18，L6/L7 VCCIO 和 MEMS VDD 须实测为 1.8 V。J10 还包括 L5 上的四路 I2S 输出，使用 LVCMOS33、8 mA、FAST，要求 3.3 V 逻辑接收端并共地；不能把整个 J10 视为 1.8 V。具体引脚见[音频监听指南](audio_monitor.md)，下载与构建方法见[上板指南](board_bringup.md)。

[第一版](reports/i2s_parity_20261009.md)已发布/JTAG 下载、实板网络 BIST 和偶/奇各 64 路零增益功能通过，但 UART 数字通道选择被编译为常量 0。UART 修复候选 `MEMS_Array_i2s_parity_uartfix_20261009` 两轮正式时序均失败，未生成位流、未下载。

前一seed3已完成其18层回归、严格发布、JTAG和A–F数字实测，见[历史基线报告](reports/i2s_parity_dc_roundsat_seed3_20261011.md)。FIR8已有自己的完整回归、严格发布和下载证据，本次FIR8已完成自己的[A–F数字验收](../log/i2s_parity/fir8_auto_hardware_acceptance_20261011.json)，结果PASS_WITH_KNOWN_ISSUES；原捕获失败与物理未测范围保留。采集方式见[FIR8报告](reports/i2s_fir8_auto_20261011.md#本次工程采集方式)。

旧 B 版 F 阶段得到 **143,907 帧**，DATA1/ch2、3 固定负满量程（−8,388,608）。新DC应拒绝并保留这类异常，不能把offset学习成负rail来制造零音频。全部64对AC、DAC模拟、实际1.8V及带载测量仍未验收，见[旧B实板结果](reports/i2s_parity_fir_fixed_result_20261009.md)。

历史 timingfix2/3 首轮未完成后主动取消，时序UNKNOWN，无位流或下载，见[历史](reports/version_history.md)。DC roundsat 的128个APM实例名已按[实际角色配对](../log/i2s_parity/dc_roundsat_floorplan_role_pairing_20261009.json)更新，48个历史RAM实例名及176项位置、BEL、顺序保持不变。[更名记录](../log/i2s_parity/dc_roundsat_floorplan_apply_actual_20261009.json)只证明角色范围；完整物理通过另由[seed3正式发布门禁](../fpga/build/MEMS_Array_i2s_parity_dc_roundsat_seed3_20261009/release.json)给出。原seed2完整构建实际超时FAIL、最终时序未知，见[终态记录](../log/i2s_parity/dc_roundsat_seed2_route_timeout_actual_20261009.json)，未生成位流；seed3是已完成并下载的单候选基线。

默认原始引脚采样时刻约 138.346 ns，扣除麦克风最大 tDV=100 ns 后，留给输出/输入路径、往返布线与不确定度约 38.346 ns；其中外部传播预算为 20 ns。这是预算组成，不能直接作为布局布线后的剩余裕量。旧版双角剩余预算见[历史发布报告](reports/clk8_18v_update.md)；新增功能须以新候选自己的实现与发布检查为准。两级输入寄存器不替代采样窗口检查。

FIR历史逻辑存储约192KiB。FIR8每级8-lane×16组，两级1090/2114拍，小于1280/2560拍任务间隔；相对seed3的546/1058拍共同增加1600拍，约13.02µs，采样率和帧号不变。补偿仍131拍，DC另用8×16×109位状态银行和三步side流水。[实际映射](../log/i2s_parity/fir8_auto_map_actual_20261011.json)为LUT28,512、FF47,953、APM68、DRM70.5，分布式RAM2,290。新一轮路由1850秒，详细1528.25秒；实际比较和严格时序见[FIR8报告](reports/i2s_fir8_auto_20261011.md)，不据资源下降推断单因素因果。结构见[RTL架构](rtl_architecture.md#启动-dc-状态与奇偶补偿)。

板级自动写入 `rtl/board/calibration_coeff.svh`。正常设置 `INDEPENDENT_AUDIO=1`，ROM装载后开始真实PDM；50ms预热、96帧滤波瞬态和4096帧DC训练后，从4192释放PCM。I2S时钟先运行，无PCM时输出零并可能累计启动欠载；应在训练完成后比较稳态增量。此过程无需PHY/ARP，只有UDP等待千兆全双工和ARP，并从完整帧开始发送。可移植默认 `INDEPENDENT_AUDIO=0` 和BIST才网络门控；DC禁用可移植默认及BIST首帧仍96。

默认ROM为单位增益/零偏置，奇偶AC增益为1，I2S监听通道0；这些默认值不是个体AC校准。导入实测ROM可用 `python lib/model/export_board_calibration.py doc/calibration/measured.txt`，随后重新构建。正常断网保留采集、增益配置和冻结DC；reset、disable、模式切换会清DC并重训。KEY0、UART `r` 或PLL失锁重载ROM并重放观察域期望配置。BIST使用DC0/奇偶1/逐通道1与零ROM偏置；退出后恢复增益并重新训练，运行中保留不是掉电保存。SYS3 AudioFlags12/13/14反馈DC启用/审核完成/any-reject，done不代表128路全接受。
