# UART 完整系统布线耗时诊断

2026-09-19 最终结果：`MEMS_Array_uart_chain8` 已生成工程上板位流，[最终发布检查](../../fpga/build/MEMS_Array_uart_chain8/release.json) 为 PASS。完整 PNR 33 分 58 秒，双角时序及物理接口预算通过。本记录保留诊断过程；各历史中止/失败版本不能作为下载版本。

## 观察到的异常

旧 `MEMS_Array_selftest` 在相同器件和 `performance` 策略下完成布局布线约需 20 分钟。新 `MEMS_Array_uart` 的布局在 202.69 秒结束，但随后详细布线单轮耗时逐步升到约 110～135 秒，个别轮达到 238 秒。旧版相近阶段约 10～15 秒。新设计只是从约 56,475 条一般网络增加到 61,074 条，不能仅以规模增长解释这个量级的变化。

首轮新构建在保存日志和清单后于 00:11 中止，保留 compile/synthesize/map 和完成的布局数据库。构建清单正确记录 FAIL，未生成或发布新位流。证据目录：[slow_route_20260919](../../log/system_uart/slow_route_20260919)。

## 已排查

- 逻辑资源不是容量瓶颈：LUT 21%、FF 13%、DRM 14%。
- 采样时可用内存约 10 GB，PDS 缺页计数没有增长；未见内存换页导致的停顿。
- 进程 CPU 亲和性允许全部 20 个逻辑处理器，优先级 Normal。CPU 性能计数约为基准频率的 131%～135%，未见降频证据。
- 布线配置为 5 个工作线程。慢轮采样时一个布线工作线程占满单核，其余等待；不是主线程持续执行 STA。尚未取得逐函数 CPU 栈，不能直接将其归为工具缺陷。
- 新旧布局后的最差预估 slack 均为 −376 ps，TNS 均为 −1880 ps。对新布局单独导出时序报告，新加的八个 UART CDC 方向均有较大正的 Setup 预估裕量（最小约 6.36 ns），没有发现新增 CDC 被错误要求作极小周期同步收敛的证据。这是布局估计，不能替代布线后时序。

## 拥塞网络证据

诊断 A 使用同一个已完成布局数据库，所有 RTL 和约束保持不变，只开启 `-dump_router_congestion_plot TRUE`，并设置 5 分钟动作超时。前几轮网络数与原慢运行完全相同，复现了原布局的布线过程。

在 `CongestionNetInfo_4.txt` 中，按每条网络的 congestion value 累加：

| 模块 | 指标之和 |
|---|---:|
| FIR2 | 20,274 |
| FIR1 | 20,203 |
| 校准 | 12,556 |
| CIC | 5,700 |
| 输出 FIFO | 4,265 |

全部 UART 相关网络仅占该轮指标的约 1.684%。主要高值网络包括 `fir2/N9979`、`calibration/N729`、`calibration/N743`、`fir1/final_valid` 以及输出 FIFO 写地址。它们与综合网表中的大扇出控制/选择网络对应；原 FIR/校准逻辑在新旧综合网表中均存在相同的大扇出结构。

这里的指标之和不是不同物理冲突节点的数量，不能与日志中的 overused 数直接等同。原始文件位于 `fpga/build/uart_route_diagA/place_route/CongestionNetInfo/`，机器可读统计见 [congestion_analysis.json](../../log/system_uart/congestion_analysis.json)。

现有证据将重点指向布局导致的局部拥塞。新增 UART 改变了全局布局结果，但不应据此删除 UART 或放宽 CDC/网口时序约束。

## 对照运行

诊断 B 复用同一 map 数据库，从布局开始，只将 `-plc_decongestion` 从默认 1 调至 3；其余时序目标、hold 修复阈值及功能逻辑保持不变。开启拥塞明细，设置 15 分钟动作超时，结束后执行双角时序分析。目录 `fpga/build/uart_route_diagB`。

