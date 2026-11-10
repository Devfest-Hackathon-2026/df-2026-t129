#!/usr/bin/env python3
"""TRAVEL QUEST: ログイン用アカウントを作ります（パスワードはハッシュにして保存。平文は残りません）。

使い方（Cloud Shell でも自分のPCでもOK。インストール不要）:
  python3 tools/make_users.py demo:demo                 # デモアカウント「demo」を作る（パスワードは自動生成）
  python3 tools/make_users.py demo:demo yamada          # 通常ユーザー「yamada」も一緒に作る
  python3 tools/make_users.py --ask yamada              # パスワードを自分で入力する

名前の後ろに ":demo" を付けると、デモアカウント（セッション1日・AI回数少なめ）になります。
名前は英数字と _ . - のみ、32文字まで。大文字小文字は区別しません。
"""
import getpass, os, secrets, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import accounts  # noqa: E402


def main(argv):
    ask = "--ask" in argv
    specs = [a for a in argv if a != "--ask"]
    if not specs or any(a in ("-h", "--help") for a in specs):
        print(__doc__)
        return 1
    entries, shown, seen = [], [], set()
    for spec in specs:
        name, _, role = spec.partition(":")
        name = name.lower()
        if not accounts.NAME_RE.match(name) or role not in ("", "demo") or name in seen:
            print("【エラー】名前が正しくありません: %r（英数字と _ . - のみ・32文字まで・重複なし・役割は demo のみ）" % spec)
            return 1
        seen.add(name)
        if ask:
            pw = getpass.getpass("%s のパスワード（12文字以上）: " % name)
            if len(pw) < 12 or pw != getpass.getpass("もう一度: "):
                print("【エラー】12文字未満、または一致しません。")
                return 1
        else:
            pw = accounts.generate_password(16)
        entries.append("%s:%s%s" % (name, accounts.hash_password(pw), ":demo" if role else ""))
        shown.append((name, pw if not ask else "（入力したもの）", bool(role)))

    value = "~".join(entries)
    print("\n=== 作成したアカウント（パスワードはこの画面にしか出ません。今すぐ控えてください）")
    for name, pw, demo in shown:
        print("  ID: %-16s パスワード: %s%s" % (name, pw, "   [デモ]" if demo else ""))
    env = "AUTH_USERS=%s,SESSION_SECRET=%s" % (value, secrets.token_urlsafe(32))
    print("\n=== A) deploy.sh で公開するとき（シングルクォートごとコピー）")
    print("AUTH_ENV='%s' bash deploy.sh" % env)
    print("\n=== B) gcloud で直接公開するとき（コマンドの末尾に付ける）")
    print("--update-env-vars='%s'" % env)
    print("\n※ 追加・変更のときは、残したい人も含めて全員分をもう一度作り直してください（この値が全員分の一覧です）。")
    print("※ SESSION_SECRET は毎回変わります。変えると全員がログインし直しになります。固定したいときは前回の値を使ってください。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
