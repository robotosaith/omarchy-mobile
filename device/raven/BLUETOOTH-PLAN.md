<!-- SPDX-License-Identifier: MIT -->
# Pixel 6 Pro (raven): Bluetooth

Status (2026-10-15): **Bluetooth works and is on at boot** (kernel
`g014e0672a241`, omamobile-device-raven 0.1.1). The patched BCM4389C1
(`ES1PX_GG_R4`, build 0203) loads at every boot, bluetoothd runs, the
controller is powered, and a scan found 18 devices. Next: set the phone's
own Bluetooth address (as cheetah's `omamobile-bt-addr` does: power on
first, then set it), then pair and play audio.

## 1. Facts

From Google's raviole DT: `gs101-common-bluetooth.dtsi`,
`gs101-raven-bluetooth.dtsi` and `gs101-usi.dtsi`.

| Item | raven (gs101) | cheetah (gs201) |
| --- | --- | --- |
| UART | APM USI1 at `0x175b0000`, SPI 69, FIFO 256, pins `uart16_bus` (gpa3-0..3, func 2) | `0x181b0000`, SPI 69 |
| USI mode | `sysreg_apm` + `0x4e4` (Google: sysreg `0x174204e0`, usi-offset 4) | the same offset |
| BT_REG_ON | gpp16-2 | gpp16-2 |
| Device wake | **gpp14-3** | gpp16-3 |
| Host wake | gpa6-6 | gpa6-6 |
| Timesync | gpp11-1 (raven only, not used) | - |
| UART clock | `mout_apm_func` on the 24.576 MHz oscillator, `dout_apm_usi1_uart` 12.288 MHz | 197 MHz from `mout_apm_funcsrc` (PLL_ALV/2) |

Upstream already has: `brcm,bcm4389-bt` in hci_bcm and its binding, gs101
CMU_APM with the USI1 UART gates, and `uart16_bus`.

## 2. Results

**BT1 (2026-10-15, `g0133ca8741af`):**
- The UART probes as ttySAC1 and serdev creates `serial0-0`.
- `modprobe hci_uart`: hci0 appears; BT_REG_ON and device wake are driven
  high (gpio debugfs).
- Both `0xfc18` (update baud rate) and `HCI_Reset` time out: no Command
  Complete. The UART interrupt fired twice, and nothing was received.
- No hang. hci_uart was unloaded again.

**BT1.1 (same day, read only):**
- CMU_APM in hardware: `MUX_APM_FUNC` 1 (FUNCSRC), `MUX_APM_FUNCSRC` 0
  (PLL_ALV/2), `DIV_USI1_UART` 1 (/2), so the UART runs at **197 MHz**. The
  gates `0x2038`, `0x203c` and `0x20a4` read `0x00200000`.
- Linux's clock tree had cached `mout_apm_func` on the oscillator (24.576 MHz,
  so the UART at 12.288 MHz): the mux must have been 0 when cmu_apm
  registered, then changed. The serial driver then programmed a baud divisor
  16x too small.
- A module calling `clk_set_parent(mout_apm_func, mout_apm_funcsrc)`, which
  rewrites the value the hardware already held, fixed the tree (UART
  196608000).
- With that, UBRDIV `0x69` and UFRACVAL `0xa` give 115200 baud; TX drains
  (UTRSTAT `0x6`), RX stays empty, and hci0 still times out on `0xfc18` and
  HCI_Reset. So the clock was one bug, not the only one.
- Listing `/sys/kernel/debug/pinctrl/*/pins` aborted the SoC (AGENTS.md
  gotcha); rebooted.

- Pins, from a single read of the alive pinctrl bank (powered): gpa3 CON
  `0x2222`, so all four UART pins are in function 2.
- So the UART side (registers, pins, clock once fixed) is right, and the
  silence is on the chip's side: power-up sequence, wake lines or rails.

## 3. Next (gated, with the human there)

1. **Read only:** CMU_APM's mux, divider and the UART gate registers
   (cheetah BT1.1 decoding: bit 28 auto-gating, bit 20 manual, bit 21
   value), through the clock driver's debugfs or raw reads of a block now
   proven readable. Confirm that the UART's IPCLK runs.
2. **Loopback** (cheetah BT1.2, `tools/bt-uart-test`): the UART node
   without the bluetooth child, TX looped to RX, at 115200 and 3000000.
   This separates the UART from the chip.
3. The chip's power-up. Google's `nitrous.c` (GPL, google-modules/bluetooth/
   broadcom, raviole android14) on rfkill unblock does:
   - REG_ON low, 30 ms, REG_ON high;
   - DEV_WAKE high;
   - timesync on;
   - 10-20 ms wait.

   Timesync (gpp11-1, raven only) is an input IRQ from the chip, so it is
   not needed for power-up. **Test first:** a clean REG_ON low-high cycle
   before hci_uart opens: the GPIO read high before hci_bcm took it, so the
   chip may have been left on in some state. Then check the host-wake
   (gpa6-6) and device-wake polarities.
4. Make the clock fix permanent: re-parent `mout_apm_func` to
   `mout_apm_funcsrc` (197 MHz, as on cheetah), or have the clock driver
   re-read the mux. **Risk: boot hang.** The
   mux also clocks the alive pinctrl and the APM mailbox, so the first try
   must be by hand (a module), never a DTB that every boot uses.

**BT2 passes (2026-10-15):**
- `tools/bt-uart-test hci --tty /dev/ttySAC1 --wake gpp14:3` (DT child
  disabled for one boot): HCI_Reset passes, HCI 10, LMP subversion `0x6209`,
  chip id 170.
- `patch` (new): the 3038 Write RAM records stream with no answer to any
  of them; Launch RAM is answered and the version reads `0x20cb` after it.
  At 115200 that takes 41.5 s, at 3 Mbaud 1.7 s.
- Through the kernel: btattach loads the patch at 115200 and the HCI core's
  2 s command timer fires on Launch RAM, so it cannot work. The serdev
  path sets 3 Mbaud before the download and, with
  `btbcm.patchram_nowait=1` (cheetah's option, now `4a245b278`), loads the
  patch.
- The clock fix is permanent as `assigned-clock-parents` on usi_apm1
  (`014e0672a`). After a cold boot, `dout_apm_usi1_uart` reads 196608000
  and Bluetooth comes up by itself.
- Android's `bt_vendor.conf` has `FastDownloadDisable = false` and
  `BigHammerBtRegOnDelay = 100`. The vendor image also has `BTFW_B.hcd` and
  `BTFW_D.hcd`; `BCM.hcd` is the one in use.
- **The shell's tile (same day):** after boot the tile read Off while the
  adapter was powered. Omarchy's shell started before the adapter appeared
  (about 11 s into boot, once the patch loaded) and never picked it up; a
  shell restart fixed it. omamobile-device-raven 0.1.2: an sddm drop-in
  waits up to 15 s for a powered hci0 (`omamobile-wait-bluetooth`). On the
  next boot sddm waited about 7 s and the tile is right.
