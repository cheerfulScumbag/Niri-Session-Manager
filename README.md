# Niri Session Manager

A lightweight, KISS-compliant Python daemon for the [Niri](https://github.com/YaLTeR/niri) window manager that saves and restores your spatial window layouts. 

NSM tracks the exact monitor (`output`) and workspace index (`idx`) of your active windows, hooks into Niri's event stream, and smoothly restores windows to their original positions via IPC on your next login!

## Features
- **Instant Restore:** Dramatically speeds up restoration by launching all your apps concurrently instead of waiting for each one sequentially.
- **Accurate Placement:** Reliably restores applications to different monitors and workspace indices, ignoring transient workspace IDs.
- **Auto-Save/Restore:** Operates silently in the background. It automatically saves your layout when Niri quits (SIGTERM) and automatically restores it when Niri starts (if no other windows are present).

---

## 🚀 Installation & Setup

### 1. Requirements
Ensure you are running Niri with python3 installed. This script relies entirely on standard library python packages (no `pip install` required!) and the `niri` CLI.

### 2. Make the script executable
Clone this repository or move `nsm.py` to a secure location where it won't be deleted. (For example, `~/Scripts/nsm.py` or keep it where you cloned it).
Then make it executable:
```bash
chmod +x /path/to/nsm.py
```

### 3. Add to Niri Configuration
To use NSM, you need to tell Niri to spawn the daemon on startup and define the keybinds for manually saving/restoring (if you want manual control).

Open your Niri config `~/.config/niri/config.kdl` and add the following lines:

**Autostart Daemon:**
```kdl
// Start the Niri Session Manager Daemon
spawn-at-startup "/path/to/nsm.py" "--daemon"
```
*(Make sure to change `/path/to/nsm.py` to wherever you actually placed the python script!)*

### 4. Update the Quit Keybind (Important!)
To ensure your session is always saved right before you exit Niri, it's recommended to update your quit keybind to explicitly call `--save` before the `quit` action, or to rely on the daemon's SIGTERM hook. 

However, since Niri's `quit` action can exit very quickly, a bulletproof method is to chain the commands in your `config.kdl`:

```kdl
    // Save session then quit
    Mod+Shift+E { spawn-sh "/path/to/nsm.py --save && niri msg action quit"; }
```

### 5. Restart Niri
Once added, you can either log out and log back in, or reload Niri. Starting from your next boot, any running applications will be saved automatically upon exiting Niri (via your new quit bind or the daemon's SIGTERM hook), and your workspace layout will seamlessly fade back in concurrently on your next login!

