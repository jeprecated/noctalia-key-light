import QtQuick
import QtQuick.Controls

Column {
  id: root
  required property var control
  required property var store
  width: parent ? parent.width : 400
  spacing: 4
  readonly property bool adjustable: control.enabled === true
  readonly property bool switchControl: control.kind === "bool" || (!!control.toggleValues && control.toggleValues.length === 2)

  function submittedValue(position) {
    const raw = control.slider === "log" ? Math.exp(position) : position
    const aligned = control.min + Math.round((raw - control.min) / control.step) * control.step
    return Math.min(control.min + Math.floor((control.max - control.min) / control.step) * control.step, Math.max(control.min, aligned))
  }
  function switchValue(checked) {
    return control.toggleValues ? control.toggleValues[checked ? 1 : 0] : (checked ? 1 : 0)
  }
  Text {
    text: root.control.label + "  ·  " + root.control.text
    color: root.adjustable ? "#e5e1e6" : "#92929c"
    wrapMode: Text.Wrap
    width: parent.width
  }
  Switch {
    objectName: "switch-" + root.control.id
    visible: root.switchControl
    enabled: root.adjustable
    checked: root.control.value === root.switchValue(true)
    onToggled: root.store.setValue(root.control.id, root.switchValue(checked))
  }
  ComboBox {
    objectName: "menu-" + root.control.id
    visible: root.control.kind === "menu" && !root.switchControl
    enabled: root.adjustable
    width: parent.width
    model: root.control.options ?? []
    textRole: "label"
    currentIndex: (root.control.options ?? []).findIndex(option => option.value === root.control.value)
    onActivated: index => root.store.setValue(root.control.id, root.control.options[index].value)
  }
  Row {
    visible: root.control.kind === "int" && !root.switchControl
    width: parent.width
    spacing: 6
    Button {
      text: "−"
      objectName: "decrease-" + root.control.id
      width: 38
      enabled: root.adjustable && root.control.value > root.control.min
      onClicked: root.store.adjustValue(root.control.id, -root.control.uiStep)
    }
    Slider {
      id: slider
      objectName: "slider-" + root.control.id
      width: parent.width - 88
      enabled: root.adjustable
      from: root.control.slider === "log" ? Math.log(root.control.min ?? 1) : (root.control.min ?? 0)
      to: root.control.slider === "log" ? Math.log(root.control.max ?? 1) : (root.control.max ?? 1)
      stepSize: root.control.slider === "log" ? 0 : (root.control.uiStep ?? 1)
      value: root.control.slider === "log" ? Math.log(root.control.value ?? 1) : (root.control.value ?? 0)
      onMoved: if (!pressed) root.store.setValue(root.control.id, root.submittedValue(value))
      onPressedChanged: if (!pressed && root.adjustable) root.store.setValue(root.control.id, root.submittedValue(value))
    }
    Button {
      text: "+"
      objectName: "increase-" + root.control.id
      width: 38
      enabled: root.adjustable && root.control.value < root.control.max
      onClicked: root.store.adjustValue(root.control.id, root.control.uiStep)
    }
  }
  Button {
    text: "Reset to configured value"
    objectName: "reset-" + root.control.id
    visible: root.control.hasDefault === true
    enabled: root.adjustable
    onClicked: root.store.resetValue(root.control.id)
  }
  Text {
    visible: root.control.error !== "" && root.control.error !== undefined
    text: root.control.error ?? ""
    color: "#f38ba8"
    width: parent.width
    wrapMode: Text.Wrap
  }
}
