# Noctalia Key Light

A Noctalia v4 bar plugin for controlling an Elgato Key Light over its local HTTP API.

- Left click opens brightness, power, and colour-temperature controls.
- Right click toggles power.
- Scroll adjusts brightness in 5% steps.
- The icon reflects connectivity and power state.

## Keyboard shortcut / IPC

With the plugin enabled, bind your compositor shortcut to:

```sh
noctalia-shell ipc call plugin:key-light toggle
```

The command uses the same state and controls as the bar widget, and works even
when no Key Light widget is shown. No separate HTTP script is needed.

## Development

```sh
devenv test
KEY_LIGHT_LIVE_TEST=1 devenv shell check
devenv shell install-local
```

The normal checks use an offscreen, isolated Quickshell instance and a loopback
fake light to verify IPC toggling without a widget and shared state across two
widgets. They do not contact your light or running Noctalia session.

Enable **Elgato Key Light** in Noctalia's plugin settings, then add `plugin:key-light` to the bar. Source changes are loaded from the symlink created by `install-local`.

The default host is `elgato-key-light.local`. Change `host`, `port`, polling interval, or Kelvin limits in the plugin's local `settings.json` if needed.
