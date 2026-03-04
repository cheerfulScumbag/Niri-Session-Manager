{ osConfig, lib, ... }:
''
  binds {
      // Keys consist of modifiers separated by + signs, followed by an XKB key name
      // in the end. To find an XKB name for a particular key, you may use a program
      // like wev.
      //
      // "Mod" is a special modifier equal to Super when running on a TTY, and to Alt
      // when running as a winit window.
      //
      // Most actions that you can bind here can also be invoked programmatically with
      // `niri msg action do-something`.

      // Mod-Shift-/, which is usually the same as Mod-?,
      // shows a list of important hotkeys.
      Mod+Shift+Slash { show-hotkey-overlay; }

      // Suggested binds for running programs: terminal, app launcher, screen locker.
      Mod+Return hotkey-overlay-title="Open a Terminal: kitty" { spawn "kitty"; }
${if osConfig.desktops.niri.shell == "noctalia" then ''
      Mod+Space hotkey-overlay-title="Run an Application: noctalia" { spawn-sh "noctalia-shell ipc call launcher toggle"; }
'' else ''
      Mod+Space hotkey-overlay-title="Run an Application: vicinae open" { spawn-sh "vicinae open"; }
''}

      Super+Alt+L hotkey-overlay-title="Lock the Screen: swaylock" { spawn "swaylock"; }

      // Use spawn-sh to run a shell command. Do this if you need pipes, multiple commands, etc.
      // Note: the entire command goes as a single argument. It's passed verbatim to `sh -c`.
      // For example, this is a standard bind to toggle the screen reader (orca).
      Super+Alt+S allow-when-locked=true hotkey-overlay-title=null { spawn-sh "pkill orca || exec orca"; }

      // Example volume keys mappings for PipeWire & WirePlumber.
      // The allow-when-locked=true property makes them work even when the session is locked.
      // Using spawn-sh allows to pass multiple arguments together with the command.
      XF86AudioRaiseVolume allow-when-locked=true { spawn-sh "wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.1+"; }
      XF86AudioLowerVolume allow-when-locked=true { spawn-sh "wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.1-"; }
      XF86AudioMute        allow-when-locked=true { spawn-sh "wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"; }
      XF86AudioMicMute     allow-when-locked=true { spawn-sh "wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"; }

      // Example brightness key mappings for brightnessctl.
      // You can use regular spawn with multiple arguments too (to avoid going through "sh"),
      // but you need to manually put each argument in separate "" quotes.
      XF86MonBrightnessUp allow-when-locked=true { spawn "brightnessctl" "--class=backlight" "set" "+10%"; }
      XF86MonBrightnessDown allow-when-locked=true { spawn "brightnessctl" "--class=backlight" "set" "10%-"; }

      // Open/close the Overview: a zoomed-out view of workspaces and windows.
      // You can also move the mouse into the top-left hot corner,
      // or do a four-finger swipe up on a touchpad.
      Mod+O repeat=false { toggle-overview; }

      Mod+Q repeat=false { close-window; }

      Mod+B hotkey-overlay-title="Open Browser: Firefox" { spawn "firefox"; }

      Mod+Left  { focus-column-left; }
      Mod+Down  { focus-window-down; }
      Mod+Up    { focus-window-up; }
      Mod+Right { focus-column-right; }
      Mod+H     { focus-column-left; }
      //Mod+J     { focus-window-down; }
      //Mod+K     { focus-window-up; }
      Mod+L     { focus-column-right; }

      Mod+Ctrl+Left  { move-column-left; }
      Mod+Ctrl+Down  { move-window-down; }
      Mod+Ctrl+Up    { move-window-up; }
      Mod+Ctrl+Right { move-column-right; }
      Mod+Ctrl+H     { move-column-left; }
      //Mod+Ctrl+J     { move-window-down; }
      //Mod+Ctrl+K     { move-window-up; }
      Mod+Ctrl+L     { move-column-right; }

      // Alternative commands that move across workspaces when reaching
      // the first or last window in a column.
      Mod+J     { focus-window-or-workspace-down; }
      Mod+K     { focus-window-or-workspace-up; }
      Mod+Ctrl+J     { move-window-down-or-to-workspace-down; }
      Mod+Ctrl+K     { move-window-up-or-to-workspace-up; }

      Mod+Home { focus-column-first; }
      Mod+End  { focus-column-last; }
      Mod+Ctrl+Home { move-column-to-first; }
      Mod+Ctrl+End  { move-column-to-last; }

      Mod+Shift+Left  { focus-monitor-left; }
      Mod+Shift+Down  { focus-monitor-down; }
      Mod+Shift+Up    { focus-monitor-up; }
      Mod+Shift+Right { focus-monitor-right; }
      Mod+Shift+H     { focus-monitor-left; }
      Mod+Shift+J     { focus-monitor-down; }
      Mod+Shift+K     { focus-monitor-up; }
      Mod+Shift+L     { focus-monitor-right; }

      Mod+Shift+Ctrl+Left  { move-column-to-monitor-left; }
      Mod+Shift+Ctrl+Down  { move-column-to-monitor-down; }
      Mod+Shift+Ctrl+Up    { move-column-to-monitor-up; }
      Mod+Shift+Ctrl+Right { move-column-to-monitor-right; }
      Mod+Shift+Ctrl+H     { move-column-to-monitor-left; }
      Mod+Shift+Ctrl+J     { move-column-to-monitor-down; }
      Mod+Shift+Ctrl+K     { move-column-to-monitor-up; }
      Mod+Shift+Ctrl+L     { move-column-to-monitor-right; }

      Mod+Page_Down      { focus-workspace-down; }
      Mod+Page_Up        { focus-workspace-up; }
      Mod+U              { focus-workspace-down; }
      Mod+I              { focus-workspace-up; }
      Mod+Ctrl+Page_Down { move-column-to-workspace-down; }
      Mod+Ctrl+Page_Up   { move-column-to-workspace-up; }
      Mod+Ctrl+U         { move-column-to-workspace-down; }
      Mod+Ctrl+I         { move-column-to-workspace-up; }

      Mod+Shift+Page_Down { move-workspace-down; }
      Mod+Shift+Page_Up   { move-workspace-up; }
      Mod+Shift+U         { move-workspace-down; }
      Mod+Shift+I         { move-workspace-up; }

      // You can bind mouse wheel scroll ticks using the following syntax.
      // These binds will change direction based on the natural-scroll setting.
      //
      // To avoid scrolling through workspaces really fast, you can use
      // the cooldown-ms property. The bind will be rate-limited to this value.
      // You can set a cooldown on any bind, but it's most useful for the wheel.
      Mod+WheelScrollDown      cooldown-ms=150 { focus-workspace-down; }
      Mod+WheelScrollUp        cooldown-ms=150 { focus-workspace-up; }
      Mod+Ctrl+WheelScrollDown cooldown-ms=150 { move-column-to-workspace-down; }
      Mod+Ctrl+WheelScrollUp   cooldown-ms=150 { move-column-to-workspace-up; }

      Mod+WheelScrollRight      { focus-column-right; }
      Mod+WheelScrollLeft       { focus-column-left; }
      Mod+Ctrl+WheelScrollRight { move-column-right; }
      Mod+Ctrl+WheelScrollLeft  { move-column-left; }

      // Usually scrolling up and down with Shift in applications results in
      // horizontal scrolling; these binds replicate that.
      Mod+Shift+WheelScrollDown      { focus-column-right; }
      Mod+Shift+WheelScrollUp        { focus-column-left; }
      Mod+Ctrl+Shift+WheelScrollDown { move-column-right; }
      Mod+Ctrl+Shift+WheelScrollUp   { move-column-left; }

      Mod+1 { focus-workspace 1; }
      Mod+2 { focus-workspace 2; }
      Mod+3 { focus-workspace 3; }
      Mod+4 { focus-workspace 4; }
      Mod+5 { focus-workspace 5; }
      Mod+6 { focus-workspace 6; }
      Mod+7 { focus-workspace 7; }
      Mod+8 { focus-workspace 8; }
      Mod+9 { focus-workspace 9; }
      Mod+Ctrl+1 { move-column-to-workspace 1; }
      Mod+Ctrl+2 { move-column-to-workspace 2; }
      Mod+Ctrl+3 { move-column-to-workspace 3; }
      Mod+Ctrl+4 { move-column-to-workspace 4; }
      Mod+Ctrl+5 { move-column-to-workspace 5; }
      Mod+Ctrl+6 { move-column-to-workspace 6; }
      Mod+Ctrl+7 { move-column-to-workspace 7; }
      Mod+Ctrl+8 { move-column-to-workspace 8; }
      Mod+Ctrl+9 { move-column-to-workspace 9; }

      Mod+BracketLeft  { consume-or-expel-window-left; }
      Mod+BracketRight { consume-or-expel-window-right; }

      Mod+Comma  { consume-window-into-column; }
      Mod+Period { expel-window-from-column; }

      Mod+R { switch-preset-column-width; }
      Mod+Shift+R { switch-preset-window-height; }
      Mod+Ctrl+R { reset-window-height; }
      Mod+F { maximize-column; }
      Mod+Shift+F { fullscreen-window; }

      Mod+Ctrl+F { expand-column-to-available-width; }

      Mod+C { center-column; }

      Mod+Ctrl+C { center-visible-columns; }

      Mod+Minus { set-column-width "-10%"; }
      Mod+Equal { set-column-width "+10%"; }

      Mod+Shift+Minus { set-window-height "-10%"; }
      Mod+Shift+Equal { set-window-height "+10%"; }

      Mod+V       { toggle-window-floating; }
      Mod+Shift+V { switch-focus-between-floating-and-tiling; }

      Mod+W { toggle-column-tabbed-display; }

      Print { screenshot; }
      Ctrl+Print { screenshot-screen; }
      Alt+Print { screenshot-window; }
      Mod+S { spawn "sh" "-c" "grim -g \"$(slurp)\" - | swappy -f -"; }

      // Mod+Shift+E { quit; }
      // Ctrl+Alt+Delete { quit; }

      // Replace standard quit with a save-and-quit sequence
      Mod+Shift+E { spawn "/home/kenn/Projects/Niri-Session-Manager/nsm.py" "--save"; quit; }

      Mod+Shift+P { power-off-monitors; }
  }
''
