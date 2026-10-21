# 启动 DC roundsat seed3：发布与实板验收

核对日期：2026-10-11。**`MEMS_Array_i2s_parity_dc_roundsat_seed3_20261009` 已完成严格发布、JTAG SRAM下载和A–F数字验收，是前一16-lane基线。** 独立验收为`PASS_WITH_KNOWN_ISSUES`：DATA1/ch2、3固定负满量程故障保留，电气、DAC模拟与声学校准未完成。当前已下载版本改为[FIR8](i2s_fir8_auto_20261011.md)，其本次A–E数字验收通过，联合结果为PASS_WITH_KNOWN_ISSUES；F真实采样连续，DATA1/ch2、3及物理未测边界保留；本报告仍只记录seed3实际结果。

## 位流与验证身份

| 项目 | 实际记录 |
|---|---|
| 器件 | PG2L200H，JTAG index0 ID `0x00603899` |
| 位流 | [mems_array_pg2l200h.sbit](../../fpga/build/MEMS_Array_i2s_parity_dc_roundsat_seed3_20261009/generate_bitstream/mems_array_pg2l200h.sbit)，9,188,552 bytes；SHA-256 `60ecd3f36daee11bdcf6c22810d611396347a6e730384cffbe62ce09d3f285c7` |
| 构建 | [manifest](../../fpga/build/MEMS_Array_i2s_parity_dc_roundsat_seed3_20261009/manifest.json) PASS，exit0，2026-10-10 01:32:54完成，sources_unchanged=true |
| 回归 | [不可变18/18](../../log/i2s_parity/full_regression_dc_roundsat_20261009.json)，104项验证输入、22份向量；SHA-256 `6a83d8e7941a9132c4a217bb76c5f80df639bd7e4ad92b4ccbfeda1bbb964f30` |
| 发布 | [release.json](../../fpga/build/MEMS_Array_i2s_parity_dc_roundsat_seed3_20261009/release.json) PASS / release_authorized=true；范围 engineering_board_bringup |
| 下载 | [download.json](../../log/i2s_parity/jtag_dc_roundsat_seed3_20261009/download.json) PASS；2026-10-11 14:55:41，mode=JTAG_SRAM，未写Flash，读回状态 `0x081ffca0` |
| 实板验收 | [独立DC验收](../../log/i2s_parity/dc_roundsat_seed3_hardware_acceptance_20261011.json) PASS_WITH_KNOWN_ISSUES，digital_acceptance_pass=true，failures/pending_reasons为空；SHA-256 `6d562f4c2ffffb7579f1a99abd317dd3f6b65e4c70abd4639601207e1b4349ba` |

[下载前独立身份核对](../../log/i2s_parity/dc_roundsat_seed3_readonly_identity_recovery_20261011.json)确认当时38项生产输入、104项验证输入及22份向量全部匹配。[A–E外层执行记录](../../log/i2s_parity/dc_roundsat_seed3_hw_20261009_outer_invocation/result.json)绑定实际命令、起止时间、exit0及46个所属原始文件；F独立记录其后实际捕获及分析。通过结论来自本次新映像，不继承旧B记录，不使用mtime作为执行证明。后续源码修改须另行验证。

## 首轮布线与严格时序

本候选使用seed3、Center、decongestion5。原生[首轮日志](../../fpga/build/MEMS_Array_i2s_parity_dc_roundsat_seed3_20261009/place_route/route_constraint_ite_1/run.log)记录完整路由成功、数据库保存，用时 **2小时23分2秒**，2026-10-10 01:27:09完成；其中 detailed routing为8,360.84秒。最终快/慢角setup、hold、recovery、removal与minimum pulse width均通过原发布门禁。

| 最小裕量 | Slow | Fast |
|---|---|---|
| 全域setup | +0.140 ns | +0.387 ns |
| audio122→audio122 setup | +0.190 ns | +1.909 ns |
| 全域hold | +0.057 ns | +0.020 ns |

用户允许单候选一次完整布线，并将setup≥−0.20ns、hold≥0作为工程测试范围；**本位流实际通过严格非负时序，无需采用负setup许可**。旧DC负时序FAIL与seed2布线超时FAIL仍保留，不追改为成功，见[版本历史](version_history.md)。PDS模型通过不等于实板TXC/PDM/I2S波形已经测量。

## A–F 实际结果

