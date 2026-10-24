"""Opt-in native CLI lifecycle check in a temporary CODEX_HOME; no inference."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from codex_provider_routing.manage import canonical_socket, check_schema, native_snapshot, private_json, verify_proxy
from codex_provider_routing.rpc import Client


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=25)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def wait_for(path, process):
    for _ in range(200):
        if process.poll() is not None:
            raise RuntimeError("Test daemon exited; inspect its log in the temporary test directory")
        if path.exists():
            try:
                with Client(path) as client:
                    client.rpc('config/read', {'includeLayers': False})
                return
            except (OSError, EOFError, RuntimeError):
                pass
        time.sleep(0.1)
    raise TimeoutError("Test daemon didn't become ready")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True)
    args = parser.parse_args()
    cli = str(Path(args.codex).expanduser().absolute())
    print(check_schema(cli))
    with tempfile.TemporaryDirectory(prefix='codex-routing-native-') as tmp:
        root = Path(tmp)
        home = root / 'home'
        home.mkdir(mode=0o700)
        config = home / 'config.toml'
        # The unreachable loopback endpoint makes unintended inference fail immediately.
        config.write_text('[model_providers.local]\nname = "Local test"\n'
                          'base_url = "http://127.0.0.1:1/v1"\nwire_api = "responses"\n')
        digest = hashlib.sha256(config.read_bytes()).hexdigest()
        env = dict(os.environ, CODEX_HOME=str(home))
        env.pop('OPENAI_API_KEY', None)
        env.pop('OPENAI_BASE_URL', None)
        alias = home / 'app-server-control/app-server-control.sock'
        private = home / 'app-server-control/routing-native.sock'
        private_json(root / 'routes.json', {'routes': {'example-local-model': 'local'}})
        process = None
        with (root / 'test-native.log').open('wb') as log:
            try:
                process = subprocess.Popen([cli, 'app-server', '--listen', 'unix://'], env=env, cwd=root,
                                           stdin=subprocess.DEVNULL, stdout=log, stderr=log)
                wait_for(alias, process)
                canonical = canonical_socket(alias)
                snapshot, environment = native_snapshot(alias)
                if snapshot['pid'] != process.pid:
                    raise RuntimeError('Test bootstrap daemon ownership mismatch')
                private_json(root / 'environment.json', environment)
                stop(process)
                for _ in range(2):
                    process = subprocess.Popen([sys.executable, '-m', 'codex_provider_routing.router',
                        '--home', str(home), '--listen', str(canonical), '--alias', str(alias),
                        '--upstream', str(private), '--routes', str(root / 'routes.json'),
                        '--ownership-lock', str(canonical) + '.lock', '--codex', cli,
                        '--environment', str(root / 'environment.json')], env=env, cwd=root,
                        stdin=subprocess.DEVNULL, stdout=log, stderr=log)
                    wait_for(alias, process)
                    verify_proxy(cli, home, 'example-local-model', 'local')
                    if hashlib.sha256(config.read_bytes()).hexdigest() != digest:
                        raise RuntimeError('Test configuration changed')
                    stop(process)
                print('PASS: two router lifecycles, actual proxy, ephemeral provider selection, unchanged config.')
            finally:
                if process:
                    stop(process)


if __name__ == '__main__':
    main()
