"""Consumer-facing handoff commands; no song analysis or user media."""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import shutil
import struct
import subprocess
import wave
import zipfile
from pathlib import Path

import pytest

from beatscope.edit_plan import default_edit_plan
from beatscope.exports import DIRECTING_EXAMPLES, HANDOFF_RESOURCES, generate_codex_export

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which('node') is None, reason='Node is required')


def node(package, *args, expected=0, timeout=40):
    result = subprocess.run(['node', *map(str, args)], cwd=package, capture_output=True, text=True, encoding='utf-8', timeout=timeout)
    assert result.returncode == expected, result.stderr or result.stdout
    return json.loads(result.stdout) if result.stdout.strip().startswith('{') else result.stdout


@pytest.fixture
def package(tmp_path):
    rhythm = json.loads((ROOT / 'tests/fixtures/runtime/characterization-project.json').read_text())
    audio = tmp_path / 'song.wav'
    with wave.open(str(audio), 'wb') as stream:
        stream.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
        stream.writeframes(b''.join(struct.pack('<h', int(6000*math.sin(2*math.pi*120*i/44100))) for i in range(8*44100)))
    rhythm['source']['sha256'] = hashlib.sha256(audio.read_bytes()).hexdigest()
    plan = default_edit_plan(rhythm)
    plan['boundaries'] = [{'id': 's:saved', 'time': 1.234}]
    plan['cues'] = [{'id': 'o:0', 'deleted': True}, {'id': 'o:1', 'time': 2.2}, {'id': 'u:added', 'time': 2.345}]
    out = tmp_path / 'timing'
    with zipfile.ZipFile(io.BytesIO(generate_codex_export(rhythm, edit_plan=plan))) as archive:
        archive.extractall(out)
    return out


def test_bounded_query_preserves_full_stage_and_resolved_cues(package):
    brief = node(package, 'query.mjs', '2.1', '2.4', '--stages', '--onsets', '--limit', '1', '--activity-points', '2')
    assert brief['stages'][0]['interval'] == [1.234, 8]
    assert brief['stages'][0]['queriedInterval'] == [2.1, 2.4]
    assert brief['stages'][0]['musicalRole'] is None
    assert len(brief['activityTrend']['bins']) == 2
    assert len(brief['onsets']['shown']) == 1 and brief['onsets']['truncated']
    assert brief['onsets']['total'] == 2
    assert brief['onsets']['shown'][0]['id'] == 'o:1'
    assert brief['onsets']['shown'][0]['time'] == 2.2
    assert brief['onsets']['shown'][0]['sourceTime'] != 2.2
    assert 'automaticSections' not in brief
    assert 'o:0' not in [c['id'] for c in brief['onsets']['shown']]


def test_accent_selector_uses_measured_accents_and_applies_overrides(package):
    rhythm = json.loads((package / 'rhythm-map.json').read_text())
    # Portable maps carry compact references as {time, onset: SOURCE_ID}.
    rhythm['cues']['accent'] = [{'time': 1, 'onset': rhythm['onsets'][2]['id']}, {'time': 0, 'onset': rhythm['onsets'][0]['id']}]
    (package / 'rhythm-map.json').write_text(json.dumps(rhythm))
    brief = node(package, 'query.mjs', '0', '3', '--accents', '--limit', '12')
    assert [c['id'] for c in brief['accents']['shown']] == ['o:2', 'o:1', 'u:added']
    assert brief['accents']['shown'][1]['time'] == 2.2


@pytest.mark.parametrize('args', [('--unknown',), ('0', '3', '--limit', '0'), ('3', '2'), ('0', '3', '--limit', '1.5')])
def test_query_rejects_bad_arguments(package, args):
    node(package, 'query.mjs', *args, expected=2)


