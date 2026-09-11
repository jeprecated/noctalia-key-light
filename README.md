# Studio Controls

A Noctalia v4 bar plugin for **declaratively configured** local V4L2 cameras and
Elgato Key Lights. The popup renders configured controls in caller-selected order
and groups. Device state belongs to the device; deployment policy belongs to the
consumer (for example NixOS/Home Manager), not this project.

The default configuration is empty: no selected device, endpoint, control, action,
reset value or input binding. Startup, opening the popup, polling and reconnecting
only read. There is no frame capture, background daemon, automatic restoration,
GUI settings writer or device-settings persistence. The only local state is
private per-device lock files under `$XDG_RUNTIME_DIR/studio-controls-UID` (private
`/tmp/studio-controls-UID` fallback), used to serialize concurrent helper processes.

## Packaging and consumer configuration

Install the `studio-controls/` directory as the Noctalia plugin `studio-controls`.
Package `backend.py` with Python 3 and `v4l2-ctl` from v4l-utils. Provide a
`studio-controls` wrapper that executes `python3 /immutable/path/backend.py "$@"`
and pins `V4L2_CTL` to the packaged `v4l2-ctl` executable. The helper uses the Python
standard library; no pip packages are needed. Set `backendCommand` to the wrapper's
absolute path as an argv array, e.g. `["/nix/store/.../bin/studio-controls"]`.

The consumer writes Noctalia `studio-controls/settings.json` from its own source
configuration and selects `plugin:studio-controls` in its bar layout. The plugin
never rewrites that file. Do **not** install a writable checkout by symlinking it
into live Home Manager-managed configuration. The old imperative install helper
has deliberately been removed.

`examples/camera-and-light.json` is an **opt-in illustration**, not a shipped
selection. It uses a nonexistent camera identity and reserved example hostname;
copy/translate only desired fields into the consumer configuration. Never put
personal USB serials, hostnames or preferred presets in this repository.

### Settings contract

| Field | Meaning |
|---|---|
| `backendCommand` | Helper argv array, default logical command `["studio-controls"]`; consumer should pin an absolute wrapper path |
| `pollIntervalMs` | Read refresh interval, 1000–3600000 ms; 5000 ms mechanism default |
| `devices` | Ordered objects `{id,type,path}` for `type: "v4l2"`, or `{id,type,url}` for `type: "key-light"` |
| `controls` | Ordered selected controls, described below; no implicit controls |
| `actions` | Named explicit single-control operations, described below; no implicit actions |
| `bar` | Optional `rightClickAction`, `scrollUpAction`, `scrollDownAction` referencing configured action IDs |

An omitted, `null` or empty V4L2 `path` means explicitly unconfigured: its controls
show unavailable with a device error, without locking or invoking V4L2. Other
devices remain usable. Nonempty paths must start with `/dev/`; there is no automatic
device selection or fallback.

Left click always opens/closes the popup. Other bar interactions do nothing unless
configured. Both Noctalia and Stream Deck can invoke the same configured actions.
IDs must start with an ASCII letter, followed by letters, digits, `_` or `-`.

Each control has `id`, `device` (configured device ID), and `control` (V4L2 control
name, or light `power`, `brightness`, `temperature`). Optional presentation/policy:

- `label`, `group`, `unit`: caller-owned text. Adjacent controls with the same group
  share a heading. Units are presentation only, not numerical conversions.
- `step`: positive UI +/- increment in **raw device units**, required to be a
  multiple of the discovered device step. Defaults to the device step. Slider
  selections are quantized to the device step; explicit `set` rejects misalignment.
- `slider`: `linear` (default) or `log` for positive integer ranges. Log sliders
  provide practical exposure control over large ranges, with linear configured
  +/- steps. `display: "exposure100us"` shows raw V4L2 exposure as ms and reciprocal
  seconds; otherwise `display: "raw"`.
- `toggleValues: [offValue,onValue]`: renders a two-value switch instead of a menu
  or integer slider. Both values must be supported. This handles sparse camera
  auto-exposure menus such as `[1,3]` without treating menu holes as valid values.
- `enabledWhen: {control: "automaticControlId", equals: 0}`: optional same-device
  dependency. Runtime inactive/disabled/read-only/grabbed flags remain authoritative
  even without a configured dependency. Manual adjustments never silently disable
  an automatic mode.
- `default`: optional **explicit reset target**, in raw units. Shows a reset button;
  it is never applied during initialization, reconnect, refresh or an auto/manual
  transition. Driver-reported defaults are metadata only, never reset policy.
- `powerOnChange`: opt-in light behavior, normally configured for brightness.
  `true` adds `on:1` to that control's write; absent/false preserves power. A
  brightness write preserves colour temperature. Without this field, turning a
  brightness control does not implicitly turn the light on.

