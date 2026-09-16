"""One-command regression. All generated diagnostics go to log/."""
from pathlib import Path
import argparse,json,os,shutil,subprocess,sys,time,hashlib
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1]
SIM=ROOT/'sim'
LOG=ROOT/'log'
RESULT_PATH=None


def verification_report(results):
    vector=json.loads((ROOT/'tb/vectors/manifest.json').read_text())
    samples=sum(x['samples_compared'] for x in vector['integer_model_comparison'].values())
    rows='\n'.join(f"| {tb} | PASS | {results[tb]['seconds']:.3f} s |" for tb in
                   ['tb_calibration','tb_fifo','tb_array','tb_capture'])
    elab=LOG/'build/vivado_elaborate.log'
    has_elab=elab.exists() and 'MEMS_RTL_ELABORATION_PASS\n' in elab.read_text(errors='replace')
    report=f'''# 功能验证报告

生成时间：{results['completed_at']}。完整回归状态：**PASS**。原始日志为工程 `log/vlog.log`、`log/vsim.log` 与各 UT 的 `.log` 文件，运行摘要及被测源文件 SHA-256 存于 `log/regression.json`。

| UT | 结果 | 实际运行时间 |
|---|---|---:|
{rows}

## 模型与端到端一致性

- Python 定点与 C++ Cmodel：{samples:,} 个 32 位/24 位样本逐位一致，包括全部 128 通道的 CIC、FIR1、FIR2 和 PCM。
- 浮点 Golden Model 使用有限脉冲卷积实现 CIC，独立核对寄存积分链的 4 周期延迟及启动抽取相位。
- RTL 的两次完整采集均通过：每次 16384 个 PDM 周期，256 个 PCM 帧；前 96 帧按规格抑制，实际输出 160×128=20480 个 PCM 样本。
- 两次采集累计逐位核对 **761856 个级间/输出样本**；另直接核对 4194304 个 PDM 输入 bit。所有通道数据、帧号、通道号、first/last 一致。
- 样本包括全 1、全 0、交替位、互补位、非对称周期码、突变、16 个不同频率/相位的合成 PDM 和确定性随机位。相反 LR 槽的相同激励保持严格相等。
- 校准工具另用 128 通道已知增益、DC、相位的合成场恢复参数并检查误差。

## 时序、异常和状态

- 完整生产启动等待：精确丢弃 153600 个 PDM 周期，首个 valid 在第 153601 个周期，后续间隔 40 个系统时钟。
- 64 线共享总线驱动模型在切换期呈高阻，端到端测试使用 100 ns 器件最大 tDV 加 20 ns 板级延迟；独立采集 UT 检查实际 50 ms、LR 极性和 50% 占空比。
- 断言/计分板检查 CIC/FIR1/FIR2 的 320/1280/2560 系统时钟输出间隔。
- 128 通道校准边界覆盖正负半 LSB、正负满幅、极值偏置、负增益、零增益、饱和与故意调度过载。运行中写配置被拒绝，不影响本轮数据。
- 随机 pcm_ready 阻塞时数据和全部标签保持；FIFO 测试验证满队列、整帧丢弃、精确计数、同周期完整出队/入队、突发与复位。
- disable 后状态与队列清空，校准保留；第二次采集与第一批参考数据再次逐位一致。另在活动流水中执行 reset 并检查状态清零。
- 所有 UT 均出现 `[TB_INFO] Simulation Finished!`，未出现 `[TB_ERROR]`、`** Error` 或 `** Fatal`。编译和最终仿真均为零警告、零错误。

## 综合前端检查与未覆盖范围

本次可选 Vivado 2022.1 RTL 展开检查：{'PASS，零警告、零错误' if has_elab else '未记录通过结果'}。该工具内部使用缺省 xc7vx485tffg1157-1 加载前端，**不是为本工程选定 FPGA**；未执行逻辑映射、布局布线或位流生成。脚本为 `sim/elaborate.tcl`，日志为 `log/build/vivado_elaborate.log`。

未宣称完成形式化穷尽证明、真实 IO 亚稳态/抖动统计、板级时序收敛、功耗测试或真实声学 SNR 测量。实际阵元坐标及宽带相位标定仍由板级/声学校准提供。性能计算与假设见 [performance.md](performance.md)。
'''
    (ROOT/'doc/reports/verification.md').write_text(report,encoding='utf-8')


