# はじめてのセットアップ手順（GitHub と Google Cloud）

所要時間の目安は、はじめてなら1〜2時間です。用語は最初に出てきたところで説明します。

## 全体の流れ
1. GitHub に、コードを保管する（コードの置き場所）
2. Google Cloud に、アプリを公開する（スマホから開けるURLができる）
3. 動作を確認する
4. あとから、AI・地図・自動更新を足す

最初は **AIなし・地図なし**で始められます。それでも、旅の登録・クエスト・バトル・みんなのMAPの一覧は動きます。AI（ステップ3.7）と地図（ステップ3.8）は、そのあとで足します。

## 用意するもの
- Google アカウント
- GitHub アカウント（無料。https://github.com で作成）
- クレジットカード（Google Cloud の課金設定に必要。使った分だけの請求で、無料枠もあります）
- パソコン（スマホだけでは作業しにくいです）
- 配布された `travel-quest-repo.zip`

---

## ステップ1：GitHub にコードを置く
GitHub は、コードを保管して、チームで共有する場所です。

1. GitHub にログインし、右上の「＋」→「New repository」を押します。
2. 次のように入力します。
   - Repository name：`travel-quest`
   - **Private**（非公開）を選ぶ
   - 他はそのままで「Create repository」
3. `travel-quest-repo.zip` をパソコンで展開（解凍）します。
4. 作ったページの「uploading an existing file」というリンクを押します。
5. 展開したフォルダの**中身**（`app` フォルダ、`README.md`、`SETUP.md` など）を、画面にドラッグ＆ドロップします。
6. 下の「Commit changes」を押して完了です。

> 補足：`.github` という隠しフォルダは、アップロードされないことがあります。それは「自動更新」用なので、最初は無くて大丈夫です（ステップ4で扱います）。

> 絶対に守ること：パスワードや API キーは、GitHub に載せません。

## ステップ2：Google Cloud を準備する
Google Cloud は、Google が貸してくれるサーバー（常時動いているコンピューター）です。

1. https://console.cloud.google.com を開き、Google アカウントでログインします。
2. 上部のプロジェクト名をクリック →「新しいプロジェクト」→ 名前は `travel-quest` →「作成」。
   - 作ったあと、画面上部で**そのプロジェクトが選ばれていること**を確認します。
3. 左のメニュー →「お支払い」→ 課金アカウントを作り、プロジェクトに紐づけます（カード登録が必要です）。
4. **予算アラートを設定します（とても大事）**。
   「お支払い」→「予算とアラート」→「予算を作成」→ 金額を例えば 1,000 円にして、メールの通知を有効にします。
   - このアプリは、URL を知っている人が誰でも使えるので、使いすぎの早期発見のために必ず設定してください。

## ステップ3：Cloud Shell でアプリを公開する

> **コマンドの貼り付け方（大事）**
> 手順に出てくる灰色の枠の中身だけを、黒い画面に貼り付けます。枠の上下にある「```bash」や「```」という行は、書き方の印なので**貼りません**（貼ると、コマンドが動かず、何も起きないまま進んでしまいます）。
> 貼り付けたあとに、`>` が表示されて止まったときは、Ctrl キーを押しながら C を押して中断し、やり直してください。
> 1つのコマンドが終わって、`$` の入力待ちに戻ってから、次のコマンドを貼ります。

Cloud Shell は、ブラウザの中で使える作業用の画面（黒い画面）です。自分のパソコンに何もインストールしなくて済みます。

1. Google Cloud の画面の右上にある「Cloud Shell をアクティブにする」（`>_` のアイコン）を押します。
2. 下に黒い画面が開きます。最初の確認が出たら「承認」を押します。
3. 黒い画面の右上の「⋮」→「アップロード」から、`travel-quest-repo.zip` をアップロードします。
4. 黒い画面に、次を1行ずつ貼り付けて、Enter を押します。

```bash
unzip -o travel-quest-repo.zip -d travel-quest
cd travel-quest
```

5. 必要な機能（API）を有効にします。数分かかります。

```bash
gcloud services enable cloudfunctions.googleapis.com run.googleapis.com \
  cloudbuild.googleapis.com artifactregistry.googleapis.com \
  firestore.googleapis.com secretmanager.googleapis.com
```

6. みんなのMAP用のデータベース（Firestore）を作ります。

```bash
gcloud firestore databases create --location=asia-northeast1
```

   「すでにある」というエラーが出たら、そのまま次へ進んで大丈夫です。

7. アプリが、データベースを使えるようにします。