PDS 本机用户手册的 Place & Route 章节说明，该选项扩大布局范围以降低局部密度，可能改善布线速度，同时可能影响时序。因此必须同时比较布线速度、拥塞与最终双角时序，不能仅凭运行更快认定成功。

诊断 B 的前四轮一般网络布线耗时为 8.082、8.979、14.739、102.295 秒，比原布局更早进入慢速搜索，00:23 主动停止；停止导致的 `Flow-0189` 是被终止进程的结果，不能据此认定自然发生了工具崩溃。此策略不采用。

进一步追踪综合网表：校准的 `N729` / `N743` 分别是正向/负向饱和判断，参与约 3,000 个输出相关负载；输入锁存、FIR 结果写回等也有数千负载的使能网络。开始诊断 C：仅使用厂商支持的 `synthesize -fanout_guide 256`，先检查综合是否减少大扇出，确认生效后才运行布线。RTL、算法、处理时延和所有时序约束均保持不变。目录 `fpga/build/uart_fanout_probe`。

确定实现策略后，正式构建仍需完整源文件冻结、两角物理预算和最终 release 检查；诊断结果不会直接冒充发布产物。

## 扇出优化的网表验证

诊断 C 的 compile/synthesize/dev_map 在 4 分 9 秒完成。综合网表确认 `N729` 从 3,073 个输入引脚连接分为每个副本最多 256；`N743` 从 2,946 降为每个副本最多 256。部分地址选择网络也被复制。详细比较见 [fanout_comparison.json](../../log/system_uart/fanout_comparison.json)。同步控制网络仍可能保有较大扇出，因此该参数并不意味着所有物理网络都被硬限制为 256，最终效果需布线验证。

00:29 起，正式构建 `MEMS_Array_uart_fan256` 从 compile 重新开始，采用 `-fanout_guide 256`；布局去拥塞恢复默认 1。保持全部原时序约束，加入拥塞明细与 30 分钟 PNR 超时。不会将独立诊断 C 的 map 结果直接包装成发布结果。

## 控制引脚需要显式约束

`MEMS_Array_uart_fan256` 的一般网络布线第 10、11、12 轮耗时分别达到 52.863、102.651、164.068 秒。拥塞明细仍以 FIR/校准的输入锁存使能、结果有效信号和同步清除为主。该运行在保存日志后于 00:45 中止，未生成位流；证据目录 `log/system_uart/slow_route_fan256/`。

随后用同一版本 ADS 对 64 位寄存器做独立对照：仅设置 `-fanout_guide 8` 时，CE 网络仍有 64 个引脚负载；对驱动网显式设置 `syn_maxfan=8` 后，变为 8 个副本、每个 8 个负载。对同步清除和寄存器生成的 valid 信号也验证了显式属性有效。组合网络需配合 `syn_keep=1` 保留边界，否则逻辑合并可能消除属性作用点。

原始实验位于 `fpga/build/fanout_semantics*` 和 `fpga/build/fanout_controls`；日志位于 `log/system_uart/fanout_*.log`。本机 ADS 手册的 `syn_maxfan` 章节说明显式属性优先于全局 Fanout Guide，且不适用于时钟和异步复位。这里限制的是同步控制信号。

RTL 调整：FIR 输入锁存/结果有效/同步清除，校准输入锁存/结果有效/同步清除，CIC 流水有效信号，以及每个帧 FIFO bank 的写使能显式设置 256 扇出上限。FIFO 的逐 bank 写条件与原动态索引写等价；没有增加流水级或改变采样调度。新的功能回归与综合网表检查均须通过后再继续物理实现。综合网表诊断入口为 `fpga/scripts/report_control_fanout.py`，其引脚连接统计不能代替布线后的物理时序检查。

第一轮控制属性综合在 `uart_control_probe` 完成，功能回归 12 项 PASS。FIR/校准的输入捕获和结果 valid 的 CE 最大引脚负载从 4,096 / 3,072 降到 256；同步清除也已复制，校准单个副本在后续优化后为 267，说明属性是综合优化目标，不能把它当成所有阶段严格不超限的保证。该版 FIFO 的逐 bank 写法让 1,568 个 LUTRAM 变成 12,544 个寄存器，因此不采用该写法做物理实现。

