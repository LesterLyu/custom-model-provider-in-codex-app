import argparse
import asyncio
import fcntl
import json
import os
from pathlib import Path
import tempfile
import unittest

from websockets.asyncio.client import unix_connect
from websockets.asyncio.server import unix_serve

from codex_provider_routing.router import run
from codex_provider_routing.rpc import Client


class Relay(unittest.IsolatedAsyncioTestCase):
    async def test_websocket_roundtrip_and_lifetime_lock(self):
        with tempfile.TemporaryDirectory(prefix='cr-') as tmp:
            folder = Path(tmp)
            home = folder / 'home'
            home.mkdir()
            routes = folder / 'routes.json'
            routes.write_text(json.dumps({'routes': {'sample': 'local'}}))
            listen, upstream, alias = (folder / n for n in ('public.sock', 'native.sock', 'alias.sock'))
            lock = str(listen) + '.lock'
            received = []

            async def echo(conn):
                async for msg in conn:
                    received.append((msg, conn.request.headers.get('Authorization')))
                    await conn.send(msg)

            async with unix_serve(echo, str(upstream)):
                args = argparse.Namespace(home=str(home), listen=str(listen), upstream=str(upstream),
                                          routes=str(routes), ownership_lock=lock, alias=str(alias),
                                          codex=None, audit=None)
                task = asyncio.create_task(run(args))
                try:
                    for _ in range(100):
                        if alias.exists():
                            break
                        if task.done():
                            task.result()
                        await asyncio.sleep(0.01)
                    self.assertEqual(alias.resolve(), listen)
                    with open(lock, 'a') as handle, self.assertRaises(BlockingIOError):
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    async with unix_connect(str(alias), additional_headers={'Authorization': 'Bearer example'}) as conn:
                        await conn.send(json.dumps({'id': 1, 'method': 'thread/resume', 'params': {'model': 'sample'}}))
                        self.assertEqual(json.loads(await conn.recv())['params']['modelProvider'], 'local')
                        text = '{ "method": "turn/start", "params": {"input": "keep"} }'
                        await conn.send(text)
                        self.assertEqual(await conn.recv(), text)
                        await conn.send(b'\x00\xff')
                        self.assertEqual(await conn.recv(), b'\x00\xff')
                    self.assertEqual(received[0][1], 'Bearer example')
                finally:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                self.assertFalse(listen.exists())
                with open(lock, 'a') as handle:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

    async def test_rpc_client_uses_http_upgrade_and_masked_frames(self):
        with tempfile.TemporaryDirectory(prefix='cr-rpc-') as tmp:
            path = str(Path(tmp) / 'native.sock')
            methods = []

            async def server(conn):
                async for raw in conn:
                    request = json.loads(raw)
                    methods.append(request['method'])
                    if 'id' in request:
                        await conn.send(json.dumps({'id': request['id'], 'result': {'ok': True}}))

            def call():
                with Client(path) as client:
                    return client.rpc('config/read', {})

            async with unix_serve(server, path):
                self.assertTrue((await asyncio.to_thread(call))['ok'])
            self.assertEqual(methods, ['initialize', 'initialized', 'config/read'])