```bash
PN=$(gcloud projects describe $(gcloud config get-value project) --format='value(projectNumber)')
gcloud projects add-iam-policy-binding $(gcloud config get-value project) \
  --member="serviceAccount:${PN}-compute@developer.gserviceaccount.com" \
  --role="roles/datastore.user"
```

8. 公開します（5〜10分かかります）。途中の質問には、`y` と答えます。

```bash
gcloud functions deploy travel-quest \
  --gen2 --runtime=python312 --region=asia-northeast1 \
  --source=app --entry-point=app --trigger-http --allow-unauthenticated \
  --memory=512Mi --timeout=120s --max-instances=3
```

9. 公開されたアプリのURLを表示します。

```bash
gcloud functions describe travel-quest --gen2 --region=asia-northeast1 \
  --format='value(serviceConfig.uri)'
```

   `https://…run.app` というURLが出ます。これをスマホで開いてください。

> `--allow-unauthenticated` は「URLを知っていれば誰でも開ける」設定です。限定したいときは外せますが、そのぶんログインの仕組みが別途必要です。


## ステップ3.5：パスワードだけでログイン（デモ向け・いちばん簡単）
最初の画面でパスワードを入力した人だけが使えます（IDは不要）。`あなたのパスワード` の部分を、決めたパスワードに変えて、次のコマンドで公開します（パスワードはこのコマンドの中にだけ書き、ファイルには書かないでください）。
```
AUTH_ENV='ACCESS_CODE=あなたのパスワード' bash deploy.sh
```
- パスワードはリポジトリには書かず、Google Cloud の関数の設定にだけ保存されます。変えたいときは、値を変えて同じコマンドをもう一度実行します（以前のパスワードで入った端末は、すべて入力し直しになります）。
- ログインの失敗は、接続元IPごとに10分間に10回までです（超えると約10分入れません）。IPの偽装には対応していません。
- 設定が無いと「公開停止」の画面になります。ログイン有効期間は30日です。
- 人ごとにIDを分けたい・デモ用の回数制限を付けたいときは、下の「ログインとデモアカウント」を使います。

## ステップ3.5：ログインとデモアカウントを作る（IDごとに分けたい場合）
ステップ3の公開が終わった直後は、ログイン設定がまだ無いため、URLを開くと「公開停止」の画面が出ます。これは正常です（他人に開かれないための動作）。下の手順でアカウントを作ると、使えるようになります。

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

## ステップ3.5（旧方式）：合言葉だけで守る
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



## かんたん公開スクリプト（おすすめ）
手順が多くて迷うときは、`deploy.sh` を使います。コードの確認、API の有効化、権限の付与、公開、AI の動作テストを、1コマンドで行います。何度実行しても大丈夫です。
```
bash ~/travel-quest/deploy.sh
```
最後に、`★ AIは動いています` と出れば成功です。出ないときは、表示された内容をそのまま貼ってください。

## ステップ3.7：AI を動かす（Vertex AI・キー不要）
旅程づくりと写真判定の AI は、Google Cloud の Vertex AI（Gemini）を使います。**AI のキーは作りません。** 関数に「AIを使ってよい」という権限を付けるだけです。AI の利用は、使った分の課金になります（予算アラートを設定してください）。

1. AI の機能を有効にします。
```
gcloud services enable aiplatform.googleapis.com
```
2. 関数に、AI を使う権限を付けます（2行を1行ずつ）。
```
PN=$(gcloud projects describe $(gcloud config get-value project) --format='value(projectNumber)')
```
```
gcloud projects add-iam-policy-binding $(gcloud config get-value project) --member="serviceAccount:${PN}-compute@developer.gserviceaccount.com" --role="roles/aiplatform.user"
```
3. 新しい `travel-quest-repo.zip` をアップロードして、`unzip -o`（上書き）してから、公開のコマンドをもう一度実行します。
4. アプリの「旅程ランダム」で、気分を書いて試します。写真クエストの撮影でも「映っているもの」が出れば成功です。

- うまくいかないときは、ログを見ます。
```
gcloud functions logs read travel-quest --gen2 --region=asia-northeast1 --limit=30
```
- 使うモデルは、初期値が `gemini-3.8-flash` です（終了したときは、次のモデルに自動で切り替わります）。変えたいときは、公開のコマンドの末尾に `--update-env-vars=GEMINI_MODEL=モデル名` を足します。使えるモデル名・地域は変わることがあるので、Google Cloud の最新の情報で確認してください。
- AI が使えないときは、アプリは自動でランダム案・ダミー判定に切り替わります。

## ステップ3.8：地図を表示する（Google Maps のキー）
みんなのMAPの地図表示と、予定の地図画面の埋め込みに使います。地図のキーだけは、アプリを開いた人のブラウザに渡る仕組みなので、**使える場所を必ず制限**します。

