import io
import json
import shutil
import struct
import subprocess
import zipfile
from types import SimpleNamespace

import pytest

from beatscope.assets import AssetStore
from beatscope.custom_media import load_media, media_request
from beatscope.movie_output import movie_output

PNG = __import__('base64').b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1XkAAAAASUVORK5CYII=')


@pytest.fixture
def media_project(tmp_path):
    directory = tmp_path / ('a' * 12)
    directory.mkdir()
    rhythm = {'source': {'duration': 12, 'sha256': 'b' * 64}}
    return SimpleNamespace(get_project_rhythm=lambda _: rhythm, get_project_dir=lambda _: directory), directory


def _catalog_entry(store, data, kind, **extra):
    """Register bytes in the store with an explicit kind (sniffing is covered elsewhere)."""
    import hashlib

    aid = hashlib.sha256(data).hexdigest()
    store.assets_dir.mkdir(parents=True, exist_ok=True)
    ext = 'mp4' if kind == 'video' else 'png'
    (store.assets_dir / f'{aid}.{ext}').write_bytes(data)
    entry = {'asset_id': aid, 'sha256': aid, 'mime': 'video/mp4' if kind == 'video' else 'image/png',
             'kind': kind, 'extension': ext, 'width': 640, 'height': 360,
             'duration': 4.0 if kind == 'video' else None, 'display_name': f'clip.{ext}', 'bytes': len(data)}
    entry.update(extra)
    entries = store.manifest() + [entry]
    entries.sort(key=lambda e: e['asset_id'])
    store._write_manifest(entries)
    return aid


def test_video_rows_and_slot_offsets(media_project):
    manager, directory = media_project
    store = AssetStore(directory, 'a' * 12)
    video = _catalog_entry(store, b'vid-bytes', 'video', duration=4.0)
    clip = _catalog_entry(store, b'clip-bytes', 'video', duration=4.0)
    poster = _catalog_entry(store, PNG, 'image')
    row = {'id': video, 'kind': 'video', 'clip': clip, 'proxy': poster, 'duration': 4.0,
           'focus': {'x': .5, 'y': .5, 'zoom': 1, 'fit': 'cover'}, 'overrides': {}}
    slot = {'start': 1, 'end': 3, 'asset': video, 'fixed': True, 'offset': .5}

    status, headers, body = media_request(manager, 'a' * 12)
    etag = headers['ETag']
    doc = json.loads(body)
    doc['assets'] = [row]
    doc['slots'] = [slot]
    assert media_request(manager, 'a' * 12, json.dumps(doc).encode(), etag)[0] == 200

    def attempt(assets, slots):
        candidate = {**json.loads(body), 'assets': assets, 'slots': slots}
        return media_request(manager, 'a' * 12, json.dumps(candidate).encode(), media_request(manager, 'a' * 12)[1]['ETag'])[0]

    # Asset-row violations.
    for bad in [
        {**row, 'kind': 'image'},
        {k: v for k, v in row.items() if k != 'clip'},
        {**row, 'clip': poster},
        {**row, 'proxy': clip},
        {k: v for k, v in row.items() if k != 'proxy'},
        {**row, 'duration': 4.01},
        {k: v for k, v in row.items() if k != 'duration'},
    ]:
        assert attempt([bad], [slot]) == 422, bad
    # Slot offset rules: required for video, must fit inside the clip.
    assert attempt([row], [{k: v for k, v in slot.items() if k != 'offset'}]) == 422
    assert attempt([row], [{**slot, 'offset': 2.1}]) == 422
    assert attempt([row], [{**slot, 'offset': -1}]) == 422
    # Forbidden on image slots; old documents without kind/offset stay valid.
    image_row = {'id': poster, 'focus': {'x': .5, 'y': .5, 'zoom': 1, 'fit': 'cover'}, 'overrides': {}}
    image_slot = {'start': 0, 'end': 2, 'asset': poster, 'fixed': True}
    assert attempt([image_row], [image_slot]) == 200
    assert attempt([image_row], [{**image_slot, 'offset': 0}]) == 422
    for malformed in [None, [], 'slot', 1]:
        assert attempt([image_row], [malformed]) == 422


def test_palette_settings_round_trip_and_reject_invalid_values(media_project):
    manager, _ = media_project
    project_id = 'a' * 12
    assert 'color' not in load_media(manager, project_id)
    doc = load_media(manager, project_id)
    doc['color'] = {'enabled': True, 'strength': .65}
    etag = media_request(manager, project_id)[1]['ETag']
    assert media_request(manager, project_id, json.dumps(doc).encode(), etag)[0] == 200
    assert load_media(manager, project_id)['color'] == doc['color']
    for bad in [{'enabled': 1, 'strength': .5}, {'enabled': True, 'strength': True},
                {'enabled': True, 'strength': 1.01}, {'enabled': True}, None]:
        etag = media_request(manager, project_id)[1]['ETag']
        candidate = {**doc, 'color': bad}
        assert media_request(manager, project_id, json.dumps(candidate).encode(), etag)[0] == 422


