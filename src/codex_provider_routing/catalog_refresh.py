"""Refresh an OpenAI catalog, preserving separately managed custom definitions."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request

MAX_BYTES = 4 * 1024 * 1024
ENDPOINT = 'https://chatgpt.com/backend-api/codex/models'


def entries(data):
    models = data.get('models') if isinstance(data, dict) else None
    if not isinstance(models, list) or not models:
        raise ValueError('Expected a nonempty Codex models catalog')
    slugs = [m.get('slug') if isinstance(m, dict) else None for m in models]
    if any(not isinstance(s, str) or not s.strip() for s in slugs) or len(set(slugs)) != len(slugs):
        raise ValueError('Invalid or duplicate model IDs')
    return models


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, data):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Refusing to replace a symlink')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + path.name + '-', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def locked(path):
    """A crash releases this OS lock; other launches keep their existing catalog."""
    with open(path, 'a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'\0')
            stream.flush()
        stream.seek(0)
        acquired = False
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            pass
        try:
            yield acquired
        finally:
            if acquired:
                if sys.platform == 'win32':
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def authentication(home):
    auth = read_json(Path(home) / 'auth.json')
    if auth.get('auth_mode') == 'chatgpt':
        tokens = auth.get('tokens') or {}
        token, account = tokens.get('access_token'), tokens.get('account_id')
        if not token or not account:
            raise ValueError('Missing ChatGPT file credentials')
        headers = {'Authorization': 'Bearer ' + token, 'ChatGPT-Account-ID': account}
    else:
        token = auth.get('OPENAI_API_KEY')
        if not token:
            raise ValueError('File-backed OpenAI login required')
        headers = {'Authorization': 'Bearer ' + token}
    # Token/account changes invalidate the local freshness record. Never persist credentials.
    identity = digest(json.dumps(headers, sort_keys=True).encode())
    return headers, identity


def cli_version(cli, env):
    result = subprocess.run([str(cli), '--version'], env=env, capture_output=True,
                            text=True, encoding='utf-8', timeout=10, check=True)
    match = re.search(r'\b(\d+\.\d+\.\d+)(?:[-+][\w.-]+)?', result.stdout)
    if not match:
        raise ValueError('Cannot determine native CLI version')
    return match.group(1)


def fetch_catalog(headers, version, timeout):
    # Fixed official origin; credentials are never sent to a configured custom provider or redirect.
    request = urllib.request.Request(ENDPOINT + '?' + urllib.parse.urlencode({'client_version': version}),
                                     headers=dict(headers, **{'User-Agent': 'codex_cli_rs/' + version,
                                                              'originator': 'codex_cli_rs'}))
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('Oversized catalog response')
        control = response.headers.get('Cache-Control', '').lower()
        match = re.search(r'(?:^|[,\s])max-age\s*=\s*"?(\d+)', control)
        ttl = int(match.group(1)) if match else None
        # The generated catalog is the user's local configuration, not an HTTP cache.
        # No-store/no-cache responses are always fetched again at the next backend start.
        if 'no-cache' in control or 'no-store' in control:
            ttl = 0
        data = json.loads(raw)
        entries(data)
        return data, ttl


def validate_catalog(cli, candidate, env):
    with tempfile.TemporaryDirectory(prefix='codex-catalog-check-') as folder:
        home = Path(folder)
        (home / 'config.toml').write_text('model_catalog_json=' + json.dumps(str(candidate)) +
                                         '\ncli_auth_credentials_store="file"\n[features]\nplugins=false\n',
                                         encoding='utf-8')
        isolated = dict(env, CODEX_HOME=str(home))
        isolated.pop('CODEX_CLI_PATH', None)
        result = subprocess.run([str(cli), 'debug', 'models'], env=isolated, cwd=folder,
                                capture_output=True, text=True, encoding='utf-8', timeout=15, check=True)
        parsed = entries(json.loads(result.stdout))
        if {m['slug'] for m in parsed} != {m['slug'] for m in entries(read_json(candidate))}:
            raise ValueError('Native CLI did not load the proposed catalog')


def enable(home, model_ids, interval=3600, timeout=10):
    home = Path(home).expanduser().resolve()
    config = tomllib.loads((home / 'config.toml').read_text(encoding='utf-8-sig'))
    catalog = Path(config['model_catalog_json']).expanduser()
    if not catalog.is_absolute() or catalog.is_symlink():
        raise ValueError('An absolute regular model_catalog_json is required')
    root = home / 'provider-catalog'
    root.mkdir(mode=0o700, exist_ok=True)
    if (root / 'settings.json').exists() or (root / 'custom.json').exists():
        raise ValueError('Catalog refresh is already configured; edit its private settings/custom file')
    models = entries(read_json(catalog))
    selected = [m for m in models if m['slug'] in set(model_ids)]
    if {m['slug'] for m in selected} != set(model_ids) or not selected:
        raise ValueError('Every requested custom model must exist in the current catalog')
    write_json(root / 'original.json', read_json(catalog))
    write_json(root / 'custom.json', {'models': selected})
    write_json(root / 'settings.json', {'catalog': str(catalog), 'interval_seconds': interval,
                                        'timeout_seconds': timeout})


def refresh_catalog(home, cli, env=None, force=False):
    home = Path(home).expanduser().resolve()
    root = home / 'provider-catalog'
    if not (root / 'settings.json').is_file():
        return 'disabled'
    try:
        with locked(root / 'refresh.lock') as acquired:
            if not acquired:
                return 'busy'
            settings = read_json(root / 'settings.json')
            catalog = Path(settings['catalog'])
            if not catalog.is_absolute() or catalog.is_symlink():
                raise ValueError('Invalid destination catalog')
            old, custom_bytes = catalog.read_bytes(), (root / 'custom.json').read_bytes()
            custom = entries(json.loads(custom_bytes))
            entries(json.loads(old))
            headers, identity = authentication(home)
            env = dict(os.environ if env is None else env)
            env.pop('CODEX_CLI_PATH', None)
            version = cli_version(cli, env)
            key = {'identity': identity, 'version': version, 'catalog_digest': digest(old),
                   'custom_digest': digest(custom_bytes)}
            state_path = root / 'state.json'
            try:
                state = read_json(state_path)
            except (OSError, ValueError):
                state = {}
            now = time.time()
            if not isinstance(state, dict):
                state = {}
            if not force and isinstance(state.get('fetched_at'), (int, float)) and \
                    isinstance(state.get('ttl'), (int, float)) and \
                    all(state.get(k) == v for k, v in key.items()) and \
                    0 <= now - state.get('fetched_at', 0) < state.get('ttl', 0):
                return 'cached'
            timeout = min(30, max(1, float(settings.get('timeout_seconds', 10))))
            upstream, upstream_ttl = fetch_catalog(headers, version, timeout)
            hosted = entries(upstream)
            if {m['slug'] for m in hosted} & {m['slug'] for m in custom}:
                raise ValueError('Custom model collides with an upstream ID')
            combined = {'models': hosted + custom}
            ttl = min(86400, max(0, float(settings.get('interval_seconds', 3600))))
            if upstream_ttl is not None:
                ttl = min(ttl, upstream_ttl)
            with tempfile.TemporaryDirectory(prefix='codex-catalog-candidate-', dir=catalog.parent) as temporary:
                candidate = Path(temporary) / 'models.json'
                write_json(candidate, combined)
                validate_catalog(cli, candidate, env)
                candidate_digest = digest(candidate.read_bytes())
            # Candidate cleanup must finish before publishing; a cleanup failure retains the old catalog.
            if catalog.read_bytes() != old or (root / 'custom.json').read_bytes() != custom_bytes:
                raise ValueError('Catalog was edited while refreshing')
            changed = json.loads(old) != combined
            if changed:
                write_json(root / 'previous.json', json.loads(old))
                write_json(catalog, combined)
            key.update(catalog_digest=candidate_digest if changed else digest(old), fetched_at=now, ttl=ttl)
            # The catalog is already complete; a state write failure must not undo a successful update.
            with contextlib.suppress(OSError, ValueError):
                write_json(state_path, key)
            print('Catalog refresh: ' + ('updated' if changed else 'unchanged') +
                  f' ({len(hosted)} OpenAI, {len(custom)} custom)', file=sys.stderr)
            return 'updated' if changed else 'unchanged'
    except Exception as exc:
        reason = 'HTTP ' + str(exc.code) if isinstance(exc, urllib.error.HTTPError) else type(exc).__name__
        print('Catalog refresh: keeping previous catalog (' + reason + ')', file=sys.stderr)
        return 'failed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', required=True)
    parser.add_argument('--codex')
    parser.add_argument('--enable', action='store_true')
    parser.add_argument('--model', action='append', default=[])
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    if args.enable:
        enable(args.home, args.model)
        print('Enabled automatic catalog refresh; custom definitions stored separately.')
    if args.codex:
        result = refresh_catalog(args.home, args.codex, force=args.force)
        print('Catalog refresh result:', result)
        return int(result == 'failed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
