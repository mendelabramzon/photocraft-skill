#!/usr/bin/env python3
"""PhotoCraft helper: drive the live desktop app over its JSON control channel,
and find the headless `photocraft-cli` (`cli-info` says which release to get).

Standard library only, and no internet access: it talks to 127.0.0.1 only.
Run `pc.py -h` or `pc.py <subcommand> -h` for usage.

State lives in ~/.photocraft-skill/ (override with PHOTOCRAFT_SKILL_HOME):
  token       control-channel bearer token (mode 0600, created by the app at `launch`)
  state.json  port / pid / automation roots of the instance this script launched
  bin/        where the user puts photocraft-cli (or anywhere on PATH)
  app.log     stdout/stderr of the launched app
"""

import argparse
import base64
import json
import os
import plistlib
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get("PHOTOCRAFT_SKILL_HOME", Path.home() / ".photocraft-skill"))
TOKEN_FILE = HOME / "token"
STATE_FILE = HOME / "state.json"
BIN_DIR = HOME / "bin"
DEFAULT_PORT = 7878
REPO = "storytold/photocraft"
APP_CANDIDATES = [Path("/Applications/PhotoCraft.app"), Path.home() / "Applications/PhotoCraft.app"]


def die(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- app discovery

def find_app():
    env = os.environ.get("PHOTOCRAFT_APP")
    if env:
        return Path(env)
    for p in APP_CANDIDATES:
        if p.exists():
            return p
    try:
        out = subprocess.run(["mdfind", "kMDItemCFBundleIdentifier == 'ai.storyteller.photocraft'"],
                             capture_output=True, text=True, timeout=10).stdout.split("\n")
        for line in out:
            if line.endswith(".app"):
                return Path(line)
    except Exception:
        pass
    return None


def app_binary(app):
    return app / "Contents/MacOS/PhotoCraft"


def app_version(app):
    try:
        with open(app / "Contents/Info.plist", "rb") as f:
            return plistlib.load(f).get("CFBundleShortVersionString")
    except Exception:
        return None


def running_instances():
    """PIDs and command lines of running PhotoCraft desktop processes."""
    out = subprocess.run(["pgrep", "-fl", "PhotoCraft.app/Contents/MacOS/PhotoCraft"],
                         capture_output=True, text=True).stdout
    rows = []
    for line in out.strip().splitlines():
        pid, _, cmd = line.partition(" ")
        rows.append({"pid": int(pid), "cmd": cmd, "control": "--control" in cmd})
    return rows


# ---------------------------------------------------------------- control channel

def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def read_token():
    """The token the app wrote when `pc.py launch` started it; never a credential from the environment."""
    try:
        return TOKEN_FILE.read_text().strip()
    except FileNotFoundError:
        die(f"no control token at {TOKEN_FILE}; start the app with `pc.py launch` first")


class Control:
    """One authenticated JSON-lines connection to `PhotoCraft --control <port>`."""

    def __init__(self, port=None, timeout=65.0):
        self.port = port or int(os.environ.get("PHOTOCRAFT_CONTROL_PORT", 0)) or load_state().get("port") or DEFAULT_PORT
        self.sock = socket.create_connection(("127.0.0.1", self.port), timeout=timeout)
        self.file = self.sock.makefile("rwb")
        self.next_id = 0
        reply = self._roundtrip({"id": "auth", "method": "auth", "params": {"token": read_token()}})
        if not reply.get("ok"):
            raise RuntimeError(f"auth failed: {reply.get('error')}")

    def _roundtrip(self, req):
        self.file.write((json.dumps(req) + "\n").encode())
        self.file.flush()
        while True:
            line = self.file.readline()
            if not line:
                raise ConnectionError("PhotoCraft closed the connection")
            reply = json.loads(line)
            if reply.get("id") == req["id"]:
                return reply

    def call(self, method, params=None):
        """Return the raw reply {"id", "ok", "result"|"error"}."""
        self.next_id += 1
        return self._roundtrip({"id": self.next_id, "method": method, "params": params or {}})

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def port_open(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
        return True
    except OSError:
        return False


def parse_json_arg(text, what="params"):
    if text is None:
        return {}
    if text == "-":
        text = sys.stdin.read()
    elif text.startswith("@"):
        text = Path(text[1:]).read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        die(f"{what} is not valid JSON ({e}): {text[:200]}")


def emit(reply, max_chars):
    if not reply.get("ok"):
        print(json.dumps({"ok": False, "error": reply.get("error")}), file=sys.stderr)
        return False
    text = json.dumps(reply.get("result"), ensure_ascii=False)
    if max_chars and len(text) > max_chars:
        text = text[:max_chars] + f"... [truncated, {len(text)} chars total; use --max-chars 0 or --out]"
    print(text)
    return True


def with_control(args, fn):
    try:
        c = Control(getattr(args, "port", None))
    except (ConnectionRefusedError, socket.timeout, OSError) as e:
        die(f"cannot reach the PhotoCraft control channel ({e}). Is it running with --control? Try `pc.py status`.")
    try:
        return fn(c)
    finally:
        c.close()


# ---------------------------------------------------------------- subcommands

def cmd_status(args):
    app = find_app()
    state = load_state()
    info = {
        "app": str(app) if app else None,
        "appVersion": app_version(app) if app else None,
        "cli": str(find_cli()) if find_cli() else None,
        "instances": running_instances(),
        "launched": state or None,
        "controlReachable": False,
    }
    port = state.get("port") or DEFAULT_PORT
    if port_open(port) and TOKEN_FILE.exists():
        try:
            c = Control(port, timeout=10)
            r = c.call("ui.inspect")
            c.close()
            if r.get("ok"):
                res = r["result"]
                info["controlReachable"] = True
                info["port"] = port
                info["tool"] = res.get("tool")
                info["dialogs"] = [d.get("kind") for d in res.get("dialogs", [])]
        except Exception as e:
            info["controlError"] = str(e)
    print(json.dumps(info, indent=2))


def cmd_launch(args):
    app = find_app()
    if not app:
        die("PhotoCraft.app not found (set PHOTOCRAFT_APP=/path/to/PhotoCraft.app)")
    state = load_state()
    if state.get("port") and port_open(state["port"]):
        try:
            Control(state["port"], timeout=10).close()
            print(json.dumps({"alreadyRunning": True, **state}))
            return
        except Exception:
            pass
    HOME.mkdir(parents=True, exist_ok=True)
    os.chmod(HOME, 0o700)
    port = args.port
    while port_open(port):
        port += 1
    read_root = str(Path(args.read_root or Path.home()).expanduser().resolve())
    write_root = str(Path(args.write_root or Path.home()).expanduser().resolve())
    cmd = [str(app_binary(app)), "--control", str(port), "--control-token-file", str(TOKEN_FILE),
           "--automation-read-root", read_root, "--automation-write-root", write_root]
    cmd += [str(Path(f).expanduser().resolve()) for f in args.files]
    log = open(HOME / "app.log", "ab")
    proc = subprocess.Popen(cmd, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + args.wait
    while time.time() < deadline:
        if proc.poll() is not None:
            die(f"PhotoCraft exited with code {proc.returncode}; see {HOME / 'app.log'}")
        if port_open(port) and TOKEN_FILE.exists():
            try:
                Control(port, timeout=10).close()
                break
            except Exception:
                pass
        time.sleep(0.3)
    else:
        die(f"control channel did not come up on port {port} within {args.wait}s; see {HOME / 'app.log'}")
    state = {"port": port, "pid": proc.pid, "readRoot": read_root, "writeRoot": write_root, "app": str(app)}
    STATE_FILE.write_text(json.dumps(state, indent=2))
    print(json.dumps({"launched": True, **state}))


def cmd_call(args):
    params = parse_json_arg(args.params)
    ok = with_control(args, lambda c: emit(c.call(args.method, params), args.max_chars))
    sys.exit(0 if ok else 1)


def cmd_exec(args):
    params = parse_json_arg(args.params)
    req = {"command": args.command, "params": params}
    if args.no_wait:
        req["wait"] = False
    ok = with_control(args, lambda c: emit(c.call("engine.execute", req), args.max_chars))
    sys.exit(0 if ok else 1)


def cmd_menu(args):
    req = {"id": args.id}
    if args.params is not None:
        req["params"] = parse_json_arg(args.params)
    ok = with_control(args, lambda c: emit(c.call("ui.menu.invoke", req), args.max_chars))
    sys.exit(0 if ok else 1)


def cmd_script(args):
    """Run many requests on one connection. Input: a JSON array, or JSON lines. Each step is
    [method, params], {"method", "params"}, or {"command", "params"} (= engine.execute)."""
    raw = Path(args.file).read_text() if args.file != "-" else sys.stdin.read()
    raw = raw.strip()
    try:
        steps = json.loads(raw)  # a JSON array of steps
        if not isinstance(steps, list) or (steps and isinstance(steps[0], str)):
            steps = [steps]  # a single step on its own
    except json.JSONDecodeError:
        steps = [json.loads(l) for l in raw.splitlines() if l.strip()]  # JSON lines

    def norm(step):
        if isinstance(step, list):
            return step[0], (step[1] if len(step) > 1 else {})
        if "command" in step:
            p = {"command": step["command"], "params": step.get("params", {})}
            if "wait" in step:
                p["wait"] = step["wait"]
            return "engine.execute", p
        return step["method"], step.get("params", {})

    def run(c):
        failed = 0
        for i, step in enumerate(steps):
            method, params = norm(step)
            r = c.call(method, params)
            label = params.get("command", method) if method == "engine.execute" else method
            row = {"step": i, "call": label, "ok": r.get("ok")}
            if r.get("ok"):
                body = r.get("result")
                text = json.dumps(body, ensure_ascii=False)
                # Long results become a truncated string so each step stays one readable line.
                row["result"] = body if not args.max_chars or len(text) <= args.max_chars else text[:args.max_chars] + "..."
            else:
                row["error"] = r.get("error")
            print(json.dumps(row, ensure_ascii=False))
            if not r.get("ok"):
                failed += 1
                if not args.keep_going:
                    return False
        return failed == 0

    sys.exit(0 if with_control(args, run) else 1)


def cmd_screenshot(args):
    def run(c):
        params = {}
        if args.no_focus:
            params["focus"] = False
        r = c.call("ui.screenshot", params)
        if not r.get("ok"):
            return emit(r, 0)
        res = r["result"]
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(base64.b64decode(res["base64"]))
        print(json.dumps({"path": str(out.resolve()), "width": res.get("width"), "height": res.get("height")}))
        return True

    sys.exit(0 if with_control(args, run) else 1)


def cmd_export(args):
    """Export the active document (flattened copy) to a file, for looking at the result.
    The document keeps its own name, path and dirty state. The path must be under the write root."""
    out = Path(args.out).expanduser().resolve()
    state = load_state()
    root = state.get("writeRoot")
    if root and not str(out).startswith(root.rstrip("/") + "/"):
        die(f"{out} is outside the automation write root {root}; relaunch with --write-root or pick another path")
    out.parent.mkdir(parents=True, exist_ok=True)
    ok = with_control(args, lambda c: emit(c.call("app.save", {"path": str(out)}), 0))
    sys.exit(0 if ok else 1)


def cmd_quit(args):
    """app.quit closes WITHOUT the unsaved-changes prompt, so check for dirty documents first."""
    def run(c):
        if not args.force:
            insp = c.call("ui.inspect")
            if not insp.get("ok"):
                die(f"could not check for unsaved documents: {insp.get('error')}")
            docs = (insp["result"].get("session") or {}).get("documents") or []
            dirty = [d.get("name") for d in docs if d.get("dirty")]
            if dirty:
                die(f"unsaved documents {dirty}; save them, or pass --force to discard")
        return emit(c.call("app.quit"), 0)

    ok = with_control(args, run)
    if ok and STATE_FILE.exists():
        STATE_FILE.unlink()
    sys.exit(0 if ok else 1)


# ---------------------------------------------------------------- headless CLI

def find_cli():
    env = os.environ.get("PHOTOCRAFT_CLI")
    if env and Path(env).exists():
        return Path(env)
    p = BIN_DIR / "photocraft-cli"
    if p.exists():
        return p
    w = shutil.which("photocraft-cli")
    return Path(w) if w else None


def cmd_cli_info(args):
    """Which photocraft-cli to get: the release matching the installed app. Downloads nothing; the user
    installs the binary themselves, then `status` finds it."""
    version = args.version
    if not version:
        app = find_app()
        version = app_version(app) if app else None
    page = f"https://github.com/{REPO}/releases/" + (f"tag/v{version}" if version else "latest")
    print(json.dumps({
        "installed": str(find_cli()) if find_cli() else None,
        "appVersion": version,
        "releasePage": page,
        "file": f"photocraft-cli-{version}-macos-universal.zip" if version else "photocraft-cli-<version>-macos-universal.zip",
        "checksums": "SHA256SUMS.txt on the same release page",
        "installTo": str(BIN_DIR / "photocraft-cli") + " (or any folder on PATH)",
    }, indent=1))


def cmd_cli(args):
    cli = find_cli()
    if not cli:
        die("photocraft-cli not found; `pc.py cli-info` says which file to download and where it goes")
    os.execv(str(cli), [str(cli)] + args.rest)


# ---------------------------------------------------------------- main

def main():
    # `cli` forwards everything after it untouched; argparse would claim flags like --version.
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        cmd_cli(argparse.Namespace(rest=sys.argv[2:]))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, help="control port (default: from state.json, else 7878)")
    sub = ap.add_subparsers(dest="sub", required=True)

    sub.add_parser("status", help="app path/version, CLI, running instances, control reachability").set_defaults(fn=cmd_status)

    p = sub.add_parser("launch", help="start PhotoCraft with the control channel enabled")
    p.add_argument("files", nargs="*", help="files to open at launch")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--read-root", help="automation read root (default: home folder)")
    p.add_argument("--write-root", help="automation write root (default: home folder)")
    p.add_argument("--wait", type=float, default=40)
    p.set_defaults(fn=cmd_launch)

    for name, fn, helptext in [("call", cmd_call, "send one control method, e.g. ui.inspect"),
                               ("exec", cmd_exec, "engine.execute a command id with JSON params"),
                               ("menu", cmd_menu, "ui.menu.invoke a menu id (opens its dialog when no params)")]:
        p = sub.add_parser(name, help=helptext)
        p.add_argument({"call": "method", "exec": "command", "menu": "id"}[name])
        p.add_argument("params", nargs="?", help="JSON object, @file.json, or - for stdin")
        p.add_argument("--max-chars", type=int, default=20000, help="truncate printed result (0 = never)")
        if name == "exec":
            p.add_argument("--no-wait", action="store_true", help="start a long command as a background job")
        p.set_defaults(fn=fn)

    p = sub.add_parser("script", help="run many steps over one connection (JSON array or JSON lines)")
    p.add_argument("file", help="path or - for stdin")
    p.add_argument("--keep-going", action="store_true")
    p.add_argument("--max-chars", type=int, default=2000)
    p.set_defaults(fn=cmd_script)

    p = sub.add_parser("screenshot", help="save a PNG of the app window to any path")
    p.add_argument("out")
    p.add_argument("--no-focus", action="store_true", help="don't raise the window first")
    p.set_defaults(fn=cmd_screenshot)

    p = sub.add_parser("export", help="export a flattened copy of the active document (under the write root)")
    p.add_argument("out")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("quit", help="quit the controlled instance (refuses if documents are unsaved)")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_quit)

    p = sub.add_parser("cli-info", help="which photocraft-cli release to download for the installed app, and where it goes")
    p.add_argument("--version", help="release version, e.g. 0.10.0 (default: the installed app's)")
    p.set_defaults(fn=cmd_cli_info)

    p = sub.add_parser("cli", help="run photocraft-cli with the remaining arguments")
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(fn=cmd_cli)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
