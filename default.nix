{ config, lib, pkgs, osConfig, vars, ... }:
let
  host = osConfig.networking.hostName;
  
  outputs = import ./outputs.nix { inherit host config; };
  layout = import ./layout.nix { };
  keybinds = import ./keybinds.nix { inherit osConfig lib; };
  windowrules = import ./windowrules.nix { };
in
{
  xdg.configFile."niri/outputs.kdl".source = outputs;

  xdg.configFile."niri/config.kdl".text = ''
    include "outputs.kdl"

    ${layout}

    ${keybinds}

    ${windowrules}

    ${lib.optionalString (osConfig.desktops.niri.shell == "waybar") "spawn-at-startup \"waybar\""}
    ${lib.optionalString (osConfig.desktops.niri.shell == "noctalia") "spawn-at-startup \"sh\" \"-c\" \"noctalia-shell > ~/.local/state/noctalia.log 2>&1\""}

    spawn-at-startup "swaybg" "-m" "fill" "-i" "${osConfig.stylix.image}"

    // testing session restore
    spawn-at-startup "systemctl" "--user" "import-environment" "NIRI_SOCKET"
    spawn-at-startup "/home/kenn/Projects/Niri-Session-Manager/nsm.py" "--restore"

    environment {
        QT_QPA_PLATFORM "wayland;xcb"
        QT_QPA_PLATFORMTHEME "qt6ct"
        QT_AUTO_SCREEN_SCALE_FACTOR "1"
    }

    // Session-level env vars (XDG_CURRENT_DESKTOP, QT_QPA_PLATFORM, etc.)
    // are set in system/desktop/niri.nix — no need to duplicate here.
  '';

  # Packages useful in any WM environment
  home.packages = with pkgs; [
    swayidle
    brightnessctl
    playerctl
    wl-clipboard
    grim         # screenshots
    slurp        # region select for screenshots
    fuzzel
    kitty
    swaybg
    swaylock-effects
    xwayland-satellite
    swappy
    udiskie
    swww
    adw-gtk3
    gnome-themes-extra
    papirus-icon-theme
    vicinae
  ] ++ lib.optional (osConfig.desktops.niri.shell == "waybar") pkgs.waybar;

  # Polkit authentication agent for graphical privilege escalation
  systemd.user.services.polkit-kde-agent = {
    Unit = {
      Description = "PolicyKit Authentication Agent (KDE)";
      After = [ "graphical-session.target" ];
    };
    Service = {
      Type = "simple";
      ExecStart = "${pkgs.kdePackages.polkit-kde-agent-1}/libexec/polkit-kde-authentication-agent-1";
      Restart = "on-failure";
      RestartSec = 1;
      TimeoutStopSec = 10;
    };
    Install.WantedBy = [ "graphical-session.target" ];
  };
}

