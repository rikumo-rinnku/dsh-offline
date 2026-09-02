"""Create a ZIP without traversing links, then verify a fresh relocated install.

Only start.bat, launcher, runtime, dsh-core and the user guide are shipped.
No pruning of installed packages: optional features retain their dependencies.
"""
import argparse
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import time
import urllib.request
import urllib.parse
import zipfile


def inventory(root):
    files, links, directories = [], [], set()
    skip_dirs = {'.git', '__pycache__'}
    def walk(folder):
        directories.add(folder.relative_to(root).as_posix())
        with os.scandir(folder) as entries:
            for entry in sorted(entries, key=lambda e: e.name):
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                if entry.name in skip_dirs:
                    continue
                info = entry.stat(follow_symlinks=False)
                if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    target = path.resolve(strict=True)
                    target_relative = target.relative_to(root).as_posix()
                    if target.is_dir():
                        links.append({'path': relative, 'target': target_relative})
                    else:
                        files.append((target, relative))
                elif entry.is_dir(follow_symlinks=False):
                    walk(path)
                elif not (path.suffix == '.pyc' and path.with_suffix('.py').exists()):
                    files.append((path, relative))
    for name in ('launcher', 'runtime', 'dsh-core'):
        walk(root / name)
    for name in ('start.bat', '使用说明.txt'):
        files.append((root / name, name))
    for link in links:
        if link['target'] not in directories:
            raise RuntimeError('Link target excluded from archive: ' + str(link))
    files = [(path, name) for path, name in files if name != 'launcher/bundle-links.json']
    return files, links, directories


def child_env(root):
    env = os.environ.copy()
    env.update(DSH_HOME=str(root / '.dsh-home'), USERPROFILE=str(root / '.dsh-home'),
               PYTHONHOME=str(root / 'runtime/python'),
               PYTHONPATH=str(root / 'launcher'),
               NODE_PATH=str(root / 'dsh-core/node_modules'),
               TMP=str(root / '.cache/tmp'), TEMP=str(root / '.cache/tmp'),
               npm_config_cache=str(root / '.cache/npm'),
               pnpm_home=str(root / '.cache/pnpm'), pnpm_store_dir=str(root / '.cache/pnpm-store'))
    env['PATH'] = os.pathsep.join([str(root / 'runtime/node'), str(root / 'runtime/python'), env['PATH']])
    for prefix, variable in [('tcl8.', 'TCL_LIBRARY'), ('tk8.', 'TK_LIBRARY')]:
        env[variable] = str(next((root / 'runtime/python/tcl').glob(prefix + '*')))
    (root / '.cache/tmp').mkdir(parents=True, exist_ok=True)
    (root / '.dsh-home').mkdir(exist_ok=True)
    return env


def verify(root):
    env = child_env(root)
    python = str(root / 'runtime/python/python.exe')
    def run(args):
        result = subprocess.run(args, cwd=root, env=env, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        print(result.stdout.strip(), flush=True)
    run([python, str(root / 'launcher/restore_links.py')])
    run([python, str(root / 'launcher/restore_links.py')])
    run([python, '-c', 'import tkinter, customtkinter, app; print("GUI imports OK")'])
    node, cli = str(root / 'runtime/node/node.exe'), str(root / 'dsh-core/apps/cli/lib/bin.js')
    run([node, cli, '--version'])
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    log = root / '.cache/verification.log'
    with log.open('w', encoding='utf-8') as output:
        proc = subprocess.Popen([node, cli, 'web', '--port', str(port), '--no-open'],
                                cwd=root / 'dsh-core', env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 120
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError('Web process exited; inspect ' + str(log))
                match = re.search(r'\?token=([A-Za-z0-9_-]+)', log.read_text(encoding='utf-8'))
                if match:
                    try:
                        with opener.open(f'http://127.0.0.1:{port}/?token={match[1]}', timeout=3) as response:
                            page = response.read().decode('utf-8')
                            page_url = response.geturl()
                            if response.status != 200 or '<html' not in page.lower():
                                raise RuntimeError('Web did not serve HTML')
                        assets = re.findall(r'(?:src|href)="([^"?#]+\.(?:js|css))"', page)
                        if not assets:
                            raise RuntimeError('No frontend assets found')
                        for asset in assets:
                            asset_url = urllib.parse.urljoin(page_url, asset)
                            if urllib.parse.urlsplit(asset_url).netloc != f'127.0.0.1:{port}':
                                raise RuntimeError('Unexpected external frontend asset')
                            with opener.open(asset_url, timeout=10) as response:
                                if response.status != 200 or not response.read():
                                    raise RuntimeError('Empty frontend asset: ' + asset)
                        print(f'Web HTML and {len(assets)} frontend assets OK', flush=True)
                        return
                    except (ConnectionError, TimeoutError):
                        pass
                time.sleep(0.5)
            raise RuntimeError('Web startup timed out; inspect ' + str(log))
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output = root / 'release-output' / time.strftime('%Y%m%d-%H%M%S')
    output.mkdir(parents=True, exist_ok=False)
    print('Scanning physical files without following directory links...', flush=True)
    files, links, directories = inventory(root)
    print(f'{len(files)} files, {len(links)} links recorded as metadata', flush=True)
    archive = output / 'dsh-portable.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as bundle:
        for directory in sorted(directories):
            bundle.writestr(directory + '/', b'')
        for index, (source, name) in enumerate(files, 1):
            bundle.write(source, name)
            if index % 10000 == 0:
                print(f'Packed {index}/{len(files)} files', flush=True)
        bundle.writestr('launcher/bundle-links.json', json.dumps({'version': 1, 'links': links}, ensure_ascii=False))
    extracted = output / 'verify install'
    print('Extracting to a fresh directory (CRC checked during extraction)...', flush=True)
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError('Duplicate archive entries')
        if any(name.split('/')[0] not in {'start.bat', '使用说明.txt', 'launcher', 'runtime', 'dsh-core'} for name in names):
            raise RuntimeError('Unexpected archive root')
        for index, member in enumerate(bundle.infolist(), 1):
            bundle.extract(member, extracted)
            if index % 10000 == 0:
                print(f'Extracted {index}/{len(names)} entries', flush=True)
    finish(archive, extracted, len(files), len(links))


def finish(archive, extracted, file_count, link_count):
    output = archive.parent
    verify(extracted)
    # Move an already initialized bundle: absolute junctions must be repaired.
    moved = output / 'verify moved'
    extracted.rename(moved)
    print('Checking links and startup after moving the initialized directory...', flush=True)
    verify(moved)
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    report = {'archive': archive.name, 'sha256': digest.hexdigest(), 'files': file_count,
              'directory_links': link_count, 'bytes': archive.stat().st_size,
              'verification': 'PASS: fresh extraction and relocation; GUI imports, CLI version, authenticated HTML and frontend assets',
              'limits': 'No real API request, shell execution or complete plugin feature test performed.'}
    (output / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('VERIFIED ARCHIVE: ' + str(archive), flush=True)
    print('Verification directory retained: ' + str(moved), flush=True)


if __name__ == '__main__':
    main()
