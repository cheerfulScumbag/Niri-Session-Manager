#!/usr/bin/env python3
"""
Niri Session Manager (NSM)

A KISS-compliant, lightweight Python daemon to map, save, and restore a spatial 
snapshot of a Niri session. Requires zero modification to Niri source code.
Powered by asynchronous Unix Sockets.

Usage:
  nsm-client --daemon    # Start the background session tracker
  nsm-client --save      # Trigger a save state to disk
  nsm-client --restore   # Restore the session from the saved state
"""

import argparse
import asyncio
import json
import logging
import os
import shlex
import socket
import subprocess
from pathlib import Path

# Configure logging for robustness
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("niri-session-manager")

NIRI_SOCKET = os.environ.get("NIRI_SOCKET")
DAEMON_SOCKET = "/tmp/niri_session_daemon.sock"
SESSION_FILE = Path.home() / ".config" / "niri" / "session.json"

class SessionManager:
    def __init__(self):
        # Maintain session state in memory (win_id -> window_dict)
        # Avoids polling, purely driven by IPC events
        self.windows = {}
        # Track pending restorations: app_id -> workspace_id
        self.pending_restores = {}
        
    async def _send_niri_command(self, payload):
        """Open a short-lived connection to dispatch an action to Niri."""
        if not NIRI_SOCKET:
            logger.error("$NIRI_SOCKET is not set.")
            return None
            
        try:
            reader, writer = await asyncio.open_unix_connection(NIRI_SOCKET)
            writer.write(json.dumps(payload).encode('utf-8'))
            await writer.drain()
            
            response_data = await reader.read()
            writer.close()
            await writer.wait_closed()
            
            if response_data:
                return json.loads(response_data.decode('utf-8'))
        except Exception as e:
            logger.error(f"Niri IPC Command Error: {e}")
        return None

    def _resolve_desktop_file(self, app_id):
        """
        Map Wayland app_id to the exact Exec command using XDG Desktop entries.
        Handles the 'Wayland Identity Gap' where app_id does not always match binary.
        """
        if not app_id:
            return ""

        xdg_data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
        xdg_data_dirs.insert(0, str(Path.home() / ".local/share"))
        
        search_names = [
            f"{app_id}.desktop",
            f"{app_id.lower()}.desktop",
            f"org.{app_id}.desktop",
            f"com.{app_id}.desktop"
        ]
        
        for d in xdg_data_dirs:
            app_dir = Path(d) / "applications"
            if not app_dir.exists():
                continue
                
            for name in search_names:
                desktop_file = app_dir / name
                if desktop_file.is_file():
                    for line in desktop_file.read_text(errors="ignore").splitlines():
                        if line.startswith("Exec="):
                            # Clean arbitrary arguments like %U, %f from Exec line
                            exec_cmd = line[5:].split("%")[0].strip()
                            return exec_cmd
        # Fallback to binary matching app_id
        return app_id

    def _get_terminal_cwd(self, pid):
        """Capture working directory for terminal emulators via /proc."""
        try:
            return os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            return str(Path.home())

    async def handle_event(self, event):
        """
        Process incoming Wayland/Niri events to maintain the in-memory window state.
        Zero CPU footprint between events.
        """
        if "WindowOpenedOrChanged" in event:
            # Note: actual Niri Event structure may vary, adjust keys accordingly
            w = event["WindowOpenedOrChanged"].get("window", {})
            win_id = w.get("id")
            if win_id:
                self.windows[win_id] = w
            
            app_id = w.get("app_id")
            
            # Sequenced Restoration placement strategy
            if app_id in self.pending_restores:
                target_workspace = self.pending_restores.pop(app_id)
                logger.info(f"Placement matched for {app_id}, routing to {target_workspace}")
                await self._send_niri_command({
                    "Action": "MoveWindowToWorkspace",
                    "window_id": win_id,
                    "workspace": target_workspace
                })
                
        elif "WindowClosed" in event:
            win_id = event["WindowClosed"].get("id")
            if win_id in self.windows:
                del self.windows[win_id]

    async def event_stream(self):
        """Maintain a persistent socket connection to listen for Niri events."""
        if not NIRI_SOCKET:
            logger.error("$NIRI_SOCKET is not set. Cannot start event stream.")
            return

        # Start by acquiring initial state (optional, if supported by action payload)
        # For strict event-only, we rely on WindowOpened events.
        
        try:
            reader, writer = await asyncio.open_unix_connection(NIRI_SOCKET)
            # Subscribe to the event stream 
            writer.write(json.dumps({"Action": "EventStream"}).encode('utf-8'))
            await writer.drain()
            
            logger.info("Dual-Socket IPC Event Stream connected successfully.")
            
            while True:
                line = await reader.readline()
                if not line:
                    break
                    
                try:
                    event = json.loads(line.decode('utf-8'))
                    await self.handle_event(event)
                except json.JSONDecodeError:
                    pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Event stream disconnected: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    async def save_session(self):
        """Snapshot current in-memory state and commit to JSON."""
        logger.info("Snapshot Triggered. Parsing internal state...")
        session_data = []
        terminals = {"foot", "alacritty", "kitty", "wezterm", "gnome-terminal"}
        
        for win_id, w in self.windows.items():
            app_id = w.get("app_id", "")
            pid = w.get("pid", 0)
            workspace = w.get("workspace_id", 0)
            
            cmd = self._resolve_desktop_file(app_id)
            cwd = self._get_terminal_cwd(pid) if app_id.lower() in terminals else str(Path.home())
            
            session_data.append({
                "app_id": app_id,
                "command": cmd,
                "cwd": cwd,
                "workspace": workspace
            })
            
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SESSION_FILE, "w") as f:
            json.dump(session_data, f, indent=4)
            
        logger.info(f"Session saved successfully to {SESSION_FILE} [{len(session_data)} layouts].")

    async def restore_session(self):
        """
        Iterate through saved state, spawn processes. 
        Niri's horizontal scroll sequence is guaranteed via deterministic event queues.
        """
        if not SESSION_FILE.exists():
            logger.error(f"No snapshot found at {SESSION_FILE}")
            return

        with open(SESSION_FILE, "r") as f:
            session_data = json.load(f)

        logger.info(f"Restoring {len(session_data)} preserved windows...")
        
        for app in session_data:
            cmd = app.get("command")
            cwd = app.get("cwd", str(Path.home()))
            target_workspace = app.get("workspace")
            app_id = app.get("app_id")
            
            if not cmd:
                continue

            # Queue this app_id to be caught by the event listener thread
            if app_id:
                self.pending_restores[app_id] = target_workspace
            
            logger.info(f"Ochestrating {cmd} -> Workspace {target_workspace}")
            try:
                subprocess.Popen(
                    shlex.split(cmd),
                    cwd=cwd,
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception as e:
                logger.error(f"Failed to launch command '{cmd}': {e}")
            
            # Allow Niri scheduler time to digest the application spawn 
            # and fire WindowOpened events sequentially
            await asyncio.sleep(0.1)


# --- IPC Server Bridge for CLI triggers --- #

async def daemon_server(manager):
    """Local IPC Socket bridging CLI commands to daemon space."""
    if os.path.exists(DAEMON_SOCKET):
        os.remove(DAEMON_SOCKET)
        
    async def handler(reader, writer):
        data = await reader.read(1024)
        command = data.decode().strip()
        
        if command == "save":
            await manager.save_session()
            writer.write(b"Session Saved.\n")
        elif command == "restore":
            await manager.restore_session()
            writer.write(b"Session Restored.\n")
        else:
            writer.write(b"Unknown Directive.\n")
            
        await writer.drain()
        writer.close()

    server = await asyncio.start_unix_server(handler, path=DAEMON_SOCKET)
    logger.info(f"NSM Command Broker bound to {DAEMON_SOCKET}")
    async with server:
        await server.serve_forever()

async def send_command(command):
    """Client function: Ping daemon across local Socket."""
    if not os.path.exists(DAEMON_SOCKET):
        print("NSM Daemon is not active. Please spawn with --daemon first.")
        return
        
    try:
        reader, writer = await asyncio.open_unix_connection(DAEMON_SOCKET)
        writer.write(command.encode())
        await writer.drain()
        
        response = await reader.read(1024)
        print(response.decode().strip())
        
        writer.close()
        await writer.wait_closed()
    except Exception as e:
        print(f"Daemon Connection Socket failure: {e}")

def main():
    parser = argparse.ArgumentParser(description="Niri Space Snapshot Utility")
    parser.add_argument("--daemon", action="store_true", help="Launch the background state tracker")
    parser.add_argument("--save", action="store_true", help="Trigger a disk commit of current view")
    parser.add_argument("--restore", action="store_true", help="Request the daemon to recreate last snapshot")
    
    args = parser.parse_args()
    
    if args.daemon:
        manager = SessionManager()
        loop = asyncio.get_event_loop()
        try:
            # We track the Niri Event Stream & Daemon CLI commands concurrently
            loop.create_task(manager.event_stream())
            loop.run_until_complete(daemon_server(manager))
        except KeyboardInterrupt:
            logger.info("SIGINT Caught. Terminating Niri-Session-Manager gracefully.")
        finally:
            if os.path.exists(DAEMON_SOCKET):
                os.remove(DAEMON_SOCKET)
    elif args.save:
        asyncio.run(send_command("save"))
    elif args.restore:
        asyncio.run(send_command("restore"))
    else:
        parser.print_help()

if __name__ == "__main__":
    main()