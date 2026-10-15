<!-- SPDX-License-Identifier: MIT -->
# Pixel 6 Pro (raven): GPU

Status (2026-10-14): **the Mali-G78 renders Omarchy through Panfrost**
(GLES 3.1, Hyprland on top) and panfrost loads at boot. Kernel branch
`omamobile-raven-gpu` (worktree `~/android/mainline/wt-raven`, output
`~/android/mainline/out-raven`), `7.3.0-rc6-omamobile-push1-g4fd3f0dd1ecf`;
Mesa from `packages/mesa` with the G78 patch. No GPU DVFS yet, and PanVK
refuses the G78.

## 1. Goal

1. Hyprland and Chromium on the GPU instead of llvmpipe (done).
2. GPU DVFS through ACPM, as cheetah's [GPU-PLAN](../cheetah/GPU-PLAN.md).
3. Vulkan (PanVK), once Mesa supports the G78 there.

## 2. Facts

- [V] Mali-G78 MC20, GPU_ID 0x9202 r0p1 (Arm's tBEx): a Valhall v9.2
  job-manager GPU, so **Panfrost, not Panthor** (cheetah's G710 is a CSF
  GPU on Panthor).
- [V] The G3D power domain is up after ABL: panfrost reads the GPU's
  registers at probe without a power-domain driver.
- [V] Neither upstream panfrost nor postmarketOS's knew the G78 (the only
  Valhall model was the G57): `GPU model not found: mali-unknown id rev
  0x9202 0x10`. Arm's kbase lists nearly the same features and issues for
  tBEx and tNAx (the G57).
- [V] Mesa 26.2.4 has no G78 in its model table either, so the Gallium
  driver refuses the GPU and the session falls back to llvmpipe.

## 3. What was built

| Where | Change |
| --- | --- |
| `omamobile-raven-gpu` `94a571672` | gs101 GPU node (raven) and panfrost's gs101 match |
| `fbb7b6c75` (+ fixup `7ba71bf34`) | drm/panfrost: add the Mali-G78, matched on its masked ID 0x9002 with G57's features and `TTRX_2968_TTRX_3162` |
| `c91469c1c` | drm/panfrost: gs101 uses the AArch64 page table format |
| `e01f31ddd` | drm/panfrost: program `GPU_COHERENCY_ENABLE` |
| `packages/mesa` 0003 | the G78 (and upstream's G68) in Panfrost's model table |
| `omamobile-device-raven` | panfrost loads at boot (no longer blacklisted) |

## 4. Results

- **First probe** (kernel `g94a5716728ce`, log streamed, watchdog feeder
  armed): panfrost probed, read the GPU's registers and stopped at the
  unknown model. Parked with panfrost blacklisted until the model entries
  existed.
- **First render** (2026-10-14, `g4fd3f0dd1ecf`): Hyprland on the G78,
  much faster than llvmpipe, but black lines and no wallpaper, with
  `DATA_INVALID_FAULT` on every fragment job. A headless GLES probe
  (`PAN_MESA_DEBUG=sync,trace`) showed the faulting job header read back
  with job type 0; no Mesa debug option changed it, nor did disabling
  flush reduction.
- **Cause:** gs101 used panfrost's legacy Mali LPAE page tables. Every
  G57 SoC entry (mt8188, mt8192, mt8370) sets
  `GPU_QUIRK_FORCE_AARCH64_PGTABLE`. With it on gs101, clears, solid,
  blended and textured draws up to 4096x4096 give the right pixels and no
  faults. Also, `GPU_COHERENCY_ENABLE` read 0 (ACE-Lite) at probe and
  panfrost never wrote it; it now programs the selected mode (NONE).
- **Now:** `Mali-G78 MC20 (Panfrost)`, GLES 3.1; panfrost loads at boot.
  PanVK still refuses the G78 (`panvk_physical_device.c:421`).
- Mesa was built for the phone in an emulated arm64 container on the
  laptop, in about 1 h (`tools/build-packages --all` does the same).

## 5. Open

- GPU DVFS: the G3D clock comes from ACPM (cheetah's `clk_acpm` path);
  until then the GPU runs at ABL's rate.
- PanVK support for the G78 in Mesa.
