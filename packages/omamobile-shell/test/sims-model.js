// SPDX-License-Identifier: MIT
// node test/sims-model.js: the SIMs page's decisions.
const assert = require("assert")
const m = require("../plugins/omamobile.quicksettings/SimsModel.js")

const listed = m.parse(JSON.stringify({
  sims: [
    { number: 1, label: "SIM 1 (tray)", state: "ready", stage: "running", operator: "", tech: "EDGE", registration: "home", data: false },
    { number: 2, label: "SIM 2 (eSIM)", state: "pin", stage: "sim", operator: "", tech: "", registration: "unknown", data: true }
  ],
  defaults: { data: 2, calls: 2, texts: 1 }
}))
assert.strictEqual(listed.sims.length, 2)
assert.strictEqual(listed.defaults.texts, 1)
assert.strictEqual(m.parse("nope"), null)
assert.strictEqual(m.parse("{}"), null)

assert.strictEqual(m.statusText(listed.sims[0]), "EDGE")
assert.strictEqual(m.statusText(listed.sims[1]), "Needs its PIN")
assert.strictEqual(m.statusText({ stage: "off" }), "Off")
assert.strictEqual(m.statusText({ state: "ready", registration: "roaming", operator: "Op", tech: "LTE" }), "Op · LTE · roaming")
assert.strictEqual(m.statusText({ state: "ready", stage: "registering", registration: "unknown" }), "Starting…")
assert.ok(m.needsPin(listed.sims))
assert.ok(!m.needsPin([listed.sims[0]]))

assert.deepStrictEqual(m.KINDS.map(k => k.id), ["data", "calls", "texts"])
assert.deepStrictEqual(m.setArgv("data", 2), ["omamobile-sit", "sims", "set", "data", "2"])
console.log("ok - SIMs page model")
