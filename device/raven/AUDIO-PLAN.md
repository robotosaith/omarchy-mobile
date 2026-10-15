<!-- SPDX-License-Identifier: MIT -->
# Pixel 6 Pro (raven): AoC, speakers and microphones

Status (2026-10-15): **R0 done; R1 set up on the phone, not yet run.** Kernel branch `omamobile-gs101-aoc`
(the hashes below are from the stacked bring-up branch it was split from):
- cheetah's Trusty, GSA and AoC stack imported (`ce7ae89a5`, `fa0873edc`);
- it builds against gs101's firmware interface (`9f5ed4b1f`, raven's
  `device/raven/kernel.config` sets `CONFIG_GOOGLE_AOC_GS101`);
- gs101 compatibles in the GSA, AoC, SysMMU and mailbox drivers, and
  disabled DT nodes for Trusty, GSA, the AoC SysMMU, the AoC mailbox and
  the AoC (`aa41c40c0`); builds clean.
- Findings:
  - the AoC carve-out is `0x94000000` on both SoCs (already reserved
    upstream as `aoc_reserve`);
  - the boot helper's `AOC_DRAM_BASE 0x98000000` is the AoC's own view;
  - the AoC core counts its mailbox channels from `mboxes` (16 on gs101).
- Next: the AoC rails on raven's PMICs (`gs201-aoc-rails.c` speaks
  S2MPG12/13), the AoC firmware in `extract-vendor-firmware -d raven`, then
  R1 on the phone.
- **R1 setup done (2026-10-15, kernel `g8c2f974b6ab5`, branch head
  `8c2f974b6`):**
  - Trusty and GSA are enabled in raven's DT and the phone runs that kernel.
  - Every AoC-stack module is blacklisted on the phone
    (`/etc/modprobe.d/omamobile-raven-aoc-bringup.conf`, not packaged yet).
  - Next: load `trusty_core`, `trusty_log` and `gsa` by hand, with kmsg
    streamed and the watchdog fed, and read the Trusty log. No RPMB writes
    and no storageproxyd.
- After that boot, Bluetooth's firmware loaded but the adapter read
  Powered: no, probably the rfkill state restored from before. Check it
  first next time.

The goal: port cheetah's AoC stack (`device/cheetah/AOC-PLAN.md`: on cheetah the AoC starts at every
boot and drives both speakers, the microphones and the sensors) to gs101.
The calibration partitions were checked first: four of them differed after
GrapheneOS's boot on 2026-10-14 (efs, efs_backup, modem_userdata, persist).
A fresh read-only backup is in `~/android/reference/raven-backup-2026-10-15`,
verified against the phone (private, never committed).

## 1. Facts

From Google's raviole DT and GPL sources.

| Item | raven (gs101) | cheetah (gs201) | Source |
| --- | --- | --- | --- |
| AoC | `0x19000000` (16 MiB), `aoc-board-cfg "r4"`, board id `0x20202`, rev `0x10000` | the same base | `gs101-aoc.dtsi:28`, `gs101-raven-audio.dtsi` |
| AoC interface | `aoc-interface-gs101.h` (2799 lines, google-modules/aoc raviole android14) | `aoc-interface-gs201.h` | fetched to scratch |
| Speaker amplifiers | 2x CS35L41 on **SPI 13** (`cs35l41@0`, `@1`, 25 MHz) | 2x CS35L41 on I2C | `gs101-raviole-audio.dtsi:223-280` |
| Haptics | **CS40L25A** on I2C 8 at `0x43` | CS40L26 | `gs101-raviole-audio.dtsi:162-211` |
| Start | through Trusty (GSA hwmgr), as on cheetah | the same | AGENTS.md AoC gotchas |

**AoC node, gs101** (Google's `gs101-aoc.dtsi`):

| Item | Value |
| --- | --- |
| `blk_aoc` | `0x19000000` (16 MiB) |
| `aoc_req` | `0x175d0000` |
| `aoc_s2mpu` | `0x1a0b0000` |
| `ssmt_aoc` | `0x1a060000` |
| mailbox `aoc2ap` | `0x176a0000` (IRQ `MAILBOX_AOC2AP_ALIVE`), 16 channels, `wc-mbox-non-wake-channels` `0x7000` |
| IOMMU and memory | `sysmmu_asoc`, `aoc_reserve` |
| ACPM channel | 13 |
| PCU | `pcu-base` `0xb00000`, doorbells at `0xd004`/`0xd008` |
| GPIO base | `0xb70000` |
| AoC vsync pins | gpp3-1, gpp5-1, gpp7-1, gpp9-1 (function 2) |

## 2. Port

Reusable from cheetah's integration snapshot (`ebe48386d`), with DT data:
the AoC core, IPC, firmware loader, channel and char devices, the ALSA card
(`drivers/soc/google/aoc/`), `drivers/trusty/` and `gsa.c`.

To redo for gs101:
- `aoc-interface-gs201.h` becomes gs101's;
- `gs201-aoc-boot.c`: addresses and boot sequence;
- `gs201-aoc-rails.c`: raven's PMICs are the S2MPG10 and S2MPG11, not the
  S2MPG12 and S2MPG13;
- `gs201-aoc-sysmmu.c`: gs101's AoC SysMMU;
- the CS35L41 amplifiers over SPI 13, with gs101's USI and pinctrl.

Raven's AoC firmware and speaker tuning come from the owner's factory
image (`tools/extract-vendor-firmware -d raven` gets an AoC map). The
speaker calibration is never committed.

## 3. Stages (each gated, read-only first; AGENTS.md AoC gotchas apply)

1. **R0 (offline):** import the stack on a branch `omamobile-raven-aoc`;
   gs101 interface, boot, rails and sysmmu; DT nodes disabled; build.
2. **R1:** Trusty and GSA up on raven (read-only probes, no RPMB writes).
3. **R2:** the AoC started through Trusty, its firmware log readable.
4. **R3:** the AoC sound card and the microphones (capture).
5. **R4:** the speakers at cheetah's safe level (stage `media`), with
   speaker protection.
6. **R5:** sensors (auto-rotate) through the same AoC.
