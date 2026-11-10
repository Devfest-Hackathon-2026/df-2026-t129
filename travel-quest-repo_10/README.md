# TRAVEL QUEST
旅をRPGにするWebアプリ。`app/index.html` が画面、`app/main.py` がAI（Claude）とGoogle Placesの中継サーバーです。

## 構成
- `app/` … Cloud Functions にデプロイする本体
- `.github/workflows/deploy.yml` … main に push すると自動デプロイ（変数設定後のみ動作）

## 手動デプロイ
```bash
gcloud functions deploy travel-quest --gen2 --runtime=python312 --region=asia-northeast1 \
  --source=app --entry-point=app --trigger-http --allow-unauthenticated \
  --memory=512Mi --timeout=120s --max-instances=3 \
  --set-secrets=GOOGLE_PLACES_API_KEY=google-places-key:latest
```
Places を使わない場合は `--set-secrets=...` の行ごと外します。`MAPS_EMBED_KEY` は `--set-env-vars` で渡します（任意）。

## 秘密情報
APIキーは Secret Manager に入れ、リポジトリには置かないでください。予算アラートを必ず設定してください。

## みんなのMAP（共有スポット）の準備
トイレ・喫煙所・ATM・AED などの場所を全員で共有する機能は、Firestore（データベース）に保存します。Cloud 版だけで動きます。
```bash
gcloud services enable firestore.googleapis.com
gcloud firestore databases create --location=asia-northeast1
PN=$(gcloud projects describe $(gcloud config get-value project) --format='value(projectNumber)')
gcloud projects add-iam-policy-binding $(gcloud config get-value project) \
  --member="serviceAccount:${PN}-compute@developer.gserviceaccount.com" --role="roles/datastore.user"
```
- 地図表示（任意）: Google Cloud で **Maps JavaScript API** を有効にし、HTTPリファラ制限つきのキーを作って `MAPS_EMBED_KEY` に入れます。キーが無くても一覧と「Googleマップで開く」は使えます。
- 悪用対策: 登録は匿名で全員に公開されます。リンク入りのメモは拒否し、IPごとの回数制限（1時間に20件登録）、3件の通報で非表示にします。回数制限は関数インスタンスごとなので、`--max-instances` は小さいままにしてください。通報された場所の確認・削除は Firebase コンソールの Firestore（コレクション `spots`）で行います。
- 位置情報: 一覧の取得時は、現在地付近の座標（約100m単位に丸めたもの）だけを送り、保存しません。登録した場所の座標は保存・公開されます。

## 言語
日本語・英語・中国語（簡体字）に対応しています。ヘッダーの「⚙ 設定」から、🇯🇵🇺🇸🇨🇳 の3つを選べます。旅先データ・サンプル旅行は日本語（英語がある部分は英語）のままです。

## Claude 上の公開ページでのみんなのMAP
Cloud 版のサーバーが無い環境（Claude の公開ページ）では、Claude の共有データ（db）に登録を保存します。ページのリンクを開いた人どうしで共有されます。共有するときは、相手の権限を「共同利用者（Contributor）」にしてください（閲覧のみだと登録できません）。地図の表示と現在地の取得は、この環境では使えない場合があります。その場合は、一覧の下の「場所を選んで見る」で都市を選べます。

## 設定タブ
AI・地図のキーを画面から入力・選択する「詳細設定」は、安全のため削除しました。AIの接続先は常にこのサーバーの `/ai`、地図のキーは環境変数 `MAPS_EMBED_KEY` だけから設定されます（ブラウザに保存された古い値は無視されます）。

## パスワードだけでログイン（デモ向け・いちばん簡単）
最初の画面でパスワードを入力した人だけが使えます（IDは不要）。`あなたのパスワード` の部分を、決めたパスワードに変えて、次のコマンドで公開します（パスワードはこのコマンドの中にだけ書き、ファイルには書かないでください）。
```
AUTH_ENV='ACCESS_CODE=あなたのパスワード' bash deploy.sh
```
- パスワードはリポジトリには書かず、Google Cloud の関数の設定にだけ保存されます。変えたいときは、値を変えて同じコマンドをもう一度実行します（以前のパスワードで入った端末は、すべて入力し直しになります）。
- ログインの失敗は、接続元IPごとに10分間に10回までです（超えると約10分入れません）。IPの偽装には対応していません。
- 設定が無いと「公開停止」の画面になります。ログイン有効期間は30日です。
- 人ごとにIDを分けたい・デモ用の回数制限を付けたいときは、下の「ログインとデモアカウント」を使います。

## ログインとデモアカウント（IDごとに分けたい場合）
IDとパスワードでログインした人だけが使えます（AI・候補検索・みんなのMAPの通信も、ログインなしでは使えません）。**ログイン設定が無いときは、アプリは「公開停止」の画面になります**（うっかり全員に開かれないための安全側の動作です）。

