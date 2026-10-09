# -*- coding: utf-8 -*-
# 心臓3Dビューア: Slicer 起動時に実行。モジュールを登録して「アプリ画面」にする。
import os, sys
UPDATE_TIMEOUT = 6      # 秒。ネットが無い・遅いときは待たずに今の版で起動する


def _readSource(root):
    for enc in ("utf-8-sig", "cp932"):
        try: return open(os.path.join(root, "update_source.txt"), encoding=enc).read().strip()
        except Exception: pass
    return None


def _autoUpdate(HV):
    """起動時の自動更新。
    - update_source.txt が https:// なら GitHub Releases の latest.json を見て、新しければ app.zip を取ってきて入れ替える（Windows / Mac / Linux 共通）
    - NAS のパスなら、版が新しければ app フォルダをコピー（Windows は起動前に update.ps1 でも同じことをしている）
    届かなければ何もしない（今の版で起動）"""
    import shutil
    root = os.path.dirname(HV)
    src = _readSource(root)
    if not src: return
    cur = ""
    try: cur = open(os.path.join(HV, "version.txt"), encoding="ascii").read().strip()
    except Exception: pass
    try:
        if src.lower().startswith("https://"):
            _updateFromWeb(HV, src, cur)
        else:
            import sys
            if sys.platform == "win32": return                      # Windows の NAS 更新は起動前の update.ps1 が行う（院外で NAS を待たない）
            nv = os.path.join(src, "app", "version.txt")
            if not os.path.exists(nv): return
            new = open(nv, encoding="ascii").read().strip()
            if new == cur: return
            print(f"[HUCViewS] 更新します {cur} → {new}（{src}）")
            shutil.copytree(os.path.join(src, "app"), HV, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    except Exception as e:
        print("[HUCViewS] 更新できませんでした（今の版で起動します）:", e)


def _sslContext():
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _fetch(url, timeout=UPDATE_TIMEOUT):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "HUCViewS-updater"})
    with urllib.request.urlopen(req, timeout=timeout, context=_sslContext()) as r:
        return r.read()


def _updateFromWeb(HV, manifestUrl, cur):
    """latest.json = {"version": "...", "app_zip": "https://.../HUCViewS-app.zip", "sha256": "...", "min_slicer": "5.6"}"""
    import json, hashlib, zipfile, io, shutil, tempfile
    man = json.loads(_fetch(manifestUrl).decode("utf-8"))
    new = str(man.get("version", "")).strip()
    if not new or new == cur: return
    print(f"[HUCViewS] 新しい版があります {cur or '(なし)'} → {new}。ダウンロード中…")
    data = _fetch(man["app_zip"], timeout=60)
    if man.get("sha256") and hashlib.sha256(data).hexdigest() != man["sha256"].lower():
        raise RuntimeError("ダウンロードしたファイルが壊れています（sha256 不一致）")
    tmp = tempfile.mkdtemp(prefix="hucviews_upd_")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in z.namelist():                                      # zip の外に書き出す名前は拒否（安全のため）
            if n.startswith("/") or ".." in n.replace("\\", "/").split("/"): raise RuntimeError("zip の中身が不正です")
        z.extractall(tmp)
    srcApp = os.path.join(tmp, "app") if os.path.isdir(os.path.join(tmp, "app")) else tmp
    if not os.path.exists(os.path.join(srcApp, "heartview_start.py")): raise RuntimeError("zip に app がありません")
    shutil.copytree(srcApp, HV, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"[HUCViewS] {new} に更新しました")


def _applySlim(HV):
    """使わない Slicer の機能を読み込まない設定（次回の起動から効く）。
    配布版（HeartView フォルダの中の Slicer）だけに設定する。開発 PC の Slicer は触らない。
    元に戻すには HeartView フォルダに full_mode.txt を置いて起動（次回から全部読み込む）。"""
    import os, slicer
    root = os.path.normcase(os.path.abspath(os.path.dirname(HV)))
    home = os.path.normcase(os.path.abspath(slicer.app.slicerHome))
    if not home.startswith(root): return
    f = os.path.join(HV, "ignore_modules.txt")
    want = []
    if os.path.exists(f) and not os.path.exists(os.path.join(root, "full_mode.txt")):
        want = [x.strip() for x in open(f, encoding="ascii").read().split(",") if x.strip()]
    rs = slicer.app.revisionUserSettings()
    cur = rs.value("Modules/IgnoreModules") or []
    if isinstance(cur, str): cur = [x for x in cur.split(",") if x]
    if sorted(cur) != sorted(want):
        rs.setValue("Modules/IgnoreModules", want); rs.sync()
        print(f"[HeartView] 読み込まない機能を {len(want)} 個に設定しました（次回の起動から軽くなります）")


def _heartview_main():
    import os, sys, qt, slicer
    HV = os.environ.get("HEARTVIEW_HOME")
    if not HV or not os.path.isdir(HV):
        HV = os.path.dirname(os.path.abspath(sys.argv[-1]))
    try: _autoUpdate(HV)                               # モジュールを読み込む前に新しい版へ
    except Exception as e: print("[HUCViewS] update:", e)
    mods = os.path.join(HV, "modules")
    fm = slicer.app.moduleManager().factoryManager()
    for name in ("CardiacView", "HeartView", "AortaSizing"):
        d = os.path.join(mods, name)
        if d not in sys.path: sys.path.insert(0, d)
        if hasattr(slicer.modules, name.lower()):
            continue                                   # 開発 PC で既に登録済みならそれを使う
        fm.registerModule(qt.QFileInfo(os.path.join(d, name + ".py")))
        fm.loadModules([name])
    slicer.heartviewAppMode = True
    try: _applySlim(HV)
    except Exception as e: print("[HeartView] slim:", e)
    import HeartView
    qt.QTimer.singleShot(300, HeartView.enterAppMode)
    test = os.environ.get("HEARTVIEW_TEST_DIR")
    if test:                                           # 動作確認用（通常は使わない）
        qt.QTimer.singleShot(3000, lambda: HeartView.selfTest(test, os.environ.get("HEARTVIEW_TEST_LOG")))

try:
    _heartview_main()
except Exception:
    import traceback, slicer
    traceback.print_exc()
    slicer.util.errorDisplay("心臓3Dビューアの起動に失敗しました。\n" + traceback.format_exc())
import sys  # Slicer が実行後に sys を使うので必ず残す
