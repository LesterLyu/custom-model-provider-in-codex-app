"""Private, immutable native runtime snapshots outside the App's relocation cache."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
from datetime import datetime, timezone


REQUIRED = ('codex.exe', 'codex-code-mode-host.exe', 'codex-command-runner.exe',
            'codex-windows-sandbox-setup.exe')
OPTIONAL = ('rg.exe', 'codex-windows-sandbox-service.exe')
APP_QUERY = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$package = Get-AppxPackage -Name OpenAI.Codex | Sort-Object Version -Descending | Select-Object -First 1
if (!$package) { throw 'Codex App package not found; specify a native runtime directory.' }
Join-Path $package.InstallLocation 'app\resources' | ConvertTo-Json -Compress
'''


def app_resources():
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', APP_QUERY],
                            capture_output=True, text=True, encoding='utf-8', timeout=30)
    if result.returncode:
        raise RuntimeError('Cannot locate the installed Codex App runtime; specify -NativeCodex explicitly.')
    return Path(json.loads(result.stdout.strip().lstrip('\ufeff')))


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(source, cache):
    source, cache = Path(source).resolve(), Path(cache).resolve()
    missing = [name for name in REQUIRED if not (source / name).is_file()]
    if missing:
        raise RuntimeError('Incomplete native runtime; missing: ' + ', '.join(missing))
    names = [*REQUIRED, *(name for name in OPTIONAL if (source / name).is_file())]
    manifest = {name: {'sha256': file_hash(source / name), 'size': (source / name).stat().st_size}
                for name in names}
    identity = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:24]
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / identity

    def complete(folder):
        return all((folder / name).is_file() and (folder / name).stat().st_size == info['size']
                   and file_hash(folder / name) == info['sha256'] for name, info in manifest.items())

    if target.exists():
        if not complete(target):
            raise RuntimeError('Private runtime snapshot is incomplete or modified: ' + str(target))
        return target / 'codex.exe'
    stage = Path(tempfile.mkdtemp(prefix='.staging-', dir=cache))
    try:
        for name in names:
            shutil.copy2(source / name, stage / name)
        if not complete(stage):
            raise RuntimeError('Native runtime changed while being copied; retry after the App update finishes.')
        (stage / 'runtime.json').write_text(json.dumps({'source': str(source), 'files': manifest}, indent=2),
                                          encoding='utf-8')
        try:
            stage.rename(target)
        except OSError:
            if not target.is_dir() or not complete(target):
                raise
        return target / 'codex.exe'
    finally:
        # Only the staging directory made by this call may be removed; snapshots remain untouched.
        if stage.exists():
            if stage.resolve().parent != cache or not stage.name.startswith('.staging-'):
                raise RuntimeError('Refusing to clean an unexpected staging path')
            shutil.rmtree(stage)


def resolve_native(settings, runtime):
    source = settings.get('native_source')
    if source is None:
        return Path(settings['codex'])
    if source == 'app':
        folder = app_resources()
    elif isinstance(source, dict) and set(source) == {'directory'}:
        folder = Path(source['directory'])
    else:
        raise ValueError('native_source must be "app" or an object with a directory path')
    return snapshot(folder, Path(runtime) / 'native')


def native_environment(cli, home):
    env = dict(os.environ, CODEX_APP_RUNTIME_CLI_PATH=str(cli), CODEX_HOME=str(home))
    env.pop('CODEX_CLI_PATH', None)
    native_bin = str(Path(cli).absolute().parent)
    env['PATH'] = native_bin + (os.pathsep + env['PATH'] if env.get('PATH') else '')
    # Already-running shells can predate an API key added to the Windows user environment.
    # Resolve only explicitly configured provider env_key names, without overriding process values.
    if os.name == 'nt':
        import winreg
        try:
            config = tomllib.loads((Path(home) / 'config.toml').read_text(encoding='utf-8-sig'))
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
                for provider in config.get('model_providers', {}).values():
                    name = provider.get('env_key')
                    if isinstance(name, str) and name not in env:
                        try:
                            value, kind = winreg.QueryValueEx(key, name)
                            if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                                env[name] = os.path.expandvars(value) if kind == winreg.REG_EXPAND_SZ else value
                        except OSError:
                            pass
        except (OSError, ValueError):
            pass
    return env


def startup_probe(command, home, timeout=30):
    info = json.dumps({'name': 'codex_desktop', 'title': 'Codex Desktop', 'version': '0.1.0'})
    result = subprocess.run([*command, '-c', 'features.code_mode_host=true', 'app-server',
                             '--analytics-default-enabled', '--print-startup-config', '--startup-client-info', info],
                            env=dict(os.environ, CODEX_HOME=str(home)), capture_output=True,
                            text=True, encoding='utf-8', timeout=timeout)
    try:
        data = json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError('Startup-policy probe did not return JSON') from exc
    if result.returncode or not isinstance(data.get('appServerVersion'), str) or \
            'requirements' not in data.get('configRequirements', {}):
        raise RuntimeError('Startup-policy probe failed; CLI override remains disabled')
    return data['appServerVersion']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', required=True)
    parser.add_argument('--native')
    args = parser.parse_args()
    path = Path(args.settings).resolve()
    settings = json.loads(path.read_text(encoding='utf-8-sig'))
    source = 'app' if args.native is None else {'directory': str(Path(args.native).resolve().parent)}
    updated = dict(settings, native_source=source)
    cli = resolve_native(updated, path.parent)
    if cli.resolve() == Path(settings['launcher']).resolve():
        raise RuntimeError('Native CLI and routing launcher must differ')
    # Check the native App startup command before changing any installed routing metadata.
    with tempfile.TemporaryDirectory(prefix='codex-native-startup-') as temp:
        version = startup_probe([str(cli)], temp)
    updated['codex'] = str(cli)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    shutil.copy2(path, path.with_name(path.name + '.before-native-update-' + stamp))
    replacement = path.with_name(path.name + '.pending-' + stamp)
    try:
        replacement.write_text(json.dumps(updated, indent=2) + '\n', encoding='utf-8')
        replacement.replace(path)
    finally:
        replacement.unlink(missing_ok=True)
    print('Native runtime ready:', version)
    print(cli)
    print('CLI override unchanged. Verify the launcher before activating it.')


if __name__ == '__main__':
    main()
