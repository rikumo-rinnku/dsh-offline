# 便携启动包发布

本项目向联网的 Windows 用户提供自带 Python 和 Node 的运行环境。

双击 `pack.bat` 即可打包；也可以在源码目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\_pack.ps1
```

脚本使用自带 Python，以 ZIP 的快速压缩级别生成 `release-output/时间戳/dsh-portable.zip`。不需要 7-Zip，不修改原有依赖，不覆盖之前的发布包。只有验证完成并生成 `verification.json` 后，才应分发 ZIP。验证目录保留在同一输出目录中，便于排查；不要把它发给用户。

打包采用根目录白名单：`start.bat`、`使用说明.txt`、`launcher`、`runtime`、`dsh-core`。不收集 `.dsh-home`、`.cache`、`logs`、打包脚本和之前的输出；树内跳过 `.git` 与 `__pycache__`。保留全部已安装依赖，未实施生产依赖裁剪。

扫描时不遍历目录链接。文件链接以目标文件内容存储，目录链接以包内相对目标记录到 `launcher/bundle-links.json`；目标缺失、越出项目或未被收集都会终止打包。ZIP 内只有普通文件和目录。`start.bat` 调用 `restore_links.py`，在本地支持 Junction 的文件系统上重建目录链接，不依赖管理员或开发者模式。

启动时也检查移动后失效的旧链接，仅替换清单中已有的链接，遇到普通目录冲突会报错。应完整解压到本地 NTFS 可写目录，不要合并不同版本。运行后重新分发必须再次使用打包脚本，不能直接压缩已经生成循环链接和用户数据的目录。

构建默认验证 ZIP 解压 CRC、链接恢复与重复执行、GUI 模块导入、CLI 版本、网页认证入口和 JS/CSS 静态资源，并移动验证目录后重复检查。它不执行真实模型请求或全部插件功能；静态网页成功不代表全部功能已验证。

链接恢复异常路径测试：`runtime\python\python.exe packaging\test_links.py`。
