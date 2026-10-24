"""Install and check a user service without changing Codex configuration."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import tomllib
from types import SimpleNamespace

from .router import run, remove_socket, validate_routes
from .rpc import Client, ProxyTransport

SERVICE = "codex-provider-routing.service"


def private_json(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")


def systemctl(*args):
    subprocess.run(["systemctl", "--user", *args], check=True)


def unit_path():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd/user" / SERVICE


def canonical_socket(alias):
    if not alias.is_symlink() or alias.lstat().st_uid != os.getuid():
        raise RuntimeError("Expected an owned native control socket symlink; connect the App once first")
    target = alias.resolve(strict=True)
    safe = Path("/tmp") / f"codex-daemon-{os.getuid()}"
    if target.parent != safe or not target.is_socket() or target.stat().st_uid != os.getuid():
        raise RuntimeError("Unrecognized canonical socket layout; no changes made")
    info = safe.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("Unexpected permissions on the native socket directory")
    return target


def native_snapshot(alias):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.connect(str(alias))
        pid, uid, _ = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if uid != os.getuid():
        raise RuntimeError("Native daemon is owned by another user")
    proc = Path("/proc") / str(pid)
    args = [part.decode() for part in (proc / "cmdline").read_bytes().split(b"\0") if part]
    supported = (["app-server", "--listen", "unix://"],
                 ["-c", "features.code_mode_host=true", "app-server", "--listen", "unix://"])
    if not args or Path(args[0]).name != "codex" or args[1:] not in supported:
        raise RuntimeError("Unrecognized native command; no process will be stopped")
    env = dict(pair.split("=", 1) for pair in
               (proc / "environ").read_bytes().decode(errors="surrogateescape").split("\0") if "=" in pair)
    return {"pid": pid, "arguments": args[1:], "cwd": os.readlink(proc / "cwd"),
            "executable": os.readlink(proc / "exe")}, env


def check_schema(cli):
    version = subprocess.check_output([str(cli), "--version"], text=True).strip()
    with tempfile.TemporaryDirectory(prefix="codex-routing-schema-") as folder:
        subprocess.run([str(cli), "app-server", "generate-json-schema", "--experimental", "--out", folder],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for name in ("ThreadStartParams", "ThreadResumeParams", "ThreadForkParams"):
            paths = list(Path(folder).rglob(name + ".json"))
            if not paths:
                raise RuntimeError("Missing protocol schema: " + name)
            props = json.loads(paths[0].read_text()).get("properties", {})
            if not {"model", "modelProvider"}.issubset(props):
                raise RuntimeError("Provider protocol changed: " + name)
    return version


def require_idle(alias):
    # Fail closed if the RPC isn't readable; a failed health probe doesn't mean idle.
    with Client(alias) as client:
        loaded = client.rpc("thread/loaded/list", {})
        if loaded.get("nextCursor"):
            raise RuntimeError("Unexpected paginated loaded-thread response; inspect work before switching")
        for item in loaded["data"]:
            tid = item.get("id") if isinstance(item, dict) else item
            status = client.rpc("thread/read", {"threadId": tid})["thread"].get("status", {})
            if status.get("type") != "idle":
                raise RuntimeError("A loaded thread is active or needs attention; wait before installing")


def require_routing_service(state):
    """Prove the router owns the public endpoint before proxy can autostart a fallback."""
    output = subprocess.check_output(
        ["systemctl", "--user", "show", SERVICE, "-p", "ActiveState", "-p", "MainPID"], text=True)
    properties = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    pid = int(properties.get("MainPID", "0"))
    if properties.get("ActiveState") != "active" or pid <= 0:
        raise RuntimeError("Routing service is not active; inspect its journal before reconnecting")
    alias = Path(state["alias"])
    if alias.resolve(strict=True) != Path(state["listen"]).resolve(strict=True):
        raise RuntimeError("Public socket alias no longer points at the installed routing endpoint")
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(2)
        sock.connect(str(alias))
        owner_pid, owner_uid, _ = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if owner_pid != pid or owner_uid != os.getuid():
        raise RuntimeError("Public endpoint is not owned by the routing service; a native fallback may be running")


def quote_unit(value):
    value = str(value)
    if any(c in value for c in ("\n", "\r", "\0")):
        raise ValueError("Invalid systemd argument")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"'


def render_unit(python, state):
    command = " ".join(quote_unit(x) for x in
                       (python, "-u", "-m", "codex_provider_routing.manage", "serve", "--state", state))
    return ("[Unit]\nDescription=Codex custom model provider routing\nAfter=network.target\n\n"
            "[Service]\nType=simple\nExecStart=" + command + "\n"
            "Restart=on-failure\nRestartSec=3\nTimeoutStopSec=30\nKillMode=control-group\nUMask=0077\n\n"
            "[Install]\nWantedBy=default.target\n")


def wait_exit(pid):
    proc = Path("/proc") / str(pid)
    for _ in range(200):
        try:
            if (proc / "stat").read_text().split(") ", 1)[1].startswith("Z"):
                return
        except FileNotFoundError:
            return
        time.sleep(0.1)
    raise RuntimeError("Native daemon didn't stop gracefully; inspect it before retrying")


def ready(alias):
    for _ in range(100):
        try:
            with Client(alias) as client:
                client.rpc("config/read", {"includeLayers": False})
            return
        except (OSError, EOFError, RuntimeError):
            time.sleep(0.1)
    raise RuntimeError("Daemon didn't become ready; inspect the user service journal")


def restore_native(state):
    alias = Path(state["alias"])
    try:
        with socket.socket(socket.AF_UNIX) as probe:
            probe.connect(str(alias))
    except (FileNotFoundError, ConnectionRefusedError):
        remove_socket(alias)
    else:
        raise RuntimeError("An active daemon exists; refusing to launch another")
    native = state["native"]
    executable = native["executable"]
    if not Path(executable).is_file():
        executable = state["codex"]
    environment = json.loads(Path(state["environment"]).read_text())
    with open(Path(state["root"]) / "rollback-native.log", "ab", buffering=0) as log:
        subprocess.Popen([executable, *native["arguments"]], cwd=native["cwd"], env=environment,
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    ready(alias)


def load_state(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("State must be a private, owned regular file")
    state = json.loads(path.read_text())
    if state.get("format") != 1:
        raise RuntimeError("Unknown installation format")
    return state


def install(args):
    home, root = Path(args.home).expanduser().resolve(), Path(args.root).expanduser().resolve()
    cli = Path(args.codex or shutil.which("codex") or "").expanduser().absolute()
    if not cli.is_file():
        raise RuntimeError("Specify an installed Codex CLI with --codex")
    unit = unit_path()
    if unit.exists() or root.exists():
        raise RuntimeError("Existing installation or runtime directory: inspect it instead of overwriting")
    routes = validate_routes(json.loads(Path(args.routes).read_text())["routes"])
    config_path = home / "config.toml"
    config_bytes = config_path.read_bytes()
    config = tomllib.loads(config_bytes.decode())
    if not set(routes.values()).issubset(config.get("model_providers", {})):
        raise RuntimeError("Register every mapped provider in the remote config.toml first")
    alias = home / "app-server-control/app-server-control.sock"
    canonical = canonical_socket(alias)
    version = check_schema(cli)
    native, environment = native_snapshot(alias)
    with Client(alias) as client:
        effective = client.rpc("config/read", {"includeLayers": False})["config"]
        if effective.get("model") in routes:
            raise RuntimeError("Default model is mapped; choose a distinct custom model ID to preserve defaults")
    require_idle(alias)
    print(version + ": protocol and native socket preflight passed; default config will stay unchanged.")
    if not args.apply:
        print("Plan only. Disconnect the App, then rerun with --apply to install the user service.")
        return
    # Recheck ownership immediately before mutation. Never stop a PID from a saved stale plan.
    current, _ = native_snapshot(alias)
    if current != native:
        raise RuntimeError("Daemon changed during preflight; retry after it settles")
    require_idle(alias)
    root.mkdir(parents=True, mode=0o700)
    os.chmod(root, 0o700)
    environment["CODEX_HOME"] = str(home)
    private_json(root / "native-environment.json", environment)
    private_json(root / "routes.json", {"routes": routes})
    state = {"format": 1, "home": str(home), "root": str(root), "codex": str(cli),
             "alias": str(alias), "listen": str(canonical), "ownership_lock": str(canonical) + ".lock",
             "upstream": str(home / "app-server-control/app-server-routing-native.sock"),
             "routes": str(root / "routes.json"), "environment": str(root / "native-environment.json"),
             "audit": str(root / "routing.jsonl") if args.audit else None,
             "native": native, "config_sha256": hashlib.sha256(config_bytes).hexdigest(), "version": version}
    state_path = root / "installation.json"
    private_json(state_path, state)
    unit.parent.mkdir(parents=True, exist_ok=True)
    with unit.open("x") as stream:
        stream.write(render_unit(sys.executable, state_path))
    stopped = False
    try:
        systemctl("daemon-reload")
        os.kill(native["pid"], signal.SIGTERM)
        stopped = True
        wait_exit(native["pid"])
        systemctl("start", SERVICE)
        ready(alias)
        verify_proxy(cli, home)
        if hashlib.sha256(config_path.read_bytes()).hexdigest() != state["config_sha256"]:
            raise RuntimeError("Config changed concurrently; inspect it")
        systemctl("enable", SERVICE)
    except BaseException:
        subprocess.run(["systemctl", "--user", "disable", "--now", SERVICE], check=False)
        if stopped:
            restore_native(state)
        raise
    print("Installed. Reconnect the App. Runtime files stay private under the selected runtime directory.")


def verify_proxy(cli, home, model=None, expected=None):
    with Client(transport=ProxyTransport(cli, home)) as client:
        client.rpc("config/read", {"includeLayers": False})
        if model:
            result = client.rpc("thread/start", {"model": model, "modelProvider": "openai", "ephemeral": True})
            if result.get("modelProvider") != expected:
                raise RuntimeError("Ephemeral thread didn't select the mapped provider")
    print("Actual codex app-server proxy WebSocket path passed; no inference requested.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    parser.add_argument("--root", default=str(Path.home() / ".local/share/codex-provider-routing"))
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("install", help="Read-only preflight unless --apply is given")
    setup.add_argument("--routes", required=True)
    setup.add_argument("--codex", help="Stable CLI path; keep its symlink for future upgrades")
    setup.add_argument("--apply", action="store_true")
    setup.add_argument("--audit", action="store_true", help="Log routing metadata only, no prompts or thread IDs")
    commands.add_parser("doctor", help="Read-only protocol and actual App proxy check")
    verify = commands.add_parser("verify", help="No-inference check through the actual App proxy")
    verify.add_argument("--model", help="Also create an ephemeral thread with this mapped model")
    commands.add_parser("rollback", help="Disable routing and restore the original native daemon")
    serve = commands.add_parser("serve", help=argparse.SUPPRESS)
    serve.add_argument("--state", required=True)
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("The daemon implementation supports Linux/WSL2; Windows is supported as the desktop client")
    os.umask(0o077)
    try:
        if args.command == "install":
            install(args)
            return
        state = load_state(args.state if args.command == "serve" else Path(args.root) / "installation.json")
        if args.command == "serve":
            asyncio.run(run(SimpleNamespace(**state)))
        elif args.command == "rollback":
            require_idle(state["alias"])
            systemctl("disable", "--now", SERVICE)
            restore_native(state)
            print("Native daemon restored. Unit and private runtime files retained for review; config unchanged.")
        else:
            require_routing_service(state)
            if args.command == "doctor":
                print(check_schema(state["codex"]))
            model = getattr(args, "model", None)
            routes = json.loads(Path(state["routes"]).read_text())["routes"]
            if model and model not in routes:
                raise RuntimeError("Verification model must exist in the installed routes file")
            verify_proxy(state["codex"], state["home"], model, routes.get(model))
    except (OSError, ValueError, RuntimeError, EOFError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"{type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
