"""Restore archive-owned junctions after extraction or moving the bundle.

Relative metadata keeps the ZIP portable. Ordinary directories are never replaced.
"""
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys


def contained(root, value):
    parts = PurePosixPath(value).parts
    if not parts or parts[0] not in ('dsh-core', 'runtime', 'launcher'):
        raise ValueError('Invalid bundle path: ' + value)
    if '\\' in value or ':' in value or any(p in ('.', '..') for p in parts):
        raise ValueError('Invalid bundle path: ' + value)
    return root.joinpath(*parts)


def restore(root):
    manifest = root / 'launcher' / 'bundle-links.json'
    if not manifest.exists():
        return 0  # Development checkout already has its own links.
    import _winapi
    import msvcrt
    cache = root / '.cache'
    cache.mkdir(exist_ok=True)
    count = 0
    with (cache / 'restore-links.lock').open('a+b') as lock:
        lock.seek(0)
        lock.write(b'0')
        lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        try:
            data = json.loads(manifest.read_text(encoding='utf-8'))
            if data['version'] != 1:
                raise ValueError('Unsupported bundle manifest version')
            for entry in data['links']:
                link = contained(root, entry['path'])
                target = contained(root, entry['target'])
                target.resolve().relative_to(root)
                link.parent.resolve().relative_to(root)
                if not target.is_dir():
                    raise RuntimeError('Missing bundled directory: ' + str(target))
                if os.path.lexists(link):
                    info = link.lstat()
                    if not info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                        raise RuntimeError('Refusing to replace ordinary path: ' + str(link))
                    if link.resolve() == target.resolve():
                        continue
                    # Remove the link alone, never its target directory.
                    os.rmdir(link)
                link.parent.mkdir(parents=True, exist_ok=True)
                _winapi.CreateJunction(str(target), str(link))
                count += 1
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
    return count


if __name__ == '__main__':
    try:
        print('Dependency links ready; created/repaired:', restore(Path(__file__).resolve().parent.parent))
    except Exception as exc:
        print('Dependency setup failed:', exc, file=sys.stderr)
        sys.exit(1)
