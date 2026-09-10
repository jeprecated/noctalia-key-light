import QtQuick
import Quickshell.Io

Item {
  id: root
  property var pluginApi: null
  readonly property alias store: lightStore

  KeyLightStore { id: lightStore; pluginApi: root.pluginApi }

  IpcHandler {
    target: "plugin:key-light"

    function toggle(): void {
      lightStore.toggle()
    }
  }
}
