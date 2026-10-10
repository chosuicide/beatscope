"""Run shipped authoring tools from fresh packages, including unranked timing."""
import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from beatscope.consumer_contract import validate_manifest
from beatscope.consumer_validation import _executable_trust_check
from beatscope.exports import generate_codex_export


@pytest.mark.parametrize('ranked', [True, False])
def test_brief_and_score_execute_from_export(tmp_path, ranked):
    if shutil.which('node') is None:
        pytest.skip('Node unavailable')
    rhythm = json.loads((Path(__file__).parent / 'fixtures/runtime/characterization-project.json').read_text())
    duration = rhythm['source']['duration']
    middle = duration / 2
    rhythm.setdefault('patterns', {})['segments'] = [
        {'id': 'one', 'start_time': 0, 'end_time': middle, 'family': 'A', 'mean_rms': .2},
        {'id': 'two', 'start_time': middle, 'end_time': duration, 'family': 'B', 'mean_rms': .4},
    ]
    with zipfile.ZipFile(io.BytesIO(generate_codex_export(rhythm, include_response_relevance=ranked))) as archive:
        members = {n: archive.read(n) for n in archive.namelist()}
        archive.extractall(tmp_path)
    manifest = json.loads(members['beatscope-package.json'])
    assert validate_manifest(manifest, members) == []
    assert _executable_trust_check(manifest, members)['status'] == 'passed'
    brief = subprocess.run(['node', 'music-brief.mjs'], cwd=tmp_path, capture_output=True, text=True, check=True)
    doc = json.loads(brief.stdout)
    assert len(doc['stages']) == 2
    assert [s['waveformRms'] for s in doc['automaticSections']] == [.2, .4]
    assert doc['stages'][0]['interval'] == [0, middle]
    assert len(brief.stdout.encode()) < 14000
    assert all(len(s['measuredAnchorCandidates']) <= 3 for s in doc['stages'])
    bad = subprocess.run(['node', 'music-brief.mjs', 'NaN', '2'], cwd=tmp_path, capture_output=True, text=True)
    assert bad.returncode == 2 and 'start must be between' in bad.stderr

    score = {'moments': {'arrival': middle},
             'stages': [{'id': 'first', 'start': 0, 'end': middle, 'focus': 'subject', 'change': 'approach'},
                        {'id': 'second', 'start': middle, 'end': duration, 'focus': 'interior', 'change': 'reveal'}],
             'tracks': [{'id': 'camera.z', 'keys': [{'at': 0, 'value': 10},
                         {'at': {'moment': 'arrival'}, 'value': 0, 'ease': 'hold'}]},
                        {'id': 'foreground.visible', 'keys': [{'at': 0, 'value': True, 'ease': 'hold'},
                         {'at': {'moment': 'arrival'}, 'value': False}]}]}
    (tmp_path / 'score.json').write_text(json.dumps(score))
    result = subprocess.run(['node', 'music-brief.mjs', '--score', 'score.json'], cwd=tmp_path,
                            capture_output=True, text=True, check=True)
    checked = json.loads(result.stdout)
    assert checked['ok'] is True and checked['moments']['arrival'] == middle

    # Same shipped command understands a grouped edit, not merely numeric tracks.
    edited = json.loads(json.dumps(score))
    edited['tracks'][0]['id'] = 'world.progress'
    edited['shots'] = [{'id': 'A', 'relation': 'whole subject', 'values': {'camera.z': 10}},
                       {'id': 'B', 'relation': 'same subject detail', 'values': {'camera.z': 2}}]
    edited['stages'][0]['entry'] = 'A'
    edited['stages'][1]['entry'] = 'B'
    edited['groups'] = [{'id': 'phrase', 'stage': 'first',
                         'anchors': [middle / 4, middle / 2, middle * .75],
                         'sequence': ['B', None, 'A']}]
    (tmp_path / 'edit.json').write_text(json.dumps(edited))
    result = subprocess.run(['node', 'music-brief.mjs', '--score', 'edit.json'], cwd=tmp_path,
                            capture_output=True, text=True, check=True)
    checked = json.loads(result.stdout)
    assert checked['ok'] is True and checked['cutCount'] == 4
    legacy_mv = subprocess.run(['node', 'music-brief.mjs', '--score', 'edit.json', '--mv'],
                               cwd=tmp_path, capture_output=True, text=True)
    assert legacy_mv.returncode == 1 and 'MV requires' in legacy_mv.stderr
    edited['intent'] = 'music-video'
    edited['stages'][0]['rhythm'] = [{'start': 0, 'end': middle, 'mode': 'alternate',
        'music': 'repeated attacks', 'reason': 'whole and detail alternate', 'anchors': [middle / 4]}]
    edited['stages'][1]['rhythm'] = [{'start': middle, 'end': duration, 'mode': 'hold',
        'music': 'sustained passage', 'reason': 'arrive inside detail', 'anchors': [middle],
        'action': 'travel through the detail toward its interior'}]
    (tmp_path / 'mv.json').write_text(json.dumps(edited))
    result = subprocess.run(['node', 'music-brief.mjs', '--score', 'mv.json', '--mv'],
                            cwd=tmp_path, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)['rhythm'][0]['switches'] == 2
    # Fresh engine exports must carry MV continuous return clocks and global
    # travel; verifying the repository module alone misses stale bundled code.
    (tmp_path / 'ongoing.mjs').write_text('''
import assert from 'node:assert/strict';
import fs from 'node:fs';
import * as music from './visual-state.js';
import {createEditScore} from './edit-score.js';
const score = JSON.parse(fs.readFileSync('mv.json', 'utf8'));
const end = music.RHYTHM_MAP.duration;
score.tracks.push({id:'world.travel',keys:[{at:0,value:0}],
  pace:{from:0,to:end,every:1,step:1,mode:'travel'}});
const edit = createEditScore(score,music);
const returned = edit.at(end*.4);
assert.equal(returned.view.id,'A');
assert.equal(returned.view.clockMode,'continuous');
assert.equal(returned.view.localTime,end*.4);
assert.ok(edit.at(end*.45).values['world.travel'] > returned.values['world.travel']);
const held = JSON.stringify(edit.at(end*.9));
edit.at(end*.1);
assert.equal(JSON.stringify(edit.at(end*.9)),held);
score.shots[0].clock = {mode:'visible'};
assert.ok(createEditScore(score,music).at(end*.4).view.localTime < returned.view.localTime);
console.log('Fresh export MV clocks and global travel passed');
''', encoding='utf-8')
    subprocess.run(['node', 'ongoing.mjs'], cwd=tmp_path, capture_output=True, text=True, check=True)
    # Exercise the actual helper shipped by the exporter with compiled music,
    # shared multi-layer motion and a return, rather than only importing source.
    (tmp_path / 'picture.mjs').write_text('''
import assert from 'node:assert/strict';
import fs from 'node:fs';
import * as music from './visual-state.js';
import {createEditScore} from './edit-score.js';
import {frame2D,frame3D,createPictureBindings} from './picture-tools.js';
const score = JSON.parse(fs.readFileSync('mv.json','utf8'));
const end = music.RHYTHM_MAP.duration;
score.shots[0].setup={target:{x:0,y:0,width:800,height:400},coverage:.8};
score.shots[1].setup={target:{x:220,y:110,width:160,height:80},coverage:.9};
score.tracks.push({id:'world.travel',keys:[{at:0,value:0}],
  pace:{from:0,to:end,every:1,step:1,mode:'travel'}});
const edit=createEditScore(score,music), drawn={};
const view=(setup,state)=>{drawn.shot=state.view.id;
  drawn.pose=frame2D(setup.target,{width:1280,height:720},{coverage:setup.coverage})};
const binding=createPictureBindings(edit,{views:{A:view,B:view},values:{
  'world.progress':v=>{drawn.progress=v},
  'foreground.visible':v=>{drawn.visible=v},
  'camera.z':v=>{drawn.z=v},
  'world.travel':[v=>{drawn.near=v*30},v=>{drawn.far=v*5}]
}});
binding.apply(end*.4);
assert.equal(drawn.shot,'A');
assert.ok(drawn.near>drawn.far && drawn.far>0);
const advanced=drawn.near;
binding.apply(end*.45); assert.ok(drawn.near>advanced);
const snapshot=JSON.stringify(drawn);
binding.apply(end*.1); binding.apply(end*.45);
assert.equal(JSON.stringify(drawn),snapshot);
assert.ok(frame3D({min:[-2,-1,-3],max:[2,1,3]},
  {direction:[1,.2,1],fov:45,aspect:16/9,coverage:.8}).distance>1);
console.log('Fresh export native bindings and framing passed');
''', encoding='utf-8')
    subprocess.run(['node', 'picture.mjs'], cwd=tmp_path, capture_output=True, text=True, check=True)
    edited['groups'] = []
    (tmp_path / 'mv.json').write_text(json.dumps(edited))
    missing = subprocess.run(['node', 'music-brief.mjs', '--score', 'mv.json', '--mv'],
                             cwd=tmp_path, capture_output=True, text=True)
    assert missing.returncode == 1 and 'no matching shot changes' in missing.stderr
    groups = subprocess.run(['node', 'music-brief.mjs', '--groups', '0', str(duration), str(duration)],
                            cwd=tmp_path, capture_output=True, text=True, check=True)
    assert json.loads(groups.stdout)['status'].startswith('numerical adjacency')
    score['tracks'].append(score['tracks'][0])
    (tmp_path / 'score.json').write_text(json.dumps(score))
    failed = subprocess.run(['node', 'music-brief.mjs', '--score', 'score.json'], cwd=tmp_path,
                            capture_output=True, text=True)
    assert failed.returncode == 1 and 'one track writer' in failed.stderr

    changed = dict(members)
    changed['choreography.js'] += b'\n// altered\n'
    assert _executable_trust_check(manifest, changed)['status'] == 'failed'
    changed = dict(members)
    del changed['choreography.js']
    assert 'authoring.module:missing-member:choreography.js' in validate_manifest(manifest, changed)
    changed = dict(members)
    changed['edit-score.js'] += b'\n// altered\n'
    assert _executable_trust_check(manifest, changed)['status'] == 'failed'
    changed = dict(members)
    changed['picture-tools.js'] += b'\n// altered\n'
    assert _executable_trust_check(manifest, changed)['status'] == 'failed'
    hidden = json.loads(json.dumps(manifest))
    hidden['capabilities']['edit_score'] = False
    assert 'authoring.editor:requires-edit-score' in validate_manifest(hidden, changed)
    assert _executable_trust_check(hidden, changed)['status'] == 'failed'
