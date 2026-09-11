import QtQuick
import Quickshell.Io

Item {
  id: root
  property var pluginApi: null
  readonly property var settings: pluginApi?.pluginSettings ?? ({})
  property var controls: []
  property var errors: ({})
  property var pending: []
  property bool requestActive: false
  property bool received: false
  property bool busy: requestActive
  readonly property alias store: root

  function enqueue(argv) {
    if (pending.length >= 64) {
      errors = ({request: "Too many pending actions"})
      return
    }
    pending = pending.concat([argv])
    drain()
  }
  function drain() {
    if (requestActive || runner.running || pending.length === 0) return
    const next = pending[0]
    pending = pending.slice(1)
    const backend = settings.backendCommand ?? ["studio-controls"]
    if (!Array.isArray(backend) || backend.length === 0 || backend.some(value => typeof value !== "string" || value.length === 0)) {
      controls = []
      errors = ({request: "backendCommand must be a nonempty argv array"})
      pending = []
      return
    }
    runner.command = backend.concat(["--config-json", JSON.stringify(settings)]).concat(next)
    received = false
    requestActive = true
    runner.running = true
  }
  function finished() {
    if (!requestActive || runner.running) return
    requestActive = false
    if (!received) {
      controls = []
      errors = ({request: "Studio Controls helper unavailable"})
    }
    drain()
  }
  function refresh() {
    if (!requestActive && pending.length === 0) enqueue(["status"])
  }
  function invoke(action) { if (action) enqueue(["invoke", action]) }
  function setValue(control, value) { enqueue(["set", control, String(value)]) }
  function adjustValue(control, delta) { enqueue(["adjust", control, String(delta)]) }
  function resetValue(control) { enqueue(["reset", control]) }

  Process {
    id: runner
    stdout: StdioCollector {
      onStreamFinished: {
        root.received = true
        try {
          const result = JSON.parse(text)
          if (!Array.isArray(result.controls) || !result.errors) throw new Error("Malformed helper response")
          root.controls = result.controls
          root.errors = result.errors
        } catch (error) {
          root.controls = []
          root.errors = ({request: "Studio Controls helper unavailable"})
        }
      }
    }
    onExited: (code, status) => { Qt.callLater(root.finished) }
    onRunningChanged: if (!running) Qt.callLater(root.finished)
  }
  Timer {
    interval: Math.max(1000, root.settings.pollIntervalMs ?? 5000)
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }
  IpcHandler {
    target: "plugin:studio-controls"
    function invoke(action: string): void { root.invoke(action) }
    function set(control: string, value: string): void { root.enqueue(["set", control, value]) }
    function refresh(): void { root.refresh() }
  }
}