@pytest.mark.parametrize('example', DIRECTING_EXAMPLES)
def test_instructional_scores_compile_and_bind(package, example):
    report = node(package, 'verify.mjs', '--example', example)
    assert report['scoreValid'] and report['savedStages'] == 'matched'
    assert all(e['binding'] == 'matched' for e in report['declaredEvents'])
    assert (package / f'examples/directing/{example}.mp4').stat().st_size < 150000


def test_real_song_example_keeps_plan_and_never_overwrites(package):
    project = package.parent / 'sample-project'
    node(package, 'examples/start.mjs', '--out', project, '--seconds', '3')
    score_path = project / 'score.json'
    score = json.loads(score_path.read_text())
    assert [(s['start'], s['end']) for s in score['stages']] == [(0, 1.234), (1.234, 8)]
    assert score['intent'] == 'music-video'
    assert score['sync'][0]['cueId'] != 'o:0'
    node(package, 'music-brief.mjs', '--score', score_path, '--mv')
    node(package, 'verify.mjs', '--score', score_path)
    before = score_path.read_bytes()
    node(package, 'examples/start.mjs', '--out', project, expected=1)
    assert score_path.read_bytes() == before


def test_verify_exposes_moved_and_deleted_bindings(package):
    project = package.parent / 'sample-project'
    node(package, 'examples/start.mjs', '--out', project)
    score_path = project / 'score.json'
    score = json.loads(score_path.read_text())
    score['sync'] = [{'at': 2, 'cueId': 'o:1', 'kind': 'impact'}, {'at': 0, 'cueId': 'o:0', 'kind': 'impact'}]
    score_path.write_text(json.dumps(score))
    report = node(package, 'verify.mjs', '--score', score_path, expected=1)
    assert report['declaredEvents'][0]['authoredOffsetMs'] == pytest.approx(-200)
    assert report['declaredEvents'][1]['binding'] == 'missing/deleted cue'
    score['stages'][0]['end'] = 1
    score['stages'][0]['rhythm'][0]['end'] = 1
    score['stages'][1]['start'] = 1
    score['stages'][1]['rhythm'][0]['start'] = 1
    score['stages'][1]['rhythm'][0]['anchors'] = [1]
    score_path.write_text(json.dumps(score))
    report = node(package, 'verify.mjs', '--score', score_path, expected=1)
    assert report['savedStages'] == 'stale stage boundaries'
    node(package, 'music-brief.mjs', '--score', score_path, '--mv', expected=1)


