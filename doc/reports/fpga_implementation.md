# PG2L200H 完整实现与位流发布报告（2026-09-16 历史版本）

> 本报告对应增加按键自测之前的已发布版本。2026-09-17 当前源码已增加自测，旧 PASS 不覆盖这些修改；原始源码快照在 `fpga/build/archive/20260916_released_before_selftest/source_snapshot/`。新版状态见 [selftest_implementation.md](selftest_implementation.md)。

**本次工程发布通过。** 2026-09-16 09:14:46 至 09:36:38（UTC+8）完成从编译、综合、映射、布局布线、双角时序分析到位流生成；09:37:00 最终发布检查为 `PASS`，`release_authorized=true`。硬件源文件在构建前后保持一致。

发布范围是 **工程上板联调**（`engineering_board_bringup`），尚未烧录或进行实板测量。PDS 原始器件模型为 `Pre-silicon`；TXC 保守抖动敏感性分析仍为 `FAIL`，实际占空比和抖动资格验证为 `UNCONFIRMED`。这些限制保留在发布清单中，不能把本次结果解释为无条件的量产签核。

## 交付入口与校验值

| 内容 | 文件 |
|---|---|
| 已完成构建的 Pango 工程 | [MEMS_Array.pds](../../fpga/build/MEMS_Array/MEMS_Array.pds) |
| JTAG 使用的带头配置位流 | [mems_array_pg2l200h.sbit](../../fpga/build/MEMS_Array/generate_bitstream/mems_array_pg2l200h.sbit) |
| 原始配置数据 | [mems_array_pg2l200h.bin](../../fpga/build/MEMS_Array/generate_bitstream/mems_array_pg2l200h.bin) |
| 最终发布状态与全部来源校验值 | [release.json](../../fpga/build/MEMS_Array/release.json) |
| 构建阶段与源文件清单 | [manifest.json](../../fpga/build/MEMS_Array/manifest.json) |
| 完整功能验证结果 | [system_verification.md](system_verification.md) |
| 接线、下载与首次采集 | [board_bringup.md](../board_bringup.md) |

原 `fpga/MEMS_Array.pds` 未修改；打开本次实现请使用上表中的独立构建工程。PDS 生成的是 `.sbit`，没有另造 `.bit` 文件。`.bin` 用于原始配置流程，不能仅凭其存在确定 Flash 型号、地址或启动模式。

| 产物 | 字节数 | SHA-256 |
|---|---:|---|
| `.sbit` | 9,188,552 | `b8b8a24bd83e808896939a17450c087ee4b791f4789cae079b6c2c2d26e80d6b` |
| `.bin` | 9,186,916 | `54086ed1e2d252d4fd4c220c0d31391c89ac6cee01fcdff882a7957f6c1c1858` |

完整回归记录 SHA-256 为 `9c608314945b24d757b134b6b7686f8fdead855fbaf14516beb2a7c16038f5ff`；布线数据库 SHA-256 为 `fd7fc3416ce9ba8f725aa92d74c174c4abeef45a2199b87958c2be1aa4e51c1d`。双角网表/SDF、时序报告与位流都绑定至这一轮布线结果。

## 已实现的系统

64 根共享 DATA 采集 128 路麦克风，四路 PDM 时钟为 3.072 MHz。前处理为 CIC5 /8 → FIR63 补偿 /4 → FIR127 抗混叠 /2 → 增益/偏置校准；输出 48 kHz、24 位有符号 PCM，定位有效通带为 20 Hz～16 kHz。所有通道保持一致的滤波相位、调度和帧号定义。

PCM 经可反压样本寄存器、异步 FIFO、三帧打包、UDP/IPv4/ARP MAC 和 RGMII 发送至 RTL8211F-CG。PHY 管理包含真实 MDIO 事务、地址扫描、配置读回、RGMII 内部延迟、关闭 EEE 广告、千兆全双工判定和断线恢复。单包 UDP 负载 1208 字节，线路占用约 163.072 Mbit/s；上位机接收器保存 24 位原始 PCM、逐帧元数据及缺帧统计。

