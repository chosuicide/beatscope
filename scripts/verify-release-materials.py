"""Verify the template source files included in a portable release."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    library = json.loads((root / 'SOURCES.json').read_bytes())
    shipped = json.loads((Path(__file__).resolve().parents[1] / 'beatscope/web/material-library.json').read_bytes())
    if library != shipped:
        raise ValueError('Material manifest does not match this release')
    for asset in library['assets']:
        file = (root / asset['file']).resolve()
        if not file.is_relative_to(root) or hashlib.sha256(file.read_bytes()).hexdigest() != asset['sha256']:
            raise ValueError(f"Invalid template source: {asset['id']}")
    print(f"Verified {len(library['assets'])} template sources")


if __name__ == '__main__':
    main()
