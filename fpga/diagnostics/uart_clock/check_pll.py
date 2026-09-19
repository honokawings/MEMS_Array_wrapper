"""Run the installed vendor IP's actual advanced PLL validator without a GUI."""
from pathlib import Path
import hashlib,json,re,shutil,subprocess

def validate(install,run,probe):
    source=Path(install)/'ip/module_ip/ipm2l_flex_pll/ipm2l_flex_pll_eval/ipm2l_pll/ui.tcl'
    ui=source.read_text(encoding='utf-8')
    begin=ui.index('proc pllCheck_adv {} {')
    end=ui.index('\nproc ui::update ',begin)
    checker=ui[begin:end]
    rtl=Path(probe).read_text(encoding='utf-8')
    rows=[]
    pattern=r'pango_audio_gpll\s*#\((.*?)\)\s*(u_pll_\w+)\s*\('
    for match in re.finditer(pattern,rtl,re.S):
        params=dict(re.findall(r'\.(\w+)\(([\d.]+)\)',match[1]))
        rows.append((match[2],float(params['INPUT_MHZ']),int(params['INPUT_DIV']),
                     int(params.get('FEEDBACK_MULTIPLY',16)),int(params['OUTPUT_DIV'])))
    assert len(rows)==3,'Expected exactly three clock PLL instances'
    assert '.STATIC_RATIOF(2.0)' in rtl and '.BANDWIDTH("OPTIMIZED")' in rtl,'Validator assumes fixed feedback F=2 and OPTIMIZED'
    tcl='''namespace eval ui {}
proc ui::getValue {args} {
    global cfg
    return $cfg([lindex $args 1])
}
proc ui::popupMessage {args} {
    puts [list VENDOR_DIAGNOSTIC [lindex $args [expr {[lsearch $args -m]+1}]]]
    return Back
}
'''+checker+'''
proc check_case {name fin idiv mdiv odiv expected} {
    global cfg
    array unset cfg
    array set cfg [list PLL_SEL_advancedPage 0 CLKIN_FREQ $fin CLKIN_FREQ_advancedPage $fin \
        STATIC_RATIOI_advancedPage $idiv STATIC_RATIOM $mdiv FB_advancedPage 7 BANDWIDTH_advancedPage OPTIMIZED]
    for {set i 0} {$i<=8} {incr i} {
        set ratio 8
        if {$i==0} {set ratio $odiv}
        if {$i==7} {set ratio 2}
        set cfg(STATIC_RATIO$i) $ratio
        set cfg(STATIC_DUTY$i) $ratio
        set cfg(STATIC_RATIO${i}_advancedPage) $ratio
        set cfg(STATIC_FRAC${i}_advancedPage) 0
    }
    set result [pllCheck_adv]
    puts [list PLL_CHECK $name $result EXPECTED $expected PFD [expr {$fin/double($idiv)}]]
    if {$result!=$expected} {exit 2}
}
check_case original_eth_rejected 125.0 1 4 4 0
'''
    for name,fin,idiv,mdiv,odiv in rows:
        tcl+=f'check_case {name} {fin} {idiv} {mdiv} {odiv} 1\n'
    tcl+='puts {PLL_VENDOR_CHECK_PASS}\n'
    script=run/'validate_vendor_pll.tcl';script.write_text(tcl,encoding='utf-8')
    exe=shutil.which('tclsh');assert exe,'tclsh is required for vendor PLL validation'
    result=subprocess.run([exe,str(script)],capture_output=True,text=True,encoding='utf-8')
    (run/'vendor_pll_check.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    assert result.returncode==0 and 'PLL_VENDOR_CHECK_PASS' in result.stdout,result.stdout+result.stderr
    evidence={'status':'PASS','vendor_source':str(source),'vendor_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
              'negative_control_original_rejected':True,'validated_instances':[
                  dict(name=n,input_mhz=f,idiv=i,mdiv=m,fdiv=2,odiv=o,bandwidth='OPTIMIZED',pfd_mhz=f/i,
                       vco_mhz=f/i*m*2,output_mhz=f/i*m*2/o) for n,f,i,m,o in rows]}
    (run/'pll_validation.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    print('[VENDOR_PLL_PASS] old configuration rejected, all corrected PLLs accepted',flush=True)
    return run/'pll_validation.json'
