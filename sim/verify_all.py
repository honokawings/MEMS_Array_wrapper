"""Front-end, network, vendor UART, board primitive and host decoder regression."""
from pathlib import Path
import argparse,subprocess,sys,time,json,hashlib
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1]
LOG=ROOT/'log/full_regression'


def source_hashes():
    files=[]
    for folder in ['rtl','tb','lib/model','lib/cmodel','lib/host','sim']:
        files.extend(p for p in (ROOT/folder).rglob('*') if p.suffix in {'.v','.sv','.svh','.py','.cpp','.do','.ps1','.bat','.f','.bin'}
            and (p.suffix != '.bin' or folder == 'lib/host')
            and not any(part.startswith('work') or part=='__pycache__' for part in p.relative_to(ROOT).parts))
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(files))}


def write_report(result):
    labels={'frontend':'Python/C++ 模型、性能与前处理 RTL','parity':'启动直流估计、奇偶补偿与帧边界配置',
        'i2s':'I2S串行位序、全部通道与数字自检','audio_uart':'独立音频UART配置、查询与帧仲裁',
        'vendor_uart':'PDS UART 编译、综合、映射与厂商门级验证',
        'board_audio':'实际前处理到I2S、无网运行与奇偶配置','fir_arithmetic':'FIR 部分乘积、实际舍入饱和与寄存器写回',
        'fir_ram':'FIR 真实 RAM 写读、指针回绕与写暂存','phy':'位级 MDIO 与 PHY 配置',
        'ethernet':'Ethernet / ARP / IPv4 / UDP','transport':'异步 FIFO 与 PCM 打包',
        'boot':'板级校准启动与复位边界','core':'PDM 引脚到线上 UDP 完整链路',
        'host':'上位机协议、文件与 UDP 接收','host_rtl':'真实 RTL 数据包与 Cmodel 样本比较',
        'system_uart':'UART、MDIO、ARP、UDP 集成诊断','board':'Pango 厂商 PLL 与 DDR 原语','selftest':'按键、LED、内部 PDM 自测与线上样本校验'}
    rows='\n'.join(f"| {labels[name]} | PASS | {item['seconds']:.3f} s |" for name,item in result['steps'].items())
    host=json.loads((LOG/'host_rtl.log').read_text(encoding='utf-8'))
    vendor_uart=json.loads((ROOT/result['steps']['vendor_uart']['evidence']['path']).read_text(encoding='utf-8'))
    fir_arithmetic=json.loads((ROOT/result['steps']['fir_arithmetic']['evidence']['path']).read_text(encoding='utf-8'))
    fir_ram=json.loads((ROOT/result['steps']['fir_ram']['evidence']['path']).read_text(encoding='utf-8'))
    model_scope='复用此前已通过Python/C++逐位比对的参考向量' if result['models_reused'] else '重新生成系数、性能报告及Python/C++参考向量'
    report=f'''# 完整系统功能验证报告

生成时间：{result['completed_at']}。本次结果：**PASS**。完整运行入口为 `python sim/verify_all.py`。
原始证据位于 `log/full_regression/`；`log/full_regression.json` 保存每项结果、耗时和所有被测源文件 SHA-256，并检查运行前后源代码没有变化。
数值模型范围：{model_scope}。本次读取的参考向量文件也在摘要中记录校验和。
UART 厂商门级证据为 `log/vendor_uart/result.json`，其 SHA-256 写入本次 `steps.vendor_uart.evidence`；该证据另记录实际工具、厂商模型、构建脚本、数据库、网表和原始日志的校验和。
实际 FIR RAM 证据为 `log/fir_ram/result.json`，其 SHA-256 写入本次 `steps.fir_ram.evidence`；该证据绑定 RTL、测试、参考系数及原始日志，并记录六个实际配置的覆盖计数：原16路并行与单组配置保留，新增8路并行生产速率配置。
实际 FIR 舍入饱和证据为 `log/fir/round_sat_result.json`，其 SHA-256 写入本次 `steps.fir_arithmetic.evidence`；测试直接检查生产逻辑的饱和值、正负溢出、分组寄存器写回及控制边界。保留的旧 `rounded()` 函数测试单独记录，不能代替新组合逻辑验证。

| 层次 | 结果 | 实际运行时间 |
|---|---|---:|
{rows}

## 端到端验证

测试从64根真实双相共享PDM总线模型开始，经过128通道滤波/校准、异步FIFO、三帧打包、ARP及以太网发送，接收端独立核验IPv4/UDP校验和与Ethernet FCS，并按包内帧号查询Python/C++定点参考。

本次上位机解析真实RTL输出 **{host['packets']} 个UDP包、{host['frames']} 个采样帧、{host['samples_compared']} 个通道样本**，全部逐位一致。payload SHA-256：`{host['payload_sha256']}`。

便携网络内核默认 `INDEPENDENT_AUDIO=0`。其前两会话分别延迟 ARP 应答 0.65 ms、2 ms，验证等待期间不采集、ARP 自主重试，以及从第 96 帧开始连续输出且无溢出。第三会话在地址解析完成后人为阻塞发送端，保留整帧丢弃、帧号缺口、溢出状态、断线清空及重新启动的保护验证。各会话具体包数与缺帧统计见 `log/full_regression/host_rtl.log`。

板级完整系统设置 `INDEPENDENT_AUDIO=1`：真实麦克风前处理与 I2S 在无 PHY 链路或 ARP 对端时仍连续运行；网络 FIFO 等待 ARP 并在第一个完整 PCM 帧开始发送。内部 PDM BIST 保留网络门控以保持原参考序列和两级自测规则。独立板级音频测试还核验奇偶补偿配置、I2S 选通及网络断线后的持续听音。\n\n## 边界覆盖

- PHY：逐位MDIO、300ns返回延迟、地址扫描、配置读回、1000M全双工判定、EEE禁用及故障恢复。
- 网络：短包、MTU边界、校验和零值、CRC/IFG、坏ARP拒绝、链路中断和独立RX时钟停止期间复位。
- 打包与CDC：随机阻塞、Gray指针回绕、64位帧号间隙、24位正负极值、畸形帧恢复和待发送时复位。
- 板级控制：两条复位链错开3拍时仍完整写入128组非默认校准系数；音频停钟时掉线和PLL失锁重启。
- 校准运算：20,056个完整乘积的舍入/半LSB边界独立比较，以及实际128通道增益、偏置、饱和和调度异常检查。
- FIR 舍入饱和：直接检查生产输出组合逻辑与时钟沿写回，覆盖正负半值、32位饱和边界、有符号72位极值和原42位回绕规则，以及分组选择、无有效写入、复位、写回使能与sticky clip。实际计数与原始日志见绑定的独立证据；没有强制生产输出或溢出标志作为预期结果。
- FIR 存储：本次六个实际配置共 {fir_ram['checks']:,} 项检查。新增8路并行配置逐帧核对1090/2114周期延迟，原16路并行和单组配置保持。实际写事务的地址、数据与提交结果，使用独立输入历史核验 RAM 读数据与卷积；覆盖指针回绕、并行读写、单组配置及流水中断，不能用强制读操作数的算术测试代替。
- 自测：真实板级按键切换、内部 PDM 源、128 通道周期预期值、LED、断线重启、故障注入与上位机逐位比较；生产速率稳定段为 16,000 包/秒。自测通过计数与等待时间在仿真中缩短，采样及传输时钟保持生产频率。
- 奇偶补偿：增益拒绝、舍入与饱和、全128通道、帧边界切换和自测旁路；启动直流估计验证完整96帧跳过与4096帧估计窗、每通道正负偏置、冻结、超限/满量程/不稳定拒绝、窗口内增益变化和流水中断。使用33位差值后乘增益，禁止乘法前提前饱和。
- I2S：标准一位延迟、24位/32位槽、全部通道选择、时钟比与占空比、欠载归零、串行故障注入；板级验证校准后PCM实际流入I2S及无网运行。
- 音频UART：独立音频帧与SYS3共用串口，配置/查询帧不交错，非法输入拒绝，配置跨时钟域握手；协议和实板模拟输出资格分别验证。
- 上位机：Python 协议/接收检查，以及独立音频 UART 的真实 RTL 日志解析和无串口会话测试；严格比较请求、期望配置和实际配置，拒绝陈旧、未应用、错误或队列溢出的回应，并检查单次打开/清空/关闭与超时记录。
- 厂商 UART：每次实际执行 PDS compile/synthesize/dev_map，使用其未修改的技术网表和安装的厂商模型进行功能仿真；本次 {vendor_uart['channels']} 个通道、{vendor_uart['checks']:,} 项检查通过，七个通道输出位分别保留独立可变寄存器。覆盖全部数字通道、非法输入、OFF、组增益和查询。此层没有 SDF 标注，也未进行布局布线，不能替代完整器件时序或实板验证。
- PLL/DDR 厂商模型：音频PLL链产生122.88MHz，网络PLL及单沿分频产生125MHz，并核验RGMII DDR收发与控制编码。本次是否纳入 PLL/DDR 层：{'是' if result['vendor_included'] else '否'}；UART 厂商门级层始终执行。

便携模型默认禁用直流估计，保留原逐位参考向量；板级完整系统默认在96帧滤波稳定期后估计4096帧并冻结，每路异常均值保留原始输出。交流增益的手册名义值仍为1；启动去直流不证明每只麦克风灵敏度已配平。

本报告证明功能仿真与参考模型一致。实际器件资源、布局布线、时序及位流发布依据单独的 FPGA 实现报告；本报告不代表已经完成实板声学或网络长时间测试。
'''
    (ROOT/'doc/reports/system_verification.md').write_text(report,encoding='utf-8')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--rtl-only',action='store_true',help='Reuse previously generated reference vectors')
    ap.add_argument('--skip-vendor',action='store_true',help='Skip PLL/DDR primitive simulation; vendor UART remains mandatory')
    args=ap.parse_args()
    LOG.mkdir(parents=True,exist_ok=True)
    py=sys.executable
    ps=['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File']
    steps=[('frontend',[py,'sim/run_all.py']+(['--rtl-only'] if args.rtl_only else [])),
        ('fir_arithmetic',[py,'sim/fir/run_arithmetic.py']),
        ('fir_ram',[py,'sim/fir/run_ram_pipeline.py']),
        ('parity',[py,'sim/run_parity.py']),
        ('i2s',[py,'sim/audio/run_i2s.py']),
        ('audio_uart',[py,'sim/audio/run_audio_uart.py']),
        ('vendor_uart',[py,'sim/audio/run_vendor_uart.py']),
        ('board_audio',[py,'sim/audio/run_board_audio.py']),
        ('phy',[py,'sim/net/run_phy.py']),
        ('ethernet',ps+['sim/net/run_ethernet.ps1']),
        ('transport',[py,'sim/net/run_transport.py']),
        ('boot',[py,'sim/net/run_boot.py']),
        ('core',[py,'sim/net/run_core.py']),
        ('selftest',[py,'sim/net/run_selftest.py']),
        ('system_uart',[py,'sim/net/run_system_uart.py']),
        ('host',[[py,'-m','unittest','discover','-s','lib/host/tests','-v'],
                 ps+['lib/host/test_audio_uart.ps1']]),
        ('host_rtl',[py,'lib/host/receive_pcm.py','--check','log/net_core/payloads.hex','--golden','tb/vectors/expected_pcm.bin'])]
    if not args.skip_vendor:steps.append(('board',ps+['sim/tb_script/board_vendor.ps1']))
    result={'status':'RUNNING','vendor_included':not args.skip_vendor,'vendor_uart_required':True,'models_reused':args.rtl_only,'steps':{}}
    result_path=ROOT/'log/full_regression.json'
    result_path.write_text(json.dumps(result,indent=2))
    before=source_hashes()
    try:
        for name,command in steps:
            print(f'[RUN] {name}',flush=True)
            begin=time.monotonic()
            with (LOG/(name+'.log')).open('w',encoding='utf-8') as out:
                commands=command if isinstance(command[0],list) else [command]
                for current in commands:
                    p=subprocess.run(current,cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=1200)
                    if p.returncode:break
            text=(LOG/(name+'.log')).read_text(errors='replace')
            if p.returncode:raise RuntimeError(f'{name} failed:\n{text[-6000:]}')
            result['steps'][name]={'status':'PASS','seconds':round(time.monotonic()-begin,3)}
            if name=='fir_arithmetic':
                evidence_path=ROOT/'log/fir/round_sat_result.json'
                evidence_bytes=evidence_path.read_bytes()
                evidence=json.loads(evidence_bytes)
                if (evidence.get('status')!='PASS' or evidence.get('scope')!='fir_round_saturation_actual_rtl_functional'
                        or evidence.get('sdf_annotated') is not False or evidence.get('real_serial_opened') is not False
                        or evidence.get('actual_round_sat_cone_checked') is not True):
                    raise RuntimeError('Actual FIR round/saturation evidence is absent, failed, or has an unexpected scope')
                required_inputs={'rtl/fir_decimator.sv','rtl/fir1_coeff.svh','rtl/fir2_coeff.svh',
                    'tb/tb_fir_arithmetic.sv','tb/tb_fir_round_sat.sv','sim/fir/run_arithmetic.py'}
                source_digests=evidence.get('sources_sha256',{})
                if set(source_digests)!=required_inputs:
                    raise RuntimeError('Actual FIR round/saturation evidence does not bind every tested input')
                for path,digest in source_digests.items():
                    if before.get(path)!=digest or hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=digest:
                        raise RuntimeError('Actual FIR round/saturation source differs from this regression: '+path)
                raw_digests=evidence.get('raw_logs_sha256',{})
                if not raw_digests:
                    raise RuntimeError('Actual FIR round/saturation raw log identities are absent')
                for path,digest in raw_digests.items():
                    if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=digest:
                        raise RuntimeError('Actual FIR round/saturation raw log identity mismatch: '+path)
                result['steps'][name]['evidence']={'path':evidence_path.relative_to(ROOT).as_posix(),
                    'sha256':hashlib.sha256(evidence_bytes).hexdigest()}
            if name=='vendor_uart':
                evidence_path=ROOT/'log/vendor_uart/result.json'
                evidence_bytes=evidence_path.read_bytes()
                evidence=json.loads(evidence_bytes)
                if (evidence.get('status')!='PASS' or evidence.get('scope')!='vendor_uart_technology_netlist_functional'
                        or evidence.get('sdf_annotated') is not False or evidence.get('placement_routing_tested') is not False):
                    raise RuntimeError('Vendor UART evidence is absent, failed, or has an unexpected verification scope')
                if any(before.get(path)!=digest for path,digest in evidence.get('sources_sha256',{}).items()):
                    raise RuntimeError('Vendor UART evidence source hashes do not match this regression')
                result['steps'][name]['evidence']={'path':evidence_path.relative_to(ROOT).as_posix(),
                    'sha256':hashlib.sha256(evidence_bytes).hexdigest()}
            if name=='fir_ram':
                evidence_path=ROOT/'log/fir_ram/result.json'
                evidence_bytes=evidence_path.read_bytes()
                evidence=json.loads(evidence_bytes)
                if (evidence.get('status')!='PASS' or evidence.get('scope')!='fir_history_ram_pipeline_functional'
                        or evidence.get('sdf_annotated') is not False or evidence.get('real_serial_opened') is not False):
                    raise RuntimeError('FIR RAM evidence is absent, failed, or has an unexpected verification scope')
                required_inputs={'rtl/fir_decimator.sv','rtl/fir1_coeff.svh','rtl/fir2_coeff.svh',
                    'tb/tb_fir_ram_pipeline.sv','sim/fir/run_ram_pipeline.py',
                    'lib/coeff/fir1_q30.hex','lib/coeff/fir2_q30.hex'}
                source_digests=evidence.get('sources_sha256',{})
                if set(source_digests)!=required_inputs:
                    raise RuntimeError('FIR RAM evidence does not bind every actual source and reference coefficient')
                for path,digest in source_digests.items():
                    if ((path in before and before[path]!=digest)
                            or hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=digest):
                        raise RuntimeError('FIR RAM evidence input hashes do not match this regression: '+path)
                result['steps'][name]['evidence']={'path':evidence_path.relative_to(ROOT).as_posix(),
                    'sha256':hashlib.sha256(evidence_bytes).hexdigest()}
            print(f'[PASS] {name}',flush=True)
        result['sources_sha256']=source_hashes()
        if before!=result['sources_sha256']:raise RuntimeError('Sources changed during regression; verify a stable source set')
        result['vectors_sha256']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT/'tb/vectors').glob('*')) if p.is_file()}
        result['completed_at']=datetime.now().astimezone().isoformat(timespec='seconds')
        result['status']='PASS'
    except Exception as error:
        result['status']='FAIL';result['error']=str(error)
        raise
    finally:result_path.write_text(json.dumps(result,indent=2)+'\n')
    write_report(result)
    print('[RUN_PASS] All requested layers passed',flush=True)


if __name__=='__main__':main()
