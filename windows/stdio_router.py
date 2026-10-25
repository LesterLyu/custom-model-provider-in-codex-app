"""Provider routing for a desktop App that launches a JSONL stdio app-server."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from codex_provider_routing.routing import Router


def is_stdio_server(arguments):
    if 'app-server' not in arguments:
        return False
    tail = arguments[arguments.index('app-server') + 1:]
    if tail and not tail[0].startswith('-'):
        return False
    if '--help' in tail or '-h' in tail or '--print-startup-config' in tail:
        return False
    for index, value in enumerate(tail):
        if value.startswith('--listen=') and value != '--listen=stdio://':
            return False
        if value == '--listen' and (index + 1 == len(tail) or tail[index + 1] != 'stdio://'):
            return False
    return True


def native_environment(cli, home):
    env = dict(os.environ, CODEX_APP_RUNTIME_CLI_PATH=str(cli), CODEX_HOME=str(home))
    env.pop('CODEX_CLI_PATH', None)
    native_bin = str(Path(cli).absolute().parent)
    env['PATH'] = native_bin + (os.pathsep + env['PATH'] if env.get('PATH') else '')
    return env


def relay(cli, arguments, router):
    env = native_environment(cli, router.home)
    child = subprocess.Popen([str(cli), *arguments], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=None, bufsize=0, env=env)

    def inbound():
        try:
            for line in sys.stdin.buffer:
                try:
                    original = line.decode('utf-8')
                except UnicodeDecodeError:
                    rewritten = line
                else:
                    changed = router.rewrite(original)
                    rewritten = line if changed == original else (changed + '\n').encode('utf-8')
                view = memoryview(rewritten)
                while view:
                    count = child.stdin.write(view)
                    if not count:
                        raise BrokenPipeError('Native CLI input closed')
                    view = view[count:]
                child.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            with contextlib.suppress(OSError):
                child.stdin.close()

    thread = threading.Thread(target=inbound, daemon=True)
    thread.start()
    try:
        while True:
            chunk = child.stdout.read(65536)
            if not chunk:
                break
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
        return child.wait()
    finally:
        child.stdout.close()
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', required=True)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    arguments = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    settings = json.loads(Path(args.settings).read_text(encoding='utf-8-sig'))
    cli = Path(settings['codex'])
    # The wrapper must always delegate to the real executable, never back to itself.
    if cli.resolve() == Path(settings.get('launcher', '')).resolve():
        parser.error('Native CLI and routing launcher must differ')
    home = Path(os.environ.get('CODEX_HOME') or settings['home']).expanduser().resolve()
    if not is_stdio_server(arguments):
        env = native_environment(cli, home)
        return subprocess.call([str(cli), *arguments], env=env)
    router = Router(home, settings['routes'], settings.get('audit'))
    return relay(cli, arguments, router)


if __name__ == '__main__':
    raise SystemExit(main())
