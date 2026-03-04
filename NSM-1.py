import json
import subprocess
import os
import signal
import sys
import asyncio
from pathlib import Path

# Constants
STATE_FILE = Path.home() / ".cache/niri-session-state.json"
TERMINALS = {"foot", "alacritty", "kitty", "ghostty", "wezterm"}

class NiriSessionManager:
    def __init__(self):
        self.active_windows = []
        self.launch_queue = asyncio.Queue()
        self.window_mapped_event = asyncio.Event()

    def get_terminal_cwd(self, pid):
        """Advanced PID-to-CWD lookup via /proc."""
        try:
            # Get the shell/process running inside the terminal
            # We look for the child of the terminal emulator PID
            children = subprocess.check_output(["pgrep", "-P", str(pid)]).decode().split()
            if children:
                # Use the first child (usually the shell) to get CWD
                return os.readlink(f"/proc/{children[0]}/cwd")
        except Exception:
            try: return os.readlink(f"/proc/{pid}/cwd")
        except: pass
        return os.path.expanduser("~")

    async def get_current_windows(self):
        """Fetch current state from Niri IPC."""
        proc = await asyncio.create_subprocess_exec(
            "niri", "msg", "-j", "windows",
            stdout=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return json.loads(stdout)

    async def watch_events(self):
        """Zero-polling listener that also acts as a sync trigger for the queue."""
        process = await asyncio.create_subprocess_exec(
            "niri", "msg", "-j", "event-stream",
            stdout=asyncio.subprocess.PIPE
        )
        while True:
            line = await process.stdout.readline()
            if not line: break
            event = json.loads(line)
            
            # Signal the restorer that a window has successfully appeared
            if "WindowOpened" in event:
                self.window_mapped_event.set()
            
            # Update internal state for the final write
            if any(k in event for k in ["WindowOpened", "WindowClosed", "WindowGeometryChanged"]):
                self.active_windows = await self.get_current_windows()

    async def restore_session(self):
        """Sequenced launch to maintain spatial integrity."""
        if not STATE_FILE.exists():
            print("No save state found.")
            return

        with open(STATE_FILE, 'r') as f:
            saved_data = json.load(f)

        print(f"Restoring {len(saved_data)} windows...")

        for win in saved_data:
            app_id = win.get("app_id", "")
            cmd = [app_id] # Fallback
            
            # 1. Advanced Terminal Restoration
            if app_id.lower() in TERMINALS and "cwd" in win:
                cmd = [app_id, "--working-directory", win["cwd"]] if app_id != "foot" else ["foot", "-D", win["cwd"]]

            # 2. Trigger Launch
            self.window_mapped_event.clear()
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                # 3. Wait for Niri to confirm the window is mapped before next launch
                # This ensures the horizontal 'scroll' order is preserved.
                await asyncio.wait_for(self.window_mapped_event.wait(), timeout=5.0)
                print(f"Restored: {app_id}")
            except asyncio.TimeoutError:
                print(f"Timeout waiting for {app_id}, moving to next...")
            except Exception as e:
                print(f"Failed to launch {app_id}: {e}")

    def save_and_exit(self):
        """Final write-to-disk logic with CWD metadata."""
        refined_state = []
        for win in self.active_windows:
            # Enrich window data with CWD if it's a terminal
            entry = {
                "app_id": win["app_id"],
                "workspace": win["workspace_id"],
                "width": win["width"]
            }
            if win["app_id"].lower() in TERMINALS:
                entry["cwd"] = self.get_terminal_cwd(win["pid"])
            refined_state.append(entry)

        with open(STATE_FILE, 'w') as f:
            json.dump(refined_state, f, indent=4)
        print("\nSession state captured. Exiting.")
        sys.exit(0)

async def main():
    manager = NiriSessionManager()
    
    if "--restore" in sys.argv:
        await manager.restore_session()
        print("Restore complete. Run without --restore to start daemon.")
        return

    # Daemon Mode
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, manager.save_and_exit)

    print("NSM Daemon: Watching Niri IPC...")
    await manager.watch_events()

if __name__ == "__main__":
    asyncio.run(main())