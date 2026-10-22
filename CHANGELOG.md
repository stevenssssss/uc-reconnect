# Changelog

## 0.1.0

First experimental source release.

The monitor watches input-channel events for one configured Mac and retries native reconnection while that peer remains disconnected. Recovery includes process-exit detection, old-process log filtering, busy-worker retry handling and cancellation of stale repair actions.

The release includes a fixed AppleScript launcher, a source build, disabled-by-default installation, isolated staging, upgrade and removal commands, bilingual documentation and synthetic regression fixtures. Local configuration, personal logs and compiled applications are excluded from the source package.

The recovery design was exercised on one macOS 26.5 Mac-to-Mac setup. The configurable release installer is verified in staging. Broader device and operating-system coverage is still pending.
