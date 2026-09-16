"""Measured DSP performance, explicit synthetic-noise assumptions, reproducible plots."""
from common import *
from scipy import signal
from design_filters import cic_response
import golden
import fixed
import json
import os
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'log/build/matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def db(x):
    return 20*np.log10(np.maximum(np.abs(x),1e-18))


def response(f,h1,h2):
    # Evaluating each stage at the original frequency automatically includes its images.
    return (cic_response(f)*np.exp(-2j*np.pi*np.asarray(f)*21.5/FS_PDM)*
            signal.freqz(h1,worN=f,fs=384000)[1]*signal.freqz(h2,worN=f,fs=96000)[1])


def a_weight(f):
    f=np.asarray(f)
    r=(12194.**2*f**4)/((f*f+20.6**2)*np.sqrt((f*f+107.7**2)*(f*f+737.9**2))*(f*f+12194.**2))
    return r*10**(2/20)


def weighted_noise(x):
    f,p=signal.welch(x,fs=FS_PCM,nperseg=min(2048,len(x)),scaling='density')
    band=(f>=20)&(f<=16000)
    return float(10*np.log10(2*np.trapezoid(p[band]*a_weight(f[band])**2,f[band])))


def synth_pdm(x):
    # Second-order error-feedback surrogate; not a model of the proprietary microphone ADC.
    out=np.empty(len(x),dtype=np.uint8)
    e1,e2=.137,-.083
    for n,v in enumerate(x):
        u=v-2*e1+e2
        y=1. if u>=0 else -1.
        e1,e2=y-u,e1
        out[n]=(y>0)
    return out


