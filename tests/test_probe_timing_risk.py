import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from beatscope.exports import generate_codex_export


@pytest.mark.skipif(shutil.which('node') is None,reason='Node unavailable')
def test_runtime_success_does_not_hide_suspect_tempo(tmp_path):
    root=Path(__file__).resolve().parents[1]
    rhythm=json.loads((root/'tests/fixtures/runtime/characterization-project.json').read_text())
    rhythm['tempo']['segments']=[{'start':0,'end':rhythm['source']['duration'],'bpm':180,'score':.1}]
    rhythm['tempo']['global_bpm']=120
    with zipfile.ZipFile(io.BytesIO(generate_codex_export(rhythm))) as z:z.extractall(tmp_path)
    proc=subprocess.run(['node',str(tmp_path/'consumer-probe.js'),str(tmp_path)],capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr+proc.stdout
    report=json.loads(proc.stdout)
    assert report['ok'] and report['runtime_contract_ok']
    assert report['timing_reliability']['assessment']=='needs-crosscheck'
    assert report['timing_reliability']['suspect_tempo_regions'][0]['bpm']==180
