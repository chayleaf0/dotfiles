{ pkgs
, lib
, inputs,
...
}:

{
  imports = [
    ../common/general.nix
    ../common/firefox.nix
    ../common/i3-sway.nix
    ../common/nvim.nix
    ../common/helix.nix
    ../common/kakoune.nix
    inputs.nur.nixosModules.nur
  ];

  nix.settings = {
    trusted-public-keys = [
      "binarycache.pavluk.org:Vk0ms/vSqoOV2JXeNVOroc8EfilgVxCCUtpCShGIKsQ="
      "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY="
      "nix-gaming.cachix.org-1:nbjlureqMbRAxR1gJ/f3hxemL9svXaZF/Ees8vCUUs4="
      # "nixpkgs-wayland.cachix.org-1:3lwxaILxMRkVhehr5StQprHdEo4IrE8sRho9R9HOLYA="
    ];
    trusted-substituters = [
      "https://binarycache.pavluk.org"
      "https://cache.nixos.org"
      "https://nix-gaming.cachix.org"
      # "https://nixpkgs-wayland.cachix.org"
    ];
  };

  nixpkgs.config.allowUnfreePredicate = pkg: builtins.elem (lib.getName pkg) [
    "steam-run"
    "steam"
    "steam-original"
    "steam-runtime"
    "steamcmd"
    "osu-lazer-bin"
  ];

  home.stateVersion = "22.11";
  home.username = "user";
  home.homeDirectory = "/home/user";
  termShell = {
    enable = true;
    path = "${pkgs.fish}/bin/fish";
  };
  # xsession.windowManager.i3.enable = true;
  wayland.windowManager.sway.enable = true;
  terminals = [ "kitty" "urxvt" ];
  services.mpd = {
    enable = true;
    network.startWhenNeeded = true;
  };
  services.mpdris2 = {
    enable = true;
  };
  programs.ncmpcpp = {
    enable = true;
  };
  services.kdeconnect.enable = true;
  systemd.user.services.kdeconnect.Service = {
    Restart = lib.mkForce "always";
    RestartSec = "30";
  };
  home.sessionVariables = {
    STEAM_EXTRA_COMPAT_TOOLS_PATHS = "${pkgs.proton-ge}";
    CARGO_PROFILE_DEV_INCREMENTAL = "true";
    # RUSTC_LINKER = "${pkgs.clang_latest}/bin/clang";
    # RUSTFLAGS = "-C link-arg=--ld-path=${pkgs.mold}/bin/mold";
    CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER = "${pkgs.clang_latest}/bin/clang";
    CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUSTFLAGS = "-C link-arg=--ld-path=${pkgs.mold}/bin/mold";
  };
  home.packages = with pkgs; [
    anki-bin
    (gimp.overrideAttrs (old: { doCheck = false; })) krita blender-hip
    kdenlive glaxnimate mediainfo
    ghidra (cutter.withPlugins (p: with p; [ sigdb rz-ghidra ]))
    openrgb piper
    steam-run steam
    # faf-client
    (osu-lazer-bin.override {
      command_prefix = "env SDL_VIDEODRIVER=wayland ${obs-studio-plugins.obs-vkcapture}/bin/obs-gamecapture";
    })
    taisei
    techmino
    (wrapOBS {
      plugins = with obs-studio-plugins; [ wlrobs obs-vkcapture ];
    })
    easyeffects
    # wineWowPackages.waylandFull
    winetricks
    # protontricks # proton-caller
    # bottles
    virt-manager looking-glass-client
    clang_latest mold
    rustc rustfmt cargo clippy
    lalrpop
    tio
    tdesktop
  ];
  xdg.configFile."looking-glass/client.ini".text = ''
    [app]
    shmFile=/dev/kvmfr0

    [input]
    rawMouse=yes
    escapeKey=KEY_RIGHTALT
  '';
}
