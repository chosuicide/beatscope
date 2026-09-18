import http.client
import json
import threading
import time
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path

import beatscope.server as server_module
from beatscope.server import MAX_UPLOAD_BYTES, Handler


def running_server():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_upload_rejects_missing_length():
    server, thread = running_server()
    try:
        conn = http.client.HTTPConnection(*server.server_address)
        conn.putrequest('POST', '/api/analyze')
        conn.endheaders()
        response = conn.getresponse()
        assert response.status == 411
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_upload_rejects_oversized_length():
    server, thread = running_server()
    try:
        conn = http.client.HTTPConnection(*server.server_address)
        conn.request('POST', '/api/analyze', body=b'', headers={'Content-Length': str(MAX_UPLOAD_BYTES + 1)})
        assert conn.getresponse().status == 413
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_studio_is_the_only_page(tmp_path):
    """`/` serves the studio build; the retired pages are gone for good.

    The old studio page and its module tree were deleted with the compiled
    visual layer, so nothing may still answer for them.
    """
    server, thread = running_server()
    try:
        conn = http.client.HTTPConnection(*server.server_address)

        conn.request('GET', '/')
        root = conn.getresponse()
        assert root.status == 302 and root.getheader('Location') == '/app/'
        root.read()

        conn.request('GET', '/app/')
        page = conn.getresponse()
        assert page.status == 200
        body = page.read().decode('utf-8')
        assert 'id="root"' in body and 'Beathi' in body

        for retired in ('/legacy.html', '/app.js', '/style.css', '/visual-stage.js',
                        '/webmcp/register.js', '/demo/project.json'):
            conn.request('GET', retired)
            response = conn.getresponse()
            assert response.status == 404, f'{retired} still answers with {response.status}'
            response.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_project_routes_serve_map_and_audio(tmp_path):
    audio = tmp_path / 'project.wav'
    with wave.open(str(audio), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(b'\x00\x00' * 80)
    server_module.PROJECT_MAP = {'source': {'path': str(audio)}, 'tempo': {}, 'grid': {}}
    server, thread = running_server()
    try:
        conn = http.client.HTTPConnection(*server.server_address)
        conn.request('GET', '/api/project')
        assert conn.getresponse().status == 200
        conn.request('GET', '/api/project/audio')
        response = conn.getresponse()
        assert response.status == 200
        assert len(response.read()) > 0
    finally:
        server_module.PROJECT_MAP = None
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_job_analysis_and_range_audio(tmp_path):
    audio = tmp_path / 'song.wav'
    with wave.open(str(audio), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(b'\x10\x00' * 4000)
    audio_bytes = audio.read_bytes()

    server, thread = running_server()
    try:
        conn = http.client.HTTPConnection(*server.server_address)
        # 1. Submit analysis job
        headers = {'Content-Length': str(len(audio_bytes)), 'X-Filename': 'test_song.wav'}
        conn.request('POST', '/api/jobs/analyze', body=audio_bytes, headers=headers)
        resp = conn.getresponse()
        assert resp.status == 200
        job_data = json.loads(resp.read().decode())
        job_id = job_data['job_id']

        # 2. Poll job status
        completed = False
        project_id = None
        for _ in range(50):
            conn.request('GET', f'/api/jobs/{job_id}')
            r = conn.getresponse()
            assert r.status == 200
            j = json.loads(r.read().decode())
            if j['state'] == 'complete':
                completed = True
                project_id = j['project_id']
                break
            time.sleep(0.1)

        assert completed
        assert project_id is not None

        # 3. GET rhythm.json
        conn.request('GET', f'/api/projects/{project_id}')
        r_resp = conn.getresponse()
        assert r_resp.status == 200
        rhythm = json.loads(r_resp.read().decode())
        assert rhythm['schema_version'] == '4.0'

        # 4. GET Audio Range request (206)
        conn.request('GET', f'/api/projects/{project_id}/audio', headers={'Range': 'bytes=0-99'})
        audio_range = conn.getresponse()
        assert audio_range.status == 206
        chunk = audio_range.read()
        assert len(chunk) == 100

        # 5. Export MIDI and CSV
        conn.request('GET', f'/api/projects/{project_id}/export/rhythm.mid')
        assert conn.getresponse().status == 200

        conn.request('GET', f'/api/projects/{project_id}/export/rhythm.csv')
        assert conn.getresponse().status == 200

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
# --- the retired visual layer has no HTTP surface ---------------------------


def _seed_project(projects_root, project_id='0a1b2c3d4e5f'):
    """Seed one cached project: rhythm.json + project.json."""
    import json as _json
    fixture = Path(__file__).parent / 'fixtures' / 'runtime' / 'characterization-project.json'
    rhythm = _json.loads(fixture.read_text(encoding='utf-8'))
    rhythm['project_id'] = project_id
    p_dir = projects_root / project_id[:12]
    p_dir.mkdir(parents=True, exist_ok=True)
    (p_dir / 'rhythm.json').write_text(_json.dumps(rhythm, ensure_ascii=False), encoding='utf-8')
    (p_dir / 'project.json').write_text(
        _json.dumps({'project_id': project_id[:12], 'display_name': 'characterization.wav'}),
        encoding='utf-8',
    )
    return rhythm


def test_visual_artifact_routes_are_gone(tmp_path):
    """The compiled recipe/timeline routes no longer exist.

    The product ships measured timing facts and no visual layer, so a request
    for the old artifact documents must not resolve to anything - not even for
    a project whose rhythm would once have compiled into them.
    """
    from beatscope.project import ProjectManager
    from beatscope.web_api import WebApi

    _seed_project(tmp_path / 'projects')
    api = WebApi(ProjectManager(tmp_path))
    for route in ('visual-recipe', 'visual-timeline'):
        status, _, body = api.handle_get(f'/api/projects/0a1b2c3d4e5f/{route}', {}, {})
        assert status == 404, f'{route} still answers with {status}'
        assert b'visual' not in body.lower()


def test_response_relevance_route_is_canonical_and_cacheable(tmp_path):
    from beatscope.project import ProjectManager
    from beatscope.response_relevance import canonical_response_relevance_bytes
    from beatscope.web_api import WebApi

    rhythm = _seed_project(tmp_path / 'projects')
    api = WebApi(ProjectManager(tmp_path))
    route = '/api/projects/0a1b2c3d4e5f/response-relevance'

    status, headers, body = api.handle_get(route, {}, {})
    assert status == 200
    document = json.loads(body.decode('utf-8'))
    assert document['project_id'] == rhythm['project_id']
    assert document['semantics'] == 'bounded-ranking-value-not-probability-or-confidence'
    assert body == canonical_response_relevance_bytes(document)
    assert len(document['events']) == len(rhythm['onsets'])
    assert all(set(row) == {'onset_id', 'response_relevance'} for row in document['events'])

    etag = headers['ETag']
    status, cached_headers, cached_body = api.handle_get(route, {}, {'If-None-Match': etag})
    assert status == 304
    assert cached_body == b''
    assert cached_headers['ETag'] == etag


def test_response_relevance_route_unknown_project_is_404(tmp_path):
    from beatscope.project import ProjectManager
    from beatscope.web_api import WebApi

    api = WebApi(ProjectManager(tmp_path))
    status, _, body = api.handle_get('/api/projects/missing/response-relevance', {}, {})
    assert status == 404
    assert json.loads(body.decode('utf-8')) == {'error': 'Project not found'}
