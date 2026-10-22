# UC Reconnect

[简体中文](README.zh-CN.md)

UC Reconnect helps a Mac recover its Universal Control keyboard and mouse connection to one configured Mac. It watches local connection events, checks whether the peer is still present in the input channel, and asks an AppleScript helper to reconnect when that channel disappears. If the connection remains stuck, it can restart the local UniversalControl process and retry.

This is an experimental source release. The recovery logic has been exercised on one Mac-to-Mac setup running macOS 26.5 with a Simplified Chinese interface. The general installer has been tested in isolated directories. English menu labels are included, but English UI operation and other macOS versions still need device testing. Recovery time depends on macOS and the peer being available.

## What it does

- Reacts to recognized disconnect and input-channel events without waiting for the periodic check.
- Checks process liveness once a second and reconciles saved logs every 30 seconds.
- Keeps retrying while disconnected, with a one-second gap after a completed attempt. Each attempt can take longer.
- Detects a checked connection menu whose input channel is still unavailable.
- Retains events when a worker is busy and bounds helper and worker execution time.
- Cancels stale repair actions when a fresh input-channel recovery is observed.

The helper opens Displays without intentionally taking focus, then hides the window it used. A window may briefly appear. It defers while System Settings is in the foreground. This release includes a CLI installer and a background helper, with no menu-bar interface.

Proxy settings, routes, Wi-Fi and Bluetooth settings are left unchanged. The project does not upload logs or include telemetry.

## Before installation

Use this on the Mac that will manage reconnection to the selected peer. Install one controller first. Running two controllers for the same pair has not been tested.

You need Python 3.9 or later and the macOS tools `zsh`, `osacompile`, `codesign` and `launchctl`. The helper targets the System Settings interface introduced in macOS 13. Only the environment described above has been tested on devices. No Python packages, Swift compiler, administrator installation or binary patching are required.

Make sure Universal Control can connect manually first. Follow [Apple's Universal Control setup instructions](https://support.apple.com/en-us/102459) for device eligibility and account settings.

## Configure and install

Download and extract the source archive, then open Terminal in the extracted `uc-reconnect` directory.

### 1. Identify the intended Mac

Connect the intended Mac once in System Settings → Displays → Link Keyboard and Mouse to. Record its exact name from that menu.

```sh
python3 scripts/uc_reconnect.py discover
```

This reads recent local input-channel logs and prints candidate peer IDs. It does not map IDs to device names. With more than one candidate, connect only the intended peer and verify its ID before proceeding. The ID is an eight-character hexadecimal value, not a hostname, IP address or Bluetooth address.

### 2. Save configuration

```sh
python3 scripts/uc_reconnect.py configure
```

Enter the exact menu name and peer ID. Configuration is saved to `config.local.json`, which is excluded from Git and the source archive. For unattended configuration, pass both values explicitly.

```sh
python3 scripts/uc_reconnect.py configure \
  --target-name 'Example MacBook' \
  --target-id ABCD1234
```

The values above are examples. Replace both with your own values.

### 3. Install the files

```sh
python3 scripts/uc_reconnect.py install
```

The installer compiles the helper from source and prepares these locations under your home directory.

| Location | Purpose |
| --- | --- |
| `~/Applications/UC Reconnect Helper.app` | Fixed AppleScript launcher |
| `~/Library/Application Support/UCReconnect` | Configuration, scripts, locks and logs |
| `~/Library/LaunchAgents/org.uc-reconnect.events.plist` | Event listener |
| `~/Library/LaunchAgents/org.uc-reconnect.watchdog.plist` | Periodic reconciliation |

Installation leaves monitoring disabled. It does not launch the helper or reconnect a device.

### 4. Grant helper permissions

```sh
python3 scripts/uc_reconnect.py permissions
```

Allow **UC Reconnect Helper** to control System Events and System Settings when macOS asks. In System Settings → Privacy & Security → Accessibility, add the helper from `~/Applications` and enable it. Review its entries under Automation as well. The installer does not grant or reset permissions itself.

Close or leave System Settings, then run `permissions` again to let the helper attempt a connection. A permission prompt may interrupt the first attempt. The fixed launcher is preserved during normal updates to avoid unnecessary permission changes.

### 5. Start monitoring

```sh
python3 scripts/uc_reconnect.py start
python3 scripts/uc_reconnect.py status
```

Monitoring starts for the current user and at future logins. Startup refuses to run alongside the known Universal Control Restarter watchdog. It does not stop or modify that existing installation. Avoid running any other automatic UC restarter at the same time.

## Stop, update or uninstall

```sh
python3 scripts/uc_reconnect.py stop
```

This disables monitoring now and at login. Run `start` to resume.

To update, stop monitoring, save your local configuration, extract the new source version, and run `install --config /path/to/your/config.json`. The target scripts update while the fixed helper launcher is kept. Run `start` when ready. If you rename the peer or its ID changes, create a new configuration with `configure --output new.local.json`, then reinstall using that file.

```sh
python3 scripts/uc_reconnect.py stop
python3 scripts/uc_reconnect.py uninstall
```

Uninstall removes this project's helper and LaunchAgents. Configuration and logs remain. Add `--purge` to also delete its runtime directory. macOS may retain helper permission entries, which you can remove in Privacy & Security.

## Test without installation

These commands build and stage files without loading a LaunchAgent or opening the helper.

```sh
python3 -m unittest discover -s tests -v
zsh -n runtime/universal-control-watchdog.zsh
python3 scripts/build.py
python3 scripts/uc_reconnect.py install \
  --config config.example.json --build-dir build --stage staging
python3 scripts/uc_reconnect.py uninstall --stage staging --purge
python3 scripts/package.py
```

Choose a fresh `--output` directory when rebuilding an existing build. The package command includes source from an explicit allowlist and excludes local configuration, build output and runtime logs. The example configuration must only be used for staging.

## Limits and troubleshooting

A peer that is offline, asleep or unavailable cannot be made instantly reachable by this tool. If macOS stops emitting usable events, the 30-second log reconciliation may help, but it cannot prove the absence of every silent failure. Log formats and accessibility controls can change after system updates.

Run `status` and check the last helper result. `settings-in-use` means the helper is waiting for System Settings to leave the foreground. `target-not-available` means the configured name was absent from the keyboard-and-mouse section. Permission errors require checking Accessibility and Automation. A missing Python executable requires reinstalling with the Python interpreter you intend to keep.

The helper selects only the keyboard-and-mouse section and avoids the mirror/extend section. It does not change screen arrangement. It may briefly show Settings, and retrying while a peer is unavailable uses more resources than idle monitoring.

Read [the privacy notes](PRIVACY.md) before sharing diagnostics. See [contribution and testing guidance](CONTRIBUTING.md) and [upstream attribution](NOTICE.md).

## License

MIT. Original upstream notices and the license text are retained in [LICENSE](LICENSE).