def test_adapter_rejects_oversized_buffers_before_loading_dependencies(package):
    result = subprocess.run(['node', 'render.mjs', '--example', 'accent', '--demo-audio', '--out', '../bad.mp4', '--width', '4096', '--height', '4096', '--memory-mb', '128'], cwd=package, capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 2 and 'Frame buffers exceed' in result.stderr


def test_new_helpers_have_a_template_trust_boundary(package):
    from beatscope.consumer_validation import validate_handoff
    report = validate_handoff(package)
    assert report['ok'], report
    helper = package / 'tool-utils.mjs'
    helper.write_bytes(helper.read_bytes() + b'\n// modified consumer executable\n')
    manifest_path = package / 'beatscope-package.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['integrity']['members']['tool-utils.mjs'] = hashlib.sha256(helper.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    report = validate_handoff(package)
    checks = {c['name']: c for c in report['checks']}
    assert checks['integrity']['status'] == 'passed'
    assert 'executable:untrusted-bytes:tool-utils.mjs' in checks['executable-trust']['errors']


@pytest.mark.skipif(not os.environ.get('BEATSCOPE_TEST_PLAYWRIGHT') or not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='Explicit existing browser tools needed for render integration')
def test_three_second_audio_render_resume_and_corrupt_segment(package):
    project = package.parent / 'sample-project'
    node(package, 'examples/start.mjs', '--out', project)
    out = package.parent / 'sample.mp4'
    args = ['render.mjs', '--entry', project / 'scene.html', '--root', package.parent, '--audio', package.parent / 'song.wav', '--out', out, '--seconds', '3', '--width', '320', '--height', '320', '--chunk-frames', '30', '--playwright', os.environ['BEATSCOPE_TEST_PLAYWRIGHT']]
    if os.environ.get('BEATSCOPE_TEST_BROWSER'):
        args += ['--browser', os.environ['BEATSCOPE_TEST_BROWSER']]
    wrong = package.parent / 'wrong.wav'
    wrong.write_bytes(b'not the original song')
    wrong_args = list(args)
    wrong_args[wrong_args.index('--audio') + 1] = wrong
    refused = subprocess.run(['node', *map(str, wrong_args)], cwd=package, capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert refused.returncode == 2 and 'source SHA-256' in refused.stderr
    report = node(package, *args, timeout=120)
    assert report['frameCount'] == 90 and report['reusedSegments'] == 0 and report['browserStarts'] == 1
    first_bytes = out.read_bytes()
    report = node(package, *args, '--resume', timeout=120)
    assert report['reusedSegments'] == 3 and out.read_bytes() == first_bytes
    checkpoint = next(package.parent.glob('.render-*/state.json'))
    state = json.loads(checkpoint.read_text())
    assert not (checkpoint.parent / 'joined.mp4').exists()
    (checkpoint.parent / state['parts'][1]['name']).write_bytes(b'broken partial segment')
    report = node(package, *args, '--resume', timeout=120)
    assert report['reusedSegments'] == 2 and out.read_bytes() == first_bytes
    sync = node(package, 'verify.mjs', '--score', project / 'score.json', '--video', out, '--threshold', '1')
    assert sync['audioIdentity'] == 'bound by render report'
    assert all(e['observed'] == 'unverified' for e in sync['declaredEvents'])
    with (project / 'score.json').open('a') as stream:
        stream.write('\n')
    node(package, *args, '--resume', expected=2)
    assert out.read_bytes() == first_bytes


def test_no_per_song_audio_in_instructional_package(package):
    assert all((package / name).is_file() for name in HANDOFF_RESOURCES)
    assert not list(package.rglob('*.wav')) and not list(package.rglob('*.mp3'))


def render_args(package, output='sample.mp4', chunk='30'):
    args = ['render.mjs', '--example', 'transition', '--demo-audio', '--out', package.parent / output, '--seconds', '1', '--width', '320', '--height', '320', '--chunk-frames', chunk, '--playwright', os.environ['BEATSCOPE_TEST_PLAYWRIGHT']]
    if os.environ.get('BEATSCOPE_TEST_BROWSER'):
        args += ['--browser', os.environ['BEATSCOPE_TEST_BROWSER']]
    return args


browser_tools = pytest.mark.skipif(not os.environ.get('BEATSCOPE_TEST_PLAYWRIGHT') or not shutil.which('ffmpeg'), reason='Explicit browser tools needed')


@browser_tools
def test_custom_executable_size_preflight_and_clean(package):
    executable = os.environ.get('BEATSCOPE_TEST_EXECUTABLE')
    if not executable:
        pytest.skip('Explicit browser executable required')
    args = render_args(package, chunk='10')
    if '--browser' in args:
        i = args.index('--browser'); del args[i:i+2]
    args += ['--executable', executable, '--clean']
    report = node(package, *args, timeout=120)
    assert report['browserStarts'] == 1 and report['cachePolicy'] == 'removed-after-success'
    assert (package.parent / 'sample.mp4').is_file()
    assert not list(package.parent.glob('.render-*'))
    # Deliberately omit resize, to verify early dimensions rather than late encoder failure.
    scene = package.parent / 'fixed.html'
    scene.write_text('<canvas id="frame" width="1280" height="720"></canvas><script>window.beatscopeRender={duration:8,selector:"#frame",renderAt(){}}</script>')
    args = ['render.mjs', '--entry', scene, '--root', package.parent, '--audio', package.parent / 'song.wav', '--out', package.parent / 'bad.mp4', '--width', '3840', '--height', '2160', '--playwright', os.environ['BEATSCOPE_TEST_PLAYWRIGHT'], '--executable', executable]
    result = subprocess.run(['node', *map(str, args)], cwd=package, capture_output=True, text=True, encoding='utf-8', timeout=40)
    assert result.returncode == 2 and '1280×720' in result.stderr and '3840×2160' in result.stderr
    assert not list(package.parent.glob('.render-*/part-*.mp4'))


@browser_tools
def test_browser_recycling_and_exclusions_preserve_pixels(package):
    generated = package / 'generated'; generated.mkdir()
    (generated / 'large.bin').write_bytes(b'not a render dependency')
    args = render_args(package, 'reuse.mp4', chunk='10') + ['--exclude', 'generated', '--exclude', 'references']
    report = node(package, *args, timeout=120)
    assert report['browserStarts'] == 1 and report['settings']['exclude'] == ['generated', 'references']
    (generated / 'large.bin').write_bytes(b'changed generated output')
    reused = node(package, *args, '--resume', timeout=120)
    assert reused['reusedSegments'] == 3
    other = render_args(package, 'recycle.mp4', chunk='10') + ['--browser-restart-every', '1', '--exclude', 'generated', '--exclude', 'references']
    report = node(package, *other, timeout=120)
    assert report['browserStarts'] == 3
    def frames(path):
        return subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:v', '-f', 'framemd5', '-'], capture_output=True, check=True).stdout
    assert frames(package.parent / 'reuse.mp4') == frames(package.parent / 'recycle.mp4')


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg needed')
def test_frames_directory_without_playwright_and_changed_frame_resume(package):
    from PIL import Image
    frames = package.parent / 'frames'; frames.mkdir()
    for i in range(9):
        Image.new('RGB', (320, 320), (i*24, 50, 200)).save(frames / f'frame-{i:06}.png')
    args = ['render.mjs', '--frames-dir', frames, '--audio', package.parent / 'song.wav', '--out', package.parent / 'frames.mp4', '--seconds', '.3', '--chunk-frames', '3', '--width', '320', '--height', '320']
    report = node(package, *args)
    assert report['frameCount'] == 9 and report['browserStarts'] == 0 and report['sourceBytes'] == 0
    assert node(package, *args, '--resume')['reusedSegments'] == 3
    Image.new('RGB', (320, 320), 'red').save(frames / 'frame-000005.png')
    node(package, *args, '--resume', expected=2)
    report = node(package, *args, '--clean')
    assert report['cachePolicy'] == 'removed-after-success'
    assert not list(package.parent.glob('.render-*'))
    Image.new('RGB', (640, 320)).save(frames / 'frame-000005.png')
    node(package, *args, expected=2)


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg needed')
def test_transcoded_audio_matches_verified_original_and_rejects_other_song(package):
    original = package.parent / 'song.wav'
    transcoded = package.parent / 'song.mp3'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(original), '-c:a', 'libmp3lame', '-b:a', '128k', str(transcoded)], check=True)
    expected = hashlib.sha256(original.read_bytes()).hexdigest()
    driver = package / 'audio-check.mjs'
    driver.write_text("import {audioIdentity} from './render-inputs.mjs'; import {hashFile} from './tool-utils.mjs'; try{console.log(JSON.stringify(await audioIdentity(process.argv[2],await hashFile(process.argv[2]),process.argv[4],process.argv[3])))}catch(e){console.error(e.message);process.exitCode=2}")
    report = node(package, driver, transcoded, original, expected)
    assert report['audioIdentity'] == 'transcoded-match'
    assert len(report['comparisons']) == 3 and report['referenceSha256'] == expected
    other = package.parent / 'other.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=350:duration=8', str(other)], check=True)
    node(package, driver, other, original, expected, expected=2)
    node(package, driver, transcoded, other, expected, expected=2)
    # Exercise the actual frame driver and verifier with the transcoded result.
    from PIL import Image
    frames = package.parent / 'frames'; frames.mkdir()
    for i in range(3):
        Image.new('RGB', (320, 320), (80*i, 100, 40)).save(frames / f'frame-{i:06}.png')
    media = package.parent / 'transcoded.mp4'
    report = node(package, 'render.mjs', '--frames-dir', frames, '--audio', transcoded, '--reference-audio', original, '--out', media, '--seconds', '.1', '--width', '320', '--height', '320')
    assert report['audioIdentity'] == 'transcoded-match'
    project = package.parent / 'sample-project'
    node(package, 'examples/start.mjs', '--out', project)
    sync = node(package, 'verify.mjs', '--score', project / 'score.json', '--video', media)
    assert sync['audioMatch'] == 'transcoded-match'


