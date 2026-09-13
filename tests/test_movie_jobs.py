import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from beatscope.mv_jobs import MovieJobs


@pytest.fixture
def manager(tmp_path, monkeypatch):
    audio = tmp_path / 'audio.wav'
    audio.write_bytes(b'test')
    projects = SimpleNamespace(cache_root=tmp_path,
        get_project_rhythm=lambda key: {'source': {'duration': 12}} if key == 'a' * 12 else None,
        get_project_audio_path=lambda key: audio)
    monkeypatch.setattr('beatscope.mv_jobs.renderer_tools', lambda: {'available': True})
    monkeypatch.setattr('beatscope.mv_jobs.threading.Thread.start', lambda self: None)
    return MovieJobs(projects)


def test_movie_admission_and_cancel(manager):
    a = manager.submit('a' * 12)
    assert manager.submit('a' * 12)['id'] == a['id']
    assert manager.get(a['id'])['state'] == 'queued'
    assert manager.cancel(a['id'])
    assert (manager.root / a['id'] / 'cancel').exists()
    assert manager.video(a['id']) is None
    assert manager.get('../escape') is None
    assert not manager.cancel('../escape')




def test_movie_rejects_bad_project_and_duration(manager):
    with pytest.raises(ValueError):
        manager.submit('../outside')
    with pytest.raises(ValueError):
        manager.submit('b' * 12)
    manager.projects.get_project_rhythm = lambda key: {'source': {'duration': 601}}
    with pytest.raises(ValueError):
        manager.submit('a' * 12)
    assert not list(manager.root.iterdir())


def test_movie_single_job_and_restart(manager):
    job = manager.submit('a' * 12)
    manager.projects.get_project_rhythm = lambda key: {'source': {'duration': 12}}
    with pytest.raises(RuntimeError):
        manager.submit('b' * 12)
    restarted = MovieJobs(manager.projects)
    assert restarted.get(job['id'])['state'] == 'failed'
    assert restarted.video(job['id']) is None


def test_complete_movie_survives_restart(manager):
    job = manager.submit('a' * 12)
    job.update(state='complete')
    directory = manager.root / job['id']
    (directory / 'status.json').write_text(json.dumps(job))
    (directory / 'movie.mp4').write_bytes(b'fixture')
    restarted = MovieJobs(manager.projects)
    assert restarted.video(job['id']) == directory / 'movie.mp4'


def test_renderer_modules_exist():
    from beatscope.mv_jobs import WEB, RUNTIME
    assert (RUNTIME / 'runtime.js').is_file()
    for name in ['mv-worker.mjs', 'mv-plan.mjs', 'mv-render.html', 'mv-visual.js', 'mv-frame.mjs']:
        assert (WEB / name).is_file()


def test_movie_seed_matches_preview_including_zero(manager):
    job = manager.submit('a' * 12, seed=0)
    assert job['seed'] == 0
    assert manager.submit('a' * 12, seed=0)['id'] == job['id']
    with pytest.raises(RuntimeError):
        manager.submit('a' * 12, seed=1)
    for invalid in [-1, 2**24, True, 1.1, '1']:
        with pytest.raises(ValueError):
            manager.submit('a' * 12, seed=invalid)


def test_corrupt_job_metadata_never_redirects_status_writes(manager):
    job = manager.submit('a' * 12)
    path = manager.root / job['id'] / 'status.json'
    for data in [[], {}, {'id': '../escape', 'state': 'queued'}, {'id': job['id'], 'state': 'unknown'}]:
        path.write_text(json.dumps(data))
        assert MovieJobs(manager.projects).get(job['id']) is None
