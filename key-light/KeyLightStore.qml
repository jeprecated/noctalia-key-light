import QtQuick

QtObject {
  id: root
  property var pluginApi: null
  property bool online: false
  property bool on: false
  property int brightness: 25
  property int temperature: 222
  property string error: ""
  readonly property int kelvin: Math.round(1000000 / temperature)
  readonly property string endpoint: "http://" + setting("host", "elgato-key-light-mk-2-1cf4.local") + ":" + setting("port", 9123) + "/elgato/lights"
  readonly property int minKelvin: setting("minKelvin", 2900)
  readonly property int maxKelvin: setting("maxKelvin", 7000)

  property Timer poller: Timer {
    interval: Math.max(1000, root.setting("pollIntervalMs", 5000))
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  function setting(name, fallback) {
    var settings = pluginApi && pluginApi.pluginSettings ? pluginApi.pluginSettings : ({})
    return settings[name] !== undefined ? settings[name] : fallback
  }

  function refresh() {
    request("GET", null)
  }

  function toggle() {
    setLight({"on": on ? 0 : 1})
  }

  function setPower(value) {
    on = value
    setLight({"on": value ? 1 : 0})
  }

  function setBrightness(value) {
    brightness = Math.max(0, Math.min(100, Math.round(value)))
    setLight({"brightness": brightness})
  }

  function setKelvin(value) {
    var limited = Math.max(minKelvin, Math.min(maxKelvin, Math.round(value)))
    temperature = Math.round(1000000 / limited)
    setLight({"temperature": temperature})
  }

  function setLight(values) {
    request("PUT", JSON.stringify({"numberOfLights": 1, "lights": [values]}))
  }

  function request(method, body) {
    var xhr = new XMLHttpRequest()
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== XMLHttpRequest.DONE) return
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          var parsed = JSON.parse(xhr.responseText)
          var light = parsed.lights && parsed.lights[0]
          if (!light) throw new Error("response contains no light")
          root.on = light.on === 1
          root.brightness = light.brightness
          root.temperature = light.temperature
          root.online = true
          root.error = ""
        } catch (e) {
          root.online = false
          root.error = String(e)
        }
      } else {
        root.online = false
        root.error = "Key Light unavailable (HTTP " + xhr.status + ")"
      }
    }
    xhr.open(method, endpoint)
    if (body !== null) xhr.setRequestHeader("Content-Type", "application/json")
    xhr.send(body)
  }
}
