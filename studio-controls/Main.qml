import QtQuick
import Quickshell.Io

Item {
  id: root
  property var pluginApi: null
  readonly property var settings: pluginApi?.pluginSettings ?? ({})
  property var replies: ({})
  property string requestError: ""
  readonly property var controls: {
    const rows = {}
    for (const reply of Object.values(replies))
      for (const row of reply.controls ?? []) rows[row.id] = row
    return (settings.controls ?? []).filter(control => rows[control.id]).map(control => rows[control.id])
  }
  readonly property var errors: {
    const result = {}
    for (const reply of Object.values(replies)) Object.assign(result, reply.errors)
    if (requestError) result.request = requestError
    return result
  }
  readonly property var pending: {
    let result = []
    for (let i = 0; i < workers.count; i++) result = result.concat(workers.itemAt(i)?.pending ?? [])
    return result
  }
  readonly property bool busy: {
    for (let i = 0; i < workers.count; i++) if (workers.itemAt(i)?.requestActive) return true
    return false
  }
  readonly property alias store: root

  function update(deviceId, result) {
    const previous = replies[deviceId] ?? ({controls: []})
    replies = Object.assign({}, replies, {[deviceId]: Object.assign({}, previous, result)})
  }
  function enqueue(argv) {
    const control = (settings.controls ?? []).find(control => control.id === argv[1])
    if (!control) { requestError = "Unknown configured control"; return }
    for (let i = 0; i < workers.count; i++) {
      const worker = workers.itemAt(i)
      if (worker?.deviceId !== control.device) continue
      requestError = ""
      const row = controls.find(row => row.id === control.id)
      worker.enqueue(argv, row?.enabled && row.kind === "int" ? row.step : 0)
      return
    }
    requestError = "Unknown configured device"
  }
  function refresh() {
    requestError = ""
    for (let i = 0; i < workers.count; i++) workers.itemAt(i)?.refresh()
  }
  function invoke(actionId) {
    const action = (settings.actions ?? []).find(action => action.id === actionId)
    if (!action) { requestError = "Unknown configured action"; return }
    // Resolve adjustments so identical dial events can be combined safely.
    if (action.operation === "adjust") { adjustValue(action.control, action.value); return }
    const control = (settings.controls ?? []).find(control => control.id === action.control)
    if (!control) { requestError = "Unknown configured control"; return }
    for (let i = 0; i < workers.count; i++) {
      const worker = workers.itemAt(i)
      if (worker?.deviceId !== control.device) continue
      requestError = ""
      worker.enqueue(["invoke", actionId], 0)
      return
    }
    requestError = "Unknown configured device"
  }
  function setValue(control, value) { enqueue(["set", control, String(value)]) }
  function adjustValue(control, delta) { enqueue(["adjust", control, String(delta)]) }
  function resetValue(control) { enqueue(["reset", control]) }

  Repeater {
    id: workers
    model: root.settings.devices ?? []
    delegate: DeviceQueue {
      required property var modelData
      deviceId: modelData.id
      settings: root.settings
      onCompleted: result => root.update(deviceId, result)
    }
  }
  Timer {
    interval: Math.max(1000, root.settings.pollIntervalMs ?? 5000)
    running: true
    repeat: true
    onTriggered: root.refresh()
  }
  IpcHandler {
    target: "plugin:studio-controls"
    function invoke(action: string): void { root.invoke(action) }
    function set(control: string, value: string): void { root.setValue(control, value) }
    function refresh(): void { root.refresh() }
  }
}
