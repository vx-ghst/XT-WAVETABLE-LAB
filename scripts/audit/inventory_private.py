#!/usr/bin/env python3
"""READ ONLY: inventory file sizes and SHA-256 under a private directory.

This script does not interpret, copy, alter, upload or expose data. The output
contains local paths (relative to --root), so KEEP THE REPORT PRIVATE.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    root = args.root.resolve(strict=True)
    if not root.is_dir():
        ap.error('--root must be a directory')
    output = args.out.resolve()
    if output == root or root in output.parents:
        ap.error('--out should be outside of private root, in workspace/reports')
    rows = []
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.is_symlink():
            continue
        rows.append({'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size, 'sha256': fingerprint(path)})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'schema': 1, 'files': rows}, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Inventory: {len(rows)} files; saved to private report {output.name}')
    return 0

if __name__ == '__main__':
    sys.exit(main())
