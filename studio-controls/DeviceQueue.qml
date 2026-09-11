import QtQuick
import Quickshell.Io

Item {
  id: root
  required property string deviceId
  required property var settings
  property var pending: []
  property bool requestActive: false
  property bool received: false
  signal completed(var result)

  function enqueue(argv, step) {
    // Combine only adjacent, same-direction adjustments valid at the observed
    // hardware step. Never combine opposite turns, toggles or resets: clamping
    // and intermediate mode changes make their order significant.
    const tail = pending[pending.length - 1]
    const delta = Number(argv[2])
    if (tail && argv[0] === "adjust" && tail.argv[0] === "adjust"
        && argv[1] === tail.argv[1] && step > 0 && tail.step === step) {
      const previous = Number(tail.argv[2])
      const sum = previous + delta
      if (Number.isSafeInteger(delta) && Number.isSafeInteger(previous) && Number.isSafeInteger(sum)
          && delta % step === 0 && previous % step === 0 && Math.sign(delta) === Math.sign(previous)) {
        pending = pending.slice(0, -1).concat([{argv: ["adjust", argv[1], String(sum)], step: step}])
        return
      }
    }
    if (pending.length >= 64) {
      // Preserve the last snapshot on queue overflow.
      completed({errors: {request: "Too many pending actions"}})
      return
    }
    pending = pending.concat([{argv: argv, step: step}])
    drain()
  }
  function drain() {
    if (requestActive || runner.running || pending.length === 0) return
    const next = pending[0].argv
    pending = pending.slice(1)
    const backend = settings.backendCommand ?? ["studio-controls"]
    if (!Array.isArray(backend) || backend.length === 0 || backend.some(value => typeof value !== "string" || value.length === 0)) {
      completed({controls: [], errors: {request: "backendCommand must be a nonempty argv array"}})
      pending = []
      return
    }
    runner.command = backend.concat(["--config-json", JSON.stringify(settings), "--device", deviceId]).concat(next)
    received = false
    requestActive = true
    runner.running = true
  }
  function finished() {
    if (!requestActive || runner.running) return
    requestActive = false
    if (!received) completed({controls: [], errors: {request: "Studio Controls helper unavailable"}})
    drain()
  }
  function refresh() {
    if (!requestActive && pending.length === 0) enqueue(["status"], 0)
  }

  Process {
    id: runner
    stdout: StdioCollector {
      onStreamFinished: {
        root.received = true
        try {
          const result = JSON.parse(text)
          if (!Array.isArray(result.controls) || !result.errors) throw new Error("Malformed helper response")
          root.completed(result)
        } catch (error) {
          root.completed({controls: [], errors: {request: "Studio Controls helper unavailable"}})
        }
      }
    }
    onExited: (code, status) => { Qt.callLater(root.finished) }
    onRunningChanged: if (!running) Qt.callLater(root.finished)
  }
  Component.onCompleted: refresh()
}
