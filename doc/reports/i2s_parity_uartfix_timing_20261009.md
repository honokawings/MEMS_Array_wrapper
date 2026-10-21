# UART 修正版时序失败记录

核对日期：2026-10-09。构建目录：`MEMS_Array_i2s_parity_uartfix_20261009`。

**本版未发布、未生成位流、未下载。** 完整功能回归通过，但真实布局布线的 setup 检查失败。发布检查正常阻止位流生成；板上仍是[第一版](i2s_parity_20261009.md)。

## 已完成的验证

| 检查 | 结果 |
|---|---|
| 完整功能回归 | 修改前 17/17 PASS，包含实际 PDS UART 技术网表的全 128 通道验证 |
| 发布检查器测试 | 188/188 PASS；厂商 `V_BUF` 的输出端口按真实模型修正为 `Z`，未放宽寄存器或时钟要求 |
| 最终慢角/快角实际网表 | 六个配置 CDC 寄存器及七个可变通道寄存器结构检查 PASS |
| 系统物理时序 | FAIL，最终正式报告仍有 4 个慢角 setup 违例 |
| 位流/JTAG | 未执行；位流目录没有 `.sbit` |

功能回归与物理时序是不同检查。寄存器结构通过不能替代时序，也不能代表新版本已经在板上运行。

## 实际时序结果

| 布线轮次 | 慢角 audio122 最差 setup | 失败端点 | TNS |
|---|---:|---:|---:|
| 首轮 | −0.067 ns | 4 | −0.170 ns |
| 第二轮 | −0.152 ns | 3 | −0.341 ns |
| 工具最终选用的首轮 | −0.067 ns | 4 | −0.170 ns |

两轮均完整布通，但都未满足 setup。两角 hold 检查通过。工具正常选回较优首轮，并导出正式报告、慢角和快角网表；随后位流生成前的检查拒绝该构建。

首轮失败路径包括补偿模块的通道索引到乘法器输入，以及 FIR2 的组选择到历史 RAM 写数据。连线占路径延迟约 89%～95%。补偿读取寄存器已被映射为乘法器输入寄存器，流水存在；问题是大型选择网络与长连线。

## 后续修正

新候选为 `MEMS_Array_i2s_parity_timingfix_20261009`：补偿读取拆为分组选择流水，FIR 写数据先暂存、最后一组真正提交后才启动新运算。新增独立真实 RAM 写读测试，列为强制第 18 层。

后续必须重新完成全部 18 层回归、真实双角时序及发布检查，才可生成位流、通过 JTAG 下载并进行全通道板测。本记录不能作为新候选的通过证据。

## 原始证据

- [失败构建清单](../../fpga/build/MEMS_Array_i2s_parity_uartfix_20261009/manifest.json)与[位流前检查](../../fpga/build/MEMS_Array_i2s_parity_uartfix_20261009/pre_bit_check.json)。
- [最终正式时序报告](../../fpga/build/MEMS_Array_i2s_parity_uartfix_20261009/report_timing/mems_array_pg2l200h.rtr)。
- [独立实际网表审计](../../log/i2s_parity/physical_audit_uartfix_20261009.json)。
- [归档的 17 层回归清单](../../log/i2s_parity/full_regression_uartfix_20261009.json)。
- [188 项检查器原始日志](../../log/i2s_parity/uartfix_vbuf_checker_all_tests.log)。
- [修改前受测输入归档](../../log/i2s_parity/uartfix_before_timing_pipeline_20261009.zip)：105 个输入文件均核对 SHA-256，归档 SHA-256 为 `4681ce028138326f8e8cc8df9de37c448b05bfc487a48d6c121f958db5f4ec62`。

DATA1 对应通道 2/3 的真实输入异常、板上电压实测、DAC 模拟输出与声学校准仍待处理，不能由数字自测替代。
