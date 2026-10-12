# KustomFinance

社内LANで動かす法人向け会計・財務管理アプリ（Django + PostgreSQL）。
インボイス制度（適格請求書）・電子帳簿保存法に対応した販売・購買・会計・経費・銀行・固定資産管理を目指します。

## ローカルで動かす

KustomFinance はインターネット上のサービスを使わず、手元の PC・社内のサーバーだけで動きます
（レシートのOCRで Claude API を選んだ場合だけ、画像を外部に送ります）。

### どの動かし方を選ぶか

| 使い方 | おすすめ | 手順 |
| --- | --- | --- |
| まず試す・1人で使う・開発する | macOS にそのまま入れる | [A](#a-macos-にそのまま入れる) |
| 社内の数人〜数十人で使う | 社内サーバーで Docker | [B](#b-docker-で動かす社内サーバー推奨) |
| Linux サーバーに直接入れたい | Ubuntu などにそのまま入れる | [C](#c-linux-にそのまま入れる) |
| Windows しかない | WSL2 + Docker Desktop で B と同じ | [D](#d-windows) |

### 必要なソフトウェア

| ソフトウェア | 用途 | バージョン |
| --- | --- | --- |
| Python + [uv](https://docs.astral.sh/uv/) | アプリ本体 | Python 3.13 |
| PostgreSQL | データベース | 17 以上 |
| pango | 請求書などの PDF 作成（WeasyPrint） | 1.50 以上 |
| 日本語フォント | PDF の文字 | macOS は標準のヒラギノ、Linux は Noto Sans CJK |
| Tesseract + 日本語データ | レシートのOCR（ローカル） | 5.x、`jpn` |
| ffmpeg | 動画で撮ったレシートの読み取り | 6 以上 |
| Tailwind CSS（standalone） | 画面の CSS | `make tailwind` で自動で入る |
| Docker + Compose | B・D の場合 | Docker 24 以上 / Compose v2 |

### A. macOS にそのまま入れる

```sh
brew install uv postgresql@17 pango tesseract ffmpeg
brew services start postgresql@17
createdb kustomfinance

cp .env.example .env          # SECRET_KEY を書き換える
make setup                    # 依存・Tailwind・OCRの日本語データ・マイグレーション・CSS
uv run manage.py createsuperuser
make dev                      # http://localhost:8000
```

- Homebrew の `tesseract` には日本語が入っていません。`make setup`（`make ocr-data`）が
  日本語データを `bin/tessdata/` に入れます（約14MB）。`brew install tesseract-lang` で入れても構いません。
- WeasyPrint が pango を見つけられるよう、`make` 経由で起動してください
  （直接 `uv run manage.py runserver` するときは `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` を付けます）。
- CSS を編集するときは別ターミナルで `make css-watch`。テストは `make test`。

### B. Docker で動かす（社内サーバー・推奨）

```sh
echo "SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(50))')" > .env
echo "DB_PASSWORD=$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')" >> .env
echo "ALLOWED_HOSTS=localhost,192.168.1.10" >> .env             # サーバーのIP（下の「社内LANに公開する」）
echo "CSRF_TRUSTED_ORIGINS=http://192.168.1.10:8000" >> .env
docker compose up -d --build
docker compose exec app /opt/venv/bin/python manage.py createsuperuser
```

イメージには PostgreSQL 以外のすべて（pango・Noto フォント・Tesseract 日本語・ffmpeg）が入っています。
`restart: unless-stopped` にしてあるので、サーバーを再起動しても自動で立ち上がります。

### C. Linux にそのまま入れる

Ubuntu 24.04 の例です。

```sh
sudo apt install postgresql libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-noto-cjk \
                 tesseract-ocr tesseract-ocr-jpn ffmpeg
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo -u postgres createuser --createdb $USER && createdb kustomfinance
cp .env.example .env && uv sync && uv run manage.py migrate
# Tailwind は linux 版を bin/tailwindcss に置く（Makefile の tailwind ターゲットは macOS 用）
make css && uv run manage.py createsuperuser
make serve                    # gunicorn で 0.0.0.0:8000
```

常駐させるときは systemd に登録します。

```ini
# /etc/systemd/system/kustomfinance.service
[Unit]
Description=KustomFinance
After=network.target postgresql.service

[Service]
User=kustomfinance
WorkingDirectory=/opt/KustomFinance
ExecStart=/opt/KustomFinance/.venv/bin/gunicorn config.wsgi -b 0.0.0.0:8000 -w 3
Restart=always

[Install]
WantedBy=multi-user.target
```

### D. Windows

WSL2 と Docker Desktop を入れ、WSL2 の中で B の手順を実行します。
社内の他の PC から使う場合は、Windows ファイアウォールで 8000 番ポートの受信を許可してください。

### 社内LANに公開する

1. サーバーの IP を固定する（ルーターの DHCP 予約がかんたんです）
2. `.env` の `ALLOWED_HOSTS` と `CSRF_TRUSTED_ORIGINS` にその IP（またはホスト名）を足す
3. サーバーのファイアウォールで 8000 番ポートを開ける
4. 他の PC のブラウザで `http://<サーバーのIP>:8000` を開く

いまは HTTP で動きます。社外から接続できるようにはせず、社内 LAN の中だけで使ってください
（HTTPS 化は Issue で管理しています）。

### レシートのOCR

経費精算・証憑の保存の画面で、レシートの写真・スキャン・動画から日付・金額・支払先・登録番号・明細を読み取ります。

| `.env` の `OCR_ENGINE` | 読み取り | 注意 |
| --- | --- | --- |
| `tesseract`（既定） | この PC の中だけで読み取る | 手書き・感熱紙のかすれ・斜めの写真に弱い |
| `claude` | Claude API で読み取る（`ANTHROPIC_API_KEY` が必要） | 精度は高いが、**画像が Anthropic に送信される**。失敗したときは自動で Tesseract に切り替わる |

- 動画（スマホで撮ったもの）は 1 秒に 2 枚のフレームを取り出し、ピントの合ったものを 3 枚選んで読み取ります。
- 10% と 8%（軽減）が混在するレシートは、経費精算の明細を税率ごとに 2 行に分けて入力します。
- 読み取った値は**必ず原本と見比べて確認してください**。保存されるのは申請者が確認した値です。

## 必要なハードウェア

### サーバー（アプリと DB を動かす 1 台）

| 利用人数の目安 | CPU | メモリ | ストレージ | 例 |
| --- | --- | --- | --- | --- |
| 1〜5 人 | 2 コア | 4GB | SSD 64GB | 手元の Mac・ミニ PC |
| 5〜20 人 | 4 コア | 8GB | SSD 256GB | Mac mini・Intel NUC 相当・Docker が動く NAS |
| 20 人〜 | 4 コア以上 | 16GB | SSD 512GB 以上 | 専用サーバー（`gunicorn` のワーカーを増やす） |

- **メモリ**: PostgreSQL・Django に加え、PDF 作成（WeasyPrint）と OCR（Tesseract・ffmpeg）が一時的に 500MB〜1GB ほど使います。
- **ストレージ**: 帳簿のデータ自体は小さく（年に数百MB程度）、増えるのは保存ファイルです。
  レシート画像は 1 枚 1〜3MB、動画は 1 本 10〜50MB 程度です。月 300 枚の画像なら年 10GB ほど増えます。
  電子帳簿保存法では **7 年（欠損金がある年度は 10 年）** 保存するので、その分を見込んでください。
- **24 時間動かす前提**なら、スリープしない設定にし、**UPS（無停電電源装置）** をつなぐと停電時の DB 破損を防げます。
- **ネットワーク**: 有線 LAN で、IP を固定できること。

### バックアップ先

- NAS または外付けディスクを **2 台以上**（1 台は社外に保管）。`uv run manage.py backup --dir <保存先> --keep 90` を毎日実行します。
- 容量は「DB のダンプ（数十〜数百MB）＋保存ファイル」× 世代数です。

### 使う人の PC・機器

| 機器 | 用途 | 目安 |
| --- | --- | --- |
| PC | ブラウザで使う | Chrome・Edge・Safari・Firefox の最新版。画面幅 1280px 以上（スマホ表示は未対応） |
| スマートフォン | レシートの撮影（写真・動画） | 1200 万画素以上のカメラ。明るい場所で、レシート全体が入るように |
| スキャナ | 紙の証憑の取り込み | カラー・200dpi 以上（電子帳簿保存法のスキャナ保存の要件の目安）。ADF 付きだと楽 |
| プリンタ | 請求書・注文書を紙で送る場合 | A4 |

## ロール

| ロール | できること |
|---|---|
| 管理者 | すべて（自社設定・ユーザー管理） |
| 経理 | 仕訳・入出金・承認・期間締め |
| 営業・購買 | 見積・受注・請求・発注の作成、経費申請 |
| 閲覧のみ | 閲覧 |

## 構成

- `apps/core` 自社情報・会計期間・採番・金額丸め
- `apps/accounts` ユーザー・ロール
- `apps/audit` 操作ログ（DBトリガーで変更・削除不可。電子帳簿保存法の訂正削除履歴）
- `apps/ledger` 勘定科目・税区分・仕訳・総勘定元帳・試算表・締め処理
- `apps/masters` 取引先・品目・部門・プロジェクト、帳票共通部品（明細・税率別集計・発行・PDF）
- `apps/sales` 見積書→受注（注文請書）→納品書→請求書、締め請求、入金消込、売掛金年齢表
- `apps/purchasing` 注文書→検収→仕入請求書（受領）、支払予定表、支払消込、買掛金年齢表
- `apps/expenses` 経費精算（申請→承認→精算）、領収書添付
- `apps/banking` 銀行口座、明細CSV取込、自動仕訳ルール、請求書・仕入請求書との消込、残高照合
- `apps/assets` 固定資産台帳、減価償却（定額法・定率法・一括償却・少額減価償却資産）、除却
- `apps/reports` 損益計算書（部門別・前年比較）、貸借対照表、消費税集計表
- `apps/documents` 証憑の保存・検索（電子帳簿保存法）
- `apps/ocr` レシート・領収書の読み取り（画像・動画、Tesseract / Claude API）

## 販売の流れ

- 帳票は「下書き→発行」。発行時に番号を採番し、発行時点のPDFを控えとして保存（SHA-256を記録）。発行後は編集不可で、訂正は「取消」＋「複製」。
- 請求書は適格請求書の記載事項（登録番号・税率ごとの対象額と消費税額・軽減税率対象の表示）を満たします。消費税は請求書ごと・税率ごとに1回端数処理します。
- 請求書の発行で「売掛金 / 売上高・仮受消費税」を自動計上。入金登録で消込し、手数料差引入金・前受金にも対応。
- 帳票は発行時の PDF をダウンロードできます（詳細画面の「PDFをダウンロード」、下書きなら「発行する（PDFをダウンロード）」で発行と同時に保存）。一覧で複数選ぶと ZIP でまとめてダウンロードできます。

## 購買の流れ

- 受け取った請求書は「仕入請求書」として登録し、「計上する」で「仕入高・仮払消費税 / 買掛金」を計上。受領ファイルを添付するとSHA-256を記録します。
- 税額は請求書記載の額（税率ごと）で上書きできます（先方の端数処理に合わせるため）。
- 登録番号のない仕入先は、仕入計上日に応じて経過措置を自動適用（〜2026/9/30: 80%、〜2029/9/30: 50%、以降: 控除不可）。控除できない税額は仕入高等に含めます。
- 支払は当社負担の振込手数料・先方負担の手数料差引の両方に対応。消し込まなかった額は前渡金。

## 前受金・前渡金の充当

- 入金・支払のうち請求書に消し込まなかった額は前受金・前渡金として残り、「前受金残高」「前渡金残高」で確認できます。
- 後から発行・計上した請求書（仕入請求書）の詳細画面に、同じ取引先の前受金（前渡金）が表示され、金額と充当日を指定して充当できます。仕訳は「前受金 / 売掛金」「買掛金 / 前渡金」。
- 充当の取消は取消仕訳で戻します。充当がある入金・支払・請求書は、先に充当を取り消してから取り消します。
- 充当の元になるのは入金・支払の残額です。仕訳入力で直接計上した前受金・前渡金（開始残高など）は充当の対象外のため、仕訳入力で振り替えてください。

## 経費精算・銀行

- 経費精算は「下書き→申請→承認（経費 / 未払金を計上）→精算（未払金 / 預金）」。差戻し・承認取消に対応。自分の申請は承認できません。
- 登録番号のない領収書は経過措置の税区分に自動で読み替えます。公共交通機関・出張旅費などインボイス不要の特例はチェックで全額控除。
- 銀行明細はCSV（UTF-8/Shift_JIS、西暦・和暦）を取り込み、重複は自動スキップ。列の並びは「明細CSV形式」で設定します。
- 入金は請求書、出金は仕入請求書と金額（振込手数料の差額1,000円以内を含む）と振込名義（半角カナ・法人格を正規化）で照合して消込候補を表示。
- 摘要のキーワードで科目・税区分を決める「自動仕訳ルール」、手動の科目指定、対象外の指定ができます。

## 固定資産

- 減価償却は直接法・月割（事業供用月を1か月）・1円未満切捨て。定額法・定率法は備忘価額1円を残します。
- 「減価償却の計上」は指定月末までの累計額と計上済み額の差額だけを計上するため、毎月でも決算時でも実行できます。
- 償却率表の初期値は計算式で求めた値です。**国税庁「減価償却資産の償却率等表」と照合してから使ってください**（/admin/ で修正可能）。

## 電子帳簿保存法への対応

| 要件 | 対応 |
|---|---|
| 真実性（訂正削除の防止） | 仕訳・発行済み帳票は変更不可（取消で対応）、証憑は削除・差し替え不可（DBトリガー）、操作ログは改変不可。`docs/` の事務処理規程ひな形を整備してください |
| 改ざん検知 | 発行PDF・受領ファイル・領収書のSHA-256を記録。`uv run manage.py verify_files` で検証 |
| 検索要件 | 「証憑の検索」で取引年月日・取引金額（範囲）・取引先を組み合わせて検索 |
| 見読性 | 画面表示・PDF/ファイル表示・CSV出力 |

## バックアップ

```sh
uv run manage.py backup --dir /path/to/nas --keep 90   # DBダンプ＋保存ファイル
pg_restore --clean --if-exists -d kustomfinance backups/db_YYYYmmdd_HHMMSS.dump  # 復元
```

Docker の場合は DB コンテナの pg_dump を使います: `docker compose exec db pg_dump -U kustomfinance -Fc kustomfinance > backup.dump`

## 会計の仕組み

- **税抜経理**: 仕訳は税込金額で入力し、課税取引の消費税は仮払消費税／仮受消費税へ自動で振り分けます。
  経過措置（免税事業者等からの仕入の80%・50%控除）は税区分で選択します。
- **仕訳は変更・削除不可**: DBトリガーで保護しています。訂正は取消仕訳（赤伝）＋新しい仕訳で行います。
- **貸借一致はDBで保証**: コミット時に制約トリガーで検証します。
- **繰越**: 前期以前の損益は繰越利益剰余金の期首残高に自動で含めます（決算振替仕訳は不要）。
- **締め**: 月次締め日以前・決算締め済みの期間には記帳できません。
- 他システムからの移行時は、期首日付で「開始残高」にチェックを付けて仕訳を登録します。

## 未対応・今後の課題

未対応の機能は [GitHub の Issue](https://github.com/KustomApe/KustomFinance/issues) で管理しています（書き方は [docs/issue.md](docs/issue.md)）。

| 種類 | 主なもの |
| --- | --- |
| 法令・税制対応（[`compliance`](https://github.com/KustomApe/KustomFinance/labels/compliance)） | 償却率表の照合 #1、少額特例 #2、簡易課税・2割特例 #3、仕入税額の按分 #4、消費税申告書 #5、消費税の整理仕訳 #6、源泉徴収 #7、償却資産申告 #8、スキャナ保存の要件 #9、デジタルインボイス #10 |
| 機能（[`enhancement`](https://github.com/KustomApe/KustomFinance/labels/enhancement)） | 他ソフトからの移行 #11、仕訳入力の部門・取引先 #12、開始残高の前受金の充当 #13、全銀協の明細取込 #14、総合振込データ #15、経費精算と出金の照合 #16、固定資産の売却 #17、給与 #18、請求書のメール送信 #19、定期請求 #20、受注残 #21、在庫 #22、予実対比 #23、スマホ対応 #24、PDFのOCR #25、二要素認証 #26 |
| 保守（[`chore`](https://github.com/KustomApe/KustomFinance/labels/chore)） | Docker 構成の動作確認 #27、HTTPS 化 #28、Makefile の Linux 対応 #29、CI #30 |