def main():
    out=ROOT/'doc/reports'
    out.mkdir(parents=True,exist_ok=True)
    h1,h2=coefficients()
    q1,q2=[h/2**30 for h in fixed_coefficients()]
    f=np.linspace(0,FS_PDM/2,262145)
    H=response(f,q1,q2)
    Hf=response(f,h1,h2)
    band=(f>=20)&(f<=16000)
    folded=np.abs((f+24000)%48000-24000)
    alias=(f>=32000)&(folded>=20)&(folded<=16000)
    ripple=float(np.ptp(db(H[band])))
    alias_rejection=float(-np.max(db(H[alias])))
    coef_error=float(np.max(np.abs(H[band]-Hf[band])))
    phase_error=float(np.max(np.abs(np.angle(H[band]/Hf[band])))*180/np.pi)
    # Integrate all 63 unwanted images; PSD assumes white quantization error Δ²/12.
    base=np.linspace(20,16000,4097)
    alias_psd=np.zeros_like(base)
    for k in range(1,64):
        fk=(base+k*48000+FS_PDM/2)%FS_PDM-FS_PDM/2
        hk=response(np.abs(fk),q1,q2)
        ntf=np.abs(1-np.exp(-2j*np.pi*fk/FS_PDM))**4
        alias_psd+=(1/3)/FS_PDM*ntf*np.abs(hk)**2
    alias_noise_dba=float(10*np.log10(4*np.trapezoid(alias_psd*a_weight(base)**2,base)))

    n=262144
    t=np.arange(n)/FS_PDM
    rng=np.random.default_rng(20260915)
    audio=10**(-36/20)*np.sin(2*np.pi*1000*t)+.001*np.sin(2*np.pi*7000*t+.21)
    pdm=synth_pdm(audio+rng.uniform(-1e-7,1e-7,n))
    _,_,float_pcm=golden.process(pdm)
    _,_,fixed32,pcm24=fixed.process(pdm)
    float_pcm=float_pcm[:,0]
    fixed32=fixed32[:,0]/2**30
    pcm24=pcm24[:,0]/2**23
    trim=96
    err=pcm24[trim:]-float_pcm[trim:]
    err32=fixed32[trim:]-float_pcm[trim:]
    numeric_rms=float(db(np.sqrt(2*np.mean(err**2))))
    numeric_dba=weighted_noise(err)
    internal_rms=float(db(np.sqrt(2*np.mean(err32**2))))
    # Compare fixed vs golden on exactly the same bits, so ADC surrogate noise cancels.
    loss_numeric=float(10*np.log10(1+10**((numeric_dba+108)/10)))
    loss_with_alias=float(10*np.log10(1+10**((numeric_dba+108)/10)+10**((alias_noise_dba+108)/10)))
    # An impulse trace establishes common delay and complete transient length.
    impulse=golden.cic_impulse()
    stage1=np.zeros((len(h1)-1)*8+1);stage1[::8]=h1
    stage2=np.zeros((len(h2)-1)*32+1);stage2[::32]=h2
    impulse=np.convolve(np.convolve(impulse,stage1),stage2)
    delay=(4+17.5+31*8+63*32)
    metrics={
        'sample_rates_hz':{'pdm':FS_PDM,'cic':384000,'fir1':96000,'pcm':FS_PCM},
        'passband_hz':[20,16000],'passband_ripple_db':ripple,
        'alias_rejection_db':alias_rejection,'alias_scan_step_hz':float(f[1]-f[0]),
        'coefficient_complex_error_max':coef_error,'coefficient_phase_error_deg':phase_error,
        'common_group_delay_pdm_periods':delay,'common_group_delay_us':delay/FS_PDM*1e6,
        'impulse_length_pdm_periods':len(impulse),'discard_pcm_frames':96,
        'numeric_error_dbfs_rms':numeric_rms,'numeric_error_dbfsa_20_16k':numeric_dba,
        'internal_q30_error_dbfs_rms':internal_rms,
        'second_order_white_error_alias_dbfsa':alias_noise_dba,
        'estimated_numeric_snr_loss_db':loss_numeric,'estimated_numeric_plus_alias_snr_loss_db':loss_with_alias,
        'tone_record_pdm_periods':n,'tone_record_pcm_frames':len(pcm24),
        'scope':'Digital response and same-input fixed/float error; acoustic SNR is not measured.'}
    assert ripple<.01, metrics
    assert alias_rejection>120, metrics
    assert numeric_rms< -135, metrics
    assert loss_with_alias<.1, metrics
    assert np.array_equal(fixed_coefficients()[0],fixed_coefficients()[0][::-1])
    assert len(impulse)/64<96
    (out/'performance.json').write_text(json.dumps(metrics,indent=2)+'\n')
    fig,axes=plt.subplots(2,2,figsize=(12,8),layout='constrained')
    low=f<=48000
    axes[0,0].plot(f[low]/1000,db(H[low]),color='#177e89')
    axes[0,0].axvspan(0,16,color='#177e89',alpha=.08)
    axes[0,0].set(xlabel='Frequency (kHz)',ylabel='Gain (dB)',ylim=(-180,2),title='Combined digital response')
    axes[0,1].plot(f[band]/1000,db(H[band])*1e6)
    axes[0,1].set(xlabel='Frequency (kHz)',ylabel='Gain error (micro-dB)',title='Passband detail')
    axes[1,0].plot(f[alias]/1000,db(H[alias]),'.',markersize=.8)
    axes[1,0].axhline(-120,color='#c56b3c',linestyle='--')
    axes[1,0].set(xlabel='PDM input frequency (kHz)',ylabel='Gain (dB)',ylim=(-210,-110),title='All images folding into 20 Hz - 16 kHz')
    fw,ps=signal.welch(err,fs=48000,nperseg=2048)
    axes[1,1].plot(fw/1000,10*np.log10(2*ps+1e-40))
    axes[1,1].set(xlabel='PCM frequency (kHz)',ylabel='Error PSD (dBFS/Hz)',title='24-bit fixed minus float, identical PDM')
    for ax in axes.flat:ax.grid(alpha=.2)
    fig.suptitle('IM72D128V01 array: numerical verification',fontsize=16)
    fig.savefig(out/'performance.png',dpi=160)
    plt.close(fig)
    report=f'''# 前处理链性能仿真报告

本报告由 `lib/model/performance.py` 自动生成。结果使用实际 Q2.30 系数；浮点 Golden Model 与定点模型使用同一批 PDM，独立隔离数值误差。采样率 48 kHz，验收频带 20 Hz～16 kHz。

| 检查项 | 实测 | 验收门限 |
|---|---:|---:|
| 通带峰峰纹波 | {ripple:.9f} dB | < 0.01 dB |
| 折入通带的最差镜像抑制 | {alias_rejection:.3f} dB | > 120 dB |
| 24 位输出相对浮点误差，全部 PCM 频带 | {numeric_rms:.3f} dBFS RMS | < −135 dBFS |
| 数值误差，20 Hz～16 kHz A 计权 | {numeric_dba:.3f} dBFS(A) | 计入噪声预算 |
| 内部 Q2.30 相对浮点误差 | {internal_rms:.3f} dBFS RMS | 记录 |
| 二阶白量化误差假设下的混叠噪声 | {alias_noise_dba:.3f} dBFS(A) | 模型估算 |
| 数值误差估计导致的 SNR 损失 | {loss_numeric:.6f} dB | < 0.1 dB |
| 叠加上述混叠模型后的 SNR 损失估计 | {loss_with_alias:.6f} dB | < 0.1 dB |
| 公共群延迟 | {delay/FS_PDM*1e6:.6f} μs | 全通道一致 |
| 脉冲响应长度 | {len(impulse)} 个 PDM 周期 | 小于 96 个 PCM 帧 |

![滤波器与定点误差](performance.png)

## 方法及适用范围

- dBFS 采用满幅正弦 RMS = 1/√2 的基准。没有把 72 dB(A) SNR 当作相对满量程 −72 dBFS；手册 −36 dBFS 灵敏度与 72 dB(A) SNR 对应约 −108 dBFS(A) 本底。
- 镜像扫描覆盖 0～1.536 MHz，步长 {f[1]-f[0]:.6f} Hz，检查折入 20 Hz～16 kHz 的所有非基带频率。离散频率扫描不是区间数学证明。
- 两级 FIR 都对称，量化后仍严格对称；系数量化的最大复频响误差 {coef_error:.3e}，相对相位误差 {phase_error:.3e}°。同系数、同调度、同复位的通道具有完全相同的数字延迟。
- 生成 {n} 个 PDM 周期，含 −36 dBFS、1 kHz 主信号和 7 kHz 小信号；丢弃前 96 个 PCM 帧。二阶 PDM 发生器仅用于合成激励，不代表 Infineon 内部 ADC。
- 混叠估算明确采用 Δ=2、误差方差 Δ²/12、二阶 NTF=(1−z⁻¹)²，积分全部 63 个非基带镜像；无法由这项假设保证真实麦克风的混叠噪声。需要实际 PDM 录音或厂家噪声谱来最终验证。
- 16～24 kHz 不属于保证通带；缩小带宽只用于声源定位，不宣称完整保留手册 20 kHz 带宽下的声学频响。
- RTL 一致性、饱和、启停及输出阻塞结果见 `verification.md` 与工程 `log/`；没有器件综合、布局布线或声学台架测试数据。
'''
    (out/'performance.md').write_text(report,encoding='utf-8')
    print('[MODEL_INFO] Performance gates passed: '+json.dumps(metrics))


if __name__=='__main__':main()
