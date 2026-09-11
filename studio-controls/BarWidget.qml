import QtQuick

Item {
  id: root
  property var pluginApi: null
  property var screen: null
  property string widgetId: ""
  property string section: ""
  property int sectionWidgetIndex: 0
  property int sectionWidgetsCount: 0
  readonly property var store: pluginApi?.mainInstance?.store ?? null
  implicitWidth: 42
  implicitHeight: 32

  Rectangle {
    anchors.centerIn: parent
    width: 32
    height: 28
    radius: 8
    color: mouse.containsMouse ? Qt.rgba(1, 1, 1, 0.10) : "transparent"
    Text {
      anchors.centerIn: parent
      text: "◉"
      font.pixelSize: 20
      color: Object.keys(root.store?.errors ?? ({})).length ? "#f38ba8" : "#cdd6f4"
    }
    MouseArea {
      id: mouse
      anchors.fill: parent
      hoverEnabled: true
      enabled: root.store !== null
      acceptedButtons: Qt.LeftButton | Qt.RightButton
      onClicked: event => {
        if (event.button === Qt.RightButton) root.store.invoke(root.store.settings.bar?.rightClickAction)
        else { popup.open = !popup.open; if (popup.open) root.store.refresh() }
      }
      onWheel: event => root.store.invoke(event.angleDelta.y > 0 ? root.store.settings.bar?.scrollUpAction : root.store.settings.bar?.scrollDownAction)
    }
  }
  StudioPopup {
    id: popup
    store: root.store
    anchorItem: root
    onCloseRequested: open = false
  }
}
