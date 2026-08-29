import http.client
import json
import threading
import time
import wave

from http.server import ThreadingHTTPServer
import beatscope.server as server_module
from beatscope.server import Handler, MAX_UPLOAD_BYTES


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
