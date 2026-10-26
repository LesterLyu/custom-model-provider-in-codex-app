import asyncio
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from codex_provider_routing.startup import (
    NativeIdentity, claim_endpoint, native_is_idle, prepare_directory, socket_peer,
)


class StartupChecks(unittest.TestCase):
    def test_recreates_private_endpoint_directory_after_reboot(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'rebooted'
            prepare_directory(folder / 'public.sock')
            self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)

    def test_rejects_directory_symlink_and_shared_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'link').symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, 'owned and private'):
                prepare_directory(root / 'link' / 'public.sock')
            (root / 'shared').mkdir(mode=0o755)
            with self.assertRaisesRegex(RuntimeError, 'owned and private'):
                prepare_directory(root / 'shared' / 'public.sock')

    def test_socket_probe_preserves_files_and_identifies_live_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'public.sock'
            self.assertIsNone(socket_peer(path))
            path.write_text('keep')
            with self.assertRaisesRegex(RuntimeError, 'unexpected public endpoint'):
                socket_peer(path)
            self.assertEqual(path.read_text(), 'keep')
            path.unlink()
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(path))
                server.listen()
                self.assertEqual(socket_peer(path), (os.getpid(), os.getuid()))
            self.assertIsNone(socket_peer(path))

    def test_unknown_or_paginated_thread_status_never_means_idle(self):
        with patch('codex_provider_routing.startup.Client') as factory:
            client = factory.return_value.__enter__.return_value
            client.rpc.return_value = {'data': [], 'nextCursor': 'more'}
            with self.assertRaisesRegex(RuntimeError, 'whether.*idle'):
                native_is_idle('/unused')
            for status, expected in [('active', False), ('notLoaded', False),
                                     ('new-status', False), ('idle', True), ('systemError', True)]:
                client.rpc.side_effect = [{'data': ['thread']}, {'thread': {'status': {'type': status}}}]
                self.assertEqual(native_is_idle('/unused'), expected)
            client.rpc.side_effect = OSError('RPC unavailable')
            with self.assertRaises(OSError):
                native_is_idle('/unused')


class StartupRecovery(unittest.IsolatedAsyncioTestCase):
    async def test_idle_fallback_exits_then_endpoint_can_be_claimed(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        identity = NativeIdentity(child.pid, 'test-start')
        peer = (child.pid, os.getuid())
        try:
            with patch('codex_provider_routing.startup.socket_peer',
                       side_effect=lambda _: peer if child.poll() is None else None), \
                 patch('codex_provider_routing.startup.native_identity', return_value=identity), \
                 patch('codex_provider_routing.startup.native_is_idle', return_value=True):
                await claim_endpoint('/unused', '/home', '/codex', [], '/home', asyncio.Event())
            self.assertIsNotNone(child.poll())
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)

    async def test_active_fallback_is_left_running_and_wait_is_cancellable(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        stop = asyncio.Event()
        try:
            with patch('codex_provider_routing.startup.socket_peer', return_value=(child.pid, os.getuid())), \
                 patch('codex_provider_routing.startup.native_identity', return_value=NativeIdentity(child.pid, 'same')), \
                 patch('codex_provider_routing.startup.native_is_idle', return_value=False), \
                 patch('codex_provider_routing.startup.signal.pidfd_send_signal') as send:
                asyncio.get_running_loop().call_later(0.05, stop.set)
                with self.assertRaises(asyncio.CancelledError):
                    await claim_endpoint('/unused', '/home', '/codex', [], '/home', stop)
                send.assert_not_called()
                self.assertIsNone(child.poll())
        finally:
            child.terminate()
            child.wait(timeout=5)

    async def test_process_identity_change_never_receives_signal(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        try:
            with patch('codex_provider_routing.startup.socket_peer', return_value=(child.pid, os.getuid())), \
                 patch('codex_provider_routing.startup.native_identity', side_effect=[
                     NativeIdentity(child.pid, 'old'), NativeIdentity(child.pid, 'new')]), \
                 patch('codex_provider_routing.startup.signal.pidfd_send_signal') as send:
                with self.assertRaisesRegex(RuntimeError, 'changed while'):
                    await claim_endpoint('/unused', '/home', '/codex', [], '/home', asyncio.Event())
                send.assert_not_called()
        finally:
            child.terminate()
            child.wait(timeout=5)

    async def test_unrecognized_live_listener_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'public.sock'
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(path))
                server.listen()
                with patch('codex_provider_routing.startup.signal.pidfd_send_signal') as send:
                    with self.assertRaisesRegex(RuntimeError, 'not this installation'):
                        await claim_endpoint(path, tmp, '/unused/codex', [], tmp, asyncio.Event())
                    send.assert_not_called()
                self.assertTrue(path.exists())
