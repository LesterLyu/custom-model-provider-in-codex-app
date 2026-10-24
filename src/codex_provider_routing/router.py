"""Route selected models to custom providers over the Codex Unix WebSocket interface."""
import argparse
import asyncio
import contextlib
import fcntl
import http.client
import json
import os
from pathlib import Path
import signal
import socket
import stat
import time

from websockets.asyncio.client import unix_connect
from websockets.asyncio.server import unix_serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Response

HOP_HEADERS = frozenset(("host", "connection", "upgrade", "content-length", "transfer-encoding"))


from .routing import Router, validate_routes


def remove_socket(path):
    path = Path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    native_link = stat.S_ISLNK(info.st_mode)
    if native_link:
        target = path.resolve(strict=False)
        safe_root = Path('/tmp') / f'codex-daemon-{os.getuid()}'
        if not target.is_relative_to(safe_root):
            raise RuntimeError("Refusing an unexpected socket symlink")
        if target.exists() and (not target.is_socket() or target.stat().st_uid != os.getuid()):
            raise RuntimeError("Refusing a non-owned socket target")
    if info.st_uid != os.getuid() or not (stat.S_ISSOCK(info.st_mode) or native_link):
        raise RuntimeError("Refusing to replace a non-owned socket")
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(1)
    try:
        probe.connect(str(path))
    except (ConnectionRefusedError, FileNotFoundError):
        pass
    else:
        raise RuntimeError("Refusing to replace an active socket")
    finally:
        probe.close()
    path.unlink()


def http_probe(upstream, request):
    """Retain the native daemon's plain HTTP control and health responses."""
    conn = http.client.HTTPConnection("localhost", timeout=5)
    conn.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.sock.settimeout(5)
    try:
        conn.sock.connect(str(upstream))
        conn.request("GET", request.path, headers=dict(request.headers.raw_items()))
        response = conn.getresponse()
        body = response.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024:
            raise RuntimeError("Oversized HTTP control response")
        headers = [(k, v) for k, v in response.getheaders() if k.lower() not in HOP_HEADERS]
        headers.append(("Content-Length", str(len(body))))
        return Response(response.status, response.reason, Headers(headers), body)
    finally:
        conn.close()


async def run(args):
    home, listen, upstream = Path(args.home), Path(args.listen), Path(args.upstream)
    routes = json.loads(Path(args.routes).read_text())["routes"]
    router = Router(home, routes, args.audit)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    native, native_log, wait_native = None, None, None
    ownership = None
    server = None
    try:
        if args.ownership_lock:
            fd = os.open(args.ownership_lock, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            if os.fstat(fd).st_uid != os.getuid():
                os.close(fd)
                raise RuntimeError("Non-owned public endpoint lock")
            ownership = os.fdopen(fd, 'a')
            fcntl.flock(ownership, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.codex:
            env = dict(os.environ)
            if args.environment:
                env = json.loads(Path(args.environment).read_text())
            env["CODEX_HOME"] = str(home)
            native_state = getattr(args, "native", None)
            native_args = list(native_state["arguments"]) if native_state else ["app-server", "--listen", "unix://"]
            native_args[native_args.index("--listen") + 1] = "unix://" + str(upstream)
            remove_socket(upstream)
            native_log = open(home / "app-server-control/app-server.log", "ab", buffering=0)
            native = await asyncio.create_subprocess_exec(args.codex, *native_args, env=env,
                cwd=native_state["cwd"] if native_state else str(home.parent),
                stdin=asyncio.subprocess.DEVNULL, stdout=native_log, stderr=native_log)
            for _ in range(200):
                if native.returncode is not None:
                    raise RuntimeError("Native daemon exited during startup")
                if upstream.exists():
                    try:
                        reader, writer = await asyncio.open_unix_connection(str(upstream))
                        writer.close()
                        await writer.wait_closed()
                        break
                    except OSError:
                        pass
                await asyncio.sleep(0.1)
            else:
                raise TimeoutError("Native daemon did not create its socket")
            wait_native = asyncio.create_task(native.wait())

        async def health(connection, request):
            if request.headers.get("Upgrade", "").lower() == "websocket":
                return None
            try:
                return await asyncio.to_thread(http_probe, upstream, request)
            except Exception:
                return Response(503, "Service Unavailable", Headers([("Content-Length", "0")]), b"")

        async def handle(client):
            request = client.request
            headers = [(k, v) for k, v in request.headers.raw_items()
                       if k.lower() not in HOP_HEADERS and not k.lower().startswith("sec-websocket-")]
            try:
                async with unix_connect(str(upstream), uri="ws://localhost" + request.path,
                                        additional_headers=headers, compression=None, max_size=None,
                                        ping_interval=None, close_timeout=5) as backend:
                    async def inbound():
                        async for message in client:
                            await backend.send(router.rewrite(message))

                    async def outbound():
                        async for message in backend:
                            await client.send(message)

                    jobs = [asyncio.create_task(inbound()), asyncio.create_task(outbound())]
                    try:
                        done, pending = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
                        for job in done:
                            job.result()
                    finally:
                        for job in jobs:
                            if not job.done():
                                job.cancel()
                        await asyncio.gather(*jobs, return_exceptions=True)
            except ConnectionClosed:
                pass
            except Exception as exc:
                print("Connection relay failed:", type(exc).__name__, flush=True)
                with contextlib.suppress(Exception):
                    await client.close(code=1011, reason="Native daemon connection unavailable")

        remove_socket(listen)
        server = await unix_serve(handle, str(listen), compression=None, max_size=None, ping_interval=None,
                                  process_request=health, close_timeout=5)
        os.chmod(listen, 0o600)
        if args.alias:
            alias = Path(args.alias)
            if alias.is_symlink():
                if alias.resolve(strict=False) != listen:
                    remove_socket(alias)
                elif alias.lstat().st_uid != os.getuid():
                    raise RuntimeError('Non-owned public socket alias')
                else:
                    alias.unlink()
            elif alias.exists():
                remove_socket(alias)
            alias.symlink_to(listen)
        print("READY provider routing", str(listen), flush=True)
        wait_stop = asyncio.create_task(stop.wait())
        jobs = [wait_stop] + ([wait_native] if wait_native else [])
        await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
        if wait_native and wait_native.done() and not stop.is_set():
            raise RuntimeError("Native daemon exited")
    finally:
        if server:
            server.close()
            await server.wait_closed()
            with contextlib.suppress(OSError, RuntimeError):
                remove_socket(listen)
        if native and native.returncode is None:
            native.terminate()
            try:
                await asyncio.wait_for(native.wait(), 20)
            except asyncio.TimeoutError:
                native.kill()
                await native.wait()
        if native_log:
            native_log.close()
        if ownership:
            ownership.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routes", required=True)
    parser.add_argument("--home", required=True)
    parser.add_argument("--listen", required=True)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--codex")
    parser.add_argument("--environment")
    parser.add_argument("--audit")
    parser.add_argument("--ownership-lock")
    parser.add_argument("--alias")
    args = parser.parse_args()
    if Path(args.listen) == Path(args.upstream):
        parser.error("Public and native sockets must differ")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