最终修订保留原动态索引、单写端口 RAM 模板，仅将 `rst_n && push_frame` 命名为带属性的 `write_enable`。独立 64 位 RAM 综合实验确认保留 32 个 `GTP_RAM32X2DP`，WE 从一个大扇出驱动拆为四个各 8 负载的驱动，见 `fpga/build/fanout_ram`。同时限制 FIR 其余流水有效信号与最终乘积提交使能，并对 CIC 同步清除作同类处理。当前正式构建为 `MEMS_Array_uart_ctrl256`，重新运行完整功能回归；尚不能据此声明布线或位流已通过。

`MEMS_Array_uart_ctrl256` 的整机综合网表已核验：输出 FIFO 保留 **1,568 个 `GTP_RAM32X2DP`**，没有逐 bank 展开造成的 12,544 个寄存器。主要 CE/WE 网络的结果如下，数值是每个综合网络的引脚连接数，复制后列取各副本中的最大值：

| 网络 | 仅全局 guide | 显式控制属性 |
|---|---:|---:|
| FIR2 输入捕获 CE | 4,096 | 256 |
| FIR1/FIR2 结果提交 CE | 各 4,096 | 256 |
| 校准输入捕获 CE | 4,096 | 256 |
| 校准输出 valid CE | 3,072 | 256 |
| FIFO RAM 写使能 WE | 256 | 256 |

FIFO 的 WE 在全局 guide 方案中已被复制；本次显式属性保留这一效果。原始无 256 guide 的 FIFO 有 1,568 个 RAM 写使能负载，不应将它误作为“仅全局 guide”列的值。

全部 12 项功能回归再次 PASS，98 项发布检查器测试 PASS；正式构建输入和本轮回归的 RTL 哈希一致。详见 `log/system_uart/control_fanout_before.json`、`control_fanout_final.json`、`control256_regression.log` 和 `control256_checker_tests.log`。物理效果仍以本轮路由结果为准。

## 剩余慢迭代的隔离

控制属性版资源为 FF 41,284、LUT 33,778、DRM 54.5。相对仅全局 guide 版增加 74 个 FF、185 个 LUT，RAM 不变。第 10、11 轮为 29.611、60.975 秒，较仅全局 guide 的 52.863、102.651 秒改善，但仍异常。原先高值的 FIR/校准控制网络已从拥塞榜首消失，最大的剩余项为 FIFO 写使能。因此，大扇出是已解决的一部分，不能宣称它是全部耗时原因；该轮已保存布局并停止。

之后的路由对照都复用 `MEMS_Array_uart_ctrl256` 的同一个 map/placed 数据库，无需重复综合布局，也没有修改 RTL/约束。每个诊断动作设 5 分钟上限，出现与慢基线相同趋势时提前停止：

| 目录 | 单一调整 | 结果 |
|---|---|---|
| `uart_ctrl_normal` | mode=normal | 第 6～10 轮网络/冲突数与 performance 完全相同，第 10 轮 30.234 秒；未改善 |
| `uart_ctrl_nochain` | 关闭控制信号共享链 | 第 10 轮 28.699 秒、冲突 146,530；未见明显改善 |
| `uart_ctrl_weight30` | slack_weight=30（默认 90） | 第 10 轮 35.779 秒、冲突 140,708；未改善早期耗时 |
| `old_route_benchmark` | 原成功版 map/placed 数据库在当前机器复跑 | 第 10 轮 12.466 秒，原记录 12.536 秒；网络/冲突数逐轮一致 |
| `uart_ctrl_cost100` | pin_cost_increasing_speed=100（默认 300） | 单轮较快但收敛较慢；到第 14 轮约 134,986 冲突时累计一般路由约 145 秒，默认约 134,205 冲突时约 125 秒；不采用 |