| 阶段 | 结果与证据 |
|---|---|
| A：UART配置 | [137案例PASS](../../log/i2s_parity/dc_roundsat_seed3_hw_20261009/A/summary.json)，128/128通道实际选通；requested/desired/active一致，fresh、无pending、计数进展，OFF/非法命令/增益/复位重放及恢复通过 |
| B：真实组零增益 | [PASS_WITH_KNOWN_ISSUES](../../log/i2s_parity/gain_zero_dc_roundsat_seed3_hw_20261009.json)；even=0稳定48,012帧，odd=0稳定144,087帧，各零组64路每个样本严格0，另一组存在非零；原DATA1故障保留，finally恢复unity |
| C：PHY/MDIO→ARP→UDP | [BIST PASS](../../log/i2s_parity/dc_roundsat_seed3_hw_20261009/C/pcm_verified.json)，578,691帧、74,072,448样本匹配独立16帧oracle，错帧/错误标志/连续性及主机采集错误为0 |
| D：I2S内容与BIST旁路 | [128/128通道PASS](../../log/i2s_parity/dc_roundsat_seed3_hw_20261009/D/uart/summary.json)，每路≥4快照且≥2不同LastPcm，属于该通道16个独立值；配置0.5/0.75时BIST实际unity内容相符，稳态欠载不增，UART内容测试19.444秒。[并行UDP](../../log/i2s_parity/dc_roundsat_seed3_hw_20261009/D/pcm_verified.json)比较430,055,424样本PASS；计数不作为绝对PCM帧号 |
| E：退出及恢复 | [PASS](../../log/i2s_parity/dc_roundsat_seed3_hw_20261009/E/summary.json)，实际r回到real，unity与I2S0/启用恢复，两次fresh GAIN查询相符；27条DC就绪SYS3，启用/审核完成/有拒绝均true，stickyCLIP保留 |
| F：真实unity采样 | [PASS_WITH_KNOWN_ISSUES](../../log/i2s_parity/dc_roundsat_seed3_unity_20261009/analysis.json)，3秒144,156帧/48,052包，缺包/重复/乱序/主机队列丢弃/非法负载/未保存包为0；全部128通道统计已保存 |

C/D合计比较 **504,127,872个样本**。A–E实际执行为14:56:34至15:00:15，均exit0；F捕获15:00:56至15:00:59，分析15:01:28完成，执行记录分别为[execution_F](../../log/i2s_parity/dc_roundsat_seed3_unity_20261009/execution_F.json)与[execution_ANALYZE](../../log/i2s_parity/dc_roundsat_seed3_unity_20261009/execution_ANALYZE.json)。

## 已知故障与尚未验收范围

F中DATA1（J26/AC22）的ch2、3各144,156个样本全部为−8,388,608，min=max、ACRMS=0、rail=100%；全帧flags仅sticky saturation。其他UDP错误标志为0。DC拒绝位只表明至少一通道不合格，SYS3没有逐通道拒绝mask；不能仅凭它将某一路判为通过，也不能用DC归零掩盖当前故障。

启动DC位于奇偶增益之前，审核结束后冻结；unity不会关闭去DC，组增益0仍严格输出0。它利用稳定直流特性，并不根据手册−80/−40dBFS推出交流增益比；正常通道有数据也不证明全部64对AC幅值已配平。参考[音频操作指南](../audio_monitor.md)与[算法规格](../algorithm_spec.md)。

MEMS VDD/L6/L7 1.8V、I2S L5 3.3V、PDM满负载边沿/占空比、RGMII TXC duty/jitter/skew、PCM5102模拟输出及全部64对声学幅相仍待实测。发布qualification保留sensitivity FAIL和未确认的波形条件，unconditional_board_qualification=false；数字通过不改变这些边界。

## 后续源码范围

后续[FIR8](i2s_fir8_auto_20261011.md)六配置RAM11,435,616项和完整18层回归通过，实际APM68、FF47,953、LUT28,512。普通route入口失败已归档，从相同PLC恢复唯一1轮并64819/64819成功，严格发布及16:19:06 JTAG SRAM下载通过。新版本次A–E数字验收通过，联合结果为PASS_WITH_KNOWN_ISSUES；F真实采样连续，DATA1/ch2、3及物理未测边界保留。本报告seed3仍为16-lane、546/1058拍；FIR8为8-lane、1090/2114拍，共同延迟增加约13.02µs，不改变128通道或采样率。
