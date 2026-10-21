#!/usr/bin/env python3
"""LightCraft helper: drive the live desktop app over its JSON-lines control channel, and find or run
the headless `lightcraft-cli` (`cli-info` says which release to get). `script --import/--library`
runs the same steps headless, in one `lightcraft-cli run`.

Standard library only, and no internet access: it talks to 127.0.0.1 only. (On Linux, where there is
no desktop app, install_cli.py next to it downloads lightcraft-cli from LightCraft's release page.)
Run `lc.py -h` or `lc.py <subcommand> -h` for usage.

LightCraft's control channel has no token: while a LightCraft window started with `--control` is
open, any program on this computer can drive it. `launch` starts one only for live work; `quit`
closes it.

State lives in ~/.lightcraft-skill/:
  state.json  port / pid / library of the instance this script launched
  bin/        lightcraft-cli: put there by the user on a Mac, by install_cli.py on Linux (or anywhere on PATH)
  app.log     stdout/stderr of the launched app
"""

import argparse
import json
import os
import plistlib
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home() / ".lightcraft-skill"
STATE_FILE = HOME / "state.json"
BIN_DIR = HOME / "bin"
DEFAULT_PORT = 7980  # LightCraft's documented port; `lightcraft-cli run --connect` and `mcp --connect` default to it
APP_CANDIDATES = [Path("/Applications/LightCraft.app"), Path.home() / "Applications/LightCraft.app"]
# Where a Claude sandbox puts the user's files and collects results: a chat in the Claude apps, a Managed Agents session.
SANDBOX_DIRS = {"uploads": ("/mnt/user-data/uploads", "/mnt/session/uploads"),
                "outputs": ("/mnt/user-data/outputs", "/mnt/session/outputs")}


