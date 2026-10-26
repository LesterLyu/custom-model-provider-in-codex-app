"""Verify the Windows launcher in an isolated home without model inference."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime, timezone

if __package__:
    from .native_runtime import startup_probe
    from .code_mode_probe import verify_code_mode
else:
    from native_runtime import startup_probe
    from code_mode_probe import verify_code_mode


class JsonlClient:
    def __init__(self, command, home):
        env = dict(os.environ, CODEX_HOME=str(home))
        self.proc = subprocess.Popen([*command, 'app-server'], env=env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self.messages = queue.Queue()
        self.seq = 0

        def read():
            try:
                for line in self.proc.stdout:
                    self.messages.put(json.loads(line))
            finally:
                self.messages.put(None)

        threading.Thread(target=read, daemon=True).start()
        try:
            self.rpc('initialize', {'clientInfo': {'name': 'routing_test', 'version': '0.1'},
                                    'capabilities': {'experimentalApi': True}})
            self.send({'method': 'initialized'})
        except BaseException:
            self.close()
            raise

    def send(self, data):
        self.proc.stdin.write((json.dumps(data) + '\n').encode())
        self.proc.stdin.flush()

    def rpc(self, method, params):
        self.seq += 1
        self.send({'id': self.seq, 'method': method, 'params': params})
        while True:
            response = self.messages.get(timeout=30)
            if response is None:
                raise EOFError('App server exited')
            if response.get('id') == self.seq:
                if 'error' in response:
                    raise RuntimeError('RPC failed: ' + method + ': ' + str(response['error']))
                return response['result']

    def close(self):
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=25)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        self.proc.stdout.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True)
    args = parser.parse_args()
    runtime = Path(args.runtime)
    settings = json.loads((runtime / 'windows.json').read_text(encoding='utf-8-sig'))
    model, provider = next(iter(settings['routes'].items()))
    with tempfile.TemporaryDirectory(prefix='codex-stdio-routing-') as tmp:
        home = Path(tmp)
        config = ('[model_providers.' + provider + ']\nname = "Local test"\n'
                  'base_url = "http://127.0.0.1:1/v1"\nwire_api = "responses"\n')
        (home / 'config.toml').write_text(config)
        thread_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        fixture = home / 'resume-fixture.jsonl'
        rows = [
            {'timestamp': timestamp, 'type': 'session_meta', 'payload': {
                'id': thread_id, 'timestamp': timestamp, 'cwd': str(home), 'originator': 'routing_test',
                'cli_version': '0.163.0', 'source': 'cli', 'model_provider': provider,
                'base_instructions': {'text': 'No-inference routing fixture.'}}},
            {'timestamp': timestamp, 'type': 'response_item', 'payload': {
                'type': 'message', 'role': 'user', 'content': [
                    {'type': 'input_text', 'text': 'No-inference routing fixture.'}]}}
        ]
        fixture.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        version = startup_probe([settings['launcher']], home)
        for index in range(2):
            client = JsonlClient([settings['launcher']], home)
            try:
                initial = client.rpc('config/read', {'includeLayers': False})['config']
                if index == 0:
                    result = client.rpc('thread/start', {'model': model, 'modelProvider': 'openai', 'ephemeral': True})
                else:
                    result = client.rpc('thread/resume', {'model': model, 'modelProvider': 'openai',
                                                         'threadId': thread_id, 'path': str(fixture), 'excludeTurns': True})
                if result.get('modelProvider') != provider:
                    raise RuntimeError('Provider routing failed')
                hosted = client.rpc('thread/start', {'ephemeral': True})
                if hosted.get('modelProvider') != 'openai':
                    raise RuntimeError('Unmapped default did not use OpenAI')
                after = client.rpc('config/read', {'includeLayers': False})['config']
                for key in ('model', 'model_provider'):
                    if initial.get(key) != after.get(key):
                        raise RuntimeError('Global default changed')
                if (home / 'config.toml').read_text() != config:
                    raise RuntimeError('Config file changed')
            finally:
                client.close()
        verify_code_mode(JsonlClient, settings['launcher'], home, model, provider)
        print('PASS: startup-policy (' + version + '), Windows start/resume, mapped provider, OpenAI default, '
              'and real Code Mode host execution against localhost. No external inference.')


if __name__ == '__main__':
    main()