默认 FPGA 为 `192.168.10.2`，电脑为 `192.168.10.1`，UDP 端口 `5000`，使用同一二层网段。校准默认为增益 1、偏置 0；真实声学校准后需导出系数并重新构建。SRP-PHAT 定位由上位机执行。

## 工具、管脚与时钟

- 器件：Logos2 / PG2L200H / -6 / FBB676；工具：Pango Design Suite 2022.2-SP6.4，build 146967。
- 引脚依据修正后的 README 与《盘古MINI系列开发板硬件指导手册_V1.3》：87 个端口全部有唯一固定位置，434 条约束命令通过检查。
- D18 为 27 MHz LVCMOS33；N3/N2 为 125 MHz 差分参考、SSTL15D_I、1.5 V；C22 KEY0 为低有效复位。麦克风接口使用 3.3 V，L6/L7 可调 Bank 的实际跳线须为 3.3 V。
- 音频时钟：27 MHz → GPLL 96 MHz → GPLL 122.88 MHz，两级 I/M/F/O 分别为 1/16/2/9 与 5/16/2/5，VCO 为 864/614.4 MHz。
- 网口时钟：125 MHz → GPLL 250 MHz → `GTP_IOCLKDIV_E2` 单上升沿 /2 → 全局缓冲 125 MHz。第三 PLL 的 I/M/F/O 为 1/4/2/4，VCO 为 1000 MHz。任一 PLL 失锁都会重启全局流程。
- RX 用同一 `GTP_CLKBUFR` 驱动 IDDR 与接收逻辑，输入延迟 tap=18（Gray=0x1B）。TX 使用同源 ODDR，六个输出为 LVCMOS33、FAST、16 mA。未使用器件不支持的 24 mA 设置。
- 19 个配置复用脚已逐脚核实：J10 的 18 个信号与 G25 PHY 复位。位流命令显式使用 `-persist_pin {Release For USER}`，与 PG2L200H 官方配置文件的释放设置一致；没有占用 MODE 或 CSO_DOUT。

## 最终资源与布线

以下来自实际 [布局布线报告](../../fpga/build/MEMS_Array/place_route/mems_array_pg2l200h.prr)，不是综合估算。

| 资源 | 最终用量 |
|---|---:|
| 层次统计 LUT | 30,748 |
| FF | 36,519 |
| 分布式 RAM 原语 | 2,288 |
| APM | 130 / 740 |
| DRM36K 等效 | 53 / 415 |
| GPLL | 3 / 10 |
| IO | 87 / 400 |

PDS 同一报告的物理 CLMA/CLMS 统计分别为 25,989/8,680 个 LUT，占用合计 34,669；其统计口径与层次 LUT 行不同，不混用。FF 的两类物理统计合计仍为 36,519。

全部 55,801 条连接（含常量）完成布线。详细布线耗时 471.65 秒，第 125 轮完成全部连接合法化；hold 修复实际执行，日志报告 `No hold violation.`。完整流程从编译开始耗时约 21 分 52 秒，到最终发布检查约 22 分 14 秒。

## 布线后静态时序

原始 [RTR 报告](../../fpga/build/MEMS_Array/report_timing/mems_array_pg2l200h.rtr) 为 **ALL CONSTRAINTS MET**。慢角和快角的 Setup、Hold、Recovery、Removal、Minimum Pulse Width 全部摘要行均非负，失败端点均为 0；原始 XML 数据库与文本报告的时钟和摘要表逐项一致。

| 路径 | Slow setup / ns | Slow hold / ns | Fast setup / ns | Fast hold / ns |
|---|---:|---:|---:|---:|
| 音频域 audio122 | +0.083 | +0.090 | +1.656 | +0.020 |
| 发送域 eth125 | +0.936 | +0.060 | +3.691 | +0.020 |
| 接收域 rx125 | +2.411 | +0.100 | +4.777 | +0.021 |
| RGMII RX 外部输入 | +0.140 | +0.143 | +0.387 | +0.495 |

