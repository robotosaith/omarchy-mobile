// SPDX-License-Identifier: MIT
// Pure helpers for the phone status bar. The glyph sets match Omarchy's own
// network (panels/network/Model.js) and power (panels/power/Model.js) panels,
// so the phone reads the same as the desktop bar.

function findDevice(devices, type) {
  var list = devices || []
  var fallback = null
  for (var i = 0; i < list.length; i++) {
    var device = list[i]
    if (!device || device.type !== type) continue
    if (device.connected) return device
    if (!fallback) fallback = device
  }
  return fallback
}

function connectedNetwork(networks) {
  var list = networks || []
  for (var i = 0; i < list.length; i++)
    if (list[i] && list[i].connected) return list[i]
  return null
}

function wifiIcon(strength) {
  var icons = ["󰤯", "󰤟", "󰤢", "󰤥", "󰤨"]
  var index = Math.max(0, Math.min(4, Math.ceil(strength / 20) - 1))
  return icons[index]
}

// kind: "wifi" | "ethernet" | "off" | "disconnected"
function networkIcon(kind, strength) {
  if (kind === "wifi") return wifiIcon(strength)
  if (kind === "ethernet") return "󰈀"
  if (kind === "off") return "󰤭"
  return "󰤮"
}

function cellularIcon(strength) {
  if (strength < 0) return "󰞃"
  var icons = ["󰢿", "󰢼", "󰢽", "󰢾"]
  return icons[Math.max(0, Math.min(3, Math.floor(strength / 25.01)))]
}

function batteryIcon(percent, charging, full) {
  if (percent < 0) return ""
  if (full) return "󰂅"
  var chargingIcons = ["󰢜", "󰂆", "󰂇", "󰂈", "󰢝", "󰂉", "󰢞", "󰂊", "󰂋", "󰂅"]
  var defaultIcons = ["󰁺", "󰁻", "󰁼", "󰁽", "󰁾", "󰁿", "󰂀", "󰂁", "󰂂", "󰁹"]
  var index = Math.max(0, Math.min(9, Math.floor(percent / 10)))
  return charging ? chargingIcons[index] : defaultIcons[index]
}

// One SIM from omamobile-sitd's public state.json: whether it is on a
// network, its 0-4 bars and its generation ("4G"); null without a file.
function parseSim(text) {
  var v
  try { v = JSON.parse(String(text || "")) } catch (e) { return null }
  var m = v && v.modem
  if (!m) return null
  var registered = m.registration === "home" || m.registration === "roaming"
  var bars = Number(m.signal)
  return {
    registered: registered,
    bars: registered && isFinite(bars) ? Math.max(0, Math.min(4, Math.round(bars))) : 0,
    generation: registered && typeof m.generation === "string" ? m.generation : "",
    roaming: m.registration === "roaming"
  }
}

// The data SIM from /etc/omamobile/sims.conf ("data = 2"); 1 by default.
function dataSim(text) {
  var m = /^\s*data\s*=\s*([12])\s*$/m.exec(String(text || ""))
  return m ? Number(m[1]) : 1
}

// The label next to the meter: the data SIM's generation, else the other's.
function generationLabel(sims, data) {
  var first = sims[data - 1], other = sims[2 - data]
  if (first && first.generation) return first.generation
  return other && other.generation ? other.generation : ""
}

