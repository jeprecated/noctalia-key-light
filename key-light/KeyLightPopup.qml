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
  implicitWidth: 340
  implicitHeight: 250
  anchor.item: anchorItem
  anchor.rect.x: anchorItem ? (anchorItem.width - implicitWidth) / 2 : 0
  anchor.rect.y: anchorItem ? anchorItem.height + 6 : 0

  Rectangle {
    anchors.fill: parent
    radius: 12
    color: Qt.rgba(0.08, 0.08, 0.10, 0.96)
    border.color: Qt.rgba(1, 1, 1, 0.14)

    Column {
      anchors.fill: parent
      anchors.margins: 16
      spacing: 10

      Row {
        width: parent.width
        Text { text: "Elgato Key Light"; color: "#e5e1e6"; font.pixelSize: 15; font.weight: Font.DemiBold; width: parent.width - 28 }
        Text {
          text: "×"; color: "#e5e1e6"; font.pixelSize: 18; horizontalAlignment: Text.AlignHCenter; width: 28
          MouseArea { anchors.fill: parent; onClicked: root.closeRequested() }
        }
      }

      Row {
        width: parent.width
        spacing: 10
        Switch { checked: root.store ? root.store.on : false; enabled: root.store && root.store.online; onToggled: root.store.setPower(checked) }
        Text { anchors.verticalCenter: parent.verticalCenter; text: root.store && root.store.on ? "On" : "Off"; color: "#e5e1e6" }
        Text { anchors.verticalCenter: parent.verticalCenter; text: root.store && root.store.online ? "Connected" : "Offline"; color: root.store && root.store.online ? "#a6e3a1" : "#f38ba8" }
      }

      Row {
        width: parent.width
        spacing: 6
        Text { anchors.verticalCenter: parent.verticalCenter; text: "Brightness  " + (root.store ? root.store.brightness : 0) + "%"; color: "#e5e1e6"; width: parent.width - 70 }
        Button { text: "−"; width: 32; enabled: root.store && root.store.online; onClicked: root.store.setBrightness(root.store.brightness - 5) }
        Button { text: "+"; width: 32; enabled: root.store && root.store.online; onClicked: root.store.setBrightness(root.store.brightness + 5) }
      }
      Slider {
        width: parent.width; from: 0; to: 100; stepSize: 1; value: root.store ? root.store.brightness : 0; enabled: root.store && root.store.online
        onPressedChanged: if (!pressed && root.store) root.store.setBrightness(value)
      }

      Row {
        width: parent.width
        Text { anchors.verticalCenter: parent.verticalCenter; text: "Temperature  " + (root.store ? root.store.kelvin : 0) + " K"; color: "#e5e1e6"; width: parent.width - warmButton.width }
        Button {
          id: warmButton
          text: "Warm " + (root.store ? root.store.warmthKelvin : 3200) + " K"
          enabled: root.store && root.store.online
          onClicked: root.store.setKelvin(root.store.warmthKelvin)
        }
      }
      Slider {
        width: parent.width; from: root.store ? root.store.minKelvin : 2900; to: root.store ? root.store.maxKelvin : 7000; stepSize: 100; value: root.store ? root.store.kelvin : 4500; enabled: root.store && root.store.online
        onPressedChanged: if (!pressed && root.store) root.store.setKelvin(value)
      }

      Text {
        width: parent.width; visible: root.store && root.store.error !== ""; text: root.store ? root.store.error : ""; color: "#f38ba8"; font.pixelSize: 11; elide: Text.ElideRight
      }
    }
  }
}