TX 六输出内部最大延迟约束为 2.500 ns，slow/fast 余量为 +0.523/+1.005 ns。该 datapath-only 约束替代普通输出 hold 检查；最小传播与同源匹配另由完整 Max Skew 最小路径组和 SDF 审计，不声称普通 TX 输出 hold 已通过。

独立时钟跨域保留 7.5 ns 数据路径上限与单独 hold 例外，未用全域异步 clock group 覆盖该上限。audio→eth、eth→audio、rx→eth、eth→rx 分别覆盖 11、11、228、3 个端点，双角均通过。复位例外限定到异步控制与释放同步器；功能逻辑的恢复/移除检查保留。

## PDM 采样物理预算

当前 `SAMPLE_TICK=19`；扣除两级输入寄存器后，实际选取的是发出半周期边沿后 **17 个音频周期，即 138.346354 ns** 的引脚值。审计从真实网表追踪全部四个输出 pad、发射 FF、64 个首级输入 FF 和公共时钟缓冲，并使用同一布线结果的双角 SDF。

| 项目 / ns | Slow | Fast |
|---|---:|---:|
| 麦克风 DATA 有效延迟预算 | 100.000 | 100.000 |
| 外部缓冲、连接器与往返布线预算 | 20.000 | 20.000 |
| FPGA 时钟输出约束上限 | 4.000 | 4.000 |
| 实际输入 pad 至寄存器、含 setup | 3.621 | 2.201 |
| 实际发射时钟支路保守上界 | 1.749 | 1.102 |
| 时钟不确定度与舍入保护量 | 0.301 | 0.301 |
| 合计上界 | 129.671 | 127.604 |
| 剩余建立时间 | **8.675** | **10.742** |

捕获时钟支路下界保守按 0 计入；公共 PLL/全局缓冲路径经连接关系证明后抵消。采样距离下一半周期边沿仍有 3 个音频周期，即 24.414 ns。外部传播、负载和边沿必须满足上述假设；PDS 默认负载下的 pad 结果不能替代 32 只麦克风的真实扇出测量。

补充 [PDM 窗口压力测试](../../fpga/build/pdm_window_probe/README.md) 中，DATA 在半周期开始后 136 ns 才有效：当前设置 64 次采样全部正确，旧 SAMPLE_TICK=18 负对照 64 次均失配，停止/重启与时钟一致性通过。

## RGMII 发送物理结果与未完成的板级资格验证

真实双角同沿管脚传播范围最大为 slow **0.279 ns**、fast **0.265 ns**，均低于 FPGA 0.300 ns 限制。PCB 相对偏差另预留 0.200 ns。原始 Max Skew 值包含共同源的 ±0.050 ns 抖动项；仅在逐路径证明其来源后消除公共项，并独立判断物理限制，未直接将原始值当成裸管脚偏差。

第三 PLL → 单沿分频器 → 全局缓冲 → TXC ODDR → pad 的实际路径给出：

| 角 | fall−rise 传播差 / ns | 名义高电平 / ns | 名义低电平 / ns | 名义占空比 | 额外边沿对抖动预算 / ns |
|---|---:|---:|---:|---:|---:|
| Slow | −0.092 | 3.908 | 4.092 | 48.8500% | 0.308 |
| Fast | +0.129 | 4.129 | 3.871 | 51.6125% | 0.271 |

名义模型通过 45%～55% 检查。厂商 PLL 手册的 180 ps 输出抖动未明确逐沿、周期、峰峰或 RMS 定义；若保守解释成每个边沿 ±180 ps，枚举连续三边沿的相关组合后，slow 最低占空比为 **44.35%**、fast 最高为 **56.1125%**，敏感性检查为 **FAIL**。这是未获厂商确认的保守解释，既不能擦去该失败，也不能据此断言实际器件必然不合格。

