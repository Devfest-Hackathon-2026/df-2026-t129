#!/bin/bash
# TRAVEL QUEST: まとめて公開するスクリプト（何度実行しても大丈夫です）
# 使い方:  bash ~/travel-quest/deploy.sh
exec 1>&2            # Cloud Shell で結果が見えるように、表示を1か所にまとめる
cd "$(dirname "$0")" || exit 1

REGION=asia-northeast1
PROJECT=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT" ]; then echo "【エラー】プロジェクトが選ばれていません。 gcloud config set project プロジェクトID を実行してください。"; exit 1; fi
PN=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
SA="${PN}-compute@developer.gserviceaccount.com"
echo "=== プロジェクト: $PROJECT (番号 $PN)"

echo; echo "=== 1/6 コードが新しいか確認"
if ! grep -q "google.genai" app/main.py; then
  echo "【止まります】app/main.py が古いままです（AIが Vertex AI に切り替わっていません）。"
  echo "  新しい travel-quest-repo.zip をアップロードして、unzip -o で上書きしてから、もう一度実行してください。"
  exit 1
fi
echo "OK: 新しいコードです"

echo; echo "=== 2/6 必要なAPIを有効にする（数分かかることがあります）"
gcloud services enable cloudfunctions.googleapis.com run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com firestore.googleapis.com aiplatform.googleapis.com secretmanager.googleapis.com || { echo "【エラー】APIを有効にできませんでした（課金設定を確認してください）"; exit 1; }

echo; echo "=== 3/6 権限を付ける"
for ROLE in roles/datastore.user roles/aiplatform.user roles/cloudbuild.builds.builder; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" --role="$ROLE" --condition=None --quiet >/dev/null \
    && echo "OK: $ROLE" || echo "【注意】$ROLE を付けられませんでした"
done

echo; echo "=== 4/6 公開する（5〜10分かかります）"
# 環境変数の引き継ぎ（地図キー・ログイン設定）。AUTH_ENV を渡したときはそれで上書きします。
ENVS=""
add_env() { ENVS="${ENVS:+$ENVS,}$1"; }
get_env() { gcloud functions describe travel-quest --gen2 --region=$REGION --format="value(serviceConfig.environmentVariables.$1)" 2>/dev/null; }
MK=$(get_env MAPS_EMBED_KEY)
if [ -n "$MK" ]; then add_env "MAPS_EMBED_KEY=$MK"; echo "（設定済みの地図キーを引き継ぎます）"; fi
if [ -n "$AUTH_ENV" ]; then
  add_env "$AUTH_ENV"; echo "（新しいログイン設定を反映します）"
  case ",$AUTH_ENV" in *,AUTH_USERS=*) ;; *) add_env "AUTH_USERS=";; esac   # パスワードだけの方式にするときは、古いアカウント設定を空にする
else
  for K in AUTH_USERS SESSION_SECRET ACCESS_CODE; do
    V=$(get_env $K); if [ -n "$V" ]; then add_env "$K=$V"; fi
  done
  echo "（設定済みのログイン設定を引き継ぎます）"
fi
case ",$ENVS" in
  *,AUTH_USERS=*|*,ACCESS_CODE=*) ;;
  *) echo "【注意】ログイン設定（AUTH_USERS）がありません。このままだと、アプリは「公開停止」の画面になります。"
     echo "  python3 tools/make_users.py demo:demo  で作成し、AUTH_ENV を付けて実行してください（SETUP.md「ログインとデモアカウント」）。";;
esac
EXTRA=()
if [ -n "$ENVS" ]; then EXTRA=("--update-env-vars=$ENVS"); fi
gcloud functions deploy travel-quest --gen2 --runtime=python312 --region=$REGION --source=app \
  --entry-point=app --trigger-http --allow-unauthenticated --memory=512Mi --timeout=120s --max-instances=3 \
  "${EXTRA[@]}" --quiet || { echo "【エラー】公開に失敗しました。上のエラー文を、そのまま貼ってください。"; exit 1; }

URL=$(gcloud functions describe travel-quest --gen2 --region=$REGION --format='value(serviceConfig.uri)')
echo; echo "=== 5/6 アプリのURL"
echo "$URL"

echo; echo "=== 6/6 ログイン保護とAIの動作テスト（最大90秒）"
CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 30 -X POST "$URL/ai" -H "Content-Type: application/json" -d '{"task":"itinerary","prompt":"x"}')
if [ "$CODE" = "401" ]; then echo "OK: ログインなしでは /ai が使えません（401）"; else echo "【要確認】ログインなしの /ai が $CODE を返しました（401 のはずです）。"; fi
if [ -n "$TQ_USER" ] && [ -n "$TQ_PASS" ]; then
  JAR=$(mktemp)
  curl -s -o /dev/null -m 30 -c "$JAR" -X POST "$URL/login" --data-urlencode "username=$TQ_USER" --data-urlencode "password=$TQ_PASS"
  RES=$(curl -s -m 90 -b "$JAR" -X POST "$URL/ai" -H "Content-Type: application/json" \
    -d '{"task":"itinerary","prompt":"Reply with the JSON {\"ok\":true} and nothing else."}')
  rm -f "$JAR"
  echo "サーバーの返事: $RES"
  case "$RES" in
    *'"result"'*) echo; echo "★ ログインもAIも動いています。アプリの「旅程ランダム」で試してください。";;
    *)
      echo; echo "【ログインまたはAIが動いていません】原因の手がかり（最近のログ）:"
      sleep 5
      gcloud functions logs read travel-quest --gen2 --region=$REGION --limit=60 2>/dev/null | grep -iE "ai error|permission|denied|not ?found|quota|resource|invalid|module|import|403|404|429" | head -15
      echo; echo "↑ この表示を、そのまま貼ってください。";;
  esac
else
  echo "AIの確認は、ブラウザでURLを開いてログインし、「旅程ランダム」で試してください。"
  echo "（スクリプトで確認したいときは TQ_USER=demo TQ_PASS=パスワード bash deploy.sh）"
fi
