// SPDX-License-Identifier: MIT
import QtQuick
import Quickshell
import Quickshell.Bluetooth
import Quickshell.Io
import Quickshell.Networking
import Quickshell.Services.UPower
import Quickshell.Wayland
import qs.Commons
import qs.Commons as Commons
import "StatusModel.js" as StatusModel

// Phone status bar, a full `bar` option that replaces omarchy.bar.
//
// The phone has no window list, tray or workspaces to show, so this bar only
// reports state: the clock on the left and connectivity, do-not-disturb and
// battery on the right. The middle stays empty for the camera cutout. The
// whole strip is one touch target: a tap or a downward pull opens the quick
// settings sheet.
Item {
  id: root

  // Injected by the host (see shell.qml configureBar).
  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property var shell: null
  property var manifest: null
  property var barWidgetRegistry: null
  property var pluginRegistry: null
  property var barConfig: ({})

  // Scalar bar state the host mirrors to other plugins (notifications and the
  // OSD place themselves clear of the bar with these).
  readonly property bool barHidden: false
  readonly property string position: "top"
  readonly property bool vertical: false
  readonly property string fontFamily: Style.font.family
  // A phone status bar is a touch target, and the Pixel's camera cutout sits
  // in it, so it is never thinner than 44 logical px.
  readonly property int barSize: Math.max(44, Style.bar.sizeHorizontal)

  readonly property color foreground: Commons.Color.bar.text
  readonly property color background: Commons.Color.bar.background
  readonly property color urgent: Commons.Color.bar.active

  function setting(name, fallback) {
    var value = barConfig ? barConfig[name] : undefined
    return value === undefined || value === null || value === "" ? fallback : value
  }

  readonly property string clockFormat: String(setting("clockFormat", "HH:mm"))
  readonly property bool showBatteryPercent: setting("showBatteryPercent", true) !== false
  readonly property string quickSettingsId: String(setting("quickSettings", "omamobile.quicksettings"))

  // A full bar may read the notification service's do-not-disturb state
  // through the host's narrow proxy.
  readonly property var notifications: shell && typeof shell.firstPartyServiceFor === "function"
    ? shell.firstPartyServiceFor("omarchy.notifications") : null
  readonly property bool doNotDisturb: notifications ? notifications.doNotDisturb === true : false

  // ---------------------------------------------------------------- state

  SystemClock {
    id: clock
    precision: SystemClock.Minutes
  }

  readonly property var networkDevices: Networking.devices ? Networking.devices.values : []
  readonly property var wifiDevice: StatusModel.findDevice(networkDevices, DeviceType.Wifi)
  readonly property var wiredDevice: StatusModel.findDevice(networkDevices, DeviceType.Wired)
  readonly property var wifiNetwork: StatusModel.connectedNetwork(wifiDevice && wifiDevice.networks ? wifiDevice.networks.values : [])
  readonly property string networkKind: {
    if (wiredDevice && wiredDevice.connected) return "ethernet"
    if (wifiNetwork) return "wifi"
    return wifiDevice && !Networking.wifiEnabled ? "off" : "disconnected"
  }
  readonly property string networkIcon: StatusModel.networkIcon(networkKind,
    wifiNetwork ? Math.round((wifiNetwork.signalStrength || 0) * 100) : -1)

  // Cellular: omamobile-sitd's public state per SIM (omamobile-modem-sit;
  // SIM 2's files end in -2), polled since sitd replaces them by renaming.
  // The bar shows the data SIM's generation ("4G") and one row of 4 bars
  // per SIM, stacked as Android shows two SIMs.
  property var sims: [null, null]
  property int dataSim: 1
  readonly property QtObject cellular: QtObject {
    readonly property bool available: root.sims[0] !== null || root.sims[1] !== null
    readonly property string generation: StatusModel.generationLabel(root.sims, root.dataSim)
  }

  FileView {
    id: sim1State
    path: "/run/omamobile-sit/state.json"
    printErrors: false
    onLoaded: root.sims = [StatusModel.parseSim(text()), root.sims[1]]
    onLoadFailed: root.sims = [null, root.sims[1]]
  }

  FileView {
    id: sim2State
    path: "/run/omamobile-sit-2/state.json"
    printErrors: false
    onLoaded: root.sims = [root.sims[0], StatusModel.parseSim(text())]
    onLoadFailed: root.sims = [root.sims[0], null]
  }

  FileView {
    id: simsConf
    path: "/etc/omamobile/sims.conf"
    printErrors: false
    onLoaded: root.dataSim = StatusModel.dataSim(text())
    onLoadFailed: root.dataSim = 1
  }

  Timer {
    interval: 3000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: { sim1State.reload(); sim2State.reload(); simsConf.reload() }
  }

  readonly property var btAdapter: Bluetooth.defaultAdapter
  readonly property bool bluetoothConnected: {
    var devices = Bluetooth.devices ? Bluetooth.devices.values : []
    for (var i = 0; i < devices.length; i++)
      if (devices[i] && devices[i].connected) return true
    return false
  }

  readonly property var battery: UPower.displayDevice
  readonly property bool hasBattery: !!battery && battery.isPresent === true
  readonly property int batteryPercent: hasBattery ? Math.round(battery.percentage * 100) : -1
  readonly property bool charging: hasBattery && !UPower.onBattery
  readonly property string batteryIcon: StatusModel.batteryIcon(batteryPercent, charging,
    hasBattery && battery.state === UPowerDeviceState.FullyCharged)

  // ---------------------------------------------------------------- host API

  // The host calls these on whatever bar is active. A phone bar hosts no
  // widget panels, so every per-widget route answers "not here".
  function summonBarWidget(id) { return false }
  function hideBarWidget(id) { return false }
  function isBarWidgetOpen(id) { return false }
  function panelWidgetIdAt(section, index) { return "" }
  function debugBarGeometry() { return [{ position: position, size: barSize }] }

  function openQuickSettings() {
    if (shell && typeof shell.summon === "function")
      shell.summon(quickSettingsId, JSON.stringify({ source: "bar" }))
  }

  function toggleQuickSettings() {
    if (shell && typeof shell.toggle === "function")
      shell.toggle(quickSettingsId, JSON.stringify({ source: "bar" }))
  }

  // Edge-swipe gestures and hardware keys reach the sheet through here, e.g.
  // `omarchy-shell omamobile.bar pullDown` from a Hyprland gesture bind.
  IpcHandler {
    target: "omamobile.bar"

    function pullDown(): string {
      root.openQuickSettings()
      return "ok"
    }

    function toggleQuickSettings(): string {
      root.toggleQuickSettings()
      return "ok"
    }

    // What the cellular icon draws from, for debugging: both SIMs as parsed
    // and the data SIM.
    function cellular(): string {
      return JSON.stringify({ sims: root.sims, dataSim: root.dataSim, generation: root.cellular.generation })
    }
  }

  // ---------------------------------------------------------------- surface

  Variants {
    model: Quickshell.screens

    PanelWindow {
      id: barWindow

      required property var modelData
      screen: modelData

      anchors { top: true; left: true; right: true }
      implicitHeight: root.barSize
      exclusionMode: ExclusionMode.Auto
      color: root.background
      WlrLayershell.namespace: "omarchy-bar"
      WlrLayershell.layer: WlrLayer.Top

      Item {
        anchors.fill: parent
        anchors.leftMargin: Style.spacing.huge
        anchors.rightMargin: Style.spacing.huge

        Text {
          id: clockText
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          textFormat: Text.PlainText
          text: Qt.formatDateTime(clock.date, root.clockFormat)
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.title
          font.bold: true
        }

        Row {
          id: status
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.spacing.xl

          StatusGlyph {
            visible: root.doNotDisturb
            text: "󰂛"
          }

          StatusGlyph {
            visible: !!root.btAdapter && root.btAdapter.enabled
            text: root.bluetoothConnected ? "󰂱" : "󰂯"
          }

          Row {
            visible: root.cellular.available
            spacing: Style.spacing.xs
            anchors.verticalCenter: parent.verticalCenter

            Text {
              visible: text !== ""
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: root.cellular.generation
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Math.round(Style.font.iconLarge * 0.6)
              font.bold: true
            }

            // One signal icon for both SIMs, as Android stacks them: four
            // rising columns, each split in two, the top half lit for SIM 1's
            // bars and the bottom half for SIM 2's. One SIM: whole columns.
            SignalStack {
              anchors.verticalCenter: parent.verticalCenter
              height: Math.round(Style.font.iconLarge * 0.8)
              // The data SIM's bars rise; the other SIM's sit under them.
              upper: root.sims[root.dataSim - 1]
              lower: root.sims[2 - root.dataSim]
            }
          }

          StatusGlyph {
            visible: root.networkIcon !== ""
            text: root.networkIcon
            opacity: root.networkKind === "off" || root.networkKind === "disconnected" ? 0.55 : 1
          }

          Row {
            visible: root.hasBattery
            spacing: Style.spacing.xs
            anchors.verticalCenter: parent.verticalCenter

            StatusGlyph {
              text: root.batteryIcon
              color: root.batteryPercent >= 0 && root.batteryPercent <= 10 && !root.charging ? root.urgent : root.foreground
            }

            Text {
              visible: root.showBatteryPercent
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: root.batteryPercent + "%"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
            }
          }
        }
      }

      // The whole strip is the touch target. A downward pull past a small
      // threshold opens the sheet; a tap toggles it.
      MouseArea {
        id: touch
        anchors.fill: parent
        property real pressY: 0
        property bool pulled: false
        readonly property real pullThreshold: Style.space(14)

        onPressed: function(mouse) { pressY = mouse.y; pulled = false }
        onPositionChanged: function(mouse) {
          if (!pulled && mouse.y - pressY > pullThreshold) {
            pulled = true
            root.openQuickSettings()
          }
        }
        onClicked: if (!pulled) root.toggleQuickSettings()
      }
    }
  }

  // As Android stacks two SIMs in one icon: the data SIM's four bars rising
  // left to right, and under them the other SIM's four as a row of short
  // bars, all one height. One SIM: its rising bars fill the icon. Unlit bars, and a SIM
  // off any network, are dim.
  component SignalStack: Column {
    id: stack
    property var upper: null
    property var lower: null
    readonly property bool both: upper !== null && lower !== null
    readonly property var main: upper !== null ? upper : lower
    readonly property int gap: 2
    readonly property int lowHeight: both ? Math.max(2, Math.round(height * 0.2)) : 0
    function lit(sim, index) { return sim !== null && sim.registered && index < sim.bars }
    spacing: both ? gap : 0

    Row {
      id: rising
      spacing: 1
      height: stack.height - stack.lowHeight - stack.spacing
      Repeater {
        model: 4
        delegate: Rectangle {
          required property int index
          width: 3
          height: Math.max(2, Math.round(rising.height * (index + 1) / 4))
          anchors.bottom: parent.bottom
          radius: 0.5
          color: root.foreground
          opacity: stack.lit(stack.main, index) ? 1 : 0.3
        }
      }
    }

    Row {
      visible: stack.both
      spacing: 1
      height: stack.lowHeight
      Repeater {
        model: 4
        delegate: Rectangle {
          required property int index
          width: 3
          height: stack.lowHeight
          radius: 0.5
          color: root.foreground
          opacity: stack.lit(stack.lower, index) ? 1 : 0.3
        }
      }
    }
  }

  component StatusGlyph: Text {
    anchors.verticalCenter: parent ? parent.verticalCenter : undefined
    textFormat: Text.PlainText
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.iconLarge
  }
}
