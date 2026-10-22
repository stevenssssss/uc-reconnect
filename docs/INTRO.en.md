# Software introduction

UC Reconnect is an experimental macOS helper that attempts to restore a Universal Control keyboard and mouse connection between two Macs. It watches local connection events and input-channel state, selects the configured peer through System Settings, and can restart the local UniversalControl process when the connection remains stuck.

It includes local configuration, background monitoring, and installation and removal tools. The user chooses the target Mac. Proxy and network settings remain unchanged, and diagnostic logs stay on the machine.

The project is intended for Mac users willing to configure a peer and help test compatibility. It depends on macOS log formats and accessibility controls and requires user-granted permissions. Settings may briefly appear during recovery. Instant recovery from every failure is not guaranteed.
