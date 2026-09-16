// C++17 bit-exact streaming reference. Unsigned CIC states model modulo 2^32.
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#include <algorithm>
using i64 = std::int64_t;
constexpr int CH = 128;
using Frame = std::array<i64, CH>;

i64 sx32(std::uint32_t v) { return (v & 0x80000000u) ? i64(v)-4294967296LL : i64(v); }
i64 rounded(i64 x, int shift) {
    const i64 half = i64(1) << (shift-1);
    return x < 0 ? -((-x+half) >> shift) : ((x+half) >> shift);
}
i64 sat(i64 x, int bits) {
    return std::clamp(x, -(i64(1) << (bits-1)), (i64(1) << (bits-1))-1);
}
std::vector<i64> load_coeff(const std::string& path) {
    std::ifstream f(path); if (!f) throw std::runtime_error("Cannot read "+path);
    std::vector<i64> h; i64 v; while (f >> v) h.push_back(v);
    if (h.empty()) throw std::runtime_error("Empty coefficient file");
    i64 l1=0; for (auto q:h) l1 += q < 0 ? -q:q;
    if (l1 >= (i64(1)<<32)) throw std::runtime_error("64-bit accumulator bound exceeded");
    return h;
}
struct Fir {
    std::vector<i64> h;
    std::vector<Frame> hist;
    std::size_t wr=0, count=0;
    int rate;
    Fir(std::vector<i64> c, int r):h(std::move(c)),hist(h.size()),rate(r) {}
    bool step(const Frame& x, Frame& y) {
        hist[wr]=x;
        const auto base=wr;
        wr=(wr+1)%h.size();
        if (++count % rate) return false;
        for (int c=0;c<CH;++c) {
            i64 acc=0;
            for (std::size_t k=0;k<h.size();++k)
                acc += h[k]*hist[(base+h.size()-k)%h.size()][c];
            y[c]=sat(rounded(acc,30),32);
        }
        return true;
    }
};
void dump(std::ofstream& f,const Frame& x,int width) {
    // Raw little-endian words, explicit encoding independent of host endian.
    for (auto v:x) for(int b=0;b<width;++b) f.put(char(std::uint64_t(v)>>(8*b)));
}
int main(int argc,char** argv) {
    try {
        if(argc!=5) throw std::runtime_error("Usage: mems_rm pdm.bin coefficient_dir output_prefix calibration.txt");
        std::ifstream input(argv[1],std::ios::binary), cal(argv[4]);
        if (!input || !cal) throw std::runtime_error("Cannot open input/calibration");
        Frame gains{},offsets{};
        for(int c=0;c<CH;++c) {
            if(!(cal>>gains[c]>>offsets[c])) throw std::runtime_error("Invalid calibration");
            if(gains[c]<-8388608 || gains[c]>8388607 || offsets[c]<-2147483648LL || offsets[c]>2147483647LL)
                throw std::runtime_error("Calibration exceeds the RTL signed field width");
        }
        Fir f1(load_coeff(std::string(argv[2])+"/fir1_q30.txt"),4);
        Fir f2(load_coeff(std::string(argv[2])+"/fir2_q30.txt"),2);
        std::ofstream a(std::string(argv[3])+"_cic.bin",std::ios::binary);
        std::ofstream b(std::string(argv[3])+"_fir1.bin",std::ios::binary);
        std::ofstream d(std::string(argv[3])+"_fir2.bin",std::ios::binary);
        std::ofstream e(std::string(argv[3])+"_pcm.bin",std::ios::binary);
        if(!a||!b||!d||!e) throw std::runtime_error("Cannot create output");
        std::array<std::array<std::uint32_t,5>,CH> integ{},comb{};
        std::array<unsigned char,16> packed{};
        Frame x{},y{},z{},pcm{}; std::size_t n=0, frames=0;
        while(input.read(reinterpret_cast<char*>(packed.data()),packed.size())) {
            for(int c=0;c<CH;++c) {
                auto old=integ[c];
                integ[c][0] += ((packed[c/8]>>(c%8))&1) ? 1u:0xffffffffu;
                for(int j=1;j<5;++j) integ[c][j] += old[j-1];
                if(n%8==7) {
                    std::uint32_t v=integ[c][4];
                    for(int j=0;j<5;++j) { auto keep=v; v-=comb[c][j]; comb[c][j]=keep; }
                    x[c]=sx32(v)*32768;
                }
            }
            if(n%8==7) {
                dump(a,x,4);
                if(f1.step(x,y)) { dump(b,y,4);
                    if(f2.step(y,z)) { dump(d,z,4);
                        for(int c=0;c<CH;++c) pcm[c]=sat(rounded((z[c]-offsets[c])*gains[c],29),24);
                        dump(e,pcm,4); ++frames;
                    }
                }
            }
            ++n;
        }
        if(input.gcount()!=0) throw std::runtime_error("Truncated PDM frame");
        std::cout<<"[RM_INFO] PDM periods="<<n<<" PCM frames="<<frames<<" channels="<<CH<<'\n';
        return 0;
    } catch(const std::exception& e) { std::cerr<<"[RM_ERROR] "<<e.what()<<'\n'; return 1; }
}
