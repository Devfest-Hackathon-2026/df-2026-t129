#!/bin/bash
# TRAVEL QUEST: 地図（Google Maps）のキーを作って、アプリに渡すスクリプト（何度実行しても大丈夫です）
# 使い方:  bash ~/travel-quest/maps.sh
exec 1>&2
cd "$(dirname "$0")" || exit 1
REGION=asia-northeast1
NAME="travel-quest-maps"
PROJECT=$(gcloud config get-value project 2>/dev/null)
echo "=== プロジェクト: $PROJECT"

URL=$(gcloud functions describe travel-quest --gen2 --region=$REGION --format='value(serviceConfig.uri)' 2>/dev/null)
if [ -z "$URL" ]; then echo "【止まります】アプリがまだ公開されていません。先に  bash ~/travel-quest/deploy.sh  を実行してください。"; exit 1; fi
echo "=== アプリのURL: $URL"

echo; echo "=== 1/4 地図の機能を有効にする"
gcloud services enable maps-backend.googleapis.com maps-embed-backend.googleapis.com apikeys.googleapis.com \
  || { echo "【エラー】有効にできませんでした（課金設定・権限を確認してください）"; exit 1; }

echo; echo "=== 2/4 地図用のキーを用意する（使える場所は、このアプリのURLだけに制限します）"
find_key() { gcloud services api-keys list --filter="displayName=$NAME" --format='value(uid)' 2>/dev/null | head -n1; }
KEYID=$(find_key)
if [ -z "$KEYID" ]; then
  gcloud services api-keys create --display-name="$NAME" --allowed-referrers="${URL}/*" \
    --api-target=service=maps-backend.googleapis.com --api-target=service=maps-embed-backend.googleapis.com \
    || { echo "【エラー】キーを作れませんでした。上のエラー文を貼ってください。"; exit 1; }
  sleep 5; KEYID=$(find_key)
else
  echo "すでにキーがあります。制限を最新の状態に更新します。"
  gcloud services api-keys update "$KEYID" --allowed-referrers="${URL}/*" \
    --api-target=service=maps-backend.googleapis.com --api-target=service=maps-embed-backend.googleapis.com \
    || echo "【注意】制限を更新できませんでした（そのまま続けます）"
fi
if [ -z "$KEYID" ]; then echo "【エラー】キーが見つかりません。"; exit 1; fi
KEY=$(gcloud services api-keys get-key-string "$KEYID" --format='value(keyString)')
if [ -z "$KEY" ]; then echo "【エラー】キーの文字列を取得できませんでした。"; exit 1; fi
echo "OK: キーを用意しました（末尾 ${KEY: -4}）。制限: このURL＋Maps JavaScript API / Maps Embed API のみ"

echo; echo "=== 3/4 アプリにキーを渡して公開しなおす（5分ほどかかります）"
gcloud functions deploy travel-quest --gen2 --runtime=python312 --region=$REGION --source=app \
  --entry-point=app --trigger-http --allow-unauthenticated --memory=512Mi --timeout=120s --max-instances=3 \
  --update-env-vars=MAPS_EMBED_KEY="$KEY" --quiet \
  || { echo "【エラー】公開に失敗しました。上のエラー文を貼ってください。"; exit 1; }

echo; echo "=== 4/4 確認"
if curl -s -m 30 "$URL/" | grep -q '"mapsKey"'; then
  echo "★ 地図のキーが、アプリに渡っています。アプリを再読み込みして、「みんなのMAP」で試してください。"
else
  echo "【注意】アプリにキーが見えません。少し待って、もう一度このスクリプトを実行してください。"
fi
echo "（キーの制限が反映されるまで、数分かかることがあります）"
