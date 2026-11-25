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
getr() { # getr <url> <file> <size>: つながりが切れたら、取れた所の続きから取り直す。取れた所までは残すので、もう一度実行しても続きから
  # 続きの頼み方: ふつうは curl -C -（HTTP の Range）。Range に応えないサーバー（3D Slicer の配布元の Girder。curl は「続きを返さない」と言って止まる）には、
  # 行き先（リダイレクトの後）の URL に offset= を付けて頼み、返ってきたのが続き（Content-Range が取れた所から）の時だけ足す
  local url="$1" out="$2" size="${3:-0}" i have rc final="" off=0 noff=0 part="$2.part" hdr="$2.hdr" sep
  case "$size" in ''|*[!0-9]*) size=0 ;; esac
  for i in $(seq 1 40); do
    have=0; [ -f "$out" ] && have=$(( $(wc -c < "$out") ))
    if [ "$size" -gt 0 ] && [ "$have" -gt "$size" ]; then rm -f "$out"; have=0; fi   # 大きすぎる残り → 初めから
    if [ "$size" -gt 0 ] && [ "$have" -eq "$size" ]; then return 0; fi
    rc=0
    if [ "$off" -eq 1 ] && [ "$have" -gt 0 ]; then
      case "$final" in *\?*) sep='&' ;; *) sep='?' ;; esac
      rm -f "$part" "$hdr"
      curl -fL --progress-bar --connect-timeout 30 --speed-time 60 --speed-limit 1 -D "$hdr" -o "$part" "${final}${sep}offset=$have" || rc=$?
      if [ -f "$part" ] && tr -d '\r' < "$hdr" 2>/dev/null | grep -qi "^content-range: bytes $have-"; then cat "$part" >> "$out"
      elif [ "$rc" -eq 22 ]; then off=0; noff=1                                 # offset が効かない → 前のやり方（初めから）に戻す
      elif [ "$rc" -eq 0 ]; then rc=99; fi                                     # 続きでない中身は足さない
      rm -f "$part" "$hdr"
    else
      curl -fL --progress-bar --connect-timeout 30 --speed-time 60 --speed-limit 1 -C - -o "$out" "$url" || rc=$?
    fi
    if [ "$rc" -eq 0 ]; then
      [ "$size" -gt 0 ] || return 0
      have=$(( $(wc -c < "$out") )); [ "$have" -eq "$size" ] && return 0
    elif [ "$rc" -eq 33 ] && [ "$noff" -eq 0 ]; then                          # Range に応えない → 行き先を調べて、次は offset で（待たずに）
      final="$(curl -fsS -o /dev/null -w '%{redirect_url}' "$url" 2>/dev/null || true)"; [ -n "$final" ] || final="$url"
      off=1; continue
    elif [ "$rc" -eq 33 ]; then rm -f "$out"                                    # 続きを返さないサーバー → 初めから
    elif [ "$rc" -eq 22 ] && [ "$off" -eq 0 ] && [ "$noff" -eq 0 ]; then return 1   # 404 など（取り直しても同じ）
    fi
    echo "  （つながりが切れました。続きから取り直します: $i 回目）"; sleep 3
  done
  return 1
}

echo "HUCViewS（心臓・大動脈 3D ビューア）をインストールします。"
echo "研究・教育用です（医療機器ではありません）。全部で 10〜30 分ほどかかります。"
mkdir -p "$HV" "$APPDIR"

if [ "$(uname -m)" = "arm64" ] && ! /usr/bin/arch -x86_64 /usr/bin/true 2>/dev/null; then
  step "Rosetta 2 を入れます（3D Slicer の Mac 版は Intel 用のため。パスワードを聞かれたら Mac のログインパスワード）"
  softwareupdate --install-rosetta --agree-to-license || sudo softwareupdate --install-rosetta --agree-to-license || fail "Rosetta 2 を入れられませんでした"
fi

curl -fsSL -o "$TMP/latest.json" "$MANIFEST" || fail "版の情報を取得できませんでした"
SV="$(json "$TMP/latest.json" slicer 2>/dev/null || true)"; case "$SV" in [0-9]*) ;; *) SV="" ;; esac   # 動作を確かめた Slicer の版

if [ ! -d "$HV/Slicer.app" ]; then
  step "3D Slicer（公式・無料・約450MB）をダウンロードしています…"
  FIND="https://download.slicer.org/find?os=macosx&stability=release"        # 確かめた版（latest.json の slicer）。無い時だけ、その日の最新の版
  { [ -n "$SV" ] && curl -fsSL -o "$TMP/find.json" "$FIND&version=$SV" && [ "$(json "$TMP/find.json" version || true)" = "$SV" ]; } \
    || curl -fsSL -o "$TMP/find.json" "$FIND" || fail "3D Slicer の情報を取得できませんでした"
  DPATH="$(json "$TMP/find.json" download_url)" || fail "3D Slicer の情報を読めませんでした"; DURL="https://download.slicer.org$DPATH"
  SSIZE="$(json "$TMP/find.json" size || true)"
  S512="$(json "$TMP/find.json" sha512 || true)"; SVER="$(json "$TMP/find.json" version || true)"
  DL="$HV/.download"; mkdir -p "$DL"; DMG="$DL/Slicer-$(printf '%s' "${SVER:-latest}" | tr -cd '0-9A-Za-z.-').dmg"   # 版ごとの名前（別の版の続きをつながない）
  getr "$DURL" "$DMG" "$SSIZE" || fail "3D Slicer のダウンロードが何度も途中で切れました。取れた所までは残してあるので、もう一度実行すると続きから取ります。"
  if [ -n "$S512" ]; then                                                    # 続きをつないだ所も含めて、公式の値と同じか
    GOT="$(shasum -a 512 "$DMG" | awk '{print $1}')"
    [ "$GOT" = "$S512" ] || { rm -f "$DMG"; fail "3D Slicer のダウンロードが壊れていました。もう一度実行してください（初めから取り直します）。"; }
  fi
  step "3D Slicer を入れています…"
  MNT="$TMP/mnt"; mkdir -p "$MNT"
  hdiutil attach -nobrowse -readonly -mountpoint "$MNT" "$DMG" >/dev/null || fail "ディスクイメージを開けませんでした"
  cp -R "$MNT/Slicer.app" "$HV/Slicer.app" || { hdiutil detach "$MNT" >/dev/null; fail "コピーできませんでした"; }
  hdiutil detach "$MNT" >/dev/null || true
  rm -rf "$DL"
else
  step "3D Slicer は入っています"
fi
SLICER="$HV/Slicer.app/Contents/MacOS/Slicer"
[ -x "$SLICER" ] || fail "3D Slicer が見つかりません"

step "HUCViewS 本体を取得しています…"
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
