// SPDX-License-Identifier: MIT
// The SIM PIN sheet's decisions, kept free of QML so test/simpin-model.js
// runs them under Node through the module.exports below.

// Each SIM's public status from omamobile-sitd (omamobile-modem-sit): SIM 1
// is /run/omamobile-sit, SIM 2 /run/omamobile-sit-2.
var STATE_FILES = ["/run/omamobile-sit/state.json", "/run/omamobile-sit-2/state.json"]

// One SIM out of its state.json text; null when the file is missing or
// unusable (no sitd for that SIM).
function parseState(text, number) {
  var value
  try { value = JSON.parse(String(text || "")) } catch (e) { return null }
  var modem = value && value.modem
  if (!modem || typeof modem !== "object") return null
  var sim = modem.sim && typeof modem.sim === "object" ? modem.sim : {}
  var retries = Number(sim.pin_retries)
  return {
    number: number,
    state: typeof sim.state === "string" ? sim.state : "unknown",
    label: typeof sim.label === "string" && sim.label.length > 0 ? sim.label : "SIM " + number,
    pinRetries: isFinite(retries) && retries >= 0 ? retries : -1
  }
}

// The SIM the sheet asks about now: the first one asking for its PIN that
// the user hasn't put off ("Not now"); null when none.
function current(sims, dismissed) {
  for (var i = 0; i < sims.length; i++) {
    var s = sims[i]
    if (s && s.state === "pin" && s.pinRetries !== 0 && (dismissed || []).indexOf(s.number) < 0) return s
  }
  return null
}

// "Not now" lasts until that SIM stops asking (unlocked, or the modem
// restarted): drop the SIMs that no longer ask.
function prune(dismissed, sims) {
  return (dismissed || []).filter(function(n) {
    for (var i = 0; i < sims.length; i++) if (sims[i] && sims[i].number === n && sims[i].state === "pin") return true
    return false
  })
}

// A SIM PIN is 4 to 8 digits.
function validPin(pin) {
  return /^[0-9]{4,8}$/.test(String(pin || ""))
}

// A key press on the keypad: a digit appends (up to 8), "back" deletes.
function press(pin, key) {
  var p = String(pin || "")
  if (key === "back") return p.slice(0, -1)
  if (/^[0-9]$/.test(key) && p.length < 8) return p + key
  return p
}

// The tries line under the title.
function triesText(retries) {
  if (retries === 1) return "Last try: a wrong PIN locks the SIM until its PUK is entered"
  if (retries > 1) return retries + " tries left"
  return ""
}

// The command: the PIN goes on stdin, never on argv. With one try left
// sitd refuses unless asked for the last try, which the sheet's warning
// and button make explicit.
function pinArgv(number, lastTry) {
  var argv = ["omamobile-sit", "--sim", String(number), "sim-pin", "--stdin"]
  if (lastTry) argv.push("--last-try")
  return argv
}

// What the sheet says after a try: "" on success, else a short message.
function failureMessage(exitCode, stdout, stderr) {
  var out = String(stdout || "").trim()
  if (exitCode === 0 && out === "unlocked") return ""
  var err = String(stderr || "")
  if (/Wrong PIN/.test(err)) return "Wrong PIN"
  if (/One PIN try left/.test(err)) return "One try left: confirm to use it"
  if (/PUK/.test(err)) return "The SIM is locked: it needs its PUK"
  if (/not asking for its PIN/.test(err) || out === "ready") return ""
  if (/no try was used/.test(err)) return "The modem didn't take the PIN; no try was used"
  return "Couldn't reach the modem"
}

if (typeof module !== "undefined") {
  module.exports = {
    STATE_FILES: STATE_FILES, parseState: parseState, current: current, prune: prune,
    validPin: validPin, press: press, triesText: triesText, pinArgv: pinArgv,
    failureMessage: failureMessage
  }
}
