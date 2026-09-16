"""Convert the 128-line gain_Q22 offset_Q30 calibration to board RTL entries."""
import argparse
from pathlib import Path


def encode(source: str) -> str:
    pairs=[]
    for line in source.splitlines():
        clean=line.split('#',1)[0].strip()
        if not clean:continue
        values=clean.split()
        if len(values)!=2:raise ValueError('Each nonempty row must have gain_Q22 and offset_Q30')
        gain,offset=map(int,values)
        if not -(1<<23)<=gain<(1<<23) or not -(1<<31)<=offset<(1<<31):
            raise ValueError('Gain or offset exceeds its signed fixed-point range')
        pairs.append((gain,offset))
    if len(pairs)!=128:raise ValueError('Exactly 128 channel rows are required')
    lines=['// Generated from measured gain_Q22 offset_Q30 calibration; channel order 0..127.']
    for ch,(gain,offset) in enumerate(pairs):
        lines.append(f"7'd{ch}: begin cfg_gain=24'sh{gain&0xffffff:06x}; cfg_offset=32'sh{offset&0xffffffff:08x}; end")
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[2]/'rtl/board/calibration_coeff.svh')
    args=parser.parse_args()
    text=encode(args.input.read_text(encoding='utf-8'))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(text,encoding='utf-8')
    print(f'128 channel coefficients exported to {args.output}; rebuild the FPGA bitstream to apply.')


if __name__=='__main__':main()
