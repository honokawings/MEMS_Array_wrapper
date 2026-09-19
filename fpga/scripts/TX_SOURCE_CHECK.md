# RGMII TX 源端证据与工程发布范围

`check_tx_source.py` 使用同一次布局布线的原始 `rtr.db`、约束、双角 SDF 和双角仿真网表，结果写入 JSON。`PASS` 的范围固定为 `engineering_board_bringup`，且 `unconditional_board_qualification=false`，不能解释为已经完成实板电气认证。

```powershell
python fpga/scripts/check_tx_source.py --report-db fpga/build/MEMS_Array/report_timing/rtr.db --constraints fpga/constraints/timing.fdc --slow-sdf fpga/build/MEMS_Array/clock_audit/slow_sta.sdf --fast-sdf fpga/build/MEMS_Array/clock_audit/fast_sta.sdf --slow-netlist fpga/build/MEMS_Array/clock_audit/slow_sim.v --fast-netlist fpga/build/MEMS_Array/clock_audit/fast_sim.v --output fpga/build/MEMS_Array/clock_audit/tx_source.json
```

## 同沿引脚偏差

TXC、TXCTRL 和四根 TXD 全部为普通输出端点，使用周期 8 ns、相位 0 的虚拟 `tx_pad_ref`，双边输出延迟均为 0。工具原生 `set_max_skew` 分别检查源时钟的上升沿和下降沿，门限 0.400 ns；软件另行对四个角/沿组合、每组最大/最小各六端口核对完整路径。

软件使用实际到达时间之差减去该路径对的 `Relative CPR`，强制物理偏差不超过 0.300 ns。外部 PCB 相对偏差另留 0.200 ns，与 RTL8211F 数据手册 Table 60 的源端 0.500 ns 要求衔接。原生报告中的两项 ±0.050 ns 公共源抖动必须逐条存在且符号正确；只有实际计算和原生数值相差恰好 0.100 ns 才接受。未知误差项、缺 TXC、缺一个角/沿、非共同源、裁掉时钟树都会拒绝。

`set_max_delay 2.500 -datapath_only` 限制 ODDR 至引脚的物理路径，并替代无实际外部捕获时钟的虚拟 setup 关系。PDS UG §6.5.1 明确指出该选项也会停止相应普通 hold 分析；因此这里的最小物理路径由原生 MaxSkew 的 min 组及软件重算覆盖，不能宣称普通 TX hold 仍在检查。真实探针证实该 max-delay 不会删掉独立 MaxSkew 表内的完整时钟树和 CPPR。

原始 `.rtr` 文本可能显示 `All Constraints Met`，同时 XML 的 MaxSkew 表仍有失败。因此门禁必须读取原始 `rtr.db`，不能只读文本摘要。

## TXC 占空比

核心板 U7 型号 `OB3225125MLDB6SI-00`，所属 YSO230LR 系列的厂家输出对称性保证为 45–55%。直接用 ODDR 转发正负沿会叠加 FPGA 输出传播差，已有慢角反例；单纯 `create_clock` 默认 50% 不能证明实板时钟合格。

最终结构为 125 MHz 输入 → GPLL 250 MHz → `GTP_IOCLKDIV_E2` 单上升沿二分频 → BUFG → TX ODDR。检查器从真实网表验证 PLL 比例 I=4、M=16、F=2、O=4、OPTIMIZED 带宽、二分频、CE 常 1，以及 TXC 的 D0=1、D1=0；沿着同一实际连接提取 SDF 延迟。2026-09-18 修正旧 I=1/M=4 的 PFD=125 MHz 与 OPTIMIZED 带宽组合不合规问题，新 PFD=31.25 MHz 已通过安装的厂商 IP 校验和独立诊断实板测试。两次相邻 250 MHz 上升沿分别产生 TXC 上升/下降，分频前公共路径都使用相同输入极性，不能沿用 XML 中抽象的振荡器下降沿。

`duty.nominal_model_status` 检查双角实际可达传播延迟形成的名义占空比。所有已知 STA、物理偏差、名义占空比违规都会拒绝工程发布。`duty.required_edgepair_jitter_max_ns` 给出满足 45–55% 所允许的额外边沿对误差上限。

DS04001 的 `TOUTJIT=180 ps` 没有定义为周期抖动、相位误差、峰峰值或 RMS。检查器完整保留一个附加敏感性分析：假设每个边沿误差为 ±180 ps，枚举相邻三个边沿的八种极值组合。高宽为 `4 ns + DCD + e1 - e0`，实际周期为 `8 ns + e2 - e0`，从而避免在分子与分母重复独立取最坏值。该分析的 `FAIL` 保留在 `duty.conservative_jitter_sensitivity`；其未定义的指标假设不作为已知器件必然违规，也不被删除或改为通过。

工程发布必须保留 `duty.qualification_status=UNCONFIRMED`。厂家抖动指标口径、实际负载下 TXC 占空比及上升/下降时间仍需实板确认。SDF 的 IOPATH 是传播延迟，不能冒充 RGMII 规定的 20%～80% 上升/下降时间（最大 0.75 ns）。

## 已完成的限定探针

八个 TXC-only 驱动/转换速率候选均已真实布局布线并取得独立快、慢角 SDF。其它五根 TX 固定为 16 mA FAST。只有六根全部 16 mA FAST 同时满足名义 duty、物理偏差及 2.5 ns 内部路径约束：

| 指标 | 慢角 | 快角 |
|---|---:|---:|
| TXC fall-minus-rise | −0.092 ns | +0.129 ns |
| 名义占空比 | 48.8500% | 51.6125% |
| 六引脚物理偏差最大值 | 0.279 ns | 0.265 ns |
| ±180 ps/沿敏感性最差占空比 | 44.3500% | 56.1125% |

额外边沿对误差余量为 0.271 ns；最大内部输出路径 1.977 ns。完整比较保存在 `fpga/build/txc_electrical_probe/final_comparison.json` 和 `comparison.md`。这些是小探针结果，最终发布必须重新审查完整工程同一数据库，不能复用小探针通过结论。

解析器回归：`python -m unittest discover -s fpga/scripts/tests -p test_check_tx_source.py -v`。测试中的合成 XML/SDF 只验证解析、覆盖和拒绝行为，不是 FPGA 时序证据。

来源：[YXC YSO230LR](https://yxcxtal.com/product/yso230lr.html)、[Pango DS04001 V2.1 Table 4-4](https://www.pangomicro.com/en/uploads/13964872_1729131653.pdf#page=32)，以及本地 PDS UG §6.2.4/§6.5.1、RTL8211F-CG Table 60、核心板原理图。
