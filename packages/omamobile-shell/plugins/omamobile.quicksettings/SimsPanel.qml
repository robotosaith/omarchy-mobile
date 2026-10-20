// SPDX-License-Identifier: MIT
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "SimsModel.js" as SimsModel

// The page behind the Mobile data tile's long-press, as Android's "SIMs":
// which SIM does mobile data, calls and texts. It reads `omamobile-sit sims
// --json` while open and sets a choice with `omamobile-sit sims set KIND N`
// (omamobile-sims-set@.service; polkit lets the active local user start it).
// Moving mobile data restarts both SIM services, about 30 s.
Item {
  id: root

  property bool opened: false
  property color foreground: Commons.Color.popups.text

  // The back glyph: the owner closes this and brings quick settings back.
  signal backRequested()

  readonly property int touchSize: Math.max(44, Style.space(48))
  readonly property int pad: Style.spacing.panelPadding

  property var sims: []
  property var defaults: ({})
  // "kind" while its change runs, else "".
  property string pending: ""
  property string message: ""

  function open() { opened = true; refresh() }
  function close() { opened = false }

  function refresh() { if (!reader.running) reader.running = true }

  function choose(kind, number) {
    if (pending !== "" || Number(defaults[kind]) === number) return
    pending = kind
    message = kind === "data" ? "Moving mobile data to SIM " + number + "…" : ""
    setter.command = SimsModel.setArgv(kind, number)
    setter.running = true
  }

  Process {
    id: reader
    command: ["omamobile-sit", "sims", "--json"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var v = SimsModel.parse(text)
        if (!v) return
        root.sims = v.sims
        root.defaults = v.defaults
      }
    }
  }

  Process {
    id: setter
    stderr: StdioCollector { id: setterErr; waitForEnd: true }
    onExited: function(exitCode) {
      root.message = exitCode === 0 ? "" : "Couldn't change it"
      root.pending = ""
      root.refresh()
    }
  }

  Timer {
    interval: 3000
    running: root.opened
    repeat: true
    onTriggered: root.refresh()
  }

  property real reveal: opened ? 1 : 0
  Behavior on reveal { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

  PanelWindow {
    id: window

    visible: root.opened || root.reveal > 0
    anchors { top: true; bottom: true; left: true; right: true }
    exclusionMode: ExclusionMode.Normal
    color: "transparent"
    WlrLayershell.namespace: "omamobile-sims"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.keyboardFocus: root.opened ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None

    Rectangle {
      anchors.fill: parent
      color: Commons.Color.menu.scrim
      opacity: root.reveal
    }

    MouseArea {
      anchors.fill: parent
      onClicked: root.close()
    }

    BorderSurface {
      id: panel

      x: Style.gapsOut
      width: parent.width - Style.gapsOut * 2
      height: parent.height - Style.gapsOut * 2
      y: Style.gapsOut + Math.round((1 - root.reveal) * Style.space(60))
      opacity: root.reveal
      color: Commons.Color.popups.background
      borderSpec: Border.surfaceSpec("popups", "border", Commons.Color.popups.border, Math.max(1, Style.space(2)))
      radius: Style.cornerRadius
      padding: root.pad

      focus: root.opened
      Keys.onEscapePressed: root.close()

      // Swallow taps so they don't reach the scrim.
      MouseArea { anchors.fill: parent }

      Item {
        id: body
        anchors.fill: parent
        anchors.topMargin: panel.contentTopInset
        anchors.rightMargin: panel.contentRightInset
        anchors.bottomMargin: panel.contentBottomInset
        anchors.leftMargin: panel.contentLeftInset

        // ---------- Header: back and title
        Item {
          id: header
          anchors.top: parent.top
          anchors.left: parent.left
          anchors.right: parent.right
          height: root.touchSize

          GlyphButton {
            id: back
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            glyph: "󰁍"
            onTapped: root.backRequested()
          }

          Text {
            anchors.left: back.right
            anchors.leftMargin: Style.spacing.lg
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: "SIMs"
            color: root.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.title
            font.bold: true
            elide: Text.ElideRight
          }
        }

        Flickable {
          id: scroller
          anchors.top: header.bottom
          anchors.topMargin: root.pad
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: pinButton.visible ? pinButton.top : parent.bottom
          anchors.bottomMargin: pinButton.visible ? Style.spacing.md : 0
          contentHeight: sections.implicitHeight
          clip: true
          boundsBehavior: Flickable.StopAtBounds

          Column {
            id: sections
            width: scroller.width
            spacing: Style.spacing.md

            Text {
              width: parent.width
              visible: root.sims.length === 0
              textFormat: Text.PlainText
              wrapMode: Text.Wrap
              text: "No SIM service is running"
              color: root.foreground
              opacity: 0.7
              font.family: Style.font.family
              font.pixelSize: Style.font.body
            }

            Repeater {
              model: root.sims.length > 0 ? SimsModel.KINDS : []
              delegate: Column {
                id: section
                required property var modelData
                width: sections.width
                spacing: Style.spacing.sm

                Text {
                  width: parent.width
                  topPadding: Style.spacing.sm
                  textFormat: Text.PlainText
                  text: section.modelData.title
                  color: root.foreground
                  font.family: Style.font.family
                  font.pixelSize: Style.font.subtitle
                  font.bold: true
                }

                Repeater {
                  model: root.sims
                  delegate: BorderSurface {
                    id: choiceRow
                    required property var modelData
                    readonly property bool selected: Number(root.defaults[section.modelData.id]) === choiceRow.modelData.number
                    readonly property bool working: root.pending === section.modelData.id
                    width: section.width
                    height: Math.max(root.touchSize, choiceText.implicitHeight + Style.spacing.md * 2)
                    radius: Style.cornerRadius
                    opacity: root.pending !== "" && !choiceRow.working ? 0.6 : 1
                    color: choiceTouch.pressed ? Style.pressedFillFor(root.foreground, Commons.Color.accent)
                      : choiceRow.selected ? Util.alpha(Commons.Color.accent, Style.selectedFillAlpha)
                      : Style.normalFillFor(root.foreground, Commons.Color.accent)
                    borderSpec: Border.controlSpec(choiceRow.selected ? "selected" : "normal", root.foreground, Commons.Color.accent)

                    Text {
                      id: choiceGlyph
                      anchors.left: parent.left
                      anchors.leftMargin: Style.spacing.lg
                      anchors.verticalCenter: parent.verticalCenter
                      textFormat: Text.PlainText
                      text: "󰘚"
                      color: choiceRow.selected ? Commons.Color.accent : root.foreground
                      font.family: Style.font.family
                      font.pixelSize: Style.font.title
                    }

                    Column {
                      id: choiceText
                      anchors.left: choiceGlyph.right
                      anchors.leftMargin: Style.spacing.lg
                      anchors.right: choiceMark.left
                      anchors.rightMargin: Style.spacing.md
                      anchors.verticalCenter: parent.verticalCenter
                      spacing: Style.spacing.xs
                      Text {
                        width: parent.width
                        textFormat: Text.PlainText
                        text: choiceRow.modelData.label
                        color: root.foreground
                        font.family: Style.font.family
                        font.pixelSize: Style.font.subtitle
                        font.bold: true
                        elide: Text.ElideRight
                      }
                      Text {
                        width: parent.width
                        textFormat: Text.PlainText
                        elide: Text.ElideRight
                        text: choiceRow.working ? "Switching…" : SimsModel.statusText(choiceRow.modelData)
                        color: root.foreground
                        opacity: 0.7
                        font.family: Style.font.family
                        font.pixelSize: Style.font.body
                      }
                    }

                    Text {
                      id: choiceMark
                      anchors.right: parent.right
                      anchors.rightMargin: Style.spacing.lg
                      anchors.verticalCenter: parent.verticalCenter
                      textFormat: Text.PlainText
                      text: choiceRow.selected ? "󰄵" : "󰄱"
                      color: choiceRow.selected ? Commons.Color.accent : root.foreground
                      font.family: Style.font.family
                      font.pixelSize: Style.font.title
                    }

                    MouseArea {
                      id: choiceTouch
                      anchors.fill: parent
                      onClicked: root.choose(section.modelData.id, choiceRow.modelData.number)
                    }
                  }
                }

                Text {
                  width: parent.width
                  visible: section.modelData.hint !== ""
                  textFormat: Text.PlainText
                  wrapMode: Text.Wrap
                  text: root.pending === section.modelData.id && root.message !== "" ? root.message : section.modelData.hint
                  color: root.foreground
                  opacity: 0.6
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                }
              }
            }

            Text {
              width: parent.width
              visible: root.message !== "" && root.pending === ""
              textFormat: Text.PlainText
              wrapMode: Text.Wrap
              text: root.message
              color: Commons.Color.urgent
              font.family: Style.font.family
              font.pixelSize: Style.font.body
            }
          }
        }

        // A SIM waiting for its PIN: the SIM PIN sheet (omamobile.simpin).
        SheetButton {
          id: pinButton
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          visible: SimsModel.needsPin(root.sims)
          label: "Enter SIM PIN"
          primary: true
          foreground: root.foreground
          onTapped: {
            Quickshell.execDetached(["omarchy-shell", "shell", "call", "omamobile.simpin", "ask", ""])
            root.close()
          }
        }
      }
    }
  }
}
