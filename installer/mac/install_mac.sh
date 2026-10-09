#!/bin/bash
# HUCViewS インストーラー（macOS・管理者権限は通常不要）
# 3D Slicer（公式・無料）と HUCViewS 本体、AI（TotalSegmentator）を ~/HUCViewS に入れ、
# 「アプリケーション」に HUCViewS を作る。以後、起動のたびに GitHub から新しい版を自動で取り込む。
# 使い方（ターミナルに貼る）:
#   curl -fsSL https://github.com/lfb15345-del/HUCViewS/releases/latest/download/install_mac.sh | bash
set -euo pipefail
REPO="lfb15345-del/HUCViewS"
MANIFEST="https://github.com/$REPO/releases/latest/download/latest.json"
HV="$HOME/HUCViewS"
APPDIR="$HOME/Applications"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
step() { printf '\n\033[36m■ %s\033[0m\n' "$1"; }
fail() { printf '\n\033[31mエラー: %s\033[0m\n' "$1"; echo "ネットにつながっているか確認して、もう一度実行してください。"; exit 1; }
json() { # json <file> <key>  （Python 不要: plutil か JavaScript で読む）
  plutil -extract "$2" raw -o - "$1" 2>/dev/null || osascript -l JavaScript -e "JSON.parse(ObjC.unwrap($.NSString.stringWithContentsOfFileEncodingError('$1', 4, null)))['$2']"
}

echo "HUCViewS（心臓・大動脈 3D ビューア）をインストールします。"
echo "研究・教育用です（医療機器ではありません）。全部で 10〜30 分ほどかかります。"
mkdir -p "$HV" "$APPDIR"

if [ "$(uname -m)" = "arm64" ] && ! /usr/bin/arch -x86_64 /usr/bin/true 2>/dev/null; then
  step "Rosetta 2 を入れます（3D Slicer の Mac 版は Intel 用のため。パスワードを聞かれたら Mac のログインパスワード）"
  softwareupdate --install-rosetta --agree-to-license || sudo softwareupdate --install-rosetta --agree-to-license || fail "Rosetta 2 を入れられませんでした"
fi

if [ ! -d "$HV/Slicer.app" ]; then
  step "3D Slicer（公式・無料・約450MB）をダウンロードしています…"
  curl -fL --progress-bar -o "$TMP/Slicer.dmg" "https://download.slicer.org/download?os=macosx&stability=release" || fail "3D Slicer をダウンロードできませんでした"
  step "3D Slicer を入れています…"
  MNT="$TMP/mnt"; mkdir -p "$MNT"
  hdiutil attach -nobrowse -readonly -mountpoint "$MNT" "$TMP/Slicer.dmg" >/dev/null || fail "ディスクイメージを開けませんでした"
  cp -R "$MNT/Slicer.app" "$HV/Slicer.app" || { hdiutil detach "$MNT" >/dev/null; fail "コピーできませんでした"; }
  hdiutil detach "$MNT" >/dev/null || true
else
  step "3D Slicer は入っています"
fi
SLICER="$HV/Slicer.app/Contents/MacOS/Slicer"
[ -x "$SLICER" ] || fail "3D Slicer が見つかりません"

step "HUCViewS 本体を取得しています…"
curl -fsSL -o "$TMP/latest.json" "$MANIFEST" || fail "版の情報を取得できませんでした"
ZIPURL="$(json "$TMP/latest.json" app_zip)"; SHA="$(json "$TMP/latest.json" sha256 || true)"; VER="$(json "$TMP/latest.json" version || true)"
curl -fsSL -o "$TMP/app.zip" "$ZIPURL" || fail "本体をダウンロードできませんでした"
if [ -n "$SHA" ]; then
  GOT="$(shasum -a 256 "$TMP/app.zip" | awk '{print $1}')"
  [ "$GOT" = "$SHA" ] || fail "ダウンロードしたファイルが壊れています"
fi
unzip -oq "$TMP/app.zip" -d "$HV"
printf '%s\n' "$MANIFEST" > "$HV/update_source.txt"
echo "  版: $VER"

export HEARTVIEW_HOME="$HV/app"
step "AI（TotalSegmentator）の拡張機能を入れています（数分）…"
HUCVIEWS_SETUP_PHASE=ext "$SLICER" --no-splash --no-main-window --python-script "$HV/app/setup_in_slicer.py" || true
step "AI の部品（PyTorch など）を入れています。Slicer の画面が出たら、閉じるまでそのままお待ちください（10〜20分）…"
HUCVIEWS_SETUP_PHASE=py "$SLICER" --no-splash --python-script "$HV/app/setup_in_slicer.py" || echo "（AI の部品は入りませんでした。表示・計測は使えます。AI は Windows で作った症例を開いて使ってください）"

step "「アプリケーション」に HUCViewS を作っています…"
rm -rf "$APPDIR/HUCViewS.app"
osacompile -o "$APPDIR/HUCViewS.app" -e 'do shell script "export HEARTVIEW_HOME=\"$HOME/HUCViewS/app\"; \"$HOME/HUCViewS/Slicer.app/Contents/MacOS/Slicer\" --no-splash --python-script \"$HOME/HUCViewS/app/heartview_start.py\" > /dev/null 2>&1 &"' || fail "起動アイコンを作れませんでした"
if [ -f "$HV/app/HUCViewS_icon.png" ]; then
  IS="$TMP/icon.iconset"; mkdir -p "$IS"
  for s in 16 32 64 128 256 512; do sips -z $s $s "$HV/app/HUCViewS_icon.png" --out "$IS/icon_${s}x${s}.png" >/dev/null 2>&1 || true; done
  iconutil -c icns "$IS" -o "$APPDIR/HUCViewS.app/Contents/Resources/applet.icns" 2>/dev/null || true
  touch "$APPDIR/HUCViewS.app"
fi

printf '\n\033[32mインストールが終わりました。Finder の「アプリケーション」（ホームの中）の HUCViewS から起動してください。\033[0m\n'
echo "（心腔の色分けを使うには、起動後の画面で「AI ライセンスを登録する」から無料の学術ライセンス番号を入れてください）"
echo "記録: $HV/setup_log.txt"
open "$APPDIR" || true