`slack_weight` 是工具搜索时对时序因素的权重，不改变任何 SDC 路径上限；即使搜索更快，最终仍须通过相同的双角时序和物理接口预算检查。上述被主动终止运行尾部的 `Flow-0189` 均为终止进程的结果，不能将它们写成工具自然崩溃。

旧版在当前环境的复跑与原成功日志一致，比仅检查 CPU/内存指标更直接地支持“当前机器运行速度基本正常”。当前重点是新布局的拥塞搜索行为，不能只因为高扇出属性生效就宣称整个异常已经解决。`pin_cost_increasing_speed` 控制拥塞端口代价的增长速度；调整它也不改变时序要求。所有路由对照可用 `python log/system_uart/routing_comparison.py` 汇总，脚本不会把冲突数量误当作任务完成百分比。

## 复用已成功实现的 FIR 宏布局

使用 PDS `generate_constraint` 从旧成功版 routed DB 导出 APM/DRM 位置。新旧 APM 的自动编号并不相同，因此通过 FIR 的 lane/product 输出身份逐一匹配，再验证两组乘法输入总线相同；48 个历史 RAM 的实例身份和原语类型也一致。派生脚本为 `log/system_uart/derive_legacy_floorplan.py`，对应关系及输入哈希在 `fpga/build/uart_legacy_floorplan/floorplan_identity.json`，源约束为 `fpga/constraints/frontend_floorplan.pcf`。

PDS 的 `add_constraint *.pcf` 指定的是映射后的物理约束文件；`dev_map` 会重写它。最初直接在 map 前加入 PCF 的尝试没有保留宏位置，已停止，不算有效布局对照。有效对照在 map 结束后追加位置，并在新的 PNR 进程中显式选择该 PCF。日志 `route_legacy_pcf_selected.log` 确认 **176 条 def_inst_site 全部被实际接受**。

| 一般路由轮次 | 未固定宏位置的同一 RTL | 复用旧 FIR 宏位置 |
|---|---:|---:|
| 10 | 29.611 s | 7.746 s |
| 11 | 60.975 s | 8.900 s |
| 12 | 已停止继续等待该慢轮 | 10.846 s |
| 13 | — | 14.044 s |
| 14 | — | 16.639 s |
| 15 | — | 17.738 s |
| 16 | — | 19.953 s |

到第 16 轮，冲突数降至 69,629；第 18 轮后诊断按预设 8 分钟动作上限退出。这个结果支持宏布局影响了搜索耗时，但不代表已完成路由或时序通过。

正式构建 `MEMS_Array_uart_floorplan` 从 compile 重新开始，使用相同策略。`build.py` 把 compile/synthesize/dev_map 与 pnr/report_timing 分为两个真实 PDS 进程，并以 map、原始 PCF、追加后 PCF 的哈希衔接，完整保留原来的双角、CDC、PDM、RGMII 和位流门禁。检查器增加 8 项相关正反例，总计 **106 PASS**。正式版本已复现对照的布局校验值 `2129E2369675BA49` 和 SA cost `7692598.218978`；实际中间文件衔接检查 PASS、构建输入哈希未变。最终路由和发布结果仍待完成。

## 完成路由后的时序定位

上述正式构建于 02:16 完成 PNR：一般网络第 180 轮清零，常量网络处理后第 183 轮全部清零。详细布线 1242.77 秒（20 分 43 秒），全部 routing 1311.48 秒，整个 PNR **26 分 53 秒**。此前未经优化的 UART 版运行近一小时仍未完成；新布局已解决百秒级单轮搜索，但路由完成不等于时序通过。

实际双角 RTR 的音频域慢角有 **12 个 setup 违规端点，WNS=-0.653 ns、TNS=-2.777 ns**。其余时钟组 setup 与 hold 检查通过。前八条报告路径均由 FIR2 `product_valid` 经组合 `finish_product`、多级 CECO 链到 `final_sum` 的 CE。最差路径的数据部分为逻辑 2.863 ns、布线 5.027 ns。预位流检查据此返回 FAIL（`RTR reports violated constraints`），没有生成位流；原始失败证据完整保留在 `MEMS_Array_uart_floorplan`。

