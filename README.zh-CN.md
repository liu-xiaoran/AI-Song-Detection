# AI Song Detection

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Español](README.es.md)

英语是本项目的主语言，英文 README 是翻译的源文档。本文件为简体中文译本，应用界面和命令保持英文。

通过网页界面、HTTP API 或命令行，在本地检测歌曲是否由 AI 生成。应用采用 MIT 协议的 [lofcz/ai-music-detector](https://github.com/lofcz/ai-music-detector) fakeprint 模型，使用 CPU 运行，无需 GPU、付费推理 API 或训练依赖。

项目已包含小型 ONNX 模型。音频在运行应用的电脑上处理，不会发送到外部检测服务。

## 桌面安装

下载并解压本项目，然后运行适用于当前电脑的安装程序：

| 平台 | 首次安装 |
| --- | --- |
| macOS 13 或更新版本，Apple Silicon 或 Intel | 双击 `Install.command`。 |
| Windows 10/11，x64 | 双击 `Install.cmd`。 |

安装程序会准备应用专用的 Python、FFmpeg/ffprobe 和依赖，创建桌面启动及停止入口，并打开应用。Windows 上还会为 ONNX Runtime 准备专用的 Microsoft Visual C++ 运行库。使用 `--no-launch` 可在安装后不打开浏览器。安装不要求电脑预先安装 Python、Git 或 Homebrew，也不需要管理员权限，不会修改全局 PATH。首次安装需要联网。uv、FFmpeg 和 Windows C++ 运行库的下载版本均已固定，并通过校验和验证；详见[安装依赖](install/README.md)。

安装后，双击桌面的 **AI Song Detection** 入口。启动器会启动本地服务，等待模型和解码器就绪，然后打开默认浏览器。选择或拖入多个音频文件，点击 **Start queue**（开始队列）。文件按顺序处理，每项显示上传进度、处理阶段和取消状态。在添加文件前，设置起始时间和 10–300 秒的分析窗口。本次会话的结果可以重新查看、复制，或下载为 JSON/CSV。后续启动和检测均可离线进行。安装后的应用独立于解压出的源文件夹运行。

重复点击启动入口会重新打开已有实例。如果首选端口被其他应用占用，启动器会选择可用端口。关闭浏览器不会停止检测服务；使用完毕后，可通过桌面的 **Stop AI Song Detection** 入口或 `stop` 命令停止服务。

macOS 或 Windows 可能会对下载的未签名脚本显示来源或安全提示。安装程序不会关闭 Gatekeeper、SmartScreen 或企业安全策略。这些脚本安装程序不是已签名的消费级应用安装包。

安装路径、命令行启动、日志和故障排查说明见[运行与维护](docs/operations.md)。各平台的验证记录见[验证记录](docs/verification.md)。

### 命令行

安装程序会输出命令入口的路径。例如，可用以下命令启动已安装的应用：

```bash
# macOS
"$HOME/Library/Application Support/AI Song Detection/bin/ai-song-detection" launch
```

```powershell
# Windows PowerShell
& "$env:LOCALAPPDATA\AI Song Detection\bin\ai-song-detection.cmd" launch
```

同一个命令入口支持检测、诊断、维护和离线安装包命令。在开发工作副本中，使用：

```bash
uv run ai-song-detection launch
uv run ai-song-detection status
uv run ai-song-detection stop
uv run ai-song-detection detect song.mp3
uv run ai-song-detection detect song.mp3 another-song.flac --json
uv run ai-song-detection detect ./songs --recursive --start 30 --duration 60 --output reports.csv
uv run ai-song-detection doctor --json
uv run ai-song-detection logs --lines 100
uv run ai-song-detection status --url
uv run ai-song-detection launch --port 8001 --strict-port
uv run ai-song-detection evaluate labeled-songs.csv --output evaluation.json
```

`launch` 管理后台实例并打开默认浏览器。`serve` 用于前台运行，可按 Ctrl+C 停止。启动器的 `--no-browser` 选项适用于自动化检查。检测的 JSON 模式会为每个输入文件输出一个 JSON 对象；只要有文件处理失败，就以状态码 1 退出。

对于已安装的桌面应用，`update` 会先准备并检查新版本，再进行切换。`cleanup --keep 2` 和 `uninstall` 默认预览待执行的变更，添加 `--apply` 后执行。清理旧版本前应先停止服务。使用 `shell-setup --directory "$HOME/.local/bin"` 可在指定目录创建简短的命令入口；如有需要，再自行将该目录加入 shell 的 PATH。详见[维护与离线安装](docs/operations.md#maintenance-and-offline-installation)。

### HTTP API

```bash
curl -F 'file=@song.mp3' http://127.0.0.1:8000/api/v1/detect
curl http://127.0.0.1:8000/health
```

请使用 `launch` 或 `status` 输出的地址；如果启动器选择了其他端口，请替换示例中的 `8000`。交互式 API 文档位于该地址的 `/docs`。响应字段、限制和错误说明见[运行与维护](docs/operations.md)。

### Docker

```bash
docker compose up --build
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。镜像包含 Python、FFmpeg、依赖和模型。Compose 将主机端口绑定到 localhost，并使用非 root 用户、只读根文件系统和临时存储运行容器。构建镜像需要联网，推理无需联网。

## 结果与限制

- `likely_ai_generated`：AI 分数高于 0.6。
- `likely_human_created`：AI 分数低于 0.4。
- `uncertain`：AI 分数介于 0.4 和 0.6 之间，包含两端点。

AI 分数是上述判定规则使用的模型输出。报告包含分数、判定结果、分析区间和模型详情。

网页界面支持多文件队列；每次 API 上传接收一个最大 **100 MiB**、至少包含 **10 秒**音频的文件。支持的扩展名包括 MP3、WAV、FLAC、M4A、AAC、OGG、Opus、AIFF/AIF 和 WMA，具体取决于解码器支持情况。音频必须为单声道或双声道，采样率为 16–96 kHz。默认分析**前 300 秒**，也可设置起始时间和 10–300 秒的分析时长。报告会说明实际分析区间及是否省略了部分音频。同一时间只运行一项分析。任务 API 最多接纳九项尚未完成的任务（一项运行，另有八项等待或上传）；同步接口繁忙时返回 429。

模型针对 **Suno ≤ 5 和 Udio ≤ 1.5** 的音频特征。检测分析的是音频特征；作者身份、版权归属和制作历史需要各自的佐证记录。

## 模型参考与运行成本

上游项目在包含 17,866 个样本的留出测试集上[报告了 99.88% 的准确率](https://github.com/lofcz/ai-music-detector/tree/6ba389e94a179ac90f3eb134b741ef37baa30434#performance)。

本地 CPU 推理无需按请求支付检测服务费用。延迟和实际成本取决于硬件、歌曲时长、并发量和部署方式。数据集评估和性能测量方法见[评估计划](docs/evaluation.md)。

## 开发

开发需要 Python 3.11–3.13、[uv](https://docs.astral.sh/uv/getting-started/installation/)，以及已加入 PATH 的 FFmpeg/ffprobe。桌面安装程序会自行准备所需环境。

```bash
uv sync --frozen
uv run ai-song-detection launch
uv run pytest
uv run ruff check .
node --test tests/browser/connection.test.cjs
```

在 macOS/Linux 上，`./start.sh` 会启动已经创建好的开发环境，不会同步或下载依赖。使用 `uv run ai-song-detection serve --port 8001` 可在指定端口运行前台服务。

英语是项目的主语言，README 译本供参考。请勿将凭据或私人音频提交到 Git。随项目分发且保留来源声明的模型，是通常不提交模型文件这一规则的明确例外。

## 文档与许可证

- [产品范围](docs/product-scope.md)
- [运行维护与 API 约定](docs/operations.md)
- [评估计划](docs/evaluation.md)
- [验证记录](docs/verification.md)
- [第三方声明](THIRD_PARTY_NOTICES.md)

本项目原创代码采用 [Apache 2.0](LICENSE) 许可证。上游模型和改编的推理方法保留其 [MIT 许可声明](third_party/ai-music-detector/LICENSE)。模型来源、固定的上游版本和校验和均包含在软件包资源中。其他依赖保留各自的许可证。
