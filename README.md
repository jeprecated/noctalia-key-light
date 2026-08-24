# Noctalia Key Light

A Noctalia v4 bar plugin for controlling an Elgato Key Light over its local HTTP API.

- Left click opens brightness, power, and colour-temperature controls.
- Right click toggles power.
- Scroll adjusts brightness in 5% steps.
- The icon reflects connectivity and power state.

## Development

```sh
devenv test
KEY_LIGHT_LIVE_TEST=1 devenv shell check
devenv shell install-local
```

Enable **Elgato Key Light** in Noctalia's plugin settings, then add `plugin:key-light` to the bar. Source changes are loaded from the symlink created by `install-local`.

The default host is `elgato-key-light-mk-2-1cf4.local`. Change `host`, `port`, polling interval, or Kelvin limits in the plugin's `settings.json` if needed.
