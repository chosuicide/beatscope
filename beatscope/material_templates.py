"""Versioned online-source material pack and shared preview/render preparation."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from .edit_plan import edit_plan_bytes, load_edit_plan
from .response_relevance import build_response_relevance

WEB = Path(__file__).parent / 'web'
TEMPLATES = {'voxel', 'material-mix'}

def material_root():
    if os.environ.get('BEATSCOPE_MATERIAL_ROOT'):
        return Path(os.environ['BEATSCOPE_MATERIAL_ROOT']).resolve()
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent / 'materials'
    candidates = (Path.cwd() / 'materials', WEB.parent.parent / 'materials',
                  WEB.parent.parent / 'videos/mafia-square-mv')
    return next((path.resolve() for path in candidates if path.is_dir()), candidates[0].resolve())

def validate_template(value):
    if value not in TEMPLATES:
        raise ValueError('Unknown movie template')
    return value

def _material_version(names):
    digest = hashlib.sha256()
    for name in names:
        digest.update((WEB / name).read_bytes())
    for name in ('runtime.js','edit-plan.js','edit-score.js','choreography.js'):
        digest.update((WEB.parent / 'runtime' / name).read_bytes())
    digest.update(str(material_root()).encode())
    return digest.hexdigest()

def material_data_version():
    # Shader changes do not alter graded atlases or the compiled edit plan.
    return _material_version(('material-library.json','material-setups.json','material-plan.mjs','material-prepare.mjs','mv-plan.mjs'))

def material_version():
    digest = hashlib.sha256(material_data_version().encode())
    for name in ('material-frame.mjs','material-gpu.mjs'):
        digest.update((WEB / name).read_bytes())
    return digest.hexdigest()

class MaterialTemplates:
    def __init__(self, projects):
        self.projects = projects
        self.root = projects.cache_root / 'materials'
        self.root.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.states = {}
        self.build_slots = threading.Semaphore(1)
        self.failed_at = {}

    def prepare(self, project_id, seed, template, tools, rhythm=None, edit_plan=None):
        validate_template(template)
        if template == 'voxel' or not re.fullmatch(r'[0-9a-f]{12}', project_id):
            raise ValueError('Invalid material preview request')
        if type(seed) is not int or not 0 <= seed < 2**24:
            raise ValueError('Invalid seed')
        if not tools['available']:
            raise ValueError(tools['message'])
        rhythm = rhythm or self.projects.get_project_rhythm(project_id)
        if rhythm is None:
            raise ValueError('Project analysis missing')
        edit_plan = edit_plan or load_edit_plan(self.projects, project_id, rhythm)
        digest = hashlib.sha256(edit_plan_bytes(edit_plan)).hexdigest()
        key = hashlib.sha256(json.dumps([rhythm['source']['sha256'],seed,template,digest,material_data_version()]).encode()).hexdigest()
        directory = self.root / key
        with self.lock:
            if (directory / 'ready.json').is_file():
                return {'state':'ready','key':key,'base':f'/api/materials/cache/{key}/'}
            if key in self.states:
                # Permit a later explicit retry after a transient decoder failure.
                if self.states[key]['state'] == 'failed':
                    if time.monotonic() - self.failed_at.get(key,0) < 30:
                        return dict(self.states[key])
                    del self.states[key]
                else:
                    return dict(self.states[key])
            library = json.loads((WEB / 'material-library.json').read_bytes())
            for asset in library['assets']:
                file = (material_root() / asset['file']).resolve()
                if not file.is_relative_to(material_root()) or not file.is_file():
                    raise ValueError(f"Material pack missing: {asset['id']}; set BEATSCOPE_MATERIAL_ROOT")
            directory.mkdir(exist_ok=True)
            state = {'state':'preparing','key':key,'base':f'/api/materials/cache/{key}/'}
            self.states[key] = state
            payload = {'rhythm':rhythm,'ranking':build_response_relevance(rhythm),'editPlan':edit_plan,
                       'seed':seed,'template':template,'materialRoot':str(material_root())}
            (directory / 'input.json').write_text(json.dumps(payload), encoding='utf-8')
            threading.Thread(target=self._build,args=(key,directory,tools),daemon=True).start()
            return dict(state)

    def _build(self, key, directory, tools):
        try:
            with self.build_slots, (directory / 'prepare.log').open('w',encoding='utf-8') as log:
                result = subprocess.run([tools['node'],str(WEB/'material-prepare.mjs'),str(directory)],
                    stdout=log,stderr=log,env=dict(os.environ,BEATSCOPE_FFMPEG=tools['ffmpeg']),
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=1800)
            if result.returncode:
                raise ValueError('Material preparation failed; see '+str(directory/'prepare.log'))
            (directory / 'ready.json').write_text('{"ready":true}',encoding='utf-8')
            with self.lock:
                self.states[key]['state'] = 'ready'
        except Exception as exc:
            with self.lock:
                self.failed_at[key] = time.monotonic()
                self.states[key].update(state='failed',message=str(exc))

    def resource(self, key, relative):
        if not re.fullmatch(r'[0-9a-f]{64}',key):
            return None
        if relative not in {'material-timeline.json','material-library.json','score.json','plan.json'} and not re.fullmatch(r'media/[A-Za-z0-9_-]+\.jpg',relative):
            return None
        target = self.root / key / relative
        return target if (self.root/key/'ready.json').is_file() and target.is_file() else None
