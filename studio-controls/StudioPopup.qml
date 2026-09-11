import QtQuick
import QtQuick.Controls
import Quickshell

PopupWindow {
  id: root
  property var store: null
  property var anchorItem: null
  property bool open: false
  signal closeRequested()
  visible: open
  color: "transparent"
  implicitWidth: 460
  implicitHeight: 620
  anchor.item: anchorItem
  anchor.rect.x: anchorItem ? (anchorItem.width - implicitWidth) / 2 : 0
  anchor.rect.y: anchorItem ? anchorItem.height + 6 : 0

  Rectangle {
    anchors.fill: parent
    radius: 12
    color: "#18181d"
    border.color: "#46464f"
    Column {
      anchors.fill: parent
      anchors.margins: 16
      spacing: 10
      Row {
        width: parent.width
        Text { text: "Studio Controls"; color: "#e5e1e6"; font.pixelSize: 18; width: parent.width - 45 }
        Button { text: "×"; width: 45; onClicked: root.closeRequested() }
      }
      ScrollView {
        width: parent.width
        height: parent.height - 50
        clip: true
        contentWidth: availableWidth
        Column {
          width: parent.width
          spacing: 12
          Text {
            visible: (root.store?.controls.length ?? 0) === 0
            text: "No controls available. Configure devices and controls in the consumer configuration."
            width: parent.width
            wrapMode: Text.Wrap
            color: "#e5e1e6"
          }
          Repeater {
            model: root.store?.controls.length ?? 0
            Column {
              required property int index
              readonly property var modelData: root.store.controls[index]
              width: parent.width
              spacing: 5
              Text {
                visible: modelData.group !== "" && (index === 0 || root.store.controls[index - 1].group !== modelData.group)
                text: modelData.group
                color: "#89b4fa"
                font.pixelSize: 16
              }
              ControlRow { control: modelData; store: root.store }
            }
          }
          Repeater {
            model: (root.store?.settings?.actions ?? []).filter(action => typeof action.label === "string" && action.label.trim() !== "")
            Button {
              required property var modelData
              objectName: "action-" + modelData.id
              text: modelData.label
              onClicked: root.store.invoke(modelData.id)
            }
          }
          Text {
            text: Object.values(root.store?.errors ?? ({})).join("\n")
            visible: text !== ""
            width: parent.width
            wrapMode: Text.Wrap
            color: "#f38ba8"
          }
        }
      }
    }
  }
}
