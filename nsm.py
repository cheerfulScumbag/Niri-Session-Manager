#!/usr/bin/env python3
import argparse
import asyncio
import json
import logging
import os
import shlex
import signal
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# --- Configuration ---
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("nsm")

NIRI_SOCKET = os.environ.get("NIRI_SOCKET")
DAEMON_SOCKET = Path("/tmp/nsm_daemon.sock")
STATE_FILE = Path.home() / ".cache/niri-session.json"
TERMINALS = {"foot", "alacritty", "kitty", "ghostty", "wezterm", "rio"}

# --- Utilities ---

class AppResolver:
    """Resolves Niri app_ids to executable commands using desktop files."""
    def __init__(self):
        self.cache = {}
        self._build_cache()

    def _build_cache(self):
        xdg_data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
        paths = [Path(d) / "applications" for d in xdg_data_dirs]
        paths.append(Path.home() / ".local/share/applications")
        
        for p in paths:
            if not p.exists():
                continue
            for desktop_file in p.rglob("*.desktop"):
                try:
                    with open(desktop_file, 'r', encoding='utf-8', errors='ignore') as f:
                        app_id_stem = desktop_file.stem.lower()
                        cmd = None
                        wm_class = None
                        for line in f:
                            if line.startswith("Exec="):
                                # Strip %u, %f, etc.
                                cmd = line.split("=", 1)[1].split("%")[0].strip()
                            elif line.startswith("StartupWMClass="):
                                wm_class = line.split("=", 1)[1].strip().lower()
                        
                        if cmd:
                            # Map both stem and WMClass to the command
                            self.cache[app_id_stem] = cmd
                            if wm_class:
                                self.cache[wm_class] = cmd
                except Exception as e:
                    logger.debug(f"Failed to parse {desktop_file}: {e}")

    def resolve(self, app_id):
        if not app_id:
            return None
        return self.cache.get(app_id.lower(), app_id)

def get_terminal_cwd(pid):
    """Walks the process tree to find the shell's working directory."""
    try:
        # Find child process (usually the shell running inside the terminal)
        # We try to get the CWD of the first child process
        children = subprocess.check_output(["pgrep", "-P", str(pid)]).decode().strip().split('\n')
        child_pid = children[0] if children and children[0] else pid
        return os.readlink(f"/proc/{child_pid}/cwd")
    except Exception:
        try:
            return os.readlink(f"/proc/{pid}/cwd")
        except Exception:
            return str(Path.home())

# --- Niri IPC ---

class NiriIPC:
    """Async communication with Niri SOC."""
    def __init__(self):
        # We allow NIRI_SOCKET to be None at init, as the daemon wait loop will set it in os.environ
        pass

    async def get_windows(self):
        try:
            output = subprocess.check_output(["niri", "msg", "-j", "windows"])
            resp = json.loads(output.decode().strip())
            
            if isinstance(resp, list): return resp
            if isinstance(resp, dict) and "Windows" in resp: return resp["Windows"]
            if isinstance(resp, dict) and "Ok" in resp: return resp["Ok"]
        except Exception as e:
            logger.error(f"Error getting niri windows: {e}")
        return []
        
    async def get_workspaces(self):
        try:
            output = subprocess.check_output(["niri", "msg", "-j", "workspaces"])
            resp = json.loads(output.decode().strip())
            
            if isinstance(resp, list): return resp
            if isinstance(resp, dict) and "Workspaces" in resp: return resp["Workspaces"]
            if isinstance(resp, dict) and "Ok" in resp: return resp["Ok"]
        except Exception as e:
            logger.error(f"Error getting niri workspaces: {e}")
        return []

    async def listen_events(self):
        """Returns a reader for the event stream."""
        # Ensure NIRI_SOCKET is fresh from environment (important for systemd)
        socket_path = os.environ.get("NIRI_SOCKET")
        if not socket_path:
            raise EnvironmentError("NIRI_SOCKET not set")
        reader, writer = await asyncio.open_unix_connection(socket_path)
        writer.write(b'"EventStream"\n')
        await writer.drain()
        return reader, writer

