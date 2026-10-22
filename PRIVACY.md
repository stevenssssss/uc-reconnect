# Privacy and local permissions

UC Reconnect reads local UniversalControl events. It stores the configured peer name and ID, connection state, attempt results and filtered event lines under `~/Library/Application Support/UCReconnect`. These files can identify devices and show activity times. They are not anonymous.

The project contains no telemetry, upload endpoint or automatic crash reporting. It invokes Apple's native connection machinery and does not alter proxy configuration. Accessibility and Automation permissions let the helper inspect and operate the Displays interface. The user grants those permissions in macOS.

Before opening an issue, replace device names, peer IDs, usernames, paths, timestamps and network identifiers in any excerpt. Share only the lines needed to explain the failure. Do not attach the entire runtime directory. The fixtures in this repository are synthetic.

Source packaging excludes local configuration and runtime logs. The package scan checks common personal paths, network identifiers and secret formats, but it cannot recognize every sensitive value. Review the archive before uploading it.

## 中文说明

工具会在本机保存目标设备名称、ID、连接状态、尝试结果和筛选后的事件日志。这些内容可能识别设备并反映使用时间，不能当作匿名数据。

项目没有遥测、上传接口或自动崩溃报告。辅助功能和自动化权限用于操作显示器设置，由用户在 macOS 中授予。

提交问题前，请替换日志中的设备名、ID、用户名、路径、时间戳和网络标识，只保留说明故障所需的片段，不要上传整个运行目录。源码包会排除本地配置和运行日志，但自动检查无法识别所有敏感信息，上传前仍需人工核对。
