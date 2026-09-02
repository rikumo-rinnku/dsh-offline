# DeepSeek Harness Windows 便携启动器

为已联网、但尚未配置 Python 和 Node.js 环境的 Windows 用户提供便携启动方式。完整发布包自带运行环境，解压后双击 `start.bat`，即可通过桌面启动器启动 DeepSeek Harness 并打开 Web UI。

本仓库维护启动器和打包工具，底层引擎来自 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)。使用在线模型仍需网络连接、有效的 API 凭据及对应服务。

## 主要功能

- **自带运行环境**：完整发布包包含 Python、Node.js 和已构建的引擎依赖。
- **桌面启动器**：启动或停止引擎、打开 Web UI、查看运行日志和工作目录。
- **自动选择端口**：从本机端口 3080 开始查找可用端口，并在服务就绪后打开带认证信息的网页。
- **依赖链接恢复**：首次启动创建目录链接；整体移动文件夹后，再次启动会修复链接目标。
- **可重复打包**：避免递归展开循环依赖链接，自动排除个人数据，并验证解压和搬迁后的启动。

## 用户如何启动

请使用维护者提供的完整 `dsh-portable.zip`。GitHub 的 **Code → Download ZIP** 和 `git clone` 得到的是源码，不包含被 Git 忽略的运行环境与引擎，不能直接作为完整启动包使用。

1. 将发布包完整解压到本机 **NTFS 磁盘上的可写文件夹**。
2. 双击 `start.bat`，等待依赖链接准备完成，随后显示桌面启动器。
3. 点击 **启动 DeepSeek Harness**，服务就绪后浏览器会自动打开 Web UI。
4. 在网页中配置自己的模型服务和 API 凭据，然后开始使用。

无需预先安装 Python 或 Node.js。目录链接使用 Windows Junction，创建时不要求管理员权限或开发者模式。不要在压缩软件内部直接运行脚本，也不要只提取部分文件或合并不同版本。

关闭时可在启动器中停止引擎；关闭窗口时，也可以选择停止引擎并退出，或仅关闭 GUI。

更多使用说明见 [使用说明.txt](使用说明.txt)。

## 配置、会话和日志

程序运行后会在所在目录创建以下内容：

| 目录 | 用途 |
| --- | --- |
| `.dsh-home/` | 用户配置、凭据、会话及运行时依赖链接 |
| `.cache/` | 缓存、临时文件和链接恢复锁文件 |
| `logs/` | 启动器记录的引擎日志 |

需要保留配置和会话时，请保留 `.dsh-home/`。其中可能包含 API 凭据，不应随发布包分发。更新版本时使用独立目录，按需备份和迁移个人数据。

## 开发者如何打包

源码仓库不包含 `runtime/` 和 `dsh-core/`。打包前，需要准备兼容的 Windows Node.js、带 Tkinter 与 CustomTkinter 的 Python，以及已构建并安装好依赖的 DeepSeek Harness 引擎。打包脚本不会自动下载或构建这些内容。

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

准备好目录后，双击 `pack.bat`，或执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\_pack.ps1
```

脚本使用自带 Python 生成 ZIP，不依赖 7-Zip。每次输出到独立目录：

```text
release-output/时间戳/
├── dsh-portable.zip       # 分发给用户的启动包
├── verification.json      # 验证通过后生成，含 SHA-256
└── verify moved/          # 保留的验证目录，不要分发
```

**只有脚本成功结束并生成 `verification.json` 后，才分发 ZIP。** 打包失败时可能保留未通过验证的压缩包，不能仅根据 ZIP 文件存在判断成功。

### 为什么不会重复压缩依赖

pnpm 工作区的依赖目录中存在大量符号链接和循环引用。打包脚本只遍历真实目录，将目录链接记录为包内相对路径，写入 `launcher/bundle-links.json`，不会沿链接重复收集依赖。用户启动时再根据清单创建本机 Junction。

发布包保留已安装依赖，不进行生产依赖裁剪。个人数据、缓存、日志、Git 历史和以前的打包输出不会进入发布包。不要直接压缩已运行过的整个目录再次分发，请始终通过 `pack.bat` 生成新的发布包。

完整规则见 [PACKAGING.md](PACKAGING.md)。

## 验证范围

构建流程会验证 ZIP 解压校验、链接恢复与重复执行、GUI 模块导入、CLI 版本、网页认证入口以及 JS/CSS 静态资源，并在移动已初始化的目录后再次验证。它不会执行真实模型请求或覆盖全部插件功能。

链接恢复的异常路径测试可单独运行：

```powershell
.\runtime\python\python.exe .\packaging\test_links.py
```

## 常见问题

**下载仓库后提示找不到 Python 或 Node？**

源码不包含运行环境。普通用户应获取完整发布包；维护者需要先准备上面的打包目录。

**提示依赖链接创建失败？**

确认已完整解压到本机 NTFS 可写目录，并且没有将不同版本合并。如果提示普通目录冲突，请重新解压到新的空目录。

**网页打不开或提示认证失败？**

等待引擎启动完成，再点击启动器中的“打开 Web UI”。使用启动器生成的完整地址；仅手动输入端口地址可能缺少认证信息。启动失败时可通过“查看日志文件夹”排查。

**移动文件夹后还能使用吗？**

先停止引擎并关闭启动器，整体移动文件夹，再运行 `start.bat`。启动流程会检查并修复清单中指向旧位置的依赖链接。