# --- Session Management ---

class SessionManager:
    def __init__(self):
        self.ipc = NiriIPC()
        self.resolver = AppResolver()
        self.windows = [] # Last known state

    async def capture_state(self):
        logger.info("Capturing current session state...")
        wins = await self.ipc.get_windows()
        workspaces = await self.ipc.get_workspaces()
        
        # Map workspace_id to (output, idx)
        ws_map = {}
        window_list = wins if isinstance(wins, list) else [wins]
        workspace_list = workspaces if isinstance(workspaces, list) else [workspaces]
        
        for ws in workspace_list:
            if not isinstance(ws, dict): continue
            ws_map[ws.get("id")] = (ws.get("output"), ws.get("idx"))

        state = []
        
        for w in window_list:
            if not isinstance(w, dict): continue
            
            app_id = w.get("app_id", "")
            if not app_id: continue
            
            outp, idx = ws_map.get(w.get("workspace_id"), (None, None))
            
            entry = {
                "app_id": app_id,
                "output": outp,
                "idx": idx,
                "is_active": w.get("is_active", False)
            }
            
            if app_id.lower() in TERMINALS:
                entry["cwd"] = get_terminal_cwd(w.get("pid"))
            
            state.append(entry)
        
        # Create .cache dir if it doesn't exist
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
        logger.info(f"Saved {len(state)} windows to {STATE_FILE}")
        return len(state)

    async def restore_session(self):
        if not STATE_FILE.exists():
            logger.warning("No state file found to restore.")
            return

        with open(STATE_FILE, 'r') as f:
            saved_state = json.load(f)

        logger.info(f"Restoring {len(saved_state)} windows...")
        
        # We need the event stream to sequence restoration
        reader, writer = await self.ipc.listen_events()
        
        expected_windows = defaultdict(list)
        for win in saved_state:
            expected_windows[win["app_id"]].append(win)
            
        try:
            # Launch apps concurrently
            for win in saved_state:
                app_id = win["app_id"]
                cmd = self.resolver.resolve(app_id)
                cwd = win.get("cwd", str(Path.home()))
                
                if app_id.lower() in TERMINALS and "cwd" in win:
                    if app_id.lower() == "foot":
                        actual_cmd = f"foot -D {shlex.quote(cwd)}"
                    else:
                        actual_cmd = f"{cmd} --working-directory {shlex.quote(cwd)}"
                else:
                    actual_cmd = cmd

                logger.info(f"Launching {app_id}: {actual_cmd}")
                
                try:
                    subprocess.Popen(
                        shlex.split(actual_cmd),
                        cwd=cwd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True
                    )
                except Exception as e:
                    logger.error(f"Failed to launch {actual_cmd}: {e}")

            # Wait for windows to map and move them
            mapped = 0
            total_expected = len(saved_state)
            
            async with asyncio.timeout(10.0):
                while mapped < total_expected:
                    line = await reader.readline()
                    if not line: break
                    event = json.loads(line)
                    if "WindowOpened" in event:
                        new_win = event["WindowOpened"]["window"]
                        opened_app_id = new_win.get("app_id")
                        
                        if opened_app_id and expected_windows.get(opened_app_id):
                            win_state = expected_windows[opened_app_id].pop(0)
                            outp = win_state.get("output")
                            idx = win_state.get("idx")
                            win_id = new_win["id"]
                            
                            logger.info(f"Window mapped: {opened_app_id} (ID: {win_id}) -> output {outp}, idx {idx}")
                            
                            if outp:
                                proc = await asyncio.create_subprocess_exec("niri", "msg", "action", "move-window-to-monitor", "--id", str(win_id), str(outp))
                                await proc.wait()
                            if idx is not None:
                                proc = await asyncio.create_subprocess_exec("niri", "msg", "action", "move-window-to-workspace", "--window-id", str(win_id), str(idx))
                                await proc.wait()
                                
                            mapped += 1
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for windows to map. Mapped {mapped}/{total_expected}.")
        finally:
            writer.close()
            await writer.wait_closed()

