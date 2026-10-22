# UC Reconnect

[English](README.md)

UC Reconnect 用来自动恢复两台 Mac 之间的通用控制键盘和鼠标连接。它监听本机连接事件，检查目标 Mac 是否还在键鼠通道中。发现断线后，助手会尝试在系统菜单中重新连接；连接持续卡住时，可以重启本机的 UniversalControl 进程并继续尝试。

这是实验性源码版本。恢复逻辑曾在一组 macOS 26.5、简体中文界面的 Mac 设备上验证，通用安装器已在隔离目录中测试。代码包含英文菜单名称，但英文界面和其他系统版本仍需要实机验证。恢复速度取决于 macOS 的连接过程和另一台 Mac 是否可用。

## 能做什么

- 收到已识别的断线或键鼠通道事件后，立即安排修复。
- 每秒检查进程是否存活，每 30 秒核对一次系统日志。
- 断线时持续重试，每次尝试完成后间隔一秒。单次尝试本身可能耗时更长。
- 识别菜单已勾选、键鼠通道却不可用的情况。
- 保留修复器忙碌期间收到的事件，并限制助手和工作进程的最长运行时间。
- 收到新的恢复信号后，取消尚未执行的过时修复动作。

助手会尝试在后台打开显示器设置，操作后隐藏使用过的窗口。设置窗口仍可能短暂出现。系统设置位于前台时，助手会暂缓操作。本版本提供命令行安装器和后台助手，没有菜单栏界面。

程序不修改代理、路由、Wi-Fi 或蓝牙设置，也不上传日志，没有遥测功能。

## 安装前

先只在负责发起重连的 Mac 上安装。另一台使用系统自带的通用控制即可。两端同时运行自动修复器的情况尚未验证。

需要 Python 3.9 或更新版本，以及 macOS 的 `zsh`、`osacompile`、`codesign` 和 `launchctl`。助手针对 macOS 13 起的系统设置界面编写，目前仅在前文说明的环境中做过实机验证。无需额外 Python 包、Swift 编译器或管理员安装，也无需修改二进制文件。

请先确认两台 Mac 能手动连接。设备支持范围和账户设置请参照 [Apple 的通用控制说明](https://support.apple.com/zh-cn/102459)。

## 配置与安装

下载并解压源码包，在终端进入解压后的 `uc-reconnect` 目录。

### 1. 确认要连接的 Mac

在系统设置 → 显示器 → 连接键盘和鼠标至中，手动连接目标 Mac 一次，并记下菜单里显示的完整名称。

```sh
python3 scripts/uc_reconnect.py discover
```

这个命令读取最近的本机键鼠通道日志，列出候选设备 ID。它不会自动建立名称与 ID 的对应关系。如果有多个候选，请只连接目标设备并核对 ID 后再继续。这里的 ID 是八位十六进制字符，不是主机名、IP 地址或蓝牙地址。

### 2. 保存配置

```sh
python3 scripts/uc_reconnect.py configure
```

按提示输入菜单中的设备名称和 ID。配置会保存为 `config.local.json`，Git 和源码打包工具都会排除这个文件。也可以直接提供参数。

```sh
python3 scripts/uc_reconnect.py configure \
  --target-name '工作 MacBook' \
  --target-id ABCD1234
```

示例中的名称和 ID 都需要替换成自己的值。

### 3. 安装文件

```sh
python3 scripts/uc_reconnect.py install
```

安装器从源码编译助手，并在当前用户目录中准备以下文件。

| 位置 | 用途 |
| --- | --- |
| `~/Applications/UC Reconnect Helper.app` | 固定的 AppleScript 启动器 |
| `~/Library/Application Support/UCReconnect` | 配置、脚本、锁文件与日志 |
| `~/Library/LaunchAgents/org.uc-reconnect.events.plist` | 事件监听器 |
| `~/Library/LaunchAgents/org.uc-reconnect.watchdog.plist` | 定期日志核对 |

安装完成后，监控仍处于禁用状态。安装器不会启动助手或连接设备。

### 4. 给助手授权

```sh
python3 scripts/uc_reconnect.py permissions
```

macOS 询问时，允许 **UC Reconnect Helper** 控制 System Events 和系统设置。进入系统设置 → 隐私与安全性 → 辅助功能，从 `~/Applications` 添加助手并开启权限，同时检查自动化中的对应项目。安装器不会自动授予或重置这些权限。

关闭或离开系统设置，再执行一次 `permissions`，让助手尝试连接。第一次尝试可能被授权弹窗打断。正常升级会保留固定启动器，减少不必要的重新授权。

### 5. 启动监控

```sh
python3 scripts/uc_reconnect.py start
python3 scripts/uc_reconnect.py status
```

监控会立即启动，并在以后登录时运行。如果检测到已知的 Universal Control Restarter 监控器正在运行，发布版会拒绝启动，不会替你停止或修改旧版本。也请避免同时开启其他通用控制自动修复工具。

## 暂停、升级与卸载

```sh
python3 scripts/uc_reconnect.py stop
```

这个命令停止当前监控，并禁用登录启动。需要恢复时执行 `start`。

升级时先停止监控并保存本地配置，再解压新版本，执行 `install --config /path/to/your/config.json`。安装器会更新工作脚本，保留固定启动器。完成后执行 `start`。如果设备改名或 ID 变化，可用 `configure --output new.local.json` 生成新配置，再用新文件重新安装。

```sh
python3 scripts/uc_reconnect.py stop
python3 scripts/uc_reconnect.py uninstall
```

卸载会移除本项目的助手和启动项，保留配置与日志。加上 `--purge` 会同时删除本项目的数据目录。macOS 可能保留助手的权限记录，可以在隐私与安全性中手动移除。

## 不安装到本机的验证方式

以下命令只构建文件，并将安装结果放入隔离目录。它们不会加载启动项或打开助手。

```sh
python3 -m unittest discover -s tests -v
zsh -n runtime/universal-control-watchdog.zsh
python3 scripts/build.py
python3 scripts/uc_reconnect.py install \
  --config config.example.json --build-dir build --stage staging
python3 scripts/uc_reconnect.py uninstall --stage staging --purge
python3 scripts/package.py
```

再次构建时，用 `--output` 指定新的输出目录。打包工具只收录白名单中的源码文件，排除本地配置、构建产物和运行日志。示例配置只应用于隔离验证。

## 限制与排查

另一台 Mac 离线、睡眠或不可用时，工具无法让它立即恢复连接。系统没有及时发出可识别事件时，每 30 秒的日志核对可以补充检查，但无法保证发现所有无日志的故障。系统升级也可能改变日志格式或界面控件。

执行 `status` 可以查看最近一次助手结果。`settings-in-use` 表示助手正在等待系统设置离开前台。`target-not-available` 表示键盘和鼠标菜单中没有配置的名称。权限错误需要检查辅助功能与自动化。如果 Python 可执行文件被删除，请用准备长期保留的 Python 重新安装。

助手只选择键盘和鼠标区域，避开镜像或扩展显示器的菜单项，也不改变屏幕排列。断线期间反复尝试比空闲监听消耗更多资源，设置窗口也可能短暂出现。

分享诊断材料前，请阅读 [隐私说明](PRIVACY.md)。开发和测试方法见 [贡献说明](CONTRIBUTING.md)，上游来源见 [项目归属说明](NOTICE.md)。

## 许可证

使用 MIT 许可证。原项目版权声明与许可文本保留在 [LICENSE](LICENSE) 中。
