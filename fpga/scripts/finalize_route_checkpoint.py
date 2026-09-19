"""Continue a full build from its completed, passing first PNR iteration.

Stop the optional optimizer before using this command. Its failed/cancelled
wrapper is preserved verbatim; it is never reported as a successful process.
Every electrical, functional, timing and bitstream gate still runs.
"""
from pathlib import Path
from datetime import datetime
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

from check_release import ROOT, TOP, current_build_sources, sha, check_route_selection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-name', required=True)
    parser.add_argument('--resume-exports', action='store_true', help='Retry the gate after a failed audit of already completed timing and both corner exports')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.build_name):
        raise ValueError('Invalid build name')
    build = ROOT/'fpga/build'/args.build_name
    manifest_file = build/'manifest.json'
    origin = json.loads(manifest_file.read_text())
    if origin.get('status') != 'FAIL' or bool(origin.get('route_checkpoint_selection')) != args.resume_exports:
        raise ValueError('Use the ended optimizer manifest for selection, or --resume-exports for a failed checkpoint audit')
    if origin['source_sha256'] != current_build_sources(ROOT):
        raise ValueError('Build inputs changed')
    selection_dir = build/'checkpoint_selection'
    if selection_dir.exists() and not args.resume_exports:
        raise ValueError('A checkpoint selection already exists; do not overwrite its evidence')
    original_text = (build/'build.log').read_text(encoding='utf8')
    checkpoint = build/'place_route/route_constraint_ite_1'/f'{TOP}_pnr.adf'
    checkpoint_report = checkpoint.with_name(f'{TOP}.rtr')
    routed = build/'place_route'/f'{TOP}_pnr.adf'
    routed_hash = sha(checkpoint)
    if routed.exists() and sha(routed) != routed_hash:
        raise ValueError('Another routed result already exists; preserve it')
    if (build/'generate_bitstream'/f'{TOP}.sbit').exists():
        raise ValueError('This build already contains a bitstream')
    manifest = dict(origin)
    for key in ('error','release_error','completed_at','exit_code'):
        manifest.pop(key, None)
    manifest.update(status='RUNNING', routed_db_sha256=routed_hash)
    if args.resume_exports:
        expected = [['compile','synthesize','dev_map'],['place'],['pnr'],['report_timing'],['gen_netlist'],['gen_netlist']]
        if [f.get('stages') for f in origin['flow_evidence']] != expected:
            raise ValueError('Resume requires completed timing and both corner exports, with no bitstream stage')
        previous = selection_dir/('failed_audit_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.json')
        shutil.copy2(manifest_file, previous)
        manifest['checkpoint_resume_records'] = list(origin.get('checkpoint_resume_records', []))+[
            dict(manifest=previous.relative_to(build).as_posix(), sha256=sha(previous))]
        manifest['route_checkpoint_selection'] = dict(origin['route_checkpoint_selection'], finalizer_sha256=sha(Path(__file__)))
        selected_log = original_text
    else:
        second = re.search(r'^I: Current iteration time: 2\s*$', original_text, re.M)
        if second is None:
            raise ValueError('No completed first route iteration followed by optional optimization')
        prefix = original_text[:second.start()]
        selection_dir.mkdir()
        shutil.copy2(manifest_file, selection_dir/'source_manifest.json')
        shutil.copy2(build/'build.log', selection_dir/'optimizer.log')
        shutil.copy2(checkpoint, routed)
        manifest['route_checkpoint_selection'] = dict(
            iteration=1, reason='First iteration passes timing; stop redundant optional optimization',
            source_manifest_sha256=sha(selection_dir/'source_manifest.json'),
            optimizer_log_sha256=sha(selection_dir/'optimizer.log'),
            routed_db_sha256=routed_hash, timing_report_sha256=sha(checkpoint_report),
            route_script_sha256=sha(build/'route.tcl'), finalizer_sha256=sha(Path(__file__)))
        manifest['flow_evidence'] = list(origin['flow_evidence']) + [dict(
            project='MEMS_Array_route_selection', stages=['pnr'],
            execution_kind='completed_checkpoint_selection',
            script=(build/'route.tcl').relative_to(ROOT).as_posix(), script_sha256=sha(build/'route.tcl'),
            completed_at=datetime.now().astimezone().isoformat())]
        selected_log = prefix+'MEMS_PANGO_PNR_COMPLETE\n'

    def artifact(label, path, suffix):
        path = path.resolve()
        if not path.is_relative_to(build) or not path.is_file() or path.suffix != suffix:
            raise ValueError('Invalid selection artifact: '+label)
        return path
    check_route_selection(manifest, ROOT, build, selected_log, artifact)
    (build/'build.log').write_text(selected_log, encoding='utf8', newline='\n')

    def save():
        manifest_file.write_text(json.dumps(manifest, indent=2)+'\n')
    save()
    env = os.environ.copy()
    env.setdefault('PANGO_LICENSE_FILE', 'D:/Application/ElectronicIDE/Pango/license/new_pds_F4A80DA47D72.lic')
    shell = Path('D:/Application/ElectronicIDE/Pango/PDS_2022.2-SP6.4/bin/pds_shell.exe')
    arch = 'set_arch -family Logos2 -device PG2L200H -speedgrade -6 -package FBB676\n'

    def run(filename, project, stage, action):
        script = build/filename
        script.write_text(arch+action+' -force_to_run -input_db_file {'+routed.as_posix()+'}\n')
        with (build/'build.log').open('a', encoding='utf8') as output:
            offset = output.tell()
            result = subprocess.run([str(shell), '-file', str(script), '-work_dir', str(build), '-project_name', project],
                                    cwd=build, env=env, stdout=output, stderr=subprocess.STDOUT)
        with (build/'build.log').open(encoding='utf8') as stream:
            stream.seek(offset)
            text = stream.read()
        if result.returncode or re.search(r'^[ \t]*E: |^[ \t]*[ECW]: Internal-', text, re.M):
            raise RuntimeError('PDS finalization failed: '+stage)
        if not re.search(r'^Executing : '+stage+r'(?: [^\r\n]*)? successfully\.$', text, re.M):
            raise RuntimeError('Missing native completion: '+stage)
        if stage != 'gen_netlist':
            with (build/'build.log').open('a') as stream:
                stream.write('MEMS_PANGO_'+stage.upper()+'_COMPLETE\n')
        manifest['flow_evidence'].append(dict(project=project, stages=[stage], script=script.relative_to(ROOT).as_posix(),
            script_sha256=sha(script), completed_at=datetime.now().astimezone().isoformat(), exit_code=result.returncode))
        if sha(routed) != routed_hash or current_build_sources(ROOT) != manifest['source_sha256']:
            raise RuntimeError('Frozen route or build inputs changed')
        save()
        print(stage+': complete', flush=True)

    gate = [sys.executable, str(ROOT/'fpga/scripts/check_release.py'), '--manifest', str(manifest_file),
            '--regression', str(ROOT/'log/full_regression.json'),
            '--timing-report', str(build/'report_timing'/f'{TOP}.rtr'),
            '--constraints-report', str(build/'constraint_check/constraint_check.ccr'),
            '--map-report', str(build/'device_map'/f'{TOP}.dmr'), '--build-log', str(build/'build.log')]
    try:
        if not args.resume_exports:
            run('finalize_timing.tcl', 'MEMS_Array_timing', 'report_timing',
                'report_timing -delay_type min_max -report_io_datasheet -report_max_skew -report_exception TRUE -max_path 8')
            audit = build/'clock_audit'; audit.mkdir(exist_ok=True)
            for corner in ('slow','fast'):
                run('export_'+corner+'.tcl', 'MEMS_Array_'+corner+'_sdf', 'gen_netlist',
                    'gen_netlist -sdf_annotate FALSE -process_corner '+corner)
                for suffix in ('sta.sdf','sim.v'):
                    shutil.copy2(build/'generate_netlist'/f'{TOP}_{suffix}', audit/f'{corner}_{suffix}')
        subprocess.run(gate+['--pre-bit','--output',str(build/'pre_bit_check.json')], cwd=ROOT, check=True)
        run('generate_bitstream.tcl', 'MEMS_Array_bitstream', 'gen_bit_stream',
            'gen_bit_stream -create_bit_file TRUE -create_bin_file -persist_pin {Release For USER}')
        manifest.update(status='PASS', exit_code=0, sources_unchanged=True, completed_at=datetime.now().astimezone().isoformat())
        save()
        subprocess.run(gate+['--bitstream',str(build/'generate_bitstream'/f'{TOP}.sbit'),
            '--bin',str(build/'generate_bitstream'/f'{TOP}.bin'),'--output',str(build/'release.json')], cwd=ROOT, check=True)
    except Exception as error:
        manifest.update(status='FAIL', exit_code=1, error=str(error),
                        sources_unchanged=current_build_sources(ROOT)==manifest['source_sha256'],
                        completed_at=datetime.now().astimezone().isoformat())
        save()
        raise


if __name__ == '__main__':
    main()