Camera boolean controls render switches; sparse menus render choices; bounded
integers render sliders plus +/- buttons. Unsupported types are unavailable,
not guessed. Ranges, device steps, current values, flags and menu entries come from
`v4l2-ctl --list-ctrls-menus` under `LC_ALL=C`. No custom ioctl ABI is embedded.
Light hardware ranges are power 0/1, brightness 0–100 and colour temperature
2900–7000 Kelvin; the protocol's reciprocal-temperature rounding means actual
readback may differ slightly from requested Kelvin values.

Each action is `{id,control,operation,value?,label?}`. An optional nonblank string
`label` renders an explicit popup button invoking that action's ID. Unlabeled
actions remain available through CLI/IPC/bar bindings without extra buttons;
labels never cause automatic invocation. Operations are `set`, `adjust`,
`toggle`, `reset`; `set`/`adjust` require an integer `value`. `adjust` performs a
fresh locked read-modify-write and clamps/quantizes at device limits. `set` rejects
invalid ranges/steps/menu holes rather than silently substituting a value.
`toggle` requires a boolean or explicit `toggleValues`. `reset` requires an
explicit control `default`. No arbitrary command, macro, startup-action or
multi-device preset engine is provided.

## CLI and IPC

Read-only commands:

```sh
studio-controls --config /consumer/settings.json status
studio-controls --config /consumer/settings.json --device camera status
studio-controls --config /consumer/settings.json label exposure
```

`status` emits `{controls:[...],errors:{deviceId:message}}`. Control rows include
`id`, `label`, `group`, `kind`, `value`, `text`, `min`, `max`, `step`, `uiStep`,
`options:[{value,label}]`, `enabled`, and `error` when available. `label` prints the
label and actual formatted value for a Stream Deck display; unavailability is
explicit. `label` reads only its control's device. Optional `--device ID` limits
status/operation responses to that device and rejects operations targeting another
device. Without it, status/operation responses include all devices. Polling never
sends notifications or performs writes.

Explicit device-changing commands, for operator use after configuration:

```sh
studio-controls --config /consumer/settings.json invoke exposureUp
studio-controls --config /consumer/settings.json set exposure 167
studio-controls --config /consumer/settings.json adjust exposure 10
studio-controls --config /consumer/settings.json reset exposure
noctalia-shell ipc call plugin:studio-controls invoke exposureUp
noctalia-shell ipc call plugin:studio-controls set exposure 167
```

IPC also exposes `refresh` (read-only). QML passes its settings through
`--config-json JSON` rather than maintaining a second configuration file. Do not
supply secrets in plugin settings. Helpers use argv, never shell interpolation.
Each external camera call/light request and lock acquisition is bounded to three
seconds; failed writes are never retried implicitly. Writes are read back; device
state, not optimistic GUI state, owns feedback. The immediate response reuses the
write's actual readback instead of discovering the device again. QML uses a
bounded queue and scoped snapshots **per device**, so a slow light cannot hold up
a camera action or its feedback (and vice versa). Device locks still serialize
concurrent callers for the same device. Adjacent queued same-direction adjustments
at a valid observed hardware step are combined; opposite turns, toggles and resets
keep their order so limit clamping and mode changes retain their meaning.
Rejected operations
return a nonzero exit status and a fresh read-only snapshot with `errors.request`,
so the panel retains its controls and current state. Invalid configuration has no
usable snapshot and returns empty controls with an explicit request error.

## Migration from Key Light

Plugin identity/path changes from `key-light` to `studio-controls`, and the
consumer must migrate its bar entry, generated settings, package wrapper and IPC
commands together. The old `toggle`/`adjustBrightness` methods become configured
named actions invoked through `invoke`. This is intentionally not a second live
plugin or compatibility shim. Preserve existing light behavior by declaring the
power/brightness/temperature controls, action increments, `powerOnChange` policy,
and any desired explicit temperature reset value in the consumer.

## Safe validation

```sh
devenv test
# or, inside the development environment:
check
```

Checks use Python synthetic-camera state, a loopback fake light and a private
**offscreen** Quickshell session. They do not open real cameras, capture images,
contact a configured light, query the running Noctalia instance or install/activate
anything. Tests cover all 17 synthetic C920e controls, flags, sparse menus, ranges,
steps, defaults, auto/manual dependencies, concurrent processes, bounded failures,
UI control construction/signals, shared state, configured IPC actions, and no
writes on startup/open/reopen/refresh/reconnect. Latency regressions count requests,
hold a fake light request open while camera IPC completes, hold the camera lock
while light IPC completes, and verify exact clamping/toggle results with a bounded
number of writes for dial bursts. GUI rendering/input on a real
compositor, camera firmware behavior, competing applications and persistence
across physical reconnect remain operator acceptance checks.
