<!-- SPDX-License-Identifier: MIT -->
# Pixel 6 Pro (raven): notes

Findings from real hardware that matter beyond one subsystem, newest first.
Details are in the linked plans.

## 2026-10-15

- **Never list `/sys/kernel/debug/pinctrl/*/pins` or `pinconf-pins` on
  gs101.** It reads every bank's config, a bank without power aborts the
  SoC, and the reader dies holding the pinctrl lock: reboot after one. Read
  a single bank you know is powered instead (AGENTS.md).
  [BLUETOOTH-PLAN](BLUETOOTH-PLAN.md)
- **The panel rails belong to the simple-framebuffer node.** vci (ldo22m)
  and vddi (bucka) are held by `chosen:framebuffer-0`; removing simpledrm
  for gs-decon released them and the panel went dark. They are now
  always-on in the DT. [DISPLAY-PLAN](DISPLAY-PLAN.md) D3
- **An Android boot on slot A changes the calibration partitions.** Four
  of them (`efs`, `efs_backup`, `modem_userdata`, `persist`) differed after
  one boot of slot A's Android, as on cheetah: take a fresh read-only
  backup after every Android boot, before radio, PMIC, AoC or Trusty work.
  [AUDIO-PLAN](AUDIO-PLAN.md)
- **Idle power:** about 460 mA with the screen off, from 610 mA, mostly
  from MIF at 1014 MHz, unused power domains off and DECON's trigger masked
  while dark. [POWER-PLAN](POWER-PLAN.md)

## 2026-10-14

- **Mali-G78 needs AArch64 page tables in panfrost.** With the legacy LPAE
  format every fragment job faulted (`DATA_INVALID_FAULT`); every G57 SoC
  entry already forces AArch64. [GPU-PLAN](GPU-PLAN.md)
- **Slot B falls back to slot A unless something marks it successful.**
  ABL spends a retry on every boot, resets and held power keys included.
  Raven's `devinfo` has cheetah's layout (`DEVI` 3.15), so
  `omamobile-boot-success` works unchanged. [BRINGUP-M1](BRINGUP-M1.md) §7
- **ABL reads the reboot reason from the MAX77759's nvmem.** Without
  `max77759`, `nvmem-max77759` and `nvmem-reboot-mode` loaded,
  `reboot-to bootloader` boots slot B again. The initramfs loads them first
  (`INITRAMFS_MODULES`), never the charger. [BRINGUP-M1](BRINGUP-M1.md) §7
- **The simple-framebuffer waits for PMIC rails**, so the screen console
  needs `exynos-mailbox`, `acpm-protocol` and `sec-acpm` in the initramfs
  too. [BRINGUP-M1](BRINGUP-M1.md) §7
- **Raven's ABL leaves both cluster watchdogs off** (cheetah's leaves them
  running). [BRINGUP-M1](BRINGUP-M1.md) R3
- **The MAX77759 opens the USB2 data switch on unplug**, as on cheetah: the
  initramfs closes it until switch_root, `omamobile-usb-rescue` after.
  [BRINGUP-M1](BRINGUP-M1.md) §7
- **The touch controller (S6SY79x on SPI 11) needs care:** its reset is
  active-low, a reply can arrive on the second read frame, its interface
  dozes after 1-2 ms of silence, and at boot it answers only after a power
  cycle. [BRINGUP-M1](BRINGUP-M1.md) §7
- **Create the user account under its final name.** Renaming it after the
  first login broke the theme's background symlinks (absolute paths into
  the old home). [BRINGUP-M1](BRINGUP-M1.md) §7
- **GrapheneOS on slot A keeps USB data off while the phone is locked**, so
  the laptop's USB log can't time a fallback to slot A.
