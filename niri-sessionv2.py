#!/usr/bin/env python3
import os
import sys
import json
import asyncio
import signal
import subprocess
from pathlib import Path
import shlex

NIRI_SOCKET = os.environ.get("NIRI_SOCKET")
STATE_FILE = Path.home() / ".cache/niri-session.json"
PID_FILE = Path.home() / ".cache/niri-session.pid"
TERMINALS = {"foot", "alacritty", "kitty", "ghostty", "wezterm"}

class AppResolver:
    """Parses .desktop files to map Wayland app_ids to execution commands."""
    def __init__(self):
        self.cache = {}
        self._build_cache()

    def _build_cache(self):
        paths = [Path("/usr/share/applications"), Path.home() / ".local/share/applications"]
        for p in paths:
            if not p.exists(): continue
            for desktop_file in p.rglob("*.desktop"):
                try:
                    with open(desktop_file, 'r', encoding='utf-8') as f:
                        app_id = desktop_file.stem.lower()
                        cmd = None
                        for line in f:
                            if line.startswith("Exec="):
                                # Strip %u, %f, etc.
                                cmd = line.split("=", 1)[1].split("%")[0].strip()
                            elif line.startswith("StartupWMClass="):
                                app_id = line.split("=", 1)[1].strip().lower()
                        if cmd:
                            self.cache[app_id] = cmd
                            self.cache[desktop_file.stem.lower()] = cmd # Fallback
                except Exception:
                    pass

    def get_cmd(self, app_id):
        return self.cache.get(app_id.lower(), app_id)

class NiriIPC:
    """Handles low-level async socket communication with Niri."""
    @staticmethod
    async def send_request(request_data):
        reader, writer = await asyncio.open_unix_connection(NIRI_SOCKET)
        writer.write(json.dumps(request_data).encode() + b'\n')
        await writer.drain()
        
        response = await reader.readline()
        writer.close()
        await writer.wait_closed()
        
        return json.loads(response) if response else None

    @staticmethod
    async def get_stream():
        reader, writer = await asyncio.open_unix_connection(NIRI_SOCKET)
        writer.write(b'"EventStream"\n')
        await writer.drain()
        return reader, writer

class NiriSessionManager:
    def __init__(self):
        self.resolver = AppResolver()
        self.current_windows = []

    def get_terminal_cwd(self, pid):
        """Walks the process tree to find the shell's working directory."""
        try:
            # Find child process (usually the shell running inside the terminal)
            out = subprocess.check_output(["pgrep", "-P", str(pid)]).decode().strip().split('\n')
            child_pid = out[0] if out and out[0] else pid
            return os.readlink(f"/proc/{child_pid}/cwd")
        except Exception:
            try: return os.readlink(f"/proc/{pid}/cwd")
            except: return str(Path.home())

    async def update_state(self):
        """Fetches the current window state from Niri."""
        resp = await NiriIPC.send_request("Windows")
        if resp and "Ok" in resp:
            self.current_windows = resp["Ok"]

    def save_state_and_exit(self):
        """Enriches the current state with CWDs and saves to disk."""
        print("Received save signal. Capturing session...")
        asyncio.create_task(self._async_save_and_exit())

    async def _async_save_and_exit(self):
        await self.update_state()
        state_to_save = []
        
        for win in self.current_windows:
            app_id = win.get("app_id", "")
            if not app_id: continue
            
            entry = {
                "app_id": app_id,
                "workspace_id": win.get("workspace_id"),
                "is_active": win.get("is_active", False)
            }
            
            if app_id.lower() in TERMINALS:
                entry["cwd"] = self.get_terminal_cwd(win.get("pid"))
                
            state_to_save.append(entry)

        with open(STATE_FILE, 'w') as f:
            json.dump(state_to_save, f, indent=2)
        
        print(f"Session saved to {STATE_FILE}. Exiting.")
        if PID_FILE.exists(): PID_FILE.unlink()
        sys.exit(0)

    async def daemon_mode(self):
        """Zero-polling event loop. Only tracks state internally."""
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))

        # Register SIGUSR1 to trigger the save and exit
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGUSR1, self.save_state_and_exit)
        loop.add_signal_handler(signal.SIGTERM, lambda: sys.exit(0))
        loop.add_signal_handler(signal.SIGINT, lambda: sys.exit(0))

        print("NSM Daemon listening on Niri IPC...")
        reader, _ = await NiriIPC.get_stream()
        
        while True:
            line = await reader.readline()
            if not line: break
            # We don't need to parse every event, just knowing Niri is alive is enough.
            # State is strictly fetched on-demand when SIGUSR1 is received to save CPU.

    async def restore_session(self):
        """Sequenced restoration ensuring spatial integrity."""
        if not STATE_FILE.exists():
            print("No session state found.")
            return

        with open(STATE_FILE, 'r') as f:
            saved_windows = json.load(f)

        stream_reader, _ = await NiriIPC.get_stream()
        print(f"Restoring {len(saved_windows)} windows...")

        for win in saved_windows:
            app_id = win["app_id"]
            cmd = self.resolver.get_cmd(app_id)
            
            if app_id.lower() in TERMINALS and "cwd" in win:
                # Handle terminal specific CWD flags
                if app_id.lower() == "foot":
                    cmd = f"foot -D {shlex.quote(win['cwd'])}"
                else:
                    cmd = f"{cmd} --working-directory {shlex.quote(win['cwd'])}"

            print(f"Launching: {cmd}")
            subprocess.Popen(shlex.split(cmd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # Await the exact WindowOpened event
            try:
                async with asyncio.timeout(5.0): # Use timeout to avoid hanging on failed launches
                    while True:
                        line = await stream_reader.readline()
                        event = json.loads(line)
                        if "WindowOpened" in event:
                            new_win = event["WindowOpened"]["window"]
                            if new_win.get("app_id") == app_id:
                                # Matched! Move it to the correct workspace
                                await NiriIPC.send_request({
                                    "Action": {
                                        "MoveWindowToWorkspace": {
                                            "window_id": new_win["id"],
                                            "reference": {"Id": win["workspace_id"]}
                                        }
                                    }
                                })
                                break
            except TimeoutError:
                print(f"Timeout waiting for {app_id} to map. Moving to next.")

async def main():
    if not NIRI_SOCKET:
        print("Error: NIRI_SOCKET environment variable not set.")
        sys.exit(1)

    manager = NiriSessionManager()

    if "--daemon" in sys.argv:
        await manager.daemon_mode()
    elif "--save" in sys.argv:
        if PID_FILE.exists():
            # Send POSIX signal to daemon to save and exit gracefully
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGUSR1)
        else:
            print("Daemon not running. Start it with --daemon first.")
    elif "--restore" in sys.argv:
        await manager.restore_session()
    else:
        print("Usage: niri-session.py [--daemon | --save | --restore]")

if __name__ == "__main__":
    asyncio.run(main())