def test_derive_video_endpoint_and_frame_extraction(media_project, tmp_path, monkeypatch):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        pytest.skip('ffmpeg not available')
    from beatscope.custom_media import derive_video, extract_video_frames

    manager, directory = media_project
    source = tmp_path / 'in.mp4'
    run = subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=size=640x360:rate=30',
                          '-t', '3', '-pix_fmt', 'yuv420p', str(source)], capture_output=True)
    assert run.returncode == 0, run.stderr
    entry = AssetStore(directory, 'a' * 12).add('in.mp4', source.read_bytes())
    assert entry['kind'] == 'video'

    status, _, body = derive_video(manager, 'a' * 12, entry['asset_id'])
    assert status == 200, body
    derived = json.loads(body)
    catalog = {a['asset_id']: a for a in AssetStore(directory, 'a' * 12).manifest()}
    assert catalog[derived['poster']]['kind'] == 'image'
    assert catalog[derived['clip']]['kind'] == 'video'
    assert catalog[derived['clip']]['mime'] in ('video/mp4', 'video/webm')

    with monkeypatch.context() as patch:
        def unexpected_transcode(*args, **kwargs):
            raise AssertionError('A repeated import must reuse valid derived assets')
        patch.setattr(subprocess, 'run', unexpected_transcode)
        assert json.loads(derive_video(manager, 'a' * 12, entry['asset_id'])[2]) == derived

    status, _, _ = derive_video(manager, 'a' * 12, derived['poster'])
    assert status == 422

    frames = tmp_path / 'frames'
    count = extract_video_frames(ffmpeg, source, .5, 1.7, frames)
    assert count == 51  # ceil(1.7*30)
    names = sorted(p.name for p in frames.glob('*.jpg'))
    assert len(names) == 51 and names[0] == '000000.jpg' and names[-1] == '000050.jpg'


def test_frame_extraction_cancels_running_process(tmp_path, monkeypatch):
    import sys
    import time

    from beatscope.custom_media import extract_video_frames

    popen = subprocess.Popen
    children = []

    def slow_decoder(*args, **kwargs):
        child = popen([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, 'Popen', slow_decoder)
    start = time.monotonic()
    with pytest.raises(ValueError, match='cancelled'):
        extract_video_frames('ffmpeg', tmp_path / 'clip', 0, 3, tmp_path / 'frames',
                             cancelled=lambda: time.monotonic() - start > .2)
    assert time.monotonic() - start < 3
    assert children[0].poll() is not None


def test_derive_video_accepts_odd_source_dimensions(media_project, tmp_path):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        pytest.skip('ffmpeg not available')
    from beatscope.custom_media import derive_video

    manager, directory = media_project
    source = tmp_path / 'odd.mp4'
    run = subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                          'testsrc=size=321x241:rate=30', '-t', '0.2',
                          '-c:v', 'libx264', '-pix_fmt', 'yuv444p', str(source)], capture_output=True)
    assert run.returncode == 0, run.stderr
    store = AssetStore(directory, 'a' * 12)
    original = source.read_bytes()
    entry = store.add('odd.mp4', original)
    assert (entry['width'], entry['height']) == (321, 241)
    status, _, body = derive_video(manager, 'a' * 12, entry['asset_id'])
    assert status == 200, body
    clip_id = json.loads(body)['clip']
    clip = next(a for a in store.manifest() if a['asset_id'] == clip_id)
    assert min(clip['width'], clip['height']) == 240
    # MP4 display dimensions can include SAR; check decoded pixel dimensions.
    decoded = subprocess.run([ffmpeg, '-v', 'error', '-i', str(store.path_for(clip_id)),
                              '-frames:v', '1', '-f', 'image2pipe', '-c:v', 'png', 'pipe:1'],
                             capture_output=True)
    assert decoded.returncode == 0, decoded.stderr
    width, height = struct.unpack('>II', decoded.stdout[16:24])
    assert width % 2 == height % 2 == 0
    assert store.path_for(entry['asset_id']).read_bytes() == original


def test_output_dimensions_and_validation():
    for aspect, expected in [('1:1', (1080, 1080)), ('16:9', (1920, 1080)), ('9:16', (1080, 1920))]:
        out = movie_output({'aspect': aspect, 'resolution': 1080})
        assert (out['width'], out['height']) == expected
    assert movie_output({'aspect': '9:16', 'resolution': 720})['height'] == 1280
    for bad in [{'aspect': '19:9'}, {'resolution': True}, {'resolution': 999}, {'width': 1}, []]:
        with pytest.raises(ValueError):
            movie_output(bad)


