# DeepSeek Harness Windows 便携启动器

为已联网、但尚未配置 Python 和 Node.js 环境的 Windows 用户提供便携启动方式。完整发布包自带运行环境，解压后双击 `start.bat`，即可通过桌面启动器启动 DeepSeek Harness 并打开 Web UI。

本仓库维护启动器和打包工具，底层引擎来自 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)。使用在线模型仍需网络连接、有效的 API 凭据及对应服务。

## 主要功能

- **自带运行环境**：完整发布包包含 Python、Node.js 和已构建的引擎依赖。
- **桌面启动器**：启动或停止引擎、打开 Web UI、查看运行日志和工作目录。
- **自动选择端口**：从本机端口 3080 开始查找可用端口，并在服务就绪后打开带认证信息的网页。
- **依赖链接恢复**：首次启动创建目录链接；整体移动文件夹后，再次启动会修复链接目标。


```text
项目目录/
├── start.bat
├── pack.bat
├── _pack.ps1
├── launcher/              # 桌面启动器、引擎管理和链接恢复
├── packaging/             # 打包与验证脚本
├── runtime/
│   ├── node/node.exe
│   └── python/            # python.exe、pythonw.exe、Tkinter、CustomTkinter
└── dsh-core/
    ├── apps/cli/lib/bin.js
    ├── apps/web/dist/
    ├── node_modules/
    └── …                  # 保留工作区包、资源及其依赖结构
```
