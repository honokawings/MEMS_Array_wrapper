"""Front-end, network, board primitive and host decoder regression entry point."""
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
    labels={'frontend':'Python/C++ 模型、性能与前处理 RTL','fir_arithmetic':'FIR 部分乘积、舍入与饱和边界','phy':'位级 MDIO 与 PHY 配置',
        'ethernet':'Ethernet / ARP / IPv4 / UDP','transport':'异步 FIFO 与 PCM 打包',
        'boot':'板级校准启动与复位边界','core':'PDM 引脚到线上 UDP 完整链路',
        'host':'上位机协议、文件与 UDP 接收','host_rtl':'真实 RTL 数据包与 Cmodel 样本比较',
        'system_uart':'UART、MDIO、ARP、UDP 集成诊断','board':'Pango 厂商 PLL 与 DDR 原语','selftest':'按键、LED、内部 PDM 自测与线上样本校验'}
    rows='\n'.join(f"| {labels[name]} | PASS | {item['seconds']:.3f} s |" for name,item in result['steps'].items())
    host=json.loads((LOG/'host_rtl.log').read_text(encoding='utf-8'))
    model_scope='复用此前已通过Python/C++逐位比对的参考向量' if result['models_reused'] else '重新生成系数、性能报告及Python/C++参考向量'
    report=f'''# 完整系统功能验证报告

生成时间：{result['completed_at']}。本次结果：**PASS**。完整运行入口为 `python sim/verify_all.py`。
原始证据位于 `log/full_regression/`；`log/full_regression.json` 保存每项结果、耗时和所有被测源文件 SHA-256，并检查运行前后源代码没有变化。
数值模型范围：{model_scope}。本次读取的参考向量文件也在摘要中记录校验和。

| 层次 | 结果 | 实际运行时间 |
|---|---|---:|
{rows}

## 端到端验证

测试从64根真实双相共享PDM总线模型开始，经过128通道滤波/校准、异步FIFO、三帧打包、ARP及以太网发送，接收端独立核验IPv4/UDP校验和与Ethernet FCS，并按包内帧号查询Python/C++定点参考。

本次上位机解析真实RTL输出 **{host['packets']} 个UDP包、{host['frames']} 个采样帧、{host['samples_compared']} 个通道样本**，全部逐位一致。payload SHA-256：`{host['payload_sha256']}`。

前两会话分别延迟 ARP 应答 0.65 ms、2 ms，验证等待期间不采集、ARP 自主重试，以及从第 96 帧开始连续输出且无溢出。第三会话在地址解析完成后人为阻塞发送端，保留整帧丢弃、帧号缺口、溢出状态、断线清空及重新启动的保护验证。各会话具体包数与缺帧统计见 `log/full_regression/host_rtl.log`。

## 边界覆盖

- PHY：逐位MDIO、300ns返回延迟、地址扫描、配置读回、1000M全双工判定、EEE禁用及故障恢复。
- 网络：短包、MTU边界、校验和零值、CRC/IFG、坏ARP拒绝、链路中断和独立RX时钟停止期间复位。
- 打包与CDC：随机阻塞、Gray指针回绕、64位帧号间隙、24位正负极值、畸形帧恢复和待发送时复位。
- 板级控制：两条复位链错开3拍时仍完整写入128组非默认校准系数；音频停钟时掉线和PLL失锁重启。
- 校准运算：20,056个完整乘积的舍入/半LSB边界独立比较，以及实际128通道增益、偏置、饱和和调度异常检查。
- 自测：真实板级按键切换、内部 PDM 源、128 通道周期预期值、LED、断线重启、故障注入与上位机逐位比较；生产速率稳定段为 16,000 包/秒。自测通过计数与等待时间在仿真中缩短，采样及传输时钟保持生产频率。
- 厂商模型：音频PLL链产生122.88MHz，网络PLL及单沿分频产生125MHz，并核验RGMII DDR收发与控制编码。厂商原语是否纳入本次运行：{'是' if result['vendor_included'] else '否'}。

本报告证明功能仿真与参考模型一致。实际器件资源、布局布线、时序及位流发布依据单独的 FPGA 实现报告；本报告不代表已经完成实板声学或网络长时间测试。
'''
    (ROOT/'doc/reports/system_verification.md').write_text(report,encoding='utf-8')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--rtl-only',action='store_true',help='Reuse previously generated reference vectors')
    ap.add_argument('--skip-vendor',action='store_true',help='Skip Pango primitive simulation')
    args=ap.parse_args()
    LOG.mkdir(parents=True,exist_ok=True)
    py=sys.executable
    ps=['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File']
    steps=[('frontend',[py,'sim/run_all.py']+(['--rtl-only'] if args.rtl_only else [])),
        ('fir_arithmetic',[py,'sim/fir/run_arithmetic.py']),
        ('phy',[py,'sim/net/run_phy.py']),
        ('ethernet',ps+['sim/net/run_ethernet.ps1']),
        ('transport',[py,'sim/net/run_transport.py']),
        ('boot',[py,'sim/net/run_boot.py']),
        ('core',[py,'sim/net/run_core.py']),
        ('selftest',[py,'sim/net/run_selftest.py']),
        ('system_uart',[py,'sim/net/run_system_uart.py']),
        ('host',[py,'-m','unittest','discover','-s','lib/host/tests','-v']),
        ('host_rtl',[py,'lib/host/receive_pcm.py','--check','log/net_core/payloads.hex','--golden','tb/vectors/expected_pcm.bin'])]
    if not args.skip_vendor:steps.append(('board',ps+['sim/tb_script/board_vendor.ps1']))
    result={'status':'RUNNING','vendor_included':not args.skip_vendor,'models_reused':args.rtl_only,'steps':{}}
    result_path=ROOT/'log/full_regression.json'
    result_path.write_text(json.dumps(result,indent=2))
    before=source_hashes()
    try:
        for name,command in steps:
            print(f'[RUN] {name}',flush=True)
            begin=time.monotonic()
            with (LOG/(name+'.log')).open('w',encoding='utf-8') as out:
                p=subprocess.run(command,cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=1200)
            text=(LOG/(name+'.log')).read_text(errors='replace')
            if p.returncode:raise RuntimeError(f'{name} failed:\n{text[-6000:]}')
            result['steps'][name]={'status':'PASS','seconds':round(time.monotonic()-begin,3)}
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
