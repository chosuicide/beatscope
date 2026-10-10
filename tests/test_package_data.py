"""The renderer copies these files into every job; a wheel without one cannot render."""
import fnmatch
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_movie_runtime_files_are_packaged():
    patterns = tomllib.loads((ROOT / 'pyproject.toml').read_text())['tool']['setuptools']['package-data']['beatscope']
    source = (ROOT / 'beatscope' / 'mv_jobs.py').read_text()
    names = set(re.findall(r"""["']((?:mv|movie|material|custom|media|paint)[\w.-]*\.(?:html|mjs|js))["']""", source))
    assert 'mv-visual.js' in names
    missing = [n for n in sorted(names) if (ROOT / 'beatscope' / 'web' / n).exists() and not any(fnmatch.fnmatch('web/' + n, p) for p in patterns)]
    assert not missing, f'not in package-data: {missing}'
