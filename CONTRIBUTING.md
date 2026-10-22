# Contributing

Start with the tests and a staged installation described in README. Tests replace external effects and use temporary homes, synthetic peer IDs and fixture logs. Do not run a live disconnect experiment as part of automated tests.

Keep changes focused on recovery, configuration or installation. Add a regression case for each missed event or incorrect repair. Never remove the guard that distinguishes the keyboard-and-mouse menu from display mirroring, and never claim a helper click proves an input connection was restored.

The fixed helper launcher loads `reconnect.scpt` from the runtime directory. Change the external logic when possible. Replacing the launcher can change its signing identity and require permissions again. The current build is ad-hoc signed and is not notarized. Notarized binary distribution requires a separate release process.

To report compatibility, include the macOS version, interface language, whether manual UC connection works and the last helper result. Redact personal details as described in PRIVACY. Do not include credentials or complete system logs.

The workflow in `.github/workflows/test.yml` runs source tests and a helper build on a macOS runner. It does not exercise Accessibility grants or two physical Macs. Changes to UI selectors need separate manual verification on the claimed system versions.

## 中文说明

先运行测试并使用隔离安装，不要让自动测试真实断开设备。修复遗漏事件或错误重启时，应加入对应回归用例。

请保留键鼠菜单与镜像菜单之间的识别保护，也不要把一次菜单点击视为连接恢复的证据。修改助手逻辑时优先更新外部脚本，避免更换固定启动器导致重新授权。

兼容性反馈应包含系统版本、界面语言、手动连接是否成功和最近的助手结果。日志需要先脱敏。自动化测试无法验证两台实体 Mac 或权限弹窗，界面相关变更仍需要实机检查。
