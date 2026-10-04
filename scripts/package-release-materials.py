"""Package only the accepted, hash-verified template sources for a release."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    manifest_path = Path(__file__).resolve().parents[1] / 'beatscope/web/material-library.json'
    manifest = json.loads(manifest_path.read_bytes())
    source = args.source.resolve()
    files = []
    for asset in manifest['assets']:
        file = (source / asset['file']).resolve()
        if not file.is_relative_to(source) or not file.is_file():
            raise ValueError(f"Missing or unsafe material: {asset['id']}")
        if hashlib.sha256(file.read_bytes()).hexdigest() != asset['sha256']:
            raise ValueError(f"Material hash mismatch: {asset['id']}")
        files.append((file, asset['file']))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, 'w', compression=zipfile.ZIP_STORED) as archive:
        for file, name in files:
            archive.write(file, 'materials/' + name)
        archive.write(manifest_path, 'materials/SOURCES.json')
        archive.writestr('materials/README.txt',
                         'Beathi Prismatic Echo template sources.\n'
                         'Sources, authors, licenses and SHA-256 are in SOURCES.json.\n'
                         'Media are Pexels licensed, not covered by the code MIT license.\n'
                         'https://www.pexels.com/license/\n'
                         'Keep the materials folder beside Beathi Studio.exe, or set\n'
                         'BEATSCOPE_MATERIAL_ROOT to its absolute path for a Python install.\n')
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix(args.output.suffix + '.sha256').write_text(
        digest + '  ' + args.output.name, encoding='utf-8')
    print(json.dumps({'assets': len(files), 'bytes': args.output.stat().st_size, 'sha256': digest}))


if __name__ == '__main__':
    main()