def test_snapshot_warning_and_disk_preflight(package):
    assets = package.parent / 'only-sources'; assets.mkdir()
    with (assets / 'generated.bin').open('wb') as stream:
        stream.truncate(51*1024*1024)
    driver = package / 'inputs-check.mjs'
    driver.write_text("import {sourceHashes,diskSpace} from './render-inputs.mjs'; const root=process.argv[2]; if(process.argv[3]==='disk'){try{await diskSpace(root,{width:4096,height:4096,frameCount:1e9});process.exitCode=1}catch(e){console.log(JSON.stringify({message:e.message}))}}else{console.log(JSON.stringify(await sourceHashes(root,new Set(),[])))}")
    result = subprocess.run(['node', str(driver), str(assets)], cwd=package, capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0 and '51.0 MiB' in result.stderr
    assert len(json.loads(result.stdout)['rows']) == 1
    report = node(package, driver, assets, 'disk')
    assert 'Insufficient estimated disk space' in report['message']


@browser_tools
def test_interrupted_reused_browser_job_resumes_completed_segment(package):
    args = render_args(package, 'interrupted.mp4', chunk='20')
    args[args.index('--seconds') + 1] = '2'
    process = subprocess.Popen(['node', *map(str, args)], cwd=package, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
    progress = []
    try:
        for line in process.stderr:
            progress.append(line)
            if 'Rendered segment 1/3' in line:
                process.terminate()
                break
        process.communicate(timeout=20)
        assert any('Rendered segment 1/3' in line for line in progress), ''.join(progress)
        assert process.returncode != 0
    finally:
        if process.poll() is None:
            process.kill(); process.communicate()
    report = node(package, *args, '--resume', timeout=120)
    assert report['reusedSegments'] >= 1 and report['frameCount'] == 60


@browser_tools
def test_excluded_dependency_cannot_bypass_snapshot(package):
    ignored = package / 'ignored'; ignored.mkdir()
    (ignored / 'data.json').write_text('{}')
    scene = package / 'excluded.html'
    scene.write_text('<canvas width="320" height="320"></canvas><script>window.beatscopeRender={duration:8,ready:fetch("./ignored/data.json").then(r=>{if(!r.ok)throw Error("asset failed")}),renderAt(){}}</script>')
    args = ['node', 'render.mjs', '--entry', scene, '--root', package, '--exclude', 'ignored', '--audio', package.parent / 'song.wav', '--out', package.parent / 'excluded.mp4', '--width', '320', '--height', '320', '--playwright', os.environ['BEATSCOPE_TEST_PLAYWRIGHT']]
    if os.environ.get('BEATSCOPE_TEST_BROWSER'):
        args += ['--browser', os.environ['BEATSCOPE_TEST_BROWSER']]
    result = subprocess.run(list(map(str, args)), cwd=package, capture_output=True, text=True, encoding='utf-8', timeout=40)
    assert result.returncode == 2 and 'excluded dependency' in result.stderr
    assert not list(package.parent.glob('.render-*/part-*.mp4'))