def test_media_persistence_conflicts_and_missing_files(media_project):
    manager, directory = media_project
    # Small valid PNG from the asset test fixtures.
    import base64
    raw = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1XkAAAAASUVORK5CYII=')
    entry = AssetStore(directory, 'a' * 12).add('image.png', raw)
    status, headers, body = media_request(manager, 'a' * 12)
    assert status == 200
    doc = json.loads(body)
    doc['assets'] = [{'id': entry['asset_id'], 'focus': {'x': .4, 'y': .6, 'zoom': 1.2, 'fit': 'cover'}, 'overrides': {}}]
    doc['slots'] = [{'start': 0, 'end': 4, 'asset': entry['asset_id'], 'fixed': True}]
    assert media_request(manager, 'a' * 12, json.dumps(doc).encode(), 'wrong')[0] == 409
    assert media_request(manager, 'a' * 12, json.dumps(doc).encode(), headers['ETag'])[0] == 200
    assert load_media(manager, 'a' * 12) == doc
    bad = {**doc, 'slots': doc['slots'] * 2}
    etag = media_request(manager, 'a' * 12)[1]['ETag']
    assert media_request(manager, 'a' * 12, json.dumps(bad).encode(), etag)[0] == 422
    AssetStore(directory, 'a' * 12).path_for(entry['asset_id']).unlink()
    assert media_request(manager, 'a' * 12)[0] == 422


def test_timing_export_describes_originals_without_embedding_them():
    from pathlib import Path

    from beatscope.exports import generate_codex_export
    rhythm = json.loads((Path(__file__).parent / 'fixtures/runtime/structure-project.json').read_bytes())
    with zipfile.ZipFile(io.BytesIO(generate_codex_export(rhythm, custom_media={'originals_included': False}))) as archive:
        assert json.loads(archive.read('custom-media.json'))['originals_included'] is False
        assert b'NOT included' in archive.read('AGENT.md')
        from beatscope.consumer_contract import MANIFEST_MEMBER
        manifest = json.loads(archive.read(MANIFEST_MEMBER))
        assert 'custom-media.json' in manifest['integrity']['members']


def test_change_song_reuses_images_but_not_old_timeline(media_project):
    import base64

    from beatscope.custom_media import copy_media, media_bytes

    _, directory = media_project
    source, target = 'a' * 12, 'c' * 12
    new_dir = directory.parent / target
    new_dir.mkdir()
    manager = SimpleNamespace(get_project_dir=lambda key: directory if key == source else new_dir,
                              get_project_rhythm=lambda key: {'source': {'duration': 12 if key == source else 20, 'sha256': key * 5}})
    entry = AssetStore(directory, source).add('photo.png', base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1XkAAAAASUVORK5CYII='))
    store = AssetStore(directory, source)
    extra_assets = [{'id': entry['asset_id'], 'focus': {'x': .2, 'y': .7, 'zoom': 1, 'fit': 'cover'}, 'overrides': {}}]
    copied_ids = [entry['asset_id']]
    ffmpeg = shutil.which('ffmpeg')
    if ffmpeg:  # real containers so the copy re-sniffs as video
        import tempfile
        from pathlib import Path

        blobs = []
        with tempfile.TemporaryDirectory() as tmp:
            for i, name in enumerate(('source.mp4', 'preview.mp4')):
                out = Path(tmp) / name
                assert subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=30',
                                       '-t', f'1.{i}', '-pix_fmt', 'yuv420p', str(out)]).returncode == 0
                blobs.append(out.read_bytes())
        video_entry = store.add('source.mp4', blobs[0])
        clip_entry = store.add('preview.mp4', blobs[1])
        duration = video_entry['duration']
        extra_assets.append({'id': video_entry['asset_id'], 'kind': 'video', 'clip': clip_entry['asset_id'],
                             'proxy': entry['asset_id'], 'duration': duration,
                             'focus': {'x': .5, 'y': .5, 'zoom': 1, 'fit': 'cover'}, 'overrides': {}})
        copied_ids += [video_entry['asset_id'], clip_entry['asset_id']]
    doc = load_media(manager, source)
    doc.update(assets=extra_assets,
               slots=[{'start': 2, 'end': 5, 'asset': entry['asset_id'], 'fixed': True}])
    (directory / 'custom-media.json').write_bytes(media_bytes(doc))
    copy_media(manager, source, target)
    copied = load_media(manager, target)
    assert copied['source_sha256'] != doc['source_sha256']
    assert copied['slots'] == []
    assert copied['assets'] == doc['assets']
    for aid in copied_ids:
        assert AssetStore(new_dir, target).path_for(aid).read_bytes() == AssetStore(directory, source).path_for(aid).read_bytes()
