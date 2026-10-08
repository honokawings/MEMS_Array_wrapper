# 集成与运行指南

本文保留可移植前处理的完整接口说明。PG2L200H整机顶层为 `rtl/board/mems_array_pg2l200h.sv`；数据包格式见 [transport_spec.md](transport_spec.md)，上位机接收见 [host_capture.md](host_capture.md)。

## 首次运行

需要 ModelSim/Questa（支持 SystemVerilog/SVA）、C++17 的 g++、Python 及 `lib/model/requirements.txt` 中的依赖。仿真器和编译器应在 PATH 中。

在工程根目录执行：

```powershell
python -m pip install -r lib/model/requirements.txt
python sim/verify_all.py
```

如果数值库装在另一个 Python 环境，用 `MEMS_PYTHON` 指定那个解释器的完整路径。脚本会优先使用指定解释器，再检查当前解释器；在本机 Codex 环境还可识别已有的数值运行时。`lib/.deps/` 为本机依赖缓存，不属于 RTL 源码。

完整回归将检查冻结系数、Cmodel、参考向量、性能、前处理UT、PHY/网络/打包、板级启动控制、端到端数据、接收器和Pango厂商PLL/DDR模型。成功时显示 `[RUN_PASS]`，失败返回非零退出码。完整摘要为 `log/full_regression.json`。原 `sim/sim.bat` 和以下命令专用于前处理层；各层使用独立仿真工作库，日志全部位于 `log/`。

```powershell
python sim/run_all.py --models-only
python sim/run_all.py --rtl-only
python sim/run_all.py --rtl-only --test tb_array
```

`--rtl-only` 需要已经生成 `tb/vectors/`。批处理使用 `vsim -batch`，避免旧版 ModelSim 交互进程在 IPv6 本机 RPC 初始化时的兼容问题。GUI 查看波形可在 ModelSim 中 `do <工程完整路径>/sim/modelsim_sim.do`；部分旧版 GUI 仍取决于其本机通信配置。

## 顶层接口

实例化 `mems_array_top`，向 `clk` 提供精确 122.88 MHz。所有输入控制和 PCM 接收端均在此时钟域。若来自其他时钟域，应在顶层之外完成 CDC。

| 端口 | 方向 | 语义 |
|---|---|---|
| clk / rst_n | 输入 | 系统时钟 / 同步低有效复位，至少保持 2 个系统时钟 |
| enable | 输入 | 1：启动/持续采集；0：停止并清空数据状态 |
| pdm_data[63:0] | 输入 | 64 根共享数据线，每线两只麦克风 |
| mic_clk | 输出 | 送往全部麦克风的公共时钟源 |
| started | 输出 | 麦克风 50 ms 等待结束；此时 FIR 仍可能在建立稳态 |
| cfg_valid / cfg_ready | 输入/输出 | 仅 enable=0 时握手写校准；valid 必须保持到 ready |
| cfg_channel[6:0] | 输入 | 0～127 逻辑通道号 |
| cfg_gain[23:0] | 输入 | 有符号 Q2.22，单位增益 4194304 |
| cfg_offset[31:0] | 输入 | 有符号 Q2.30，默认 0 |
| pcm_valid / pcm_ready | 输出/输入 | 当两者同时为 1 时传输一个样本 |
| pcm_data[23:0] | 输出 | 有符号 Q1.23 PCM |
| pcm_channel[6:0] | 输出 | 当前样本通道，按 0～127 递增 |
| pcm_frame_id[63:0] | 输出 | 同一 128 路采样时刻的公共帧号，重新启动归零计数 |
| pcm_first / pcm_last | 输出 | 当前有效样本为该帧通道 0 / 127 |
| overflow / dropped_frames[31:0] | 输出 | 输出队列满的粘滞标志 / 饱和计数器 |
| processing_error | 输出 | 内部调度过载；停止并重新启动本轮采集 |
| clipped | 输出 | 运行期间任何 FIR 或校准产生饱和的粘滞标志 |

当 `pcm_valid=1 && pcm_ready=0` 时，数据和全部标签保持不变。`pcm_ready` 不会停止 PDM 时钟。应根据帧号识别丢帧，不能把两个不连续帧直接拼成连续录音后进行 PHAT。disable/reset 可中止一个正在发送的帧，接收端也应同步清空该半帧。

## 推荐启动顺序

1. 确保电源和 122.88 MHz 时钟稳定，`enable=0`，复位至少两个系统时钟。
2. 如需校准，在 enable=0 时逐通道握手写入增益和偏置。配置不能在采集时修改；运行期间 `cfg_ready=0`，写请求不会被接受。
3. 接收端准备好后拉高 enable。等待 pcm_valid；缺省首帧号是 96，而不是 0。
4. 按 frame_id/channel 组装 128 路同步 PCM。每 128 个成功握手构成一帧；不要把串行总线上的到达时刻当成各麦克风的不同采样时刻。

## 校准流程

使用默认单位增益/零偏置获取安静录音，以及所有麦克风处于同一已知声场的稳态校准音录音，均去掉启停和饱和区间。保存为 `(样本数,128)` 的 int32 NPY，元素仍为原始 24 位 PCM 整数。

```powershell
python lib/model/calibration.py --silence quiet.npy --tone common_tone.npy --frequency 1000 --reference 0 --output doc/calibration/measured
```

生成 `.txt` 的每行分别是 gain_q22 和 offset_q30，可在 enable=0 时写入 FPGA。`.json` 同时记录通道号、DATA 线号、LR 状态和单音相位差。单音相位报告仅用于诊断，不能唯一确定宽带延迟，也没有自动更改通道相位。用于 SRP-PHAT 的宽带相位/时延标定应在已知声源、已知几何和多频带测量条件下完成。

不应使用不同位置的未知声源直接估计各麦克风“器件增益/相位差”，否则会把真实的传播时延和声压差错误地校正掉。阵元坐标和麦克风接线对应关系应由板级工程提供，并与 channel_id 固定关联。

## 板级接入前

板级工程包含 PG2L200H 时钟/DDR 原语及 J10/J25/J26/PHY0 约束。当前为八路同源 CLK、LVCMOS18 麦克风接口，需实测 L6/L7 VCCIO 与 MEMS VDD 为 1.8 V。推荐位流及构建方法见[上板指南](board_bringup.md)，本版未上板。

默认原始引脚采样时刻约 138.346 ns，扣除麦克风最大 tDV=100 ns 后，留给输出/输入路径、往返布线与不确定度约 38.346 ns；其中外部传播预算为 20 ns。这是预算组成，不能直接作为布局布线后的剩余裕量。当前双角剩余预算见[发布报告](reports/clk8_18v_update.md)。两级输入寄存器不替代采样窗口检查。

实现约需 192 KiB FIR 历史存储和 33 条宽乘法流水，但实际 RAM/DSP/逻辑数量由目标器件及推断方式决定。RTL 展开检查通过也不代表 122.88 MHz 布局布线时序已经收敛。

上电由板级控制自动逐通道写入 `rtl/board/calibration_coeff.svh` 中的系数，再等待 PHY 千兆全双工及 ARP 对端地址就绪后启动采集。默认ROM为空case，使用单位增益/零偏置。实测校准文件可用 `python lib/model/export_board_calibration.py doc/calibration/measured.txt` 导入，再重建位流。普通网线断连保留校准系数；KEY0复位或PLL失锁会重新装载ROM。
