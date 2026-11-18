# -*- coding: utf-8 -*-
# 心臓3Dビューア: Slicer 起動時に実行。モジュールを登録して「アプリ画面」にする。
import os, sys
UPDATE_TIMEOUT = 6      # 秒。ネットが無い・遅いときは待たずに今の版で起動する


def _readSource(root):
    for enc in ("utf-8-sig", "cp932"):
        try: return open(os.path.join(root, "update_source.txt"), encoding=enc).read().strip()
        except Exception: pass
    return None


def _shouldUpdate(new, cur):
    """新しい版に入れ替えるか。同じなら入れ替えない。どちらも「年月日-時分」の形で、相手のほうが古い時も入れ替えない
    （前は「違えば入れ替える」だったので、古い版が返ってきた時に古い版へ戻ることがあった）"""
    import re
    if not new or new == cur: return False
    ok = lambda v: bool(re.match(r"^\d{8}-\d{4}$", v or ""))
    if ok(new) and ok(cur) and new < cur: return False
    return True


def _copyApp(srcApp, HV):
    """app の中身を新しい版に入れ替える。
    1) まず全部を「<名前>.new」として写す（ここで失敗したら .new を消してやめる = 今の版は無傷のまま）
    2) 入れ替える。version.txt は最後（前は順番が決まっておらず、途中で止まると「更新済み」と思い込んで、新旧が混ざったまま直らないことがあった）"""
    import shutil
    rels = []
    for r, ds, fs in os.walk(srcApp):
        ds[:] = [d for d in ds if d != "__pycache__"]
        rels += [os.path.relpath(os.path.join(r, f), srcApp) for f in fs if not f.endswith((".pyc", ".new"))]
    rels.sort(key=lambda q: (q.replace("\\", "/") == "version.txt", q))
    done = []
    try:
        for rel in rels:
            dst = os.path.join(HV, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(srcApp, rel), dst + ".new"); done.append(dst + ".new")
    except Exception:
        for q in done:
            try: os.remove(q)
            except Exception: pass
        raise
    for rel in rels: os.replace(os.path.join(HV, rel) + ".new", os.path.join(HV, rel))


def _slicerAtLeast(minv):
    """この Slicer が、その版の求める Slicer（例 "5.8"）以上か。分からない時は True"""
    try:
        import slicer
        want = tuple(int(x) for x in str(minv).strip().split(".")[:2])
        return (int(slicer.app.majorVersion), int(slicer.app.minorVersion)) >= want
    except Exception:
        return True


def _autoUpdate(HV):
    """起動時の自動更新。
    - update_source.txt が https:// なら GitHub Releases の latest.json を見て、新しければ app.zip を取ってきて入れ替える（Windows / Mac / Linux 共通）
    - NAS のパスなら、版が新しければ app フォルダをコピー（Windows は起動前に update.ps1 でも同じことをしている）
    届かなければ何もしない（今の版で起動）"""
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
            if not _shouldUpdate(new, cur): return
            print(f"[HUCViewS] 更新します {cur} → {new}（{src}）")
            _copyApp(os.path.join(src, "app"), HV)
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


def _resolveManifest(url):
    """「最新リリース」の短縮 URL は国・回線によって古い版が数分〜しばらく返ることがあるので、
    GitHub API で最新リリースを調べて、その版の latest.json の確定 URL を使う（失敗したら元の URL）"""
    import re, json
    m = re.match(r"https://github\.com/([^/]+/[^/]+)/releases/latest/download/([^/?#]+)$", url)
    if not m: return url
    try:
        rel = json.loads(_fetch(f"https://api.github.com/repos/{m.group(1)}/releases/latest").decode("utf-8"))
        for a in rel.get("assets", []):
            if a.get("name") == m.group(2): return a["browser_download_url"]
    except Exception as e:
        print("[HUCViewS] api:", e)
    return url


def _updateFromWeb(HV, manifestUrl, cur):
    """latest.json = {"version": "...", "app_zip": "https://.../HUCViewS-app.zip", "sha256": "...", "min_slicer": "5.6"}"""
    import json, hashlib, zipfile, io, shutil, tempfile
    man = json.loads(_fetch(_resolveManifest(manifestUrl)).decode("utf-8"))
    new = str(man.get("version", "")).strip()
    if not _shouldUpdate(new, cur): return
    if man.get("min_slicer") and not _slicerAtLeast(man["min_slicer"]):
        print(f"[HUCViewS] 新しい版 {new} は Slicer {man['min_slicer']} 以上が必要です。この Slicer では更新しません（インストーラーを実行し直してください）"); return
    print(f"[HUCViewS] 新しい版があります {cur or '(なし)'} → {new}。ダウンロード中…")
    data = _fetch(man["app_zip"], timeout=60)
    if man.get("sha256") and hashlib.sha256(data).hexdigest() != man["sha256"].lower():
        raise RuntimeError("ダウンロードしたファイルが壊れています（sha256 不一致）")
    tmp = tempfile.mkdtemp(prefix="hucviews_upd_")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in z.namelist():                                  # zip の外に書き出す名前は拒否（安全のため）
                if n.startswith("/") or ".." in n.replace("\\", "/").split("/"): raise RuntimeError("zip の中身が不正です")
            z.extractall(tmp)
        srcApp = os.path.join(tmp, "app") if os.path.isdir(os.path.join(tmp, "app")) else tmp
        if not os.path.exists(os.path.join(srcApp, "heartview_start.py")): raise RuntimeError("zip に app がありません")
        _copyApp(srcApp, HV)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)                      # 失敗した時も、取ってきたものを一時フォルダに残さない
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
