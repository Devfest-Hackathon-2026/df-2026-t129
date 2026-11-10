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
EXTRA=""
MK=$(gcloud functions describe travel-quest --gen2 --region=$REGION --format='value(serviceConfig.environmentVariables.MAPS_EMBED_KEY)' 2>/dev/null)
if [ -n "$MK" ]; then EXTRA="--update-env-vars=MAPS_EMBED_KEY=$MK"; echo "（設定済みの地図キーを引き継ぎます）"; fi
gcloud functions deploy travel-quest --gen2 --runtime=python312 --region=$REGION --source=app \
  --entry-point=app --trigger-http --allow-unauthenticated --memory=512Mi --timeout=120s --max-instances=3 \
  $EXTRA --quiet || { echo "【エラー】公開に失敗しました。上のエラー文を、そのまま貼ってください。"; exit 1; }

URL=$(gcloud functions describe travel-quest --gen2 --region=$REGION --format='value(serviceConfig.uri)')
echo; echo "=== 5/6 アプリのURL"
echo "$URL"

echo; echo "=== 6/6 AIの動作テスト（最大90秒）"
JAR=$(mktemp)
CODE=$(gcloud functions describe travel-quest --gen2 --region=$REGION --format='value(serviceConfig.environmentVariables.ACCESS_CODE)' 2>/dev/null)
if [ -n "$CODE" ]; then
  echo "（合言葉が設定されているので、テスト用にログインします。合言葉は表示しません）"
  curl -s -m 30 -o /dev/null -c "$JAR" -X POST "$URL/login" --data-urlencode "code=$CODE"
fi
RES=$(curl -s -m 90 -b "$JAR" -X POST "$URL/ai" -H "Content-Type: application/json" \
  -d '{"task":"itinerary","prompt":"Reply with the JSON {\"ok\":true} and nothing else."}')
rm -f "$JAR"
echo "サーバーの返事: $RES"
case "$RES" in
  *'"result"'*) echo; echo "★ AIは動いています。アプリの「旅程ランダム」で試してください。";;
  *unauthorized*) echo; echo "【テストができませんでした】合言葉のログインに失敗しました。AIの問題とは限りません。アプリをブラウザで開き、合言葉を入れて「旅程ランダム」を直接試してください。";;
  *)
    echo; echo "【AIが動いていません】原因の手がかり（最近のログ。古い記録が混ざることがあります）:"
    sleep 5
    gcloud functions logs read travel-quest --gen2 --region=$REGION --limit=60 2>/dev/null | grep -iE "ai error|permission|denied|not ?found|quota|resource|invalid|module|import|403|404|429" | head -15
    echo; echo "↑ この表示を、そのまま貼ってください。";;
esac
