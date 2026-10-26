"""Execute a harmless Code Mode cell through a local scripted Responses endpoint."""
import http.server
import json
import os
from pathlib import Path
import subprocess
import threading
import uuid


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _exec_namespace(tools, namespace=None):
    for tool in tools:
        if tool.get('type') == 'custom' and tool.get('name') == 'exec':
            return True, namespace
        if tool.get('type') == 'namespace':
            found, parent = _exec_namespace(tool.get('tools', []), tool.get('name'))
            if found:
                return found, parent
    return False, None


def verify_code_mode(client_factory, launcher, home, model, provider):
    marker = 'routing-code-mode-' + uuid.uuid4().hex
    verified, failed = threading.Event(), []
    env = dict(os.environ, CODEX_HOME=str(home))
    exported = subprocess.run([launcher, 'debug', 'models', '--bundled'], env=env, capture_output=True,
                              text=True, encoding='utf-8', timeout=30, check=True)
    catalog = json.loads(exported.stdout)
    entries = catalog if isinstance(catalog, list) else catalog['models']
    entry = dict(entries[0], slug=model, display_name='Routing verification', tool_mode='code_mode_only',
                 use_responses_lite=False)
    catalog_path = Path(home) / 'code-mode-models.json'
    catalog_path.write_text(json.dumps({'models': [entry]}), encoding='utf-8')

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            outputs = [item.get('output') for item in request.get('input', [])
                       if item.get('type') in ('custom_tool_call_output', 'function_call_output')]
            if outputs:
                passed = any(marker == line.strip() for text in _strings(outputs) for line in text.splitlines())
                if passed:
                    verified.set()
                else:
                    failed.append('Code Mode cell did not return its verification marker')
                    verified.set()
                item = {'id': 'msg_probe', 'type': 'message', 'role': 'assistant', 'status': 'completed',
                        'content': [{'type': 'output_text', 'text': 'Verification finished.', 'annotations': []}]}
            else:
                found, namespace = _exec_namespace(request.get('tools', []))
                if not found:
                    failed.append('Code Mode exec tool was not offered')
                    verified.set()
                item = {'id': 'ctc_probe', 'type': 'custom_tool_call', 'call_id': 'call_probe', 'name': 'exec',
                        'input': 'text(' + json.dumps(marker) + ')', 'status': 'completed'}
                if namespace:
                    item['namespace'] = namespace
            response = {'id': 'resp_probe', 'object': 'response', 'created_at': 0, 'status': 'in_progress',
                        'model': model, 'error': None, 'incomplete_details': None, 'output': [],
                        'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()

            def send(kind, **data):
                event = {'type': kind, **data}
                self.wfile.write(('event: ' + kind + '\ndata: ' + json.dumps(event) + '\n\n').encode())
                self.wfile.flush()

            send('response.created', response=response)
            send('response.output_item.added', output_index=0, item=item)
            send('response.output_item.done', output_index=0, item=item)
            send('response.completed', response=dict(response, status='completed', output=[item]))

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    config_path = Path(home) / 'config.toml'
    original = config_path.read_text(encoding='utf-8')
    config = ('model=' + json.dumps(model) + '\nmodel_catalog_json=' + json.dumps(str(catalog_path)) +
              '\napproval_policy="never"\nsandbox_mode="read-only"\n' + original.replace(
                  'http://127.0.0.1:1/v1', f'http://127.0.0.1:{server.server_port}/v1') +
              '\n[features]\nplugins=false\ncode_mode_host=true\n')
    config_path.write_text(config, encoding='utf-8')
    client = None
    try:
        client = client_factory([launcher], home)
        thread = client.rpc('thread/start', {'model': model, 'modelProvider': 'openai', 'ephemeral': True,
                                             'cwd': str(home)})
        if thread.get('modelProvider') != provider:
            raise RuntimeError('Code Mode probe did not use the mapped provider')
        client.rpc('turn/start', {'threadId': thread['thread']['id'], 'input': [
            {'type': 'text', 'text': 'Run the isolated Code Mode smoke test.'}]})
        if not verified.wait(30):
            raise RuntimeError('Code Mode host verification timed out; CLI override remains disabled')
        if failed:
            raise RuntimeError(failed[0])
    finally:
        if client is not None:
            client.close()
        server.shutdown()
        server.server_close()
        config_path.write_text(original, encoding='utf-8')
