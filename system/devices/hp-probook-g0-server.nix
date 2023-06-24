{ config, ... }:

let
  efiPart = "/dev/disk/by-uuid/3E2A-A5CB";
  rootUuid = "6aace237-9b48-4294-8e96-196759a5305b";
  rootPart = "/dev/disk/by-uuid/${rootUuid}";
in {
  imports = [
    ../hardware/hp-probook-g0.nix
    ../hosts/nixserver
  ];

  boot.loader = {
    grub = {
      enable = true;
      device = "nodev";
      efiSupport = true;
      efiInstallAsRemovable = true;
    };
    efi.efiSysMountPoint = "/boot/efi";
  };
  fileSystems = {
    "/" =    { device = "none"; fsType = "tmpfs"; neededForBoot = true;
               options = [ "defaults" "size=2G" "mode=755" ]; };
    "/persist" =
             { device = rootPart; fsType = "btrfs"; neededForBoot = true;
               options = [ "compress=zstd:15" ]; };
    "/boot" =
             { device = rootPart; fsType = "btrfs"; neededForBoot = true;
               options = [ "compress=zstd:15" "subvol=boot" ]; };
    "/boot/efi" =
             { device = efiPart; fsType = "vfat"; };
  };
  services.beesd = {
    filesystems.root = {
      spec = "UUID=${rootUuid}";
      hashTableSizeMB = 128;
      extraOptions = [ "--loadavg-target" "8.0" ];
    };
  };

  zramSwap.enable = true;
  swapDevices = [ ];

  impermanence = {
    enable = true;
    path = /persist;
    directories = [
      { directory = /home/${config.common.mainUsername}; user = config.common.mainUsername; group = "users"; mode = "0700"; }
      { directory = /root; }
      { directory = /nix; }
    ];
  };
}