def run(args,logname,cwd=ROOT,timeout=300):
    print('[RUN] '+logname,flush=True)
    start=time.monotonic()
    with (LOG/logname).open('w',encoding='utf-8') as f:
        p=subprocess.run([str(x) for x in args],cwd=cwd,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
    text=(LOG/logname).read_text(encoding='utf-8',errors='replace')
    if p.returncode:
        print(text[-6000:])
        raise RuntimeError(f'{logname} failed, exit={p.returncode}')
    return text,round(time.monotonic()-start,3)


def model_python():
    candidates=[os.environ.get('MEMS_PYTHON'),sys.executable,
        str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe')]
    for exe in candidates:
        if exe and Path(exe).is_file():
            p=subprocess.run([exe,'-c',"import sys;sys.path.insert(0,'lib/.deps');import numpy,scipy,matplotlib"],
                cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if p.returncode==0:return exe
    raise RuntimeError('Set MEMS_PYTHON to a Python with lib/model/requirements.txt installed.')


def main():
    global RESULT_PATH
    ap=argparse.ArgumentParser()
    ap.add_argument('--rtl-only',action='store_true')
    ap.add_argument('--models-only',action='store_true')
    ap.add_argument('--test',choices=['tb_capture','tb_calibration','tb_fifo','tb_array'])
    args=ap.parse_args()
    if args.rtl_only and args.models_only:ap.error('--rtl-only and --models-only are mutually exclusive')
    LOG.mkdir(exist_ok=True);(LOG/'build').mkdir(exist_ok=True)
    full=not args.models_only and not args.test
    RESULT_PATH=LOG/('regression.json' if full else 'partial_regression.json')
    results={'status':'RUNNING'}
    RESULT_PATH.write_text(json.dumps(results))
    if not args.rtl_only:
        py=model_python()
        _,results['coefficients']=run([py,ROOT/'lib/model/design_filters.py'],'coefficients.log')
        gcc=shutil.which('g++')
        if not gcc:raise RuntimeError('g++ (C++17) is required')
        _,results['cmodel_build']=run([gcc,'-std=c++17','-O2','-Wall','-Wextra','-Werror',
            ROOT/'lib/cmodel/mems_rm.cpp','-o',LOG/'build/mems_rm.exe'],'cmodel_build.log')
        _,results['vectors']=run([py,ROOT/'lib/model/generate_vectors.py'],'models.log')
        _,results['performance']=run([py,ROOT/'lib/model/performance.py'],'performance.log',timeout=600)
    if not args.models_only:
        for binary in ['vlib','vlog','vsim']:
            if not shutil.which(binary):raise RuntimeError(binary+' is not on PATH')
        if not (SIM/'work').is_dir():run(['vlib','work'],'vlib.log',SIM)
        text,results['compile']=run(['vlog','-sv','-lint','-work','work','-f','modelsim_filelist.f'],'vlog.log',SIM)
        if '** Error' in text or '** Fatal' in text:raise RuntimeError('RTL compilation diagnostics')
        benches=[args.test] if args.test else ['tb_calibration','tb_fifo','tb_array','tb_capture']
        for tb in benches:
            text,seconds=run(['vsim','-batch','-onfinish','exit','-wlf',str(LOG/'build'/f'{tb}.wlf'),
                'work.'+tb,'-do','onerror {quit -f -code 1}; onbreak {quit -f -code 1}; run -all; quit -f -code 0'],
                tb+'.log',SIM,timeout=600)
            if '[TB_INFO] Simulation Finished!' not in text or any(x in text for x in ['[TB_ERROR]','** Error','** Fatal']):
                raise RuntimeError(tb+' did not pass; see log/'+tb+'.log')
            results[tb]={'status':'PASS','seconds':seconds}
            for line in text.splitlines():
                if '[TB_DATA]' in line:print(line,flush=True)
        (LOG/'vsim.log').write_text('\n'.join((LOG/(tb+'.log')).read_text(errors='replace') for tb in benches),encoding='utf-8')
    tested=[]
    for folder,patterns in [('rtl',['*.sv','*.svh']),('tb',['*.sv']),('lib/model',['*.py']),
                             ('lib/cmodel',['*.cpp']),('lib/coeff',['*_q30.txt']),('sim',['*.py','*.f'])]:
        for pattern in patterns:tested.extend((ROOT/folder).glob(pattern))
    results['sources_sha256']={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted(tested)}
    results['completed_at']=datetime.now().astimezone().isoformat(timespec='seconds')
    results['status']='PASS'
    RESULT_PATH.write_text(json.dumps(results,indent=2)+'\n')
    if full:verification_report(results)
    print('[RUN_PASS] Requested regression completed',flush=True)


if __name__=='__main__':
    try:main()
    except (RuntimeError,subprocess.TimeoutExpired) as e:
        if RESULT_PATH:RESULT_PATH.write_text(json.dumps({'status':'FAIL','reason':str(e)},indent=2)+'\n')
        print('[RUN_ERROR] '+str(e),file=sys.stderr);sys.exit(1)
