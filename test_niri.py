import asyncio
import json
import subprocess

async def test():
    # Find a window id
    windows = json.loads(subprocess.check_output(["niri", "msg", "-j", "windows"]))
    if not windows:
        print("No windows")
        return
    win_id = windows[0]["id"]
    print(f"Moving window {win_id} to DP-3, workspace 2")
    subprocess.call(["niri", "msg", "action", "move-window-to-monitor", "--id", str(win_id), "DP-3"])
    subprocess.call(["niri", "msg", "action", "move-window-to-workspace", "--window-id", str(win_id), "2"])
    
    # Check where it went
    windows = json.loads(subprocess.check_output(["niri", "msg", "-j", "windows"]))
    workspaces = json.loads(subprocess.check_output(["niri", "msg", "-j", "workspaces"]))
    for w in windows:
        if w["id"] == win_id:
            ws_id = w["workspace_id"]
            for ws in workspaces:
                if ws["id"] == ws_id:
                    print(f"Window is now on output: {ws['output']}, idx: {ws['idx']}")

asyncio.run(test())
