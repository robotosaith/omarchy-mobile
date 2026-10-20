// SPDX-License-Identifier: MIT
// The SIMs page's decisions, kept free of QML so test/sims-model.js runs
// them under Node through the module.exports below.

// `omamobile-sit sims --json` (omamobile-modem-sit): both SIMs and which
// one does data, calls and texts. null when unusable.
function parse(text) {
  var value
  try { value = JSON.parse(String(text || "")) } catch (e) { return null }
  if (!value || !Array.isArray(value.sims)) return null
  var sims = value.sims.filter(function(s) { return s && (s.number === 1 || s.number === 2) })
  return { sims: sims, defaults: value.defaults || {} }
}

// One line under a SIM's name: what it is doing now.
function statusText(sim) {
  if (!sim) return ""
  if (sim.stage === "off") return "Off"
  if (sim.state === "pin") return "Needs its PIN"
  if (sim.state === "puk") return "Locked: needs its PUK"
  if (sim.state === "absent") return "No SIM"
  var reg = sim.registration
  if (reg === "home" || reg === "roaming") {
    var words = [sim.operator, sim.tech].filter(function(w) { return w })
    if (reg === "roaming") words.push("roaming")
    return words.length ? words.join(" · ") : "Connected"
  }
  if (sim.stage && sim.stage !== "running") return "Starting…"
  return "No network"
}

// The sections: a picker each, over the SIMs.
var KINDS = [
  { id: "data", title: "Mobile data", hint: "Switching restarts both SIMs (about 30 s)" },
  { id: "calls", title: "Calls", hint: "" },
  { id: "texts", title: "Texts", hint: "" }
]

// The command for a choice; polkit lets the active local user start it.
function setArgv(kind, number) {
  return ["omamobile-sit", "sims", "set", String(kind), String(number)]
}

// Whether any SIM is waiting for its PIN (the page then offers the sheet).
function needsPin(sims) {
  return (sims || []).some(function(s) { return s && s.state === "pin" })
}

if (typeof module !== "undefined") {
  module.exports = { parse: parse, statusText: statusText, KINDS: KINDS, setArgv: setArgv, needsPin: needsPin }
}