修正将 `finish_product` 改为寄存器，在已有 middle 流水级计算 `middle_valid && middle_last`。它与下一拍原有 `product_valid && product_last` 等价，去掉写使能路径上的组合译码，不增加滤波延迟，不修改频率或时序例外。修正后的完整 12 项功能回归 PASS，日志 `log/system_uart/finish_retime_regression.log`；后续仍须验证实际综合驱动、宏身份映射和重新布线结果。

## 控制链长度对照

寄存写使能版 `MEMS_Array_uart_retimed` 确实生成每个 FIR 5 个独立 FF 驱动（最多 256 个 CE 负载），APM 和历史 RAM 身份也已重新核对。但新布局的路由后半程持续约 30～39 秒一轮；PNR 运行约 34 分钟时仍有约 6,000 个连接未完成，因此于 03:03 主动中止，没有生成位流。停止后的 `Flow-0189` 是人工终止结果，不是自然工具崩溃。该方案未采用；其 RTL、PCF、构建脚本和通过的回归已保存于 `log/archive/retime_attempt_20260919/`。

PDS 本机手册提供 `-max_ctrl_chain_length`（CE/RS 控制信号链最大长度），默认值 500。新的对照 `uart_floorplan_chain8` 直接使用已完成布线版的 map/placed 数据库，仅将该上限设为 8，保持所有时钟及 I/O 时序要求；输出位于独立目录和 `log/system_uart/route_floorplan_chain8.log`。它不是发布构建，不能将诊断数据库直接作为已验收位流。

正式构建为 `MEMS_Array_uart_chain8`：恢复与已完成布局版逐字节相同的 FIR RTL 和宏位置模板，仅在物理实现中限制控制链长度，重新从 compile 开始。完整 12 项功能回归和 106 项检查器测试通过，日志分别为 `chain8_regression.log`、`chain8_checker_tests.log`。诊断与正式构建部分并行，绝对耗时可能受到资源竞争影响；最终仍按完整收敛、双角时序和接口物理预算验收。

![布线迭代耗时对照，按图中更新时间解释](../../log/system_uart/routing_progress.png)

独立控制链长度对照于 03:31 完成，RTR 为 **All Constraints Met（双角）**。音频域慢角 setup 从 -0.653 ns 改为 **+0.076 ns**，违规端点从 12 降到 0；慢角 hold 为 +0.092 ns，快角 setup/hold 分别为 +1.667/+0.020 ns。新的最慢路径为 FIR1 `write_group[2]` 到 lane14 历史 RAM 数据输入，已不包含 CECO 链。详细布线耗时 1666.62 秒，全部 routing 1743.07 秒；它复用了已完成的布局，因此该耗时不能当作完整正式构建时间。

## 最终发布

完整正式构建于 03:47 完成，最终 `release_authorized=true`。PNR **33 分 58 秒**，其中详细布线 1657.39 秒、全部 routing 1727.22 秒。一般网络第 200 轮清零，常量网络处理后第 203 轮全部清零；各轮未完成连接/冲突数与独立对照一致。正式双角时序复现上述裕量，RGMII 实际最大偏差 0.279 ns（上限 0.300 ns），PDM 最小预算余量 8.349 ns，95 管脚及全流程哈希衔接检查通过。

下载文件：[mems_array_pg2l200h.sbit](../../fpga/build/MEMS_Array_uart_chain8/generate_bitstream/mems_array_pg2l200h.sbit)，9,188,552 字节，SHA-256：`f8c38ae04039572f3efec5a593cc4b1089eed69c4975dbfb0e9c2e7a991a03d7`。本次未放宽时序要求，没有采用寄存写使能版本，也没有将诊断数据库直接当作发布产物。

该发布范围为工程上板联调，实际 TXC 占空比/抖动及完整 PHY/MDIO → ARP → UDP 实板验收仍需新位流下载后的测量。详见 [实现报告](uart_system_implementation.md) 和 [UART 联调步骤](../system_uart_debug.md)。