1. アカウントを作ります（インストール不要。Cloud Shell でOK）。`:demo` を付けた名前が**デモアカウント**です。
   ```
   python3 tools/make_users.py demo:demo
   python3 tools/make_users.py demo:demo yamada     # 自分用の通常アカウントも作る例
   ```
   パスワードは自動生成され、**この画面にしか表示されません**（保存されるのはハッシュだけ）。自分で決めたいときは `--ask` を付けます。
2. 表示された `A)` のコマンドをそのままコピーして実行すると、公開されます。
   ```
   AUTH_ENV='AUTH_USERS=...,SESSION_SECRET=...' bash deploy.sh
   ```
   gcloud で直接公開するときは `B)` の `--update-env-vars='...'` を、公開コマンドの末尾に付けます。
3. URLを開くとログイン画面が出ます。「⚙ 設定」の下にある「ログアウト」で、ログアウトできます。
4. 人を追加・削除・パスワード変更するときは、残したい人も含めて全員分を `make_users.py` で作り直し、もう一度公開します。**パスワードを変えた人・外した人は、すぐにログアウトされます**。

| | 通常アカウント | デモアカウント（`:demo`） |
|---|---|---|
| ログインの有効期間 | 7日 | 1日 |
| AI（旅程・写真判定）の回数 | 1時間に100回 | 1時間に30回 |
| 候補検索（Places）の回数 | 1時間に300回 | 1時間に60回 |

- デモの相手には、IDとパスワードを別々の連絡手段で渡すと安全です。使い終わったらアカウントを作り直す（=パスワードを変える）と、すぐ無効になります。
- ログインの試行は、10分に10回までです（IDごと・接続元ごと。超えると一時的に止まります）。
- `SESSION_SECRET` はログインの署名用の秘密の値です（`make_users.py` が自動で作ります）。GitHub に載せないでください。
- 以前の「合言葉（`ACCESS_CODE`）」も、`AUTH_USERS` が無いときだけ動きます。アカウント方式を設定すると、合言葉は使われません。
- 自動デプロイ（GitHub）を使うときは、「Settings → Secrets and variables → Actions → **Secrets**」に `AUTH_USERS` と `SESSION_SECRET` を登録します（値は `make_users.py` の出力の `AUTH_USERS=` と `SESSION_SECRET=` の右側）。
- 動作確認: `python3 tests/test_auth.py`（Flask が入っている環境で実行できます）。
- ローカル開発でログインを外したいときだけ、環境変数 `AUTH_DISABLED=true` を付けます。公開環境では付けないでください。

## （旧方式）合言葉だけで守る
公開URLは、知っていれば誰でも開けます。合言葉を設定すると、最初に合言葉の入力画面が出て、正しく入力した人だけが使えます（AI・候補検索・みんなのMAPの通信も、合言葉なしでは使えません）。

1. 合言葉を決めます。**英数字だけ・12文字以上**にしてください（カンマや空白、記号は使わない）。
2. 公開のコマンドの末尾に、`--update-env-vars=ACCESS_CODE=あなたの合言葉` を足して、もう一度実行します。
   ```
   gcloud functions deploy travel-quest --gen2 --runtime=python312 --region=asia-northeast1 --source=app --entry-point=app --trigger-http --allow-unauthenticated --memory=512Mi --timeout=120s --max-instances=3 --update-env-vars=ACCESS_CODE=あなたの合言葉
   ```
3. URLを開くと、合言葉の画面が出ます。入力すると、30日間はその端末で入力が不要です。
4. 合言葉を変えたいときは、同じコマンドで値を変えて再公開します。以前の合言葉で入った端末は、すべて入力し直しになります。
- 合言葉は Google Cloud の関数の設定に保存され、プロジェクトの管理者には見えます。GitHub に載せたり、ファイルに書いたりしないでください。
- 自動デプロイ（GitHub）を使うときは、リポジトリの「Settings → Secrets and variables → Actions → **Secrets**」に `ACCESS_CODE` を登録します。
- 検索エンジンに載らないよう、`robots.txt` と noindex の設定も入れています。

## AI は Vertex AI（Gemini）
`/ai` は Vertex AI を呼びます。キーは不要で、関数のサービスアカウントに `roles/aiplatform.user` を付けます（SETUP.md のステップ3.7）。モデルは環境変数 `GEMINI_MODEL`（初期値 `gemini-3.8-flash`。404のときは `gemini-3.5-flash` などに自動で切り替え）、地域は `GEMINI_LOCATION`（初期値 global）で変えられます。Anthropic（Claude）のキーは不要になりました。
