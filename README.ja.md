# AI Song Detection

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Español](README.es.md)

このプロジェクトの主言語は英語で、英語版 README が原文です。このファイルは日本語訳であり、画面の表示とコマンドは英語のままです。

Web インターフェース、HTTP API、コマンドラインから、AI 生成楽曲のスクリーニングをローカルで実行できます。MIT ライセンスの [lofcz/ai-music-detector](https://github.com/lofcz/ai-music-detector) の fakeprint モデルを使用し、CPU で動作します。GPU、有料の推論 API、学習用の依存パッケージは必要ありません。

小容量の ONNX モデルを同梱しています。音声はアプリケーションを実行しているコンピューター上で処理され、外部の検出サービスには送信されません。

## デスクトップへのインストール

このプロジェクトをダウンロードして展開し、お使いのコンピューターに対応するインストーラーを実行してください。

| プラットフォーム | 初回インストール |
| --- | --- |
| macOS 13 以降、Apple Silicon または Intel | `Install.command` をダブルクリックします。 |
| Windows 10/11、x64 | `Install.cmd` をダブルクリックします。 |

インストーラーは専用の Python、FFmpeg/ffprobe、アプリケーションの依存パッケージを用意し、デスクトップに起動・停止用の項目を作成してアプリケーションを開きます。Windows では、ONNX Runtime 用の専用 Microsoft Visual C++ ランタイムも用意します。ブラウザーを開かずにインストールするには `--no-launch` を指定してください。既存の Python、Git、Homebrew、管理者権限は不要で、システム全体の PATH も変更しません。初回インストールにはインターネット接続が必要です。uv、FFmpeg、Windows C++ ランタイムのダウンロードはバージョンを固定し、チェックサムを検証します。詳細は[インストーラーの依存コンポーネント](install/README.md)を参照してください。

インストール後、デスクトップの **AI Song Detection** をダブルクリックしてください。ランチャーはローカルサービスを起動し、モデルとデコーダーの準備が整ってから既定のブラウザーを開きます。複数の音声ファイルを選択またはドロップし、**Start queue** を選択します。ファイルは 1 つずつ順番に処理され、各項目にアップロードの進捗、処理段階、キャンセル状態が表示されます。ファイルを追加する前に、開始位置と 10～300 秒の解析区間を指定してください。セッション内の結果は再表示、コピー、JSON/CSV 形式でのダウンロードが可能です。以後の起動と検出はオフラインで動作します。インストールされたアプリケーションは、展開したソースフォルダーから独立しています。

繰り返しクリックすると、既存のインスタンスを再び開きます。優先ポートが別のアプリケーションで使用されている場合、ランチャーは空いているポートを選択します。ブラウザーを閉じても検出サービスは停止しません。使用後はデスクトップの **Stop AI Song Detection** または `stop` コマンドで停止してください。

署名のないダウンロード済みスクリプトに対して、macOS や Windows が入手元やセキュリティに関する警告を表示することがあります。インストーラーは Gatekeeper、SmartScreen、企業のセキュリティポリシーを無効にしません。これらのスクリプトインストーラーは、署名済みの一般消費者向けアプリケーションパッケージではありません。

インストール先、コマンドラインからの起動、ログ、トラブルシューティングについては[運用ガイド](docs/operations.md)を参照してください。プラットフォームごとの検証記録は[検証記録](docs/verification.md)にまとめています。

### コマンドライン

インストーラーはコマンドラッパーのパスを表示します。たとえば、インストール済みのアプリケーションは次のように起動できます。

```bash
# macOS
"$HOME/Library/Application Support/AI Song Detection/bin/ai-song-detection" launch
```

```powershell
# Windows PowerShell
& "$env:LOCALAPPDATA\AI Song Detection\bin\ai-song-detection.cmd" launch
```

同じラッパーで、検出、診断、メンテナンス、オフラインバンドルの各コマンドを実行できます。開発用チェックアウトでは次のコマンドを使用してください。

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

`launch` はバックグラウンドのインスタンスを管理し、既定のブラウザーを開きます。フォアグラウンドで実行するには `serve` を使用し、Ctrl+C で停止できます。ランチャーの `--no-browser` オプションは自動チェックに便利です。検出の JSON モードでは、入力ファイルごとに 1 つの JSON オブジェクトを出力し、いずれかのファイルで失敗した場合は終了コード 1 を返します。

インストール済みのデスクトップ版では、`update` が新しいリリースを準備・確認してから切り替えます。`cleanup --keep 2` と `uninstall` は変更内容をプレビューし、`--apply` を追加すると実行します。古いリリースを削除する前にサービスを停止してください。`shell-setup --directory "$HOME/.local/bin"` を使用すると、指定したディレクトリに短いコマンド名で呼び出すためのエントリーを作成できます。必要に応じて、そのディレクトリを自分のシェルの PATH に追加してください。詳細は[メンテナンスとオフラインインストール](docs/operations.md#maintenance-and-offline-installation)を参照してください。

### HTTP API

```bash
curl -F 'file=@song.mp3' http://127.0.0.1:8000/api/v1/detect
curl http://127.0.0.1:8000/health
```

`launch` または `status` が表示するアドレスを使用してください。別のポートが選択された場合は、例のポート `8000` を置き換えます。そのアドレスの `/docs` で対話型の API ドキュメントを参照できます。レスポンスのフィールド、制限、エラーについては[運用ガイド](docs/operations.md)を参照してください。

### Docker

```bash
docker compose up --build
```

[http://127.0.0.1:8000](http://127.0.0.1:8000) を開いてください。イメージには Python、FFmpeg、依存パッケージ、モデルが含まれます。Compose はホストのポートを localhost にバインドし、読み取り専用のルートファイルシステムと一時ストレージを持つ非 root コンテナーを実行します。イメージのビルドにはネットワーク接続が必要ですが、推論には不要です。

## 結果と制限

- `likely_ai_generated`：AI スコアが 0.6 を超える場合。
- `likely_human_created`：AI スコアが 0.4 未満の場合。
- `uncertain`：AI スコアが 0.4 以上 0.6 以下の場合。

AI スコアは、上記の判定ルールで使用するモデルの出力です。レポートにはスコア、判定、解析区間、モデルの詳細が含まれます。

Web インターフェースは複数ファイルのキューに対応しています。API の各アップロードでは、**100 MiB** 以下で音声が **10 秒**以上あるファイルを 1 つ受け付けます。対応する拡張子は MP3、WAV、FLAC、M4A、AAC、OGG、Opus、AIFF/AIF、WMA で、実際に処理できる形式はデコーダーの対応状況によります。音声はサンプリングレート 16～96 kHz のモノラルまたはステレオである必要があります。既定では**先頭 300 秒**を解析し、開始位置と 10～300 秒の長さを指定することもできます。レポートには実際に解析した区間と、解析対象外の音声があるかどうかを表示します。同時に実行される解析は 1 件です。jobs API は最大 9 件の処理中・保留中ジョブ（実行中 1 件と待機中・アップロード中 8 件）を受け付けます。同期エンドポイントは処理中の場合に 429 を返します。

このモデルは **Suno ≤ 5 と Udio ≤ 1.5** に由来する特徴を対象としています。検出は音声の特徴を評価するものであり、著作者、著作権の帰属、制作履歴については、それぞれを裏付ける記録が必要です。

## モデルの参考指標と実行コスト

上流プロジェクトは、17,866 サンプルのホールドアウトテストセットで[正解率 99.88% と報告しています](https://github.com/lofcz/ai-music-detector/tree/6ba389e94a179ac90f3eb134b741ef37baa30434#performance)。

ローカルで CPU 推論を実行するため、検出サービスへのリクエストごとの料金はかかりません。処理時間と実際のコストは、ハードウェア、楽曲の長さ、同時実行数、ホスティング環境によって異なります。データセットの評価と性能測定については[評価計画](docs/evaluation.md)を参照してください。

## 開発

開発には Python 3.11～3.13、[uv](https://docs.astral.sh/uv/getting-started/installation/)、PATH 上の FFmpeg/ffprobe が必要です。デスクトップインストーラーは、これらとは別に専用の環境を用意します。

```bash
uv sync --frozen
uv run ai-song-detection launch
uv run pytest
uv run ruff check .
node --test tests/browser/connection.test.cjs
```

macOS/Linux の `./start.sh` は、依存パッケージを同期・ダウンロードせず、作成済みの開発環境を起動します。指定したポートでフォアグラウンドサービスを実行するには、`uv run ai-song-detection serve --port 8001` を使用してください。

プロジェクトの主言語は英語です。翻訳版 README は参考資料として提供しています。認証情報や非公開の音声を Git に含めないでください。出典を明記して同梱しているモデルは、モデル成果物をコミットしないという一般的な方針の意図的な例外です。

## ドキュメントとライセンス

- [製品の対象範囲](docs/product-scope.md)
- [運用と API 仕様](docs/operations.md)
- [評価計画](docs/evaluation.md)
- [検証記録](docs/verification.md)
- [サードパーティーの通知](THIRD_PARTY_NOTICES.md)

このプロジェクト独自のコードには [Apache 2.0](LICENSE) ライセンスを適用しています。上流のモデルと、それをもとに実装した推論方法には [MIT ライセンスの通知](third_party/ai-music-detector/LICENSE)を保持しています。モデルの出典、固定した上流リビジョン、チェックサムはパッケージのアセットに含まれます。その他の依存コンポーネントには、それぞれのライセンスが適用されます。
