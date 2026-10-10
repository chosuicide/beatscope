"""Re-render a bounded sample from cached music facts; never calls analysis."""
import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from beatscope.edit_plan import load_edit_plan
from beatscope.material_templates import material_root, validate_template
from beatscope.mv_jobs import RUNTIME, WEB, renderer_tools
from beatscope.project import ProjectManager
from beatscope.response_relevance import build_response_relevance

parser = argparse.ArgumentParser()
parser.add_argument('--project', default='bb4987145c2d')
parser.add_argument('--template', default='material-mix')
parser.add_argument('--seconds', type=float, default=30)
parser.add_argument('--seed', type=int, default=17)
parser.add_argument('--score', type=Path, help='Optional authored music-video score, over the same song duration')
parser.add_argument('--output', type=Path, help='Isolated sample output directory')
parser.add_argument('--renderer', type=Path, help='Authored sample adapter, copied into the isolated job')
args = parser.parse_args()
validate_template(args.template)
if not args.template.startswith('material-'):
    raise ValueError('This demo is for material templates')
projects = ProjectManager()
rhythm = projects.get_project_rhythm(args.project)
tools = renderer_tools()
if not tools['available']:
    raise ValueError(tools['message'])
root = args.output or Path('output/material-template-demo') / args.template
root.mkdir(parents=True, exist_ok=True)
payload = {'rhythm':rhythm,'ranking':build_response_relevance(rhythm),
           'editPlan':load_edit_plan(projects,args.project,rhythm),'seed':args.seed,
           'audio':str(projects.get_project_audio_path(args.project)),
           'template':args.template,'materialRoot':str(material_root()),'renderEnd':args.seconds}
if args.score:
    payload['scoreFile'] = str(args.score.resolve())
(root/'input.json').write_text(json.dumps(payload),encoding='utf-8')
for name in ('mv-render.html','mv-frame.mjs','mv-visual.js','mv-plan.mjs','mv-encode.mjs','movie-factory.mjs','movie-templates.mjs','material-frame.mjs','material-gpu.mjs','custom-media.mjs','media-color.mjs','paint-frame.mjs','paint-sources.mjs'):
    shutil.copyfile(WEB/name,root/name)
if args.renderer:
    shutil.copyfile(args.renderer,root/'material-frame.mjs')
shutil.copyfile(RUNTIME/'runtime.js',root/'beatscope-runtime.js')
shutil.copyfile(RUNTIME/'edit-plan.js',root/'edit-plan.js')
(root/'package.json').write_text('{"type":"module"}',encoding='utf-8')
env = dict(os.environ,BEATSCOPE_FFMPEG=tools['ffmpeg'],BEATSCOPE_PLAYWRIGHT_MODULE=tools['module'])
subprocess.run([tools['node'],str(WEB/'material-prepare.mjs'),str(root.resolve())],env=env,check=True)
subprocess.run([tools['node'],str(WEB/'mv-worker.mjs'),str(root.resolve())],env=env,check=True)
print(root.resolve()/'movie.mp4')
