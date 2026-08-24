import QtQuick

Item {
  id: root
  property var pluginApi: null
  property var screen: null
  property string widgetId: ""
  property string section: ""
  property int sectionWidgetIndex: 0
  property int sectionWidgetsCount: 0

  implicitWidth: 42
  implicitHeight: 32

  KeyLightStore { id: store; pluginApi: root.pluginApi }

  Rectangle {
    anchors.centerIn: parent
    width: 32
    height: 28
    radius: 8
    color: mouse.containsMouse ? Qt.rgba(1, 1, 1, 0.10) : "transparent"

    Text {
      anchors.centerIn: parent
      text: "☀"
      font.pixelSize: 18
      color: !store.online ? "#7f849c" : store.on ? "#f9e2af" : "#cdd6f4"
      opacity: store.on ? 1 : 0.72
    }

    MouseArea {
      id: mouse
      anchors.fill: parent
      hoverEnabled: true
      acceptedButtons: Qt.LeftButton | Qt.RightButton
      onClicked: function(event) {
        if (event.button === Qt.RightButton) store.toggle()
        else popup.open = !popup.open
      }
      onWheel: function(event) {
        store.setBrightness(store.brightness + (event.angleDelta.y > 0 ? 5 : -5))
      }
    }
  }

  KeyLightPopup {
    id: popup
    store: store
    anchorItem: root
    onCloseRequested: open = false
  }
}
