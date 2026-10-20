// SPDX-License-Identifier: MIT
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "SimPinModel.js" as SimPinModel

// Asks for a locked SIM's PIN: one bottom sheet per SIM, named by its slot
// ("SIM 2 (eSIM)"), with its own keypad, so it can't be taken for the
// phone's lock screen. omamobile-sitd waits at start-up for the PIN; the
// sheet reads each SIM's public state.json and sends the PIN with
// `omamobile-sit --sim N sim-pin --stdin`.
//
// The window is on the overlay layer, never over the lock screen: at boot
// the phone's own PIN comes first, then the SIMs. "Not now" leaves a SIM
// locked until the modem restarts; `omarchy-shell shell call omamobile.simpin
// ask ''` brings the sheet back.
Item {
  id: root

  // Injected by the host.
  property var shell: null
  property var manifest: null

  property var sims: [null, null]
  property var dismissed: []
  readonly property var current: SimPinModel.current(sims, dismissed)
  readonly property bool opened: current !== null
  // What the sheet last showed, so it doesn't go blank while it slides away.
  property var shown: null
  onCurrentChanged: {
    if (current && (!shown || shown.number !== current.number)) {
      sheet.pin = ""
      sheet.message = ""
    }
    if (current) shown = current
  }

  // ---------------------------------------------------------------- host API

  // Bring back every SIM put off with "Not now".
  function ask() {
    dismissed = []
    return "ok"
  }

  // `shell call omamobile.simpin snapshot ''`, for tests and debugging.
  function snapshot() {
    return JSON.stringify({ opened: opened, current: current, dismissed: dismissed, sims: sims })
  }

  function open(payloadJson) { ask() }
  function close() {}

  // ---------------------------------------------------------------- state

  function setSim(index, sim) {
    var next = sims.slice()
    next[index] = sim
    sims = next
    dismissed = SimPinModel.prune(dismissed, next)
  }

  FileView {
    id: sim1
    path: SimPinModel.STATE_FILES[0]
    printErrors: false
    onLoaded: root.setSim(0, SimPinModel.parseState(text(), 1))
    onLoadFailed: root.setSim(0, null)
  }

  FileView {
    id: sim2
    path: SimPinModel.STATE_FILES[1]
    printErrors: false
    onLoaded: root.setSim(1, SimPinModel.parseState(text(), 2))
    onLoadFailed: root.setSim(1, null)
  }

  // sitd replaces state.json by renaming over it, which a file watch
  // loses: poll instead (two small files).
  Timer {
    interval: 2000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: { sim1.reload(); sim2.reload() }
  }

  // ---------------------------------------------------------------- unlock

  function unlock(pin) {
    var s = current
    if (!s || sender.running || !SimPinModel.validPin(pin)) return
    sender.secret = pin
    sender.number = s.number
    sender.command = SimPinModel.pinArgv(s.number, s.pinRetries === 1)
    sheet.message = ""
    sender.running = true
  }

  Process {
    id: sender
    property string secret: ""
    property int number: 0
    stdinEnabled: true
    onStarted: {
      write(secret + "\n")
      secret = ""
    }
    stdout: StdioCollector { id: senderOut; waitForEnd: true }
    stderr: StdioCollector { id: senderErr; waitForEnd: true }
    onExited: function(exitCode) {
      var message = SimPinModel.failureMessage(exitCode, senderOut.text, senderErr.text)
      sheet.pin = ""
      sheet.message = message
      sim1.reload()
      sim2.reload()
    }
  }

  // ---------------------------------------------------------------- surface

  property real reveal: opened ? 1 : 0
  Behavior on reveal { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

  PanelWindow {
    visible: root.opened || root.reveal > 0
    anchors { top: true; bottom: true; left: true; right: true }
    exclusionMode: ExclusionMode.Ignore
    color: "transparent"
    WlrLayershell.namespace: "omamobile-simpin"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    SimPinSheet {
      id: sheet
      anchors.fill: parent
      sim: root.shown
      reveal: root.reveal
      busy: sender.running
      onSubmitted: function(pin) { root.unlock(pin) }
      onPutOff: if (root.current) root.dismissed = root.dismissed.concat([root.current.number])
    }
  }
}
