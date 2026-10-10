"""Every movie job dependency must be declared, even in a clean source build."""
import ast
import fnmatch
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_movie_runtime_files_are_packaged():
    # This string array uses syntax shared by TOML and Python. Keep the test
    # runnable on the project's Python 3.10 minimum without adding a parser.
    metadata = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
    array = re.search(r'(?ms)^\[tool.setuptools.package-data\]\s*\n.*?^beatscope\s*=\s*(\[.*?^\])', metadata)
    assert array is not None
    patterns = ast.literal_eval(array[1])
    source = (ROOT / 'beatscope' / 'mv_jobs.py').read_text(encoding='utf-8')
    names = set(re.findall(r'''["']((?:mv|movie|material|custom|media|paint)[\w.-]*\.(?:html|mjs|js))["']''', source))
    assert 'mv-visual.js' in names
    missing = [name for name in sorted(names)
               if not any(fnmatch.fnmatch('web/' + name, pattern) for pattern in patterns)]
    assert not missing, f'not in package-data: {missing}'
    assert all((ROOT / 'beatscope' / 'web' / name).is_file() for name in names)