def die(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- app discovery

def find_app():
    for p in APP_CANDIDATES:
        if p.exists():
            return p
    try:
        out = subprocess.run(["mdfind", "kMDItemCFBundleIdentifier == 'ai.storyteller.lightcraft'"],
                             capture_output=True, text=True, timeout=10).stdout.split("\n")
        for line in out:
            if line.endswith(".app"):
                return Path(line)
    except Exception:
        pass
    return None


def app_binary(app):
    return app / "Contents/MacOS/LightCraft"


def app_version(app):
    try:
        with open(app / "Contents/Info.plist", "rb") as f:
            return plistlib.load(f).get("CFBundleShortVersionString")
    except Exception:
        return None


def running_instances():
    """PIDs, command lines and control ports of running LightCraft desktop processes."""
    try:
        out = subprocess.run(["pgrep", "-fl", "LightCraft.app/Contents/MacOS/LightCraft"],
                             capture_output=True, text=True).stdout
    except FileNotFoundError:  # no pgrep: a slim Linux image, which has no desktop app either
        return []
    rows = []
    for line in out.strip().splitlines():
        pid, _, cmd = line.partition(" ")
        m = re.search(r"--control[= ](\d+)", cmd)
        rows.append({"pid": int(pid), "cmd": cmd, "control": bool(m), "port": int(m.group(1)) if m else None})
    return rows


# ---------------------------------------------------------------- control channel

def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


class Control:
    """One JSON-lines connection to `LightCraft --control <port>` (there is no token to send)."""

    def __init__(self, port=None, timeout=75.0):
        self.port = port or load_state().get("port") or DEFAULT_PORT
        self.sock = socket.create_connection(("127.0.0.1", self.port), timeout=timeout)
        self.file = self.sock.makefile("rwb")
        self.next_id = 0

    def call(self, method, params=None):
        """Return the raw reply {"id", "ok", "result"|"error"}."""
        self.next_id += 1
        self.file.write((json.dumps({"id": self.next_id, "method": method, "params": params or {}}) + "\n").encode())
        self.file.flush()
        while True:
            line = self.file.readline()
            if not line:
                raise ConnectionError("LightCraft closed the connection")
            reply = json.loads(line)
            if reply.get("id") == self.next_id:
                return reply
            if "id" not in reply and reply.get("ok") is False:  # refused before dispatch, e.g. too many connections
                return reply

    def execute(self, command, params=None):
        return self.call("engine.execute", {"command": command, "params": params or {}})

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


def probe(port, timeout=10):
    """library.info from a LightCraft answering on `port` ({} when it answers with no library open, e.g. while
    its window says the library is in use elsewhere), or None when nothing answers."""
    if not port_open(port):
        return None
    try:
        c = Control(port, timeout=timeout)
        try:
            r = c.execute("library.info")
        finally:
            c.close()
    except Exception:
        return None
    if r.get("ok") and isinstance(r.get("result"), dict):
        return r["result"]
    return {} if isinstance(r.get("error"), str) else None


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
        text = text[:max_chars] + f"... [truncated, {len(text)} chars total; use --max-chars 0]"
    print(text)
    return True


def with_control(args, fn):
    try:
        c = Control(getattr(args, "port", None))
    except OSError as e:
        die(f"cannot reach the LightCraft control channel ({e}). Is it running with --control? Try `lc.py status`.")
    try:
        return fn(c)
    finally:
        c.close()


def wait_for_import(c, deadline):
    """Wait until the app's background import (launch files, library.import) has finished."""
    while time.time() < deadline:
        r = c.call("ui.inspect")
        imp = (r.get("result") or {}).get("import") if r.get("ok") else None
        if not imp or imp.get("cancelled") or imp.get("done", 0) >= imp.get("total", 0):
            return imp
        time.sleep(0.3)
    return None


def shrink(path, max_side):
    """Scale a PNG down in place so its long side is at most max_side (macOS sips; the live app only runs there)."""
    if max_side and shutil.which("sips"):
        subprocess.run(["sips", "-Z", str(max_side), str(path)], capture_output=True)


# ---------------------------------------------------------------- subcommands

def cmd_status(args):
    app = find_app() if sys.platform == "darwin" else None
    state = load_state()
    instances = running_instances() if sys.platform == "darwin" else []
    cli = find_cli()
    info = {
        "platform": sys.platform,
        "app": str(app) if app else None,
        "appVersion": app_version(app) if app else None,
        "cli": str(cli) if cli else None,
        "instances": instances,
        "launched": state or None,
        "controlReachable": False,
    }
    sandbox = {k: next((d for d in dirs if os.path.isdir(d)), None) for k, dirs in SANDBOX_DIRS.items()}
    if any(sandbox.values()):
        info["sandbox"] = sandbox
    ports = [args.port] if args.port else []
    ports += [state.get("port")] + [i["port"] for i in instances if i["port"]] + [DEFAULT_PORT]
    for port in dict.fromkeys(p for p in ports if p):
        lib = probe(port)
        if lib is None:
            continue
        info.update(controlReachable=True, port=port,
                    library={"path": lib.get("path"), "photos": lib.get("photos"), "persistent": lib.get("persistent")})
        try:
            c = Control(port, timeout=10)
            ui = c.call("ui.inspect").get("result") or {}
            ls = c.execute("library.state").get("result") or {}
            c.close()
            info["view"] = (ui.get("ui") or {}).get("view")
            info["selection"] = ls.get("selection")
            for key in ("libraryProblem", "quitPrompt", "unsaved", "notices", "activity"):
                if ui.get(key):
                    info[key] = ui[key]
        except Exception as e:
            info["controlError"] = str(e)
        break
    print(json.dumps(info, indent=2))


def cmd_launch(args):
    if sys.platform != "darwin":
        die("lc.py launch drives the macOS app; without it, work headless (references/no-app.md)")
    files = [str(Path(f).expanduser().resolve()) for f in args.files]
    for f in files:
        if not Path(f).exists():
            die(f"{f} does not exist")
    state = load_state()
    instances = running_instances()
    # An instance this script launched, or one the user started with --control: reuse it.
    for port in dict.fromkeys(p for p in [state.get("port")] + [i["port"] for i in instances if i["port"]] if p):
        if probe(port) is None:
            continue
        out = {"alreadyRunning": True, "port": port}
        if files:
            def run(c):
                r = c.execute("library.import", {"paths": files})
                if not r.get("ok"):
                    die(f"library.import: {r.get('error')}")
                wait_for_import(c, time.time() + args.wait)
                return c.execute("library.state").get("result", {}).get("selection")
            out["selection"] = with_control(argparse.Namespace(port=port), run)
        if state.get("port") != port:
            state = {"port": port, "pid": next((i["pid"] for i in instances if i["port"] == port), None),
                     "startedBy": "user"}
            HOME.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(state, indent=2))
        print(json.dumps(out))
        return
    if any(not i["control"] for i in instances):
        die("LightCraft is open without its control channel, and it holds the library. Ask the user to quit it "
            "(LightCraft saves edits as they are made), then launch again. Never quit or kill it yourself.")
    app = Path(args.app).expanduser() if args.app else find_app()
    if not app or not app_binary(app).exists():
        die("LightCraft.app not found in /Applications or ~/Applications, or by Spotlight")
    HOME.mkdir(parents=True, exist_ok=True)
    os.chmod(HOME, 0o700)
    port = args.port
    while port_open(port):
        port += 1
    cmd = [str(app_binary(app)), "--control", str(port)]
    if args.memory:
        cmd.append("--memory")
    elif args.library:
        cmd += ["--library", str(Path(args.library).expanduser().resolve())]
    cmd += files
    log = open(HOME / "app.log", "ab")
    proc = subprocess.Popen(cmd, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + args.wait
    lib = None
    while time.time() < deadline:
        if proc.poll() is not None:
            die(f"LightCraft exited with code {proc.returncode}; see {HOME / 'app.log'}")
        lib = probe(port)
        if lib is not None:
            break
        time.sleep(0.3)
    else:
        die(f"control channel did not come up on port {port} within {args.wait}s; see {HOME / 'app.log'}")
    state = {"port": port, "pid": proc.pid, "library": lib.get("path"), "app": str(app)}
    STATE_FILE.write_text(json.dumps(state, indent=2))
    out = {"launched": True, **state}

    def settle(c):
        ui = c.call("ui.inspect").get("result") or {}
        if ui.get("libraryProblem"):
            out["libraryProblem"] = ui["libraryProblem"]
        if files:
            wait_for_import(c, deadline + 60)
            if len(files) == 1 and Path(files[0]).is_file():
                c.call("ui.set", {"view": "detail"})  # one photo: show it large, as the user will expect
        out["photos"] = (c.execute("library.info").get("result") or {}).get("photos")
        out["selection"] = (c.execute("library.state").get("result") or {}).get("selection")
    with_control(argparse.Namespace(port=port), settle)
    print(json.dumps(out))


def cmd_call(args):
    params = parse_json_arg(args.params)
    ok = with_control(args, lambda c: emit(c.call(args.method, params), args.max_chars))
    sys.exit(0 if ok else 1)


def cmd_exec(args):
    params = parse_json_arg(args.params)
    ok = with_control(args, lambda c: emit(c.execute(args.command, params), args.max_chars))
    sys.exit(0 if ok else 1)


def load_steps(file):
    """Steps from a JSON array or JSON lines. Each step is {"command", "params"} (an engine command),
    {"method", "params"} or [method, params] (a control method such as ui.set)."""
    raw = (Path(file).read_text() if file != "-" else sys.stdin.read()).strip()
    try:
        steps = json.loads(raw)  # a JSON array of steps
        if not isinstance(steps, list) or (steps and isinstance(steps[0], str)):
            steps = [steps]  # a single step on its own
    except json.JSONDecodeError:
        steps = [json.loads(l) for l in raw.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    out = []
    for step in steps:
        if isinstance(step, list):
            out.append({"method": step[0], "params": step[1] if len(step) > 1 else {}})
        elif "command" in step:
            out.append({"command": step["command"], "params": step.get("params", {})})
        else:
            out.append({"method": step["method"], "params": step.get("params", {})})
    return out


def row_text(i, label, ok, body, error, max_chars):
    row = {"step": i, "call": label, "ok": ok}
    if ok:
        text = json.dumps(body, ensure_ascii=False)
        # Long results become a truncated string so each step stays one readable line.
        row["result"] = body if not max_chars or len(text) <= max_chars else text[:max_chars] + "..."
    else:
        row["error"] = error
    return json.dumps(row, ensure_ascii=False)


def cmd_script(args):
    """Run many steps on one connection (live), or in one `lightcraft-cli run` (headless)."""
    steps = load_steps(args.file)
    if args.imports or args.library or args.demo:
        return script_headless(args, steps)

    def run(c):
        failed = 0
        for i, step in enumerate(steps):
            r = c.execute(step["command"], step["params"]) if "command" in step else c.call(step["method"], step["params"])
            print(row_text(i, step.get("command") or step["method"], r.get("ok"), r.get("result"), r.get("error"), args.max_chars))
            if not r.get("ok"):
                failed += 1
                if not args.keep_going:
                    return False
        return failed == 0

    sys.exit(0 if with_control(args, run) else 1)


def script_headless(args, steps):
    cli = find_cli()
    if not cli:
        die("lightcraft-cli not found; `lc.py cli-info` names the one to install and where it goes")
    cmd = [str(cli), "run"]
    if args.demo:
        cmd.append("--demo")
    if args.library:
        cmd += ["--library", str(Path(args.library).expanduser().resolve())]
    for p in args.imports or []:
        cmd += ["--import", str(Path(p).expanduser().resolve())]
    if args.keep_going:
        cmd.append("--keep-going")
    cmd += ["--script", "-"]
    lines = "".join(json.dumps(s) + "\n" for s in steps)
    proc = subprocess.run(cmd, input=lines, capture_output=True, text=True)
    n = 0
    for line in proc.stdout.splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            print(line)
            continue
        print(row_text(n, r.get("command") or r.get("method"), r.get("ok"), r.get("result"), r.get("error"), args.max_chars))
        n += 1
    err = [l for l in proc.stderr.splitlines() if l.strip()]
    if proc.returncode and err:
        print("\n".join(err[-5:]), file=sys.stderr)
    sys.exit(proc.returncode)


def cmd_screenshot(args):
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    def run(c):
        params = {"path": str(out)}
        if args.headless:
            params["headless"] = True
        r = c.call("ui.screenshot", params)
        if not r.get("ok"):
            return emit(r, 0)
        shrink(out, args.max)
        print(json.dumps({"path": str(out), "captured": [r["result"].get("width"), r["result"].get("height")]}))
        return True

    sys.exit(0 if with_control(args, run) else 1)


def cmd_render(args):
    """The photo alone (current edits, crop applied), written by the app; any folder works."""
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    params = {"path": str(out), "size": args.size}
    if args.id is not None:
        params["id"] = args.id
    ok = with_control(args, lambda c: emit(c.call("ui.render", params), 0))
    sys.exit(0 if ok else 1)


def cmd_quit(args):
    """Quit the controlled instance. Edits are already saved in the library; running exports and imports are
    cut short, so refuse while any task runs or a change could not be written, unless --force."""
    state = load_state()
    if state.get("startedBy") == "user" and not args.force:
        die("the user started this LightCraft themselves; leave it open (--force quits it anyway)")

    def run(c):
        if not args.force:
            ui = c.call("ui.inspect")
            if not ui.get("ok"):
                die(f"could not check for running tasks: {ui.get('error')}")
            res = ui["result"]
            busy = [a.get("label") for a in res.get("activity") or []] + [t.get("label", t) if isinstance(t, dict) else t
                                                                           for t in res.get("tasks") or []]
            if (res.get("export") or {}).get("running"):
                busy.append("export")
            if busy:
                die(f"LightCraft is busy ({busy}); wait for it, or pass --force to cut it short")
            if res.get("unsaved"):
                die(f"the library has changes not yet written to disk ({res['unsaved']}); fix that first")
        return emit(c.call("app.quit"), 0)

    ok = with_control(args, run)
    pid = state.get("pid")
    if ok and pid:
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.2)
    if ok and STATE_FILE.exists():
        STATE_FILE.unlink()
    sys.exit(0 if ok else 1)


# ---------------------------------------------------------------- headless CLI

def find_cli():
    p = BIN_DIR / "lightcraft-cli"
    if p.exists():
        return p
    w = shutil.which("lightcraft-cli")
    return Path(w) if w else None


def cmd_cli_info(args):
    """Which lightcraft-cli the user should install: the one from the same LightCraft release as their app.
    The user installs it; this only names it and where it goes, and `status` finds it afterwards."""
    if sys.platform.startswith("linux"):
        print(json.dumps({
            "installed": str(find_cli()) if find_cli() else None,
            "install": f"python3 {Path(__file__).resolve().with_name('install_cli.py')}",
            "what": "downloads LightCraft's official Linux release, checks its SHA-256, puts lightcraft-cli in "
                    + str(BIN_DIR),
        }, indent=1))
        return
    version = args.version
    if not version:
        app = find_app()
        version = app_version(app) if app else None
    print(json.dumps({
        "installed": str(find_cli()) if find_cli() else None,
        "appVersion": version,
        "file": f"lightcraft-cli-{version or '<version>'}-macos-universal.zip",
        "releasePage": f"https://github.com/storytold/lightcraft/releases/tag/v{version or '<version>'}",
        "installTo": str(BIN_DIR / "lightcraft-cli") + " (or any folder on PATH)",
    }, indent=1))


def cmd_cli(args):
    cli = find_cli()
    if not cli:
        die("lightcraft-cli not found; `lc.py cli-info` names the one to install and where it goes")
    os.execv(str(cli), [str(cli)] + args.rest)


# ---------------------------------------------------------------- main

def main():
    # `cli` forwards everything after it untouched; argparse would claim flags like --version.
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        cmd_cli(argparse.Namespace(rest=sys.argv[2:]))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, help=f"control port (default: from state.json, else {DEFAULT_PORT})")
    sub = ap.add_subparsers(dest="sub", required=True)

    sub.add_parser("status", help="app, CLI, running instances, control reachability, library").set_defaults(fn=cmd_status)

    p = sub.add_parser("launch", help="start LightCraft with the control channel on (imports the files given)")
    p.add_argument("files", nargs="*", help="photos or folders to import into the library (in place)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--library", help="open this library instead of the one LightCraft opens by itself")
    p.add_argument("--memory", action="store_true", help="a throwaway in-memory session that saves nothing")
    p.add_argument("--app", help="LightCraft.app, when it isn't in /Applications or ~/Applications")
    p.add_argument("--wait", type=float, default=40)
    p.set_defaults(fn=cmd_launch)

    for name, fn, helptext in [("call", cmd_call, "send one control method, e.g. ui.inspect"),
                               ("exec", cmd_exec, "engine.execute a command id with JSON params")]:
        p = sub.add_parser(name, help=helptext)
        p.add_argument({"call": "method", "exec": "command"}[name])
        p.add_argument("params", nargs="?", help="JSON object, @file.json, or - for stdin")
        p.add_argument("--max-chars", type=int, default=20000, help="truncate printed result (0 = never)")
        p.set_defaults(fn=fn)

    p = sub.add_parser("script", help="run many steps over one connection, or headless with --import/--library")
    p.add_argument("file", help="JSON array or JSON lines, or - for stdin")
    p.add_argument("--keep-going", action="store_true")
    p.add_argument("--max-chars", type=int, default=2000)
    p.add_argument("--import", dest="imports", action="append", help="headless: import this photo or folder first (repeatable)")
    p.add_argument("--library", help="headless: run in this persistent library (edits are saved there)")
    p.add_argument("--demo", action="store_true", help="headless: the procedural demo library")
    p.set_defaults(fn=cmd_script)

    p = sub.add_parser("screenshot", help="PNG of the app window, written by the app (any folder)")
    p.add_argument("out")
    p.add_argument("--max", type=int, default=1600, help="shrink to this long side after capture (0 = keep)")
    p.add_argument("--headless", action="store_true", help="draw the UI on the CPU (window hidden or on another space)")
    p.set_defaults(fn=cmd_screenshot)

    p = sub.add_parser("render", help="PNG of a photo with its edits (default: the active one)")
    p.add_argument("out")
    p.add_argument("--id", type=int, help="photo id (default: the active photo)")
    p.add_argument("--size", type=int, default=1600, help="long edge in pixels")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("quit", help="quit the controlled instance (refuses while it exports or imports)")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_quit)

    p = sub.add_parser("cli-info", help="which lightcraft-cli matches the installed app, and where it goes")
    p.add_argument("--version", help="release version, e.g. 0.9.1 (default: the installed app's)")
    p.set_defaults(fn=cmd_cli_info)

    p = sub.add_parser("cli", help="run lightcraft-cli with the remaining arguments")
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(fn=cmd_cli)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
