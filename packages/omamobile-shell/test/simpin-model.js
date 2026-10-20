// SPDX-License-Identifier: MIT
// node test/simpin-model.js: the SIM PIN sheet's decisions.
const assert = require("assert")
const m = require("../plugins/omamobile.simpin/SimPinModel.js")

const state = (sim) => JSON.stringify({ modem: { stage: "sim", sim: sim } })
const pin2 = m.parseState(state({ state: "pin", pin_retries: 3, label: "SIM 2 (eSIM)" }), 2)
assert.deepStrictEqual(pin2, { number: 2, state: "pin", label: "SIM 2 (eSIM)", pinRetries: 3 })
assert.strictEqual(m.parseState("", 1), null)
assert.strictEqual(m.parseState("{}", 1), null)
assert.strictEqual(m.parseState(state({}), 1).label, "SIM 1")
const ready1 = m.parseState(state({ state: "ready", label: "SIM 1 (tray)" }), 1)

// Asks for the first SIM that wants its PIN, unless put off.
assert.strictEqual(m.current([ready1, pin2], []), pin2)
assert.strictEqual(m.current([ready1, pin2], [2]), null)
assert.strictEqual(m.current([null, null], []), null)
const pin1 = m.parseState(state({ state: "pin", pin_retries: 2 }), 1)
assert.strictEqual(m.current([pin1, pin2], []), pin1)
assert.strictEqual(m.current([pin1, pin2], [1]), pin2)
// No tries left: nothing to ask (the PUK isn't the sheet's job).
assert.strictEqual(m.current([m.parseState(state({ state: "pin", pin_retries: 0 }), 1)], []), null)

// "Not now" lasts while that SIM still asks.
assert.deepStrictEqual(m.prune([1, 2], [ready1, pin2]), [2])
assert.deepStrictEqual(m.prune([2], [ready1, null]), [])

// The keypad and the PIN.
assert.strictEqual(m.press("123", "4"), "1234")
assert.strictEqual(m.press("12345678", "9"), "12345678")
assert.strictEqual(m.press("12", "back"), "1")
assert.strictEqual(m.press("", "x"), "")
assert.ok(m.validPin("1234") && m.validPin("12345678"))
assert.ok(!m.validPin("123") && !m.validPin("123456789") && !m.validPin("12a4"))

// The PIN never goes on argv; the last try is asked for explicitly.
assert.deepStrictEqual(m.pinArgv(2, false), ["omamobile-sit", "--sim", "2", "sim-pin", "--stdin"])
assert.deepStrictEqual(m.pinArgv(1, true).slice(-1), ["--last-try"])
assert.strictEqual(m.triesText(3), "3 tries left")
assert.ok(/Last try/.test(m.triesText(1)))
assert.strictEqual(m.triesText(-1), "")

// Outcomes.
assert.strictEqual(m.failureMessage(0, "unlocked\n", ""), "")
assert.strictEqual(m.failureMessage(1, "", "omamobile-sit: Wrong PIN\n"), "Wrong PIN")
assert.strictEqual(m.failureMessage(1, "", "omamobile-sit: The SIM is not asking for its PIN\n"), "")
assert.strictEqual(m.failureMessage(1, "", "omamobile-sit: [Errno 2] No such file or directory\n"), "Couldn't reach the modem")
console.log("ok - SIM PIN sheet model")