因此发布清单明确记录 `unconditional_board_qualification=false`、`sensitivity_status=FAIL`、`txc_duty_and_jitter=UNCONFIRMED`。首次上板须在 PHY 引脚测量 TXC 占空比 45%～55%、周期 7.2～8.8 ns，并核对 RGMII 的 20%～80% 上升/下降时间 ≤0.75 ns。在全部麦克风接入时，PDM CLK 的 10%～90% 边沿须 ≤13 ns、3.072 MHz 占空比须为 48%～52%，外部往返传播须 ≤20 ns。实际布线偏差、满载驱动能力、长期 UDP 连续性和声学 SNR 均未在本次工作中实测。

## 功能回归和实现修复依据

2026-09-16 09:13:43 完整回归 **10 项全部 PASS**，包含重新生成的 Python/C++ 模型、RTL、上位机和 Pango 官方原语。端到端真实 RTL 输出 99 个 UDP 包、297 帧、38,016 个通道样本，与定点参考逐位一致。随机反压、整帧丢弃、断线重启、校准边界、PHY 配置读回、CRC/校验和与 45%/55% 外部参考时钟均有自检覆盖；详见 [功能报告](system_verification.md)。

为消除已发现的真实问题，本版完成以下修复并重新验证：

- CIC 历史状态改为 80 个 RAM bank 与 96 个共享行有效位，保持 32 位回绕、复位后零值、调度和输出逐周期语义。独立 RTL 与真实厂商综合网表均完成 196,922 周期、597 帧、79 次复位等价验证；证据见 [CIC 实现评估](../../fpga/build/cic_ram_alternative/SYNTHESIS_EVALUATION.md)。
- 在帧 FIFO 与异步 FIFO 之间增加 100 位可反压样本寄存器，切开过长的 RAM 读写组合路径。新增检查验证 38,272 次传递与 56,091 个阻塞周期的全部字段守恒和稳定性；仅增加一拍传输延迟，不改变滤波相位或采样帧号。
- PDM 选择从逻辑第 18 拍后移至第 19 拍，解决旧路由下完整预算短缺 0.376 ns 的问题。本轮实际预算见上表。
- 启用器件支持的 route hold 修复，目标为正 20 ps，路径数量上限 50,000。它们是实现优化选项；原 SDC 时钟、接口预算及最终非负裕量要求未放松。

旧失败构建和源码快照保存在 [FF-CIC 失败归档](../../fpga/build/archive/20260916_051930_ff_cic_timing_fail/)：该轮 slow audio setup 为 −0.171 ns，并有负 hold 端点，发布检查正确拒绝生成位流。采样后移前主动停止的 RAM 构建保存在 [采样调整前归档](../../fpga/build/archive/20260916_090511_ram_before_capture_adjustment/)。这些历史记录不作为当前发布结果。

## 发布检查与复现

发布检查的 **88 项自测通过**，证据为 [审计自测日志](../../log/fpga_audit_unit_tests.log)。检查对原始报告中的已知诊断逐对象复核：四个硬时钟复位控制端无数据时序弧、三个实际已被 IO 约束引用的虚拟时钟、两个具有独立物理上限的生成时钟输出，以及零参考 min/max 相等提示。具体规则与反例测试见 [RELEASE_CHECK.md](../../fpga/scripts/RELEASE_CHECK.md)；未按消息编号批量忽略，也未豁免任何负裕量。

实际顺序为主 PDS 完成到 STA → 从同一布线数据库导出双角网表/SDF → 生成前检查 → 生成位流 → 最终发布检查。每个完成标记都对应原生命令成功退出；构建脚本、源文件、回归、报告、网表、数据库和位流均有来源记录与 SHA-256。

在工程根目录复现：

```powershell
python sim/verify_all.py
python fpga/scripts/build.py --stage gen_bit_stream
```

修改 RTL、系数、约束、验证代码或厂商工具版本后须重新验证并构建；不能沿用本报告的 PASS。安装路径可用 `--pango` 或 `PANGO_INSTALL` 设置，已有许可证用 `PANGO_LICENSE_FILE` 或 `--license-file` 指定。下载和采集操作见 [上板指南](../board_bringup.md)。
