"""Recover an idle native fallback before starting the private routing backend."""
import asyncio
from dataclasses import dataclass
import os
from pathlib import Path
import select
import signal
import socket
import stat
import struct

from .rpc import Client


def prepare_directory(path):
    """The canonical /tmp directory disappears on reboot; never follow a symlink."""
    folder = Path(path).parent
    folder.mkdir(mode=0o700, exist_ok=True)
    info = folder.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("Public socket directory must be owned and private")


def socket_peer(path):
    path = Path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if info.st_uid != os.getuid() or not stat.S_ISSOCK(info.st_mode):
        raise RuntimeError("Refusing an unexpected public endpoint")
    with socket.socket(socket.AF_UNIX) as probe:
        probe.settimeout(2)
        try:
            probe.connect(str(path))
        except (FileNotFoundError, ConnectionRefusedError):
            return None
        pid, uid, _ = struct.unpack("3i", probe.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if uid != os.getuid():
        raise RuntimeError("Public socket belongs to another user")
    return pid, uid


@dataclass(frozen=True)
class NativeIdentity:
    pid: int
    started: str


def native_identity(peer, codex, arguments, cwd, home):
    """Accept only this installation's exact native fallback, never another router."""
    pid, uid = peer
    proc = Path('/proc') / str(pid)
    args = [part.decode() for part in (proc / 'cmdline').read_bytes().split(b'\0') if part]
    supported = (["app-server", "--listen", "unix://"],
                 ["-c", "features.code_mode_host=true", "app-server", "--listen", "unix://"])
    if (uid != os.getuid() or proc.stat().st_uid != uid or not args or
            Path(args[0]).name != 'codex' or args[1:] not in supported or args[1:] != list(arguments) or
            (proc / 'exe').resolve() != Path(codex).resolve() or
            (proc / 'cwd').resolve() != Path(cwd).resolve()):
        raise RuntimeError("Public endpoint is not this installation's native fallback")
    env = dict(part.split(b'=', 1) for part in (proc / 'environ').read_bytes().split(b'\0') if b'=' in part)
    remote_home = env.get(b'CODEX_HOME') or os.fsencode(Path(os.fsdecode(env.get(b'HOME', b''))) / '.codex')
    if Path(os.fsdecode(remote_home)).resolve() != Path(home).resolve():
        raise RuntimeError("Native fallback uses a different Codex home")
    # starttime is field 22; the parenthesized process name may contain spaces.
    started = (proc / 'stat').read_text().rsplit(') ', 1)[1].split()[19]
    return NativeIdentity(pid, started)


def native_is_idle(path):
    """An unreadable, paginated or unfamiliar response never counts as idle."""
    with Client(path) as client:
        loaded = client.rpc('thread/loaded/list', {})
        if loaded.get('nextCursor') or not isinstance(loaded.get('data'), list):
            raise RuntimeError("Cannot establish whether the native fallback is idle")
        for item in loaded['data']:
            tid = item.get('id') if isinstance(item, dict) else item
            status = client.rpc('thread/read', {'threadId': tid})['thread'].get('status', {}).get('type')
            if status not in ('idle', 'systemError'):
                return False
    return True


async def claim_endpoint(path, home, codex, arguments, cwd, stop):
    """Caller holds the native startup lock until its public listener shuts down."""
    announced = False
    while not stop.is_set():
        peer = socket_peer(path)
        if peer is None:
            return
        try:
            identity = native_identity(peer, codex, arguments, cwd, home)
            if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
                raise RuntimeError("Idle fallback recovery requires Linux pidfd support")
            # Pin the process identity so PID recycling can never redirect a signal.
            with os.fdopen(os.pidfd_open(identity.pid), 'rb') as process:
                if native_identity(peer, codex, arguments, cwd, home) != identity:
                    raise RuntimeError("Native fallback changed while being inspected")
                idle = await asyncio.to_thread(native_is_idle, path)
                if idle and not stop.is_set():
                    if socket_peer(path) != peer or native_identity(peer, codex, arguments, cwd, home) != identity:
                        raise RuntimeError("Public endpoint changed while being inspected")
                    print('Recovering idle native fallback', identity.pid, flush=True)
                    signal.pidfd_send_signal(process.fileno(), signal.SIGTERM)
                    deadline = asyncio.get_running_loop().time() + 20
                    while not select.select([process], [], [], 0)[0]:
                        if asyncio.get_running_loop().time() >= deadline:
                            raise TimeoutError("Native fallback did not exit gracefully; no force-kill attempted")
                        await asyncio.sleep(0.1)
                    continue
        except (FileNotFoundError, ProcessLookupError):
            continue
        if not announced:
            print('Waiting for native fallback work to finish before enabling routing', flush=True)
            announced = True
        try:
            await asyncio.wait_for(stop.wait(), 2)
        except asyncio.TimeoutError:
            pass
    raise asyncio.CancelledError
