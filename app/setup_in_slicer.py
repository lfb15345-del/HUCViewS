# -*- coding: utf-8 -*-
"""HUCViewS の初回セットアップ（インストーラーから Slicer の中で実行される）。
  環境変数 HUCVIEWS_SETUP_PHASE:
    ext … 拡張機能（AI: TotalSegmentator と依存の PyTorch 拡張、中心線: SlicerVMTK）を Slicer に入れる（入れたら終了。次の起動から有効）
    py  … AI の Python 部品（PyTorch・totalsegmentator）を入れる（数分〜十数分）
  結果は HUCViewS フォルダの setup_log.txt に書く。患者データは扱わない。"""
import os, sys, time, traceback
import slicer, qt

HV = os.environ.get("HEARTVIEW_HOME") or os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(os.path.dirname(HV), "setup_log.txt")


def log(m):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + str(m)
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f: f.write(line + "\n")
    except Exception: pass


def installExtensions(names=("TotalSegmentator", "SlicerVMTK")):
    em = slicer.app.extensionsManagerModel()
    try: em.interactive = False                       # 確認の窓を出さない
    except Exception: pass
    ok = True
    for name in names:
        if em.isExtensionInstalled(name):
            log(f"{name}: 入っています"); continue
        log(f"{name}: ダウンロードして入れます…")
        done = False
        try:
            done = bool(em.installExtensionFromServer(name, False))
        except Exception as e:
            log(f"installExtensionFromServer: {e}")
        if not done:
            try:
                em.updateExtensionsMetadataFromServer(True, True)
                done = bool(em.downloadAndInstallExtensionByName(name, True, True))
            except Exception as e:
                log(f"downloadAndInstallExtensionByName: {e}")
        log(f"{name}: {'完了' if done else '失敗'}"); ok = ok and done
    return ok


def installPython():
    try:
        import TotalSegmentator
    except Exception as e:
        log(f"TotalSegmentator 拡張が読み込めません（先に ext を実行）: {e}"); return False
    try:
        import torch, totalsegmentator  # noqa: F401
        log(f"AI の部品は入っています（torch {torch.__version__}）"); return True
    except Exception:
        pass
    log("AI の部品（PyTorch・totalsegmentator）を入れます。数分〜十数分かかります…")
    try:
        TotalSegmentator.TotalSegmentatorLogic().setupPythonRequirements()
        import torch  # noqa: F401
        log(f"完了（torch {torch.__version__}）"); return True
    except Exception:
        log("失敗:\n" + traceback.format_exc()); return False


def main():
    phase = os.environ.get("HUCVIEWS_SETUP_PHASE", "").strip()
    log(f"setup phase={phase} slicer={slicer.app.applicationVersion} python={sys.version.split()[0]} platform={sys.platform}")
    ok = True
    try:
        if phase == "ext": ok = installExtensions()
        elif phase == "py": ok = installPython()
        else: log("phase が指定されていません"); ok = False
    except Exception:
        log(traceback.format_exc()); ok = False
    log("OK" if ok else "NG")
    qt.QTimer.singleShot(500, lambda: slicer.app.exit(0 if ok else 1))


main()
