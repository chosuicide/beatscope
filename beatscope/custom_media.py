"""Image/clip arrangement sidecar; assets reuse the existing project asset store."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .assets import AssetStore
from .composition_store import composition_lock
from .project import _atomic_write_bytes


def media_bytes(document):
    return (json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def load_media(manager, project_id):
    rhythm = manager.get_project_rhythm(project_id)
    if rhythm is None:
        raise FileNotFoundError('media/project-not-found')
    path = manager.get_project_dir(project_id) / 'custom-media.json'
    if path.exists():
        if path.stat().st_size > 512 * 1024:
            raise ValueError('media/too-large')
        return validate_media(json.loads(path.read_bytes()), rhythm, manager, project_id)
    return {'schema': 'beathi-media-1', 'source_sha256': rhythm['source'].get('sha256', ''),
            'target': .5, 'seed': 1, 'assets': [], 'slots': []}


def validate_media(doc, rhythm, manager, project_id):
    def number(v, low, high):
        return type(v) in (int, float) and math.isfinite(v) and low <= v <= high

    required = {'schema', 'source_sha256', 'target', 'seed', 'assets', 'slots'}
    if not isinstance(doc, dict) or not required <= set(doc) or set(doc) - required - {'color'}:
        raise ValueError('media/schema')
    if doc['schema'] != 'beathi-media-1' or doc['source_sha256'] != rhythm['source'].get('sha256', ''):
        raise ValueError('media/source-changed')
    if not number(doc['target'], 0, 1) or type(doc['seed']) is not int or not 0 <= doc['seed'] < 2**24:
        raise ValueError('media/settings')
    if 'color' in doc:
        color = doc['color']
        if not isinstance(color, dict) or set(color) != {'enabled', 'strength'} or type(color['enabled']) is not bool or not number(color['strength'], 0, 1):
            raise ValueError('media/settings')
    if not isinstance(doc['assets'], list) or len(doc['assets']) > 100 or not isinstance(doc['slots'], list) or len(doc['slots']) > 2000:
        raise ValueError('media/limit')
    store = AssetStore(manager.get_project_dir(project_id), project_id)
    catalog = {a['asset_id']: a for a in store.manifest()}
    ids = set()
    kinds = {}
    durations = {}
    for row in doc['assets']:
        if not isinstance(row, dict) or set(row) - {'id', 'focus', 'overrides', 'proxy', 'kind', 'clip', 'duration'} or not {'id', 'focus', 'overrides'} <= set(row) or row['id'] in ids:
            raise ValueError('media/asset')
        ids.add(row['id'])
        entry = catalog.get(row['id'])
        kind = row.get('kind', 'image')
        if kind not in ('image', 'video'):
            raise ValueError('media/asset')
        if not entry or entry['kind'] != kind or not store.path_for(row['id']):
            raise ValueError('media/asset-missing')
        if row.get('proxy') and (row['proxy'] not in catalog or catalog[row['proxy']]['kind'] != 'image' or not store.path_for(row['proxy'])):
            raise ValueError('media/proxy-missing')
        if kind == 'video':
            clip = catalog.get(row.get('clip'))
            if not clip or clip['kind'] != 'video' or not store.path_for(row['clip']):
                raise ValueError('media/asset')
            if row.get('proxy') is None:
                raise ValueError('media/asset')
            source_duration = entry.get('duration')
            if not number(row.get('duration'), 0, 120) or abs(row['duration'] - float(source_duration or -1)) > 1e-3:
                raise ValueError('media/asset')
            durations[row['id']] = row['duration']
        kinds[row['id']] = kind
        if not isinstance(row['overrides'], dict) or set(row['overrides']) - {'1:1', '16:9', '9:16'}:
            raise ValueError('media/focus')
        for focus in [row['focus'], *row['overrides'].values()]:
            if not isinstance(focus, dict) or set(focus) != {'x', 'y', 'zoom', 'fit'} or focus['fit'] not in ('cover', 'contain') or not number(focus['x'], 0, 1) or not number(focus['y'], 0, 1) or not number(focus['zoom'], 1, 3):
                raise ValueError('media/focus')
    previous = 0
    for row in doc['slots']:
        if not isinstance(row, dict):
            raise ValueError('media/slot')
        video = kinds.get(row.get('asset')) == 'video'
        if not isinstance(row, dict) or set(row) != ({'start', 'end', 'asset', 'fixed', 'offset'} if video else {'start', 'end', 'asset', 'fixed'}) or row['asset'] not in ids or type(row['fixed']) is not bool or not number(row['start'], previous, rhythm['source']['duration']) or not number(row['end'], row['start'], rhythm['source']['duration']) or row['end'] <= row['start']:
            raise ValueError('media/slot')
        if video and (not number(row.get('offset'), 0, 120) or row['offset'] + (row['end'] - row['start']) > durations[row['asset']] + 1 / 30 + 1e-6):
            raise ValueError('media/slot')
        previous = row['end']
    return doc


# Keep both output dimensions even for browser-safe H.264/YUV420. Cropped
# originals may have an odd short edge; -2 only rounds the other dimension.
def _short_edge(limit):
    return "scale=w='if(lt(iw,ih),max(2,trunc(min(%d,iw)/2)*2),-2)':h='if(lt(iw,ih),-2,max(2,trunc(min(%d,ih)/2)*2))'" % (limit, limit)


def _long_edge(limit):
    return "scale=w='if(gt(iw,ih),min(%d,iw),-2)':h='if(gt(iw,ih),-2,min(%d,ih))'" % (limit, limit)


_ffmpeg_bin = None


def _ffmpeg():
    global _ffmpeg_bin
    if _ffmpeg_bin is None:
        _ffmpeg_bin = shutil.which(os.environ.get('BEATSCOPE_FFMPEG', 'ffmpeg')) or ''
        portable_root = Path(sys.executable).resolve().parent / 'tools' if getattr(sys, 'frozen', False) else None
        if not _ffmpeg_bin and portable_root and (portable_root / 'ffmpeg.exe').is_file():
            _ffmpeg_bin = str(portable_root / 'ffmpeg.exe')
    return _ffmpeg_bin


def extract_video_frames(ffmpeg, source, offset, length, target, *, resolution=1080, cancelled=None):
    """Extract exactly ceil(length*30) deterministic JPEGs named 000000.jpg…"""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    command = [ffmpeg, '-v', 'error', '-y', '-ss', f'{offset:.6f}', '-i', str(source),
               '-t', f'{length:.6f}', '-vf', 'fps=30,' + _short_edge(resolution) + ':flags=lanczos',
               '-q:v', '3', '-start_number', '0', str(target / '%06d.jpg')]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    deadline = time.monotonic() + 600
    try:
        while True:
            if cancelled and cancelled():
                raise ValueError('cancelled')
            if time.monotonic() >= deadline:
                raise ValueError('media/video-decode: frame extraction timed out')
            try:
                _, stderr = process.communicate(timeout=.1)
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
    if process.returncode != 0:
        raise ValueError('media/video-decode: ' + stderr.decode('utf-8', 'replace').strip()[:400])
    frames = sorted(target.glob('*.jpg'))
    if not frames:
        raise ValueError('media/video-decode: no frames produced')
    want = max(1, math.ceil(length * 30 - 1e-6))
    for extra in frames[want:]:
        extra.unlink()
    frames = frames[:want]
    while len(frames) < want:  # duplicate the last decoded frame forward
        name = f'{len(frames):06d}.jpg'
        shutil.copyfile(frames[-1], target / name)
        frames.append(target / name)
    return want


_h264 = None


def _has_h264(ffmpeg):
    global _h264
    if _h264 is None:
        try:
            _h264 = 'libx264' in subprocess.run([ffmpeg, '-hide_banner', '-encoders'],
                                                capture_output=True, timeout=30).stdout.decode('utf-8', 'replace')
        except (OSError, subprocess.TimeoutExpired):
            _h264 = False
    return _h264


def derive_video(manager, project_id, asset_id):
    """Poster frame + browser-safe preview clip for an uploaded video."""
    headers = {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}
    if not re.fullmatch('[0-9a-f]{12}', project_id):
        return 404, headers, b'{"error":"media/project-not-found"}'
    store = AssetStore(manager.get_project_dir(project_id), project_id)
    entry = next((a for a in store.manifest() if a['asset_id'] == asset_id), None)
    if entry is None:
        return 404, headers, b'{"error":"media/asset-missing"}'
    if entry.get('kind') != 'video':
        return 422, headers, b'{"error":"media/not-video","message":"Only video assets can be derived."}'
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        return 503, headers, b'{"error":"media/ffmpeg-missing","message":"FFmpeg is required for video clips."}'
    source = store.path_for(asset_id)
    if source is None:
        return 404, headers, b'{"error":"media/asset-missing"}'
    cache_path = manager.get_project_dir(project_id) / 'video-proxies.json'
    with composition_lock():
        try:
            cached = json.loads(cache_path.read_bytes()).get(asset_id)
            if cached and all(store.path_for(cached[key]) for key in ('poster', 'clip')):
                return 200, headers, json.dumps(cached).encode()
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            pass
    duration = float(entry.get('duration') or 0)
    h264 = _has_h264(ffmpeg)
    poster_at = min(1.0, duration / 2)
    with tempfile.TemporaryDirectory(prefix='beathi-derive-') as tmp:
        poster = Path(tmp) / 'poster.jpg'
        clip = Path(tmp) / ('clip.mp4' if h264 else 'clip.webm')
        commands = [
            [ffmpeg, '-v', 'error', '-y', '-ss', f'{poster_at:.3f}', '-i', str(source),
             '-frames:v', '1', '-vf', _long_edge(960), '-q:v', '3', str(poster)],
            [ffmpeg, '-v', 'error', '-y', '-i', str(source),
             '-vf', 'fps=30,' + _short_edge(720),
             *((' -c:v libx264 -g 15 -keyint_min 15 -sc_threshold 0 -preset veryfast '
                '-crf 23 -pix_fmt yuv420p -movflags +faststart -an'.split()) if h264 else
               (' -c:v libvpx-vp9 -deadline realtime -cpu-used 8 -row-mt 1 -b:v 0 -crf 34 -an'.split())),
             str(clip)],
        ]
        for command in commands:
            try:
                run = subprocess.run(command, capture_output=True, timeout=180)
            except subprocess.TimeoutExpired:
                return 422, headers, json.dumps({'error': 'media/video-decode', 'message': 'Clip processing timed out.'}).encode()
            except OSError:
                return 503, headers, b'{"error":"media/ffmpeg-missing","message":"FFmpeg is required for video clips."}'
            if run.returncode != 0:
                detail = run.stderr.decode('utf-8', 'replace').strip()[:400] or 'ffmpeg failed'
                return 422, headers, json.dumps({'error': 'media/video-decode', 'message': detail}).encode()
        poster_bytes = poster.read_bytes()
        clip_bytes = clip.read_bytes()
    # ffmpeg is done; publishing the derived files is the only locked step.
    with composition_lock():
        try:
            poster_entry = store.add(entry['display_name'] + ' poster', poster_bytes)
            clip_entry = store.add(entry['display_name'] + ' preview', clip_bytes)
        except (OSError, ValueError) as exc:
            return 422, headers, json.dumps({'error': 'media/video-decode', 'message': str(exc)}).encode()
        derived = {'poster': poster_entry['asset_id'], 'clip': clip_entry['asset_id'],
                   'duration': entry.get('duration'), 'width': entry.get('width'), 'height': entry.get('height')}
        try:
            cache = json.loads(cache_path.read_bytes())
            if not isinstance(cache, dict):
                cache = {}
        except (OSError, ValueError):
            cache = {}
        cache[asset_id] = derived
        _atomic_write_bytes(cache_path, media_bytes(cache))
    return 200, headers, json.dumps(derived).encode()


def media_request(manager, project_id, body=None, match=None):
    headers = {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}
    if not re.fullmatch('[0-9a-f]{12}', project_id):
        return 404, headers, b'{"error":"media/project-not-found"}'
    with composition_lock():
        try:
            current = media_bytes(load_media(manager, project_id))
            headers['ETag'] = '"' + hashlib.sha256(current).hexdigest() + '"'
            if body is None:
                return 200, headers, current
            if len(body) > 512 * 1024:
                return 413, headers, b'{"error":"media/too-large"}'
            if match != headers['ETag']:
                return 409, headers, b'{"error":"media/conflict","message":"Project changed; reload before editing."}'
            doc = validate_media(json.loads(body), manager.get_project_rhythm(project_id), manager, project_id)
            current = media_bytes(doc)
            _atomic_write_bytes(manager.get_project_dir(project_id) / 'custom-media.json', current)
            headers['ETag'] = '"' + hashlib.sha256(current).hexdigest() + '"'
            return 200, headers, current
        except FileNotFoundError:
            return 404, headers, b'{"error":"media/project-not-found"}'
        except (ValueError, TypeError, KeyError) as exc:
            return 422, headers, json.dumps({'error': str(exc)}).encode()


def copy_media(manager, source_id, target_id):
    if not isinstance(source_id, str) or not re.fullmatch('[0-9a-f]{12}', source_id) or not re.fullmatch('[0-9a-f]{12}', target_id):
        raise ValueError('media/project-not-found')
    with composition_lock():
        target = load_media(manager, target_id)
        if target['assets'] or source_id == target_id:
            return
        source = load_media(manager, source_id)
        old = AssetStore(manager.get_project_dir(source_id), source_id)
        new = AssetStore(manager.get_project_dir(target_id), target_id)
        catalog = {a['asset_id']: a for a in old.manifest()}
        for asset in source['assets']:
            copies = [asset['id']]
            for extra in ('proxy', 'clip'):
                if asset.get(extra):
                    copies.append(asset[extra])
            for asset_id in copies:
                path = old.path_for(asset_id)
                if path is None:
                    raise ValueError('media/asset-missing')
                new.add(catalog[asset_id]['display_name'], path.read_bytes())
        target.update(assets=source['assets'], seed=source['seed'], target=source['target'])
        if 'color' in source:
            target['color'] = source['color']
        _atomic_write_bytes(manager.get_project_dir(target_id) / 'custom-media.json', media_bytes(target))