# --- IPC Daemon ---

async def run_daemon():
    # Wait for NIRI_SOCKET to be available (useful when starting with the session)
    max_retries = 30
    retry_delay = 1
    
    for i in range(max_retries):
        # We need to refresh the environment variable in case niri propagates it
        output = ""
        try:
            # Check for the niri socket
            if "NIRI_SOCKET" not in os.environ:
                sock = subprocess.check_output(["niri", "msg", "socket-path"]).decode().strip()
                if sock:
                    os.environ["NIRI_SOCKET"] = sock
        except Exception:
            pass
            
        if os.environ.get("NIRI_SOCKET"):
            logger.info("NIRI_SOCKET found. Starting daemon...")
            break
        if i % 5 == 0:
            logger.info(f"Waiting for NIRI_SOCKET... (attempt {i+1}/{max_retries})")
        await asyncio.sleep(retry_delay)
    else:
        logger.error("NIRI_SOCKET not found after waiting. Exiting.")
        sys.exit(1)

    manager = SessionManager()
    
    # Auto-restore on startup if nearly empty
    try:
        current_wins = await manager.ipc.get_windows()
        if isinstance(current_wins, list) and len(current_wins) <= 1:
            logger.info("Fresh session/startup detected. Triggering auto-restore...")
            asyncio.create_task(manager.restore_session())
    except Exception as e:
        logger.warning(f"Failed to check windows for auto-restore: {e}")
    
    if DAEMON_SOCKET.exists():
        DAEMON_SOCKET.unlink()

    async def handle_client(reader, writer):
        data = await reader.read(1024)
        command = data.decode().strip()
        
        if command == "save":
            count = await manager.capture_state()
            writer.write(f"Saved {count} windows.\n".encode())
        elif command == "restore":
            asyncio.create_task(manager.restore_session())
            writer.write(b"Restoration started.\n")
        else:
            writer.write(b"Unknown command.\n")
            
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_unix_server(handle_client, path=str(DAEMON_SOCKET))
    logger.info(f"NSM Daemon started at {DAEMON_SOCKET}")
    
    # Handle termination
    loop = asyncio.get_running_loop()
    stop = asyncio.Future()
    
    def shutdown():
        logger.info("Shutting down daemon...")
        if DAEMON_SOCKET.exists():
            DAEMON_SOCKET.unlink()
        if not stop.done():
            stop.set_result(None)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown)

    async with server:
        await stop
        # Perform auto-save before exit
        try:
            logger.info("Auto-saving session before exit...")
            await manager.capture_state()
        except Exception as e:
            logger.error(f"Failed to auto-save: {e}")

        server.close()
        await server.wait_closed()

async def send_command(command):
    if not DAEMON_SOCKET.exists():
        print("NSM Daemon is not running.")
        return

    try:
        reader, writer = await asyncio.open_unix_connection(str(DAEMON_SOCKET))
        writer.write(command.encode())
        await writer.drain()
        
        response = await reader.read(1024)
        print(response.decode().strip())
        
        writer.close()
        await writer.wait_closed()
    except Exception as e:
        print(f"Error connecting to daemon: {e}")

# --- CLI ---

def main():
    parser = argparse.ArgumentParser(description="Niri Session Manager")
    parser.add_argument("--daemon", action="store_true", help="Start the session tracking daemon")
    parser.add_argument("--save", action="store_true", help="Save current session")
    parser.add_argument("--restore", action="store_true", help="Restore last saved session")
    
    args = parser.parse_args()
    
    if args.daemon:
        asyncio.run(run_daemon())
    elif args.save:
        asyncio.run(send_command("save"))
    elif args.restore:
        asyncio.run(send_command("restore"))
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
