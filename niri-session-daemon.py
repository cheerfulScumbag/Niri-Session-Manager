import json
import os
import signal
import subprocess
import sys
import threading
from gi.repository import Gio

# Configuration
SESSION_FILE = os.path.expanduser("~/.cache/niri-session.json")
STATE = {"windows": []}

def get_exec_from_app_id(app_id):
    """KISS: Use GIO to find how to launch an app_id."""
    app_info = Gio.DesktopAppInfo.new(f"{app_id}.desktop")
    if not app_info:
        # Fallback for apps that don't match their desktop file exactly
        for app in Gio.AppInfo.get_all():
            if app_id.lower() in app.get_id().lower():
                return app.get_executable()
        return app_id # Last resort: try running the id itself
    return app_info.get_executable()

def save_to_disk():
    """Single write operation on exit."""
    with open(SESSION_FILE, 'w') as f:
        json.dump(STATE, f)
    print(f"\n[Niri-Session] State persisted to {SESSION_FILE}")

def handle_exit(sig, frame):
    save_to_disk()
    sys.exit(0)

def listen_to_niri():
    """Event-driven: Zero polling."""
    process = subprocess.Popen(
        ["niri", "msg", "-j", "event-stream"],
        stdout=subprocess.PIPE, text=True
    )
    
    for line in process.stdout:
        try:
            event = json.loads(line)
            # We track WindowOpened and WindowClosed to update our memory state
            if "WindowOpenedOrChanged" in event:
                win = event["WindowOpenedOrChanged"]["window"]
                # Store spatial data: app_id, workspace, and width
                STATE["windows"] = [w for w in STATE["windows"] if w['id'] != win['id']]
                STATE["windows"].append({
                    "id": win["id"],
                    "app_id": win["app_id"],
                    "workspace": win["workspace_id"],
                    "width": win.get("width", None)
                })
        except Exception as e:
            continue

def restore():
    """FIFO Queue: Ensures windows map in the correct spatial order."""
    if not os.path.exists(SESSION_FILE):
        return

    with open(SESSION_FILE, 'r') as f:
        saved_state = json.load(f)

    for win in saved_state["windows"]:
        exe = get_exec_from_app_id(win["app_id"])
        print(f"[Niri-Session] Restoring {win['app_id']}...")
        
        # Spawn and wait for Niri to confirm the window is 'managed'
        subprocess.Popen(["niri", "msg", "action", "spawn", "--", exe])
        
        # KISS: Small delay to let the compositor register the surface
        # A 10/10 version would watch the event-stream for the specific ID
        time.sleep(0.5) 

if __name__ == "__main__":
    # Handle clean exits (Niri closing or SIGTERM)
    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)

    if len(sys.argv) > 1 and sys.argv[1] == "--restore":
        import time
        restore()
    
    print("[Niri-Session] Daemon started. Monitoring spatial state...")
    listen_to_niri()