### かんたん版（おすすめ）：スクリプトで地図を設定する
キーの作成・制限・アプリへの受け渡しを、1コマンドで行います。何度実行しても大丈夫です。
```
bash ~/travel-quest/maps.sh
```
最後に `★ 地図のキーが、アプリに渡っています` と出れば成功です。キーは、このアプリのURLだけで使えるように制限されます。以下は、手で設定したいときの手順です。

1. 必要な機能を有効にします。
```
gcloud services enable maps-backend.googleapis.com maps-embed-backend.googleapis.com
```
2. ブラウザで Google Cloud のコンソールを開き、「APIとサービス」→「認証情報」→「認証情報を作成」→「APIキー」を押します。
3. 作成されたキーの「キーを制限」を開き、次のように設定して保存します。
   - **アプリケーションの制限**：「ウェブサイト（HTTP リファラー）」を選び、公開したURLを `https://（あなたのURLの真ん中の部分）.run.app/*` の形で追加します。
   - **API の制限**：「キーを制限」を選び、「Maps JavaScript API」と「Maps Embed API」だけにチェックを入れます。
   - 制限が反映されるまで、数分かかることがあります。
4. キーをアプリに渡して、公開しなおします（キーの部分だけ書き換えます）。
```
gcloud functions deploy travel-quest --gen2 --runtime=python312 --region=asia-northeast1 --source=app --entry-point=app --trigger-http --allow-unauthenticated --memory=512Mi --timeout=120s --max-instances=3 --update-env-vars=MAPS_EMBED_KEY=あなたのキー
```
5. アプリのみんなのMAPを開き、「現在地を取得して周辺を表示」を押すと、地図が出ます。
- キーを GitHub やファイルに書かないでください。
- 地図にエラーが出るときは、ブラウザの開発者ツール（コンソール）のメッセージを教えてください。多くは、リファラーの制限に書いたURLが違う、またはAPIが有効になっていないことが原因です。

## 動作確認チェックリスト
- [ ] 画面が開く
- [ ] 「サンプル旅行で試す」で、予定・クエスト・ボス戦が動く
- [ ] ヘッダーの国旗ボタンで、日本語・英語・中国語を切り替えられる
- [ ] 「みんなのMAP」タブで、現在地を許可すると周辺が表示される
- [ ] 場所を登録でき、一覧に出る
- [ ] （スマホ別端末でも）登録した場所が見える ← 共有ができている証拠

## うまくいかないとき
| 症状 | 確認すること |
|---|---|
| 「課金が有効でない」と出る | ステップ2の3（課金アカウントの紐づけ）を確認 |
| 「権限がありません」と出る | 画面上部で、正しいプロジェクトが選ばれているか確認 |
| デプロイが失敗する | 黒い画面のエラー文を全部コピーして、Claude に貼ってください |
| みんなのMAPで登録できない | 手順3-6と3-7（Firestore の作成と権限）をやったか確認 |
| 現在地が取れない | ブラウザの位置情報を許可。`https://` のURLで開いているか確認 |
| 詳しいログを見たい | `gcloud functions logs read travel-quest --gen2 --region=asia-northeast1` |

---

## ステップ4：あとから足すもの（今は飛ばして大丈夫）

### A. コードを直したとき
GitHub のファイルを更新したあと、ステップ3の手順を、新しい zip で3→8 と繰り返せば反映されます。

### B. AI（旅程づくり・写真判定）
ステップ3.7で、Vertex AI を使って動かします。

### C. 近くの候補検索（Places API）・地図表示（Maps）
Google Cloud で Places API (New) と Maps JavaScript API を有効にして、キーを作ります。キーには必ず「API の制限」と、地図用は「HTTP リファラの制限」をかけます。設定方法は README を見てください。

### D. GitHub に push したら自動で更新する
README の「自動デプロイ」の手順で設定できます。少し難しいので、慣れてからで大丈夫です。設定するときは、GitHub の「Settings → Secrets and variables → Actions → Variables」に値を登録します。

### E. 4人のチームで使う
GitHub のリポジトリの「Settings → Collaborators」から、メンバーを招待します。変更は、直接 main に入れずに、Pull Request（変更の提案）で確認し合う運用がおすすめです。

## 守ること（まとめ）
- API キーやパスワードは、GitHub に載せない
- 予算アラートを必ず設定する
- 公開URLは誰でも使えるので、**個人の場所（自宅など）を、みんなのMAPに登録しない**
- みんなのMAPの荒らし対策として、通報が3件で非表示になります。確認や削除は、Firebase コンソールの Firestore（`spots`）で行えます
