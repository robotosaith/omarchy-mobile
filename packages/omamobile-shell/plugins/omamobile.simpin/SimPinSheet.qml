// SPDX-License-Identifier: MIT
import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "SimPinModel.js" as SimPinModel

// The SIM PIN sheet itself: the scrim, and the card at the bottom with the
// SIM's glyph and name, the PIN so far, a keypad and two buttons. It looks
// like the permission sheet, not like the lock screen, and says which PIN
// it wants. SimPin.qml puts it in its layer-shell window.
Item {
  id: sheet

  // A SIM as SimPinModel.parseState gives it (null: nothing to show).
  property var sim: null
  // 0 hidden .. 1 shown: the card slides up from the bottom edge.
  property real reveal: 1
  property bool busy: false
  property string pin: ""
  property string message: ""
  signal submitted(string pin)
  signal putOff()

  readonly property int pad: Style.spacing.panelPadding
  readonly property color foreground: Commons.Color.popups.text
  readonly property bool lastTry: sim !== null && sim.pinRetries === 1
  readonly property int keyHeight: Math.max(52, Style.space(52))

  Rectangle {
    anchors.fill: parent
    color: Commons.Color.menu.scrim
    opacity: sheet.reveal
  }

  // The scrim takes touches: "Not now" is the way out.
  MouseArea { anchors.fill: parent }

  BorderSurface {
    id: card

    readonly property var s: sheet.sim || ({})

    x: Style.gapsOut
    width: parent.width - Style.gapsOut * 2
    height: content.implicitHeight + card.contentTopInset + card.contentBottomInset
    y: parent.height - height - Style.gapsOut + Math.round((1 - sheet.reveal) * (height + Style.gapsOut))
    color: Commons.Color.popups.background
    borderSpec: Border.surfaceSpec("popups", "border", Commons.Color.popups.border, Math.max(1, Style.space(2)))
    radius: Style.cornerRadius
    padding: sheet.pad

    MouseArea { anchors.fill: parent }

    Column {
      id: content
      x: card.contentLeftInset
      y: card.contentTopInset
      width: card.width - card.contentLeftInset - card.contentRightInset
      spacing: Style.spacing.lg
      topPadding: Style.spacing.md

      // The SIM's glyph, as the permission sheet shows an app's icon.
      Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        width: 64
        height: 64
        radius: Math.max(Style.cornerRadius, 16)
        color: Qt.rgba(sheet.foreground.r, sheet.foreground.g, sheet.foreground.b, 0.06)

        Text {
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: "󰘚"
          color: Commons.Color.accent
          font.family: Style.font.family
          font.pixelSize: Style.font.displayLarge
        }
      }

      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        textFormat: Text.PlainText
        text: card.s.label || "SIM"
        color: sheet.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.display
        font.bold: true
        wrapMode: Text.Wrap
      }

      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        textFormat: Text.PlainText
        text: "Enter the SIM card's PIN to use this SIM. It is not your phone's unlock PIN."
        color: sheet.foreground
        opacity: 0.75
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        lineHeight: 1.15
        wrapMode: Text.Wrap
      }

      Text {
        width: parent.width
        visible: text !== ""
        horizontalAlignment: Text.AlignHCenter
        textFormat: Text.PlainText
        text: sheet.message !== "" ? sheet.message : SimPinModel.triesText(card.s.pinRetries)
        color: sheet.message !== "" || sheet.lastTry ? Commons.Color.urgent : sheet.foreground
        opacity: sheet.message !== "" || sheet.lastTry ? 1 : 0.6
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        font.bold: sheet.message !== "" || sheet.lastTry
        wrapMode: Text.Wrap
      }

      // The PIN so far, as dots.
      BorderSurface {
        width: parent.width
        height: sheet.keyHeight
        radius: Style.cornerRadius
        color: Style.normalFillFor(sheet.foreground, Commons.Color.accent)
        borderSpec: Border.controlSpec("normal", sheet.foreground, Commons.Color.accent)

        Text {
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: sheet.busy ? "Checking…" : sheet.pin.length > 0 ? "●".repeat(sheet.pin.length) : "SIM PIN"
          color: sheet.foreground
          opacity: sheet.pin.length > 0 || sheet.busy ? 1 : 0.45
          font.family: Style.font.family
          font.pixelSize: sheet.pin.length > 0 ? Style.font.display : Style.font.heading
          font.letterSpacing: sheet.pin.length > 0 ? 6 : 0
        }
      }

      Grid {
        id: keys
        width: parent.width
        columns: 3
        spacing: Style.spacing.sm
        readonly property real keyWidth: (width - spacing * 2) / 3

        Repeater {
          model: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "back"]

          Key {
            required property string modelData
            width: keys.keyWidth
            height: sheet.keyHeight
            label: modelData === "back" ? "󰭜" : modelData
            visible: modelData !== ""
            enabled: !sheet.busy
            onTapped: {
              sheet.message = ""
              sheet.pin = SimPinModel.press(sheet.pin, modelData)
            }
          }
        }
      }

      Item { width: 1; height: Style.spacing.xs }

      AnswerButton {
        width: parent.width
        label: sheet.lastTry ? "Use the last try" : "Unlock SIM"
        primary: true
        enabled: !sheet.busy && SimPinModel.validPin(sheet.pin)
        opacity: enabled ? 1 : 0.45
        onTapped: sheet.submitted(sheet.pin)
      }

      AnswerButton {
        width: parent.width
        label: "Not now"
        enabled: !sheet.busy
        onTapped: {
          sheet.pin = ""
          sheet.putOff()
        }
      }
    }
  }

  // ---------------------------------------------------------------- pieces

  component Key: BorderSurface {
    id: key
    property string label: ""
    property color foreground: Commons.Color.popups.text
    signal tapped()
    radius: Style.cornerRadius
    color: touch.pressed ? Style.pressedFillFor(key.foreground, Commons.Color.accent)
      : Style.normalFillFor(key.foreground, Commons.Color.accent)
    borderSpec: Border.controlSpec("normal", key.foreground, Commons.Color.accent)

    Text {
      anchors.centerIn: parent
      textFormat: Text.PlainText
      text: key.label
      color: key.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.display
    }

    MouseArea {
      id: touch
      anchors.fill: parent
      enabled: key.enabled
      onClicked: key.tapped()
    }
  }

  component AnswerButton: BorderSurface {
    id: button
    property string label: ""
    property bool primary: false
    property color foreground: Commons.Color.popups.text
    readonly property int touchSize: Math.max(56, Style.space(56))
    signal tapped()
    height: button.touchSize
    radius: Style.cornerRadius
    color: touch.pressed ? Style.pressedFillFor(button.foreground, Commons.Color.accent)
      : button.primary ? Util.alpha(Commons.Color.accent, Style.selectedFillAlpha)
      : Style.normalFillFor(button.foreground, Commons.Color.accent)
    borderSpec: Border.controlSpec(button.primary ? "selected" : "normal", button.foreground, Commons.Color.accent)

    Text {
      anchors.centerIn: parent
      width: parent.width - Style.spacing.lg * 2
      horizontalAlignment: Text.AlignHCenter
      textFormat: Text.PlainText
      text: button.label
      color: button.primary ? Commons.Color.accent : button.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.heading
      font.bold: true
      elide: Text.ElideRight
    }

    MouseArea {
      id: touch
      anchors.fill: parent
      enabled: button.enabled
      onClicked: button.tapped()
    }
  }
}
