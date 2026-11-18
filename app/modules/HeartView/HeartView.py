# -*- coding: utf-8 -*-
r"""
HeartView — CD-R から取り込んで心臓の 3D を作る「入口」画面（研究・教育用、非医療機器）
  ① CD / フォルダ / 保存した症例 から読み込む
  ② おすすめのシリーズを自動で選ぶ（造影・軸位・薄いスライス・CTA を優先）
  ③ 「3D を作る」→ CardiacView の全自動処理 → 四腔断面で表示 → 症例を自動保存
データはこの PC の中だけで扱い、外部には送信しない。
"""
import os, re, time, glob, json
import numpy as np
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *

APP_TITLE = "HUCViewS"
APP_SUBTITLE = "心臓3Dビューア"
CASES_DIRNAME = "HeartView症例"


def appVersion():
    """この PC に入っている版（app\version.txt。「年月日-時分」）。読めなければ """""
    try:
        d = os.environ.get("HEARTVIEW_HOME") or ""
        if not os.path.exists(os.path.join(d, "version.txt")): d = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return open(os.path.join(d, "version.txt"), encoding="ascii").read().strip()[:20]
    except Exception: return ""


def casesPath():
    """症例の保存先（作らない）"""
    return os.path.join(qt.QStandardPaths.writableLocation(qt.QStandardPaths.DocumentsLocation), CASES_DIRNAME)


def casesDir():
    d = casesPath()
    os.makedirs(os.path.join(d, "画像"), exist_ok=True)
    return d


def cloudSyncName(path):
    """path がクラウドと同期するフォルダ（OneDrive・iCloud・Dropbox・Google ドライブ）の中なら、その名前。違えば ""。
    Windows の「ドキュメント」は、設定によって OneDrive の中に置かれる（その時は、保存した症例＝患者の CT がクラウドにも送られる）"""
    try:
        p = os.path.normcase(os.path.abspath(str(path))).replace("\\", "/").lower()
        for k in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
            e = os.environ.get(k)
            if e and (p + "/").startswith(os.path.normcase(os.path.abspath(e)).replace("\\", "/").lower().rstrip("/") + "/"): return "OneDrive"
        for mark, name in (("onedrive", "OneDrive"), ("icloud", "iCloud"), ("com~apple~clouddocs", "iCloud"), ("dropbox", "Dropbox"),
                           ("google drive", "Google ドライブ"), ("googledrive", "Google ドライブ"), ("マイドライブ", "Google ドライブ")):
            if any(mark in part for part in p.split("/")): return name
    except Exception: pass
    return ""


_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _fixText(t):
    """DICOM の文字（日本の CT は ISO 2022 の漢字。制御文字 ESC が混ざる）を、保存できる普通の文字に直す。
    ESC が残ると症例ファイル（.mrb）の中の XML が壊れて、開けなくなる"""
    if not t or not _CTRL.search(t): return t
    try: return t.encode("latin-1").decode("iso2022_jp")
    except Exception: return _CTRL.sub("", t)


def cleanSceneText():
    """保存の前に、シーンの名前・属性から制御文字を取り除く"""
    n = 0
    try:
        sh = slicer.mrmlScene.GetSubjectHierarchyNode()
        ids = vtk.vtkIdList(); sh.GetItemChildren(sh.GetSceneItemID(), ids, True)
        for i in range(ids.GetNumberOfIds()):
            it = ids.GetId(i); nm = sh.GetItemName(it); f = _fixText(nm)
            if f != nm: sh.SetItemName(it, f); n += 1
            for a in list(sh.GetItemAttributeNames(it)):
                v = sh.GetItemAttribute(it, a); f = _fixText(v)
                if f != v: sh.SetItemAttribute(it, a, f); n += 1
    except Exception as e: print("cleanSceneText(sh):", e)
    for i in range(slicer.mrmlScene.GetNumberOfNodes()):
        node = slicer.mrmlScene.GetNthNode(i)
        try:
            nm = node.GetName() or ""; f = _fixText(nm)
            if f != nm: node.SetName(f); n += 1
            for a in list(node.GetAttributeNames() or []):
                v = node.GetAttribute(a) or ""; f = _fixText(v)
                if f != v: node.SetAttribute(a, f); n += 1
        except Exception: pass
    return n


def repairCaseFile(path):
    """制御文字で開けなくなった症例ファイルを直す（中の .mrml の文字だけ直して、ほかはそのまま）"""
    import zipfile
    tmp = path + ".fix"
    try:
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", allowZip64=True) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename.endswith(".mrml"):
                    txt = data.decode("utf-8", "replace")
                    txt = re.sub(r'"[^"<>]*[\x00-\x08\x0b\x0c\x0e-\x1f\x7f][^"<>]*"', lambda m: '"' + _fixText(m.group(0)[1:-1]) + '"', txt)
                    data = _CTRL.sub("", txt).encode("utf-8")
                zout.writestr(item, data, compress_type=item.compress_type)
    except Exception:
        try:
            if os.path.exists(tmp): os.remove(tmp)                            # 直せなかった時に、書きかけを残さない（もとのファイルには触っていない）
        except Exception: pass
        raise
    bak = path + ".bak"
    if os.path.exists(bak): os.remove(bak)
    os.replace(path, bak); os.replace(tmp, path)
    return bak


def _safe(s, n=40):
    s = re.sub(r'[\\/:*?"<>|\s%\x00-\x1f\x7f]+', "_", str(s or "")).strip("_. ")   # 制御文字（日本語の説明に混ざる ESC など）は Windows のファイル名に使えない → 保存に失敗する
    return s[:n].rstrip("_. ") or "x"


def workSignature():
    """使う人が足したもの（計測・中心線・パッチ）のしるし。保存した時・開いた時のしるしと違えば「保存していない変更がある」。
    切断面や見る向きなどの「見方」は入れない（見ただけで「変更あり」にしない）"""
    sig = []
    try:
        for n in slicer.util.getNodesByClass("vtkMRMLMarkupsNode"):
            if n.IsA("vtkMRMLMarkupsPlaneNode") or n.IsA("vtkMRMLMarkupsROINode") or (n.GetName() or "").startswith("cv_"): continue
            k = n.GetNumberOfControlPoints()
            if k == 0: continue
            pts = []
            for i in range(k):
                q = [0.0, 0.0, 0.0]; n.GetNthControlPointPosition(i, q); pts.append(tuple(round(float(x), 2) for x in q))
            sig.append((n.GetClassName(), tuple(pts)))
        for n in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            if (n.GetName() or "") == "CV パッチ":
                pd = n.GetPolyData(); sig.append(("patch", (pd.GetNumberOfPoints(), pd.GetNumberOfCells()) if pd is not None else (0, 0)))
    except Exception as e: print("[HeartView] workSignature:", e)
    return tuple(sorted(sig, key=repr))


# ============================================================================ app mode
def enterAppMode():
    mw = slicer.util.mainWindow()
    for f in ("setMenuBarsVisible", "setToolbarsVisible", "setApplicationLogoVisible", "setModuleHelpSectionVisible",
              "setModulePanelTitleVisible", "setDataProbeVisible", "setPythonConsoleVisible"):
        try: getattr(slicer.util, f)(False)
        except Exception as e: print(f, e)
    mw.setWindowTitle(f"{APP_TITLE} — {APP_SUBTITLE}（研究・教育用／診断には元画像を確認）")
    try:
        ico = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "HUCViewS.ico")
        if os.path.exists(ico): mw.setWindowIcon(qt.QIcon(ico)); slicer.app.setWindowIcon(qt.QIcon(ico))
    except Exception: pass
    try: slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView)
    except Exception: pass
    try:
        v = slicer.app.layoutManager().threeDWidget(0).threeDView()
        vn = v.mrmlViewNode(); vn.SetBoxVisible(False); vn.SetAxisLabelsVisible(False)
        vn.SetBackgroundColor(0, 0, 0); vn.SetBackgroundColor2(0, 0, 0)
        slicer.app.layoutManager().threeDWidget(0).threeDController().setVisible(False)
    except Exception: pass
    try:
        dock = mw.findChild(qt.QDockWidget, "PanelDockWidget")
        dock.setMinimumWidth(220)                                      # 狭くもできる（境目をドラッグ）
        w0 = int(qt.QSettings().value("HUCViewS/panelWidth", 420) or 420)
        mw.resizeDocks([dock], [max(220, w0)], qt.Qt.Horizontal)
        _panelToggle(mw, dock)
        guardPanelWheel(dock)
    except Exception as e: print("panel:", e)
    try:
        if getattr(slicer, "_hvExitGuard", None) is None:
            slicer._hvExitGuard = _ExitGuard(); mw.installEventFilter(slicer._hvExitGuard)
            slicer.app.connect("aboutToQuit()", cleanupTmpDicom)              # ほかの終わり方（Slicer の確認を通った時など）でも片付ける
    except Exception as e: print("exit guard:", e)
    try: fixDicomSetting()
    except Exception as e: print("dicom setting:", e)
    slicer.heartviewAppMode = True
    slicer.util.selectModule("HeartView")
    mw.showMaximized()


class _WheelGuard(qt.QObject):
    """パネルをホイールでスクロールしている途中に、スライダー・数値欄・選択欄の上を通っても値が変わらないようにする。
    クリックして選んだ（フォーカスのある）時だけ、ホイールで値を変えられる。"""
    def eventFilter(self, obj, ev):
        try:
            if ev.type() != qt.QEvent.Wheel or obj.hasFocus(): return False
            p = obj.parentWidget()
            while p is not None and not isinstance(p, qt.QAbstractScrollArea): p = p.parentWidget()
            if p is not None:
                sb = p.verticalScrollBar(); d = ev.angleDelta().y()
                sb.setValue(sb.value - int(d / 120.0 * max(sb.singleStep, 20) * 3))
            return True
        except Exception:
            return False


class _ExitGuard(qt.QObject):
    """アプリ画面で窓を閉じる時: 保存していない変更（計測・パッチなど）があれば日本語でたずねてから終わる。無ければそのまま終わる。
    前は Slicer の英語の確認（Save before exit?）が毎回出て、その「Save」は Slicer の保存の窓（何がどこに保存されるか分かりにくい）を開いていた。
    作業の途中・ここで何か失敗した時は、前と同じ（Slicer の確認）に任せる"""
    def eventFilter(self, obj, ev):
        try:
            if ev.type() != qt.QEvent.Close or not getattr(slicer, "heartviewAppMode", False): return False
            if getattr(self, "_leaving", False):
                ev.ignore(); return True                                      # 終わる途中の二重押し
            w = slicer.modules.heartview.widgetRepresentation().self()
            if getattr(w, "_working", False): return False
            if w.logic.hasUnsaved():
                r = w._askLeave(True)
                if r not in ("save", "discard") or (r == "save" and not w.onSaveCase()):
                    ev.ignore(); return True                                  # 「やめる」・保存できなかった → 閉じない
            self._leaving = True; ev.ignore()
            qt.QTimer.singleShot(60000, lambda: setattr(self, "_leaving", False))  # 万一終わらなかった時に、閉じられないままにしない
            def leave():
                mw = None
                try: mw = slicer.util.mainWindow(); mw.hide(); slicer.app.processEvents()   # 片付け（CD の写しが多いと数秒）の間、窓を残さない
                except Exception: pass
                try: cleanupTmpDicom()
                finally:
                    try: slicer.util.exit(0)                                  # Slicer の確認を通らずに終わる
                    except Exception as e:
                        print("[HeartView] 終了:", e)
                        if mw is not None: mw.show()
            qt.QTimer.singleShot(0, leave)
            return True
        except Exception as e:
            print("[HeartView] 終了の確認:", e); return False


def guardPanelWheel(root, every=1500):
    """root の中のスライダー・数値欄・選択欄に _WheelGuard を付ける（新しくできた部品にも、定期的に付け直す）"""
    g = getattr(slicer, "_hvWheelGuard", None)
    if g is None: g = slicer._hvWheelGuard = _WheelGuard()
    def apply():
        try:
            for cls in ("QAbstractSlider", "QAbstractSpinBox", "QComboBox"):
                for w in root.findChildren(getattr(qt, cls)):
                    if w.property("hvWheel"): continue
                    w.setProperty("hvWheel", True); w.setFocusPolicy(qt.Qt.StrongFocus); w.installEventFilter(g)
        except Exception as e: print("wheel guard:", e)
    apply()
    t = getattr(slicer, "_hvWheelTimer", None)
    if t is None:
        t = slicer._hvWheelTimer = qt.QTimer(); t.setInterval(every); t.connect("timeout()", apply); t.start()
    return apply


def _placePanelButton():
    """パネルのつまみを画面の左端の真ん中へ（ビューの操作バーや全体図と重ならない）"""
    b = getattr(slicer, "_hvPanelBtn", None)
    if b is None: return
    try:
        vp = slicer.app.layoutManager().viewport(); b.move(0, max(0, int(vp.height / 2) - 28)); b.raise_()
    except Exception: slicer._hvPanelBtn = None


def _panelToggle(mw, dock):
    """左のパネルを隠す / 出すボタン（画面の左上）と Ctrl+B。幅は覚えておく"""
    for k in ("_hvPanelBtn", "_hvPanelSc"):
        o = getattr(slicer, k, None)
        if o is not None:
            try: o.setParent(None); o.deleteLater()
            except Exception: pass
    lm = slicer.app.layoutManager(); vp = lm.viewport()
    b = qt.QToolButton(vp); b.setText("◀"); b.setToolTip("左のパネルを隠す / 出す（Ctrl+B）。パネルの幅は境目をドラッグで変えられます")
    b.setCursor(qt.QCursor(qt.Qt.PointingHandCursor))
    b.setStyleSheet("QToolButton{background:rgba(20,22,26,200); color:#e6e8ec; border:1px solid #3a404c; border-left:none; border-top-right-radius:6px; border-bottom-right-radius:6px; padding:0; font-size:12px}"
                    "QToolButton:hover{background:rgba(47,123,246,220)}")
    b.setFixedSize(18, 56); b.show()
    place = _placePanelButton
    slicer._hvPanelBtn = b; place()
    if getattr(slicer, "_hvPanelTimer", None) is None:                 # タイマーとつなぎは 1 回だけ（古いボタンを触らない）
        t = slicer._hvPanelTimer = qt.QTimer(); t.setInterval(800); t.connect("timeout()", _placePanelButton); t.start()
        try: lm.connect("layoutChanged(int)", lambda i: qt.QTimer.singleShot(0, _placePanelButton))
        except Exception: pass
    def tog():
        on = not dock.isVisible()
        if not on: qt.QSettings().setValue("HUCViewS/panelWidth", dock.width)
        dock.setVisible(on); b.setText("◀" if on else "▶")
        if on: mw.resizeDocks([dock], [int(qt.QSettings().value("HUCViewS/panelWidth", 420) or 420)], qt.Qt.Horizontal)
        qt.QTimer.singleShot(0, _placePanelButton)
    b.connect("clicked()", tog)
    sc = qt.QShortcut(qt.QKeySequence("Ctrl+B"), mw); sc.setContext(qt.Qt.ApplicationShortcut); sc.connect("activated()", tog)
    slicer._hvPanelSc = sc


def exitAppMode():
    for f in ("setMenuBarsVisible", "setToolbarsVisible", "setApplicationLogoVisible", "setModuleHelpSectionVisible",
              "setModulePanelTitleVisible", "setDataProbeVisible"):
        try: getattr(slicer.util, f)(True)
        except Exception: pass
    try: slicer.app.layoutManager().threeDWidget(0).threeDController().setVisible(True)
    except Exception: pass
    slicer.util.mainWindow().setWindowTitle("3D Slicer")


def selfTest(folder, logPath=None):
    """動作確認: フォルダを取り込み → ★のシリーズで 3D 作成 → 結果をログに"""
    import traceback
    def log(m):
        print("[selftest]", m)
        if logPath:
            with open(logPath, "a", encoding="utf-8") as f: f.write(time.strftime("%H:%M:%S ") + str(m) + "\n")
    try:
        import TotalSegmentator, os as _os
        log(f"TOTALSEG_HOME_DIR={_os.environ.get('TOTALSEG_HOME_DIR')}")
        w = slicer.modules.heartview.widgetRepresentation().self()
        t0 = time.time(); w._import(folder)
        log(f"import {time.time()-t0:.0f}s: " + w.infoLabel.text)
        for r in w.rows: log(("★ " if r.get("best") else "  ") + f"{r['desc']} n={r['n']} thick={r['thick']} {r['orient']} contrast={r['contrast']} usable={r['usable']}")
        t0 = time.time(); w.onBuild()
        log(f"build {time.time()-t0:.0f}s: " + w.status.text.replace("\n", " | "))
        p = w.logic.savePNG(); log("png " + p)
    except Exception:
        log(traceback.format_exc())
    log("SELFTEST END")


STAGES = [  # (キー, 表示名, 初期の見込み秒, ステータス文に含まれる目印)
    ("load",  "シリーズの読み込み",   20,  None),
    ("total", "臓器の自動認識（AI）", 40,  "1/4"),     # 2026-10-29 AI に渡す CT を先に小さくして短縮（実績は PC ごとに学習）
    ("hc",    "心腔の自動認識（AI）", 120, "2/4"),
    ("calib", "造影の測定・閾値調整", 5,   "3/4"),
    ("build", "3D の作成・VR の準備", 40,  "4/4"),
    ("save",  "症例の保存",           10,  "保存"),
]


class Progress:
    """段階と経過時間から全体の進み具合と残り時間を出す。所要時間はこの PC の実績で学習。"""
    def __init__(self, bar, label):
        self.bar, self.label = bar, label
        st = qt.QSettings()
        self.exp = {}
        for k, name, sec, mark in STAGES:
            try: self.exp[k] = float(st.value(f"HeartView/dur/{k}", sec))
            except Exception: self.exp[k] = float(sec)
        self.done = {}; self.cur = None; self.t0 = None; self.tStart = time.time()
        self.timer = qt.QTimer(); self.timer.setInterval(1000); self.timer.connect("timeout()", self.update)
        self.bar.setRange(0, 1000); self.bar.setValue(0); self.bar.show(); self.label.show()
        self.timer.start()

    def enter(self, key):
        if key == self.cur: return
        now = time.time()
        if self.cur is not None: self.done[self.cur] = now - self.t0
        keys = [k for k, *_ in STAGES]
        if self.cur is not None and key in keys:          # 飛ばした段階（認識済みなど）は 0 秒で完了扱い
            for k in keys[keys.index(self.cur) + 1: keys.index(key)]: self.done.setdefault(k, 0.0)
        self.cur, self.t0 = key, now
        self.update()

    def message(self, m):
        for k, name, sec, mark in STAGES:
            if mark and mark in str(m): self.enter(k); return

    def update(self):
        if self.cur is None: return
        el = time.time() - self.t0
        keys = [k for k, *_ in STAGES]
        remain_keys = keys[keys.index(self.cur) + 1:]
        total = sum(self.done.get(k, self.exp[k]) for k in keys)
        doneSum = sum(self.done.values())
        curExp = max(self.exp[self.cur], el / 0.95)
        frac = (doneSum + min(el, 0.95 * curExp)) / max(total - self.exp[self.cur] + curExp, 1)
        self.bar.setValue(int(1000 * min(frac, 0.99)))
        rem = max(curExp - el, 0) + sum(self.exp[k] for k in remain_keys if k not in self.done)
        name = dict((k, n) for k, n, *_ in STAGES)[self.cur]
        i = keys.index(self.cur) + 1
        self.label.setText(f"{i}/{len(keys)}　{name}　（{_mmss(el)} 経過）　全体の残り 約 {_mmss(rem)}")
        slicer.app.processEvents()

    def finish(self, ok=True):
        self.timer.stop()
        if self.cur is not None: self.done[self.cur] = time.time() - self.t0
        if ok:
            st = qt.QSettings()
            for k, v in self.done.items():
                if v > 1: st.setValue(f"HeartView/dur/{k}", round(0.5 * self.exp[k] + 0.5 * v, 1))   # 実績で見込みを更新
            self.bar.setValue(1000)
            self.label.setText(f"完了（合計 {_mmss(time.time() - self.tStart)}）")
        else:
            self.label.setText("中断しました")


def _mmss(sec):
    sec = int(round(sec)); return f"{sec // 60}:{sec % 60:02d}"


# ============================================================================ module
class HeartView(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        parent.title = APP_TITLE
        parent.categories = ["HUCVS"]
        parent.dependencies = []
        parent.contributors = ["HUCVS"]
        parent.helpText = "CD-R から取り込んで心臓の 3D を作る入口画面（研究・教育用）。"
        parent.acknowledgementText = ""


HV_STYLE_EXTRA = """
QWidget#cvRoot QTableWidget { background:#181b21; alternate-background-color:#1c2027; color:#e6e8ec; border:1px solid #2b3039; border-radius:8px;
  selection-background-color:#1f4d69; selection-color:#ffffff; font-size:12px; }
QWidget#cvRoot QHeaderView::section { background:#181b21; color:#7d8590; border:none; border-bottom:1px solid #2b3039; padding:4px 6px; font-size:11px; }
QWidget#cvRoot QProgressBar { background:#262a33; border:1px solid #343a46; border-radius:6px; text-align:center; color:#e6e8ec; min-height:18px; }
QWidget#cvRoot QProgressBar::chunk { background:#2f7bf6; border-radius:5px; }
"""


class HeartViewWidget(ScriptedLoadableModuleWidget):
    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        self.logic = HeartViewLogic()
        try:
            import CardiacView; css = CardiacView.CV_STYLE + CardiacView._iconCSS()
        except Exception: css = ""
        css += HV_STYLE_EXTRA
        root = qt.QWidget(); root.setObjectName("cvRoot"); root.setStyleSheet(css); root.setAttribute(qt.Qt.WA_StyledBackground, True)
        _sc = qt.QScrollArea(); _sc.setWidgetResizable(True); _sc.setFrameShape(qt.QFrame.NoFrame); _sc.setWidget(root)
        _sc.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff); _sc.setStyleSheet(getattr(CardiacView, "SC_STYLE", "QScrollArea{background:#15171c; border:none}") if "CardiacView" in dir() else "QScrollArea{background:#15171c; border:none}")
        self.layout.addWidget(_sc); self.layout.setContentsMargins(0, 0, 0, 0)
        v = qt.QVBoxLayout(root); v.setContentsMargins(10, 10, 10, 10); v.setSpacing(10); self.root = root

        def card(title=None, sub=None):
            f = qt.QFrame(); f.setProperty("role", "card"); lay = qt.QVBoxLayout(f); lay.setContentsMargins(10, 8, 10, 10); lay.setSpacing(6)
            if title:
                h = qt.QHBoxLayout(); t = qt.QLabel(title); t.setProperty("role", "h"); h.addWidget(t); h.addStretch(1)
                if sub: s = qt.QLabel(sub); s.setProperty("role", "muted"); h.addWidget(s)
                lay.addLayout(h)
            v.addWidget(f); return lay
        def btn(text, kind=None, tip=None):
            b = qt.QPushButton(text)
            if kind: b.setProperty("kind", kind)
            if tip: b.setToolTip(tip)
            b.setCursor(qt.QCursor(qt.Qt.PointingHandCursor)); return b
        def lab(text, role=None):
            l = qt.QLabel(text)
            if role: l.setProperty("role", role)
            l.setWordWrap(True); return l

        # ---------------- ヘッダー
        h = qt.QHBoxLayout(); v.addLayout(h)
        h.addWidget(lab(APP_TITLE, "title")); h.addWidget(lab(APP_SUBTITLE, "muted")); h.addStretch(1)
        ver = appVersion()
        if ver:                                                              # どの版が入っているかを画面で確かめられるように（更新が届いたかどうかの確認用）
            self.versionLabel = lab(f"版 {ver}", "muted"); self.versionLabel.setWordWrap(False)
            self.versionLabel.setToolTip("この PC に入っている版（年月日-時分）。起動の時に、新しい版があれば自動で入れ替わります"); h.addWidget(self.versionLabel)
        v.addWidget(lab("研究・教育用。診断・治療方針は必ず元画像で確認してください。", "muted"))

        # ---------------- 1
        g = card("1  画像を読み込む")
        self.cdButton = btn("CD-R から読み込む", "primary", "CD-R（または USB）の DICOM を PC に取り込む"); g.addWidget(self.cdButton)
        row = qt.QHBoxLayout(); row.setSpacing(6); g.addLayout(row)
        self.folderButton = btn("フォルダから", None, "DICOM のフォルダ（CD の中身など）を選ぶ"); row.addWidget(self.folderButton, 1)
        self.caseButton = btn("保存した症例", None, "保存した症例（.mrb）を開く"); row.addWidget(self.caseButton, 1)
        self.infoLabel = lab("", "muted"); g.addWidget(self.infoLabel); self.infoLabel.hide()
        self.table = qt.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["", "シリーズ", "4D", "枚", "厚さ", "造影", "断面"])
        self.table.setSelectionBehavior(qt.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(qt.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False); self.table.setShowGrid(False); self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False); self.table.setTextElideMode(qt.Qt.ElideRight)
        self.table.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        hh = self.table.horizontalHeader(); hh.setStretchLastSection(False)
        try:
            for c in range(7): hh.setSectionResizeMode(c, qt.QHeaderView.Stretch if c == 1 else qt.QHeaderView.ResizeToContents)
        except Exception: pass
        self.table.setMinimumHeight(190)
        g.addWidget(self.table)
        g.addWidget(lab("★ = おすすめ（造影・軸位・薄いスライス・心臓用を優先）。行を選ぶと右に画像が出ます。", "muted"))

        # ---------------- 2
        g = card("2  3D を作る")
        self.buildButton = btn("3D を作る", "primary", "初回 約5〜10分（2回目から速くなります）"); self.buildButton.enabled = False
        g.addWidget(self.buildButton)
        self.progressBar = qt.QProgressBar(); self.progressBar.setTextVisible(True); self.progressBar.setFormat("%p%"); self.progressBar.hide(); g.addWidget(self.progressBar)
        self.progressLabel = lab("", "h"); self.progressLabel.hide(); g.addWidget(self.progressLabel)
        self.status = lab("CD を入れて「CD-R から読み込む」を押してください。", "muted"); g.addWidget(self.status)

        # ---------------- 3
        g = card("3  見る・保存する")
        row = qt.QHBoxLayout(); row.setSpacing(6); g.addLayout(row)
        self.viewButton = btn("見る・切る  ›", "primary", "操作パネル（CardiacView）へ"); row.addWidget(self.viewButton, 1)
        self.aortaButton = btn("大動脈サイジング  ›", "primary", "ステントグラフトのサイジング（中心線 → 径の表 → CSV）"); row.addWidget(self.aortaButton, 1)
        row = qt.QHBoxLayout(); row.setSpacing(6); g.addLayout(row)
        self.saveCaseButton = btn("症例を保存", None, "計測・パッチなど、今の状態を症例のファイルに上書き保存します\n（3D を作った時に 1 回、自動で保存されます。その後に足したものは、これで保存します）"); row.addWidget(self.saveCaseButton, 1)
        self.pngButton = btn("画像で保存", None, "今の画面を PNG で保存"); row.addWidget(self.pngButton, 1)
        self.openDirButton = btn("保存フォルダ", None, "保存した症例・画像のフォルダを開く"); row.addWidget(self.openDirButton, 1)
        self.cloudLabel = lab("", "muted"); g.addWidget(self.cloudLabel); self.cloudLabel.hide(); self._updateCloudNote()

        row = qt.QHBoxLayout(); row.setSpacing(2); v.addLayout(row)
        self.slicerButton = btn("Slicer の通常画面", "ghost", "Slicer の通常画面に切り替え（上級者用）"); row.addWidget(self.slicerButton)
        row.addStretch(1)
        self.licButton = btn("", "ghost")
        self.licButton.setToolTip("左右の心腔の色分け・心筋の断面に使う AI（TotalSegmentator の heartchambers_highres）の学術ライセンス番号を登録します（無料・各自で申請）")
        row.addWidget(self.licButton); self._updateLicLabel()
        v.addStretch(1)

        self.cdButton.connect("clicked()", self.onCD)
        self.folderButton.connect("clicked()", self.onFolder)
        self.caseButton.connect("clicked()", self.onOpenCase)
        self.buildButton.connect("clicked()", self.onBuild)
        self.viewButton.connect("clicked()", lambda: slicer.util.selectModule("CardiacView"))
        self.pngButton.connect("clicked()", self.onPNG)
        self.saveCaseButton.connect("clicked()", lambda: self.onSaveCase())
        self.aortaButton.connect("clicked()", lambda: slicer.util.selectModule("AortaSizing"))
        self.openDirButton.connect("clicked()", lambda: qt.QDesktopServices.openUrl(qt.QUrl.fromLocalFile(casesDir())))
        self.slicerButton.connect("clicked()", self.onSlicerMode)
        self.licButton.connect("clicked()", self.onLicense)
        self.table.connect("itemSelectionChanged()", self._onSel)

    # ------------------------------------------------------------------ helpers
    def _say(self, msg):
        self.status.setText(msg)
        try:
            import CardiacView; CardiacView.paintStatus(self.status, msg)     # 失敗・注意は色を変える
        except Exception: pass
        print("[HeartView]", msg); slicer.app.processEvents()

    def _busy(self, on):
        if on: qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        else: qt.QApplication.restoreOverrideCursor()
        self._working = bool(on)
        for b in (self.cdButton, self.folderButton, self.caseButton, self.saveCaseButton, self.buildButton):
            b.enabled = not on if b is not self.buildButton else (not on and bool(self.table.selectedItems()))
        for w in (self.table, self.viewButton, self.aortaButton):             # 作業の途中に、表の別の行（プレビューが画面とシーンを替える）や別の画面を押せないように
            w.enabled = not on

    # ------------------------------------------------------------------ ①
    def onCD(self):
        srcs = self.logic.findDicomMedia()
        if not srcs:
            slicer.util.infoDisplay("CD-R（または USB）に DICOM が見つかりませんでした。\nCD を入れて数秒待ってからもう一度押すか、「フォルダから…」を使ってください。", windowTitle=APP_TITLE)
            return
        self._import(srcs[0])

    def onFolder(self):
        d = qt.QFileDialog.getExistingDirectory(None, "DICOM のフォルダ（CD の中身など）を選ぶ")
        if d: self._import(d)

    def _import(self, folder):
        self._busy(True)
        try:
            self._say(f"読み込み中…（{folder}）　CD からは 1〜3 分かかります")
            self.progressBar.setRange(0, 0); self.progressBar.show(); self.progressLabel.setText("CD から PC へ取り込み中…"); self.progressLabel.show(); slicer.app.processEvents()
            rows, info = self.logic.importFolder(folder)
            self.infoLabel.setText(info); self.infoLabel.setVisible(bool(info))
            try:
                import CardiacView; CardiacView.paintStatus(self.infoLabel, info)  # 患者・検査日が混ざっている時（⚠）は色を変える
            except Exception: pass
            self._fill(rows)
            self.progressBar.setRange(0, 1000); self.progressBar.hide(); self.progressLabel.hide()
            self._say("シリーズを選んで「3D を作る」を押してください（★ がおすすめ）。" if rows else "CT のシリーズが見つかりませんでした。")
            if rows and any(r.get("phases") for r in rows): self._onSel()          # 4D の時はその説明を出す
        except Exception as e:
            import traceback; traceback.print_exc(); self._say(f"読み込みエラー: {e}")
        finally:
            self._busy(False)

    def _fill(self, rows):
        self.rows = rows
        self.table.setRowCount(len(rows))
        for r, s in enumerate(rows):
            d4 = f"{len(s['phases'])}相" if s.get("phases") else ""
            tip = s["desc"] + (f"\n4D: {len(s['phases'])} 位相（このシリーズは {s['phaseLab']}）" if s.get("phases") else "")
            vals = ["★" if s.get("best") else "", s["desc"], d4, str(s["n"]), f"{s['thick']:.1f}" if s["thick"] else "?",
                    "あり" if s["contrast"] else "", s["orient"]]
            for c, val in enumerate(vals):
                it = qt.QTableWidgetItem(val); it.setToolTip(tip)
                if c == 2 and d4: it.setForeground(qt.QBrush(qt.QColor(76, 200, 240)))
                if not s["usable"]: it.setForeground(qt.QBrush(qt.QColor(110, 116, 126)))
                self.table.setItem(r, c, it)
        best = [i for i, s in enumerate(rows) if s.get("best")]
        if best: self.table.selectRow(best[0])

    def _onSel(self):
        sel = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        self.buildButton.enabled = bool(sel) and not getattr(self, "_working", False)
        s = self.rows[sel[0].row()] if sel and sel[0].row() < len(getattr(self, "rows", [])) else None
        ph = (s or {}).get("phases") or []
        if len(ph) >= 2:
            self.buildButton.setText(f"3D ＋ 4D（{len(ph)} 位相）を作る"); self.buildButton.setToolTip("約 6〜10 分")
            self._say(f"4D（心電図同期 {len(ph)} 位相）のシリーズです。% は R 波から次の R 波までの中のタイミング。"
                      "3D は選んだ位相から、4D は全位相から作ります。75% 付近（拡張中期）は動きが少なく 3D 向き、35〜40% は収縮期。"
                      "右の画像でぶれの少ない位相を選んでください。")
        else:
            self.buildButton.setText("3D を作る"); self.buildButton.setToolTip("初回 約5〜10分（2回目から速くなります）")
        if s is not None:
            try: self.logic.preview(s)
            except Exception as e: print("preview:", e)

    # ------------------------------------------------------------------ ②
    def onBuild(self):
        sel = self.table.selectionModel().selectedRows()
        if not sel: return
        s = self.rows[sel[0].row()]
        if getattr(self, "_working", False): return                           # 作っている途中の二重押し
        if not self._confirmLeave(): return                                   # 今の症例の保存していない変更（計測・パッチなど）を、確かめずに消さない
        self._busy(True)
        prog = Progress(self.progressBar, self.progressLabel); ok = False; cv = None
        try:
            prog.enter("load")
            self._say("シリーズを読み込み中…")
            vol = self.logic.loadSeries(s)
            cv = slicer.modules.cardiacview.widgetRepresentation().self()
            self.logic.resetCardiacView(cv)
            cv.volumeSelector.setCurrentNode(vol)
            last = [""]                                                       # CardiacView が最後に出した文（失敗は「エラー: …」で知らせてくる）
            cv._status = lambda m: (last.__setitem__(0, str(m)), prog.message(m), self._say(m), type(cv)._status(cv, m))
            built = cv.onQuick()
            # onQuick は中の失敗を外へ出さない（「エラー: …」と出して False を返す）。ここで止めないと、作りかけを保存して「完了」と出してしまう
            if built is False or last[0].startswith("エラー") or not cv.logic.layerModels:
                raise RuntimeError((last[0].split(":", 1)[-1].strip() if last[0].startswith("エラー") else "") or "3D を作れませんでした")
            self._say(cv.statusLabel.text)
            ph = s.get("phases") or []
            if len(ph) >= 2:                                                  # 4D: ほかの位相も読み込んで、動く心臓を準備
                try:
                    vols = [(lab, vol if uid == s["uid"] else self.logic.phaseLoader(uid, vol)) for lab, uid, _ in ph]   # 1 位相ずつ読み込み→切り出し→消す
                    cv.logic.setup4D(vols, status=lambda m: (prog.message(m), self._say(m)))
                except Exception as e:
                    import traceback; traceback.print_exc(); self._say(f"4D の準備に失敗しました（3D はそのまま使えます）: {e}")
            prog.enter("save")
            try:
                path = self.logic.saveCase(s); saved = f"\n症例を保存しました（{os.path.basename(path)}）。"
            except Exception as e:                                            # 3D はできている。保存の失敗だけを知らせて、そのまま見られるようにする
                import traceback; traceback.print_exc(); saved = f"\n⚠ 症例を保存できませんでした: {e}"
                slicer.util.warningDisplay(f"3D はできましたが、症例を保存できませんでした。\n{e}", windowTitle=APP_TITLE)
            ok = True
            n4 = cv.logic.n4D() if hasattr(cv.logic, "n4D") else 0
            self._say(cv.statusLabel.text + saved
                      + (f"\n4D（{n4} 位相）も準備できました。操作パネルの「4D」の ▶ 再生で動きます。" if n4 >= 2 else ""))
            slicer.util.selectModule("CardiacView")
        except Exception as e:
            import traceback; traceback.print_exc(); self._say(f"エラー: {e}")
            slicer.util.errorDisplay(f"3D の作成に失敗しました。\n{e}", windowTitle=APP_TITLE)
        finally:
            prog.finish(ok)
            self._busy(False)
            try:
                if cv is not None: cv.__dict__.pop("_status", None)           # CardiacView の文の出し方を元に戻す（この後の文を、入口の進み具合へ流し続けない）
            except Exception: pass

    # ------------------------------------------------------------------ 保存していない変更
    def _askLeave(self, exiting=False):
        """保存していない変更がある時にたずねる（exiting = アプリを終わる時）。戻り値: "save" / "discard" / "cancel" """
        go = "終了" if exiting else "続ける"
        mb = qt.QMessageBox(slicer.util.mainWindow()); mb.setWindowTitle(APP_TITLE); mb.setIcon(qt.QMessageBox.Question)
        mb.setText("今の症例に、保存していない変更（計測・パッチなど）があります。")
        bs = mb.addButton(f"保存して{go}", qt.QMessageBox.AcceptRole); mb.addButton(f"保存しないで{go}", qt.QMessageBox.DestructiveRole)
        bc = mb.addButton("やめる", qt.QMessageBox.RejectRole)
        mb.setDefaultButton(bs); mb.setEscapeButton(bc)
        mb.exec_() if hasattr(mb, "exec_") else mb.exec()
        c = mb.clickedButton(); t = str(c.text) if c is not None else ""
        return {f"保存して{go}": "save", f"保存しないで{go}": "discard"}.get(t, "cancel")

    def _confirmLeave(self):
        """今の症例を閉じる（別の 3D を作る・別の症例を開く）前に、保存していない変更があれば確かめる。True = 続けてよい / False = やめる。
        3D を作った後に足したもの（計測・パッチなど）は自動では保存されないので、黙って消さない（アプリを終わる時は _ExitGuard が同じことをたずねる）"""
        try:
            if not self.logic.hasUnsaved(): return True
            r = self._askLeave()
        except Exception as e:
            print("[HeartView] 確認できませんでした（前と同じように続けます）:", e); return True
        if r == "discard": return True
        if r != "save": return False
        return self.onSaveCase()

    def onSaveCase(self, say=None):
        """今の症例を、症例のファイルに上書き保存する。戻り値: 保存できたか"""
        say = say or self._say
        if getattr(self, "_working", False): return False
        if not self.logic.caseOpen():
            say("保存する症例がありません（先に 3D を作るか、保存した症例を開いてください）。"); return False
        self._busy(True)
        try:
            say("症例を保存しています…"); p = self.logic.saveCurrent(); say(f"症例を保存しました（{os.path.basename(p)}）。"); return True
        except Exception as e:
            import traceback; traceback.print_exc(); say(f"エラー: {e}")
            slicer.util.errorDisplay(f"症例を保存できませんでした。\n{e}", windowTitle=APP_TITLE); return False
        finally:
            self._busy(False)

    # ------------------------------------------------------------------ 保存した症例
    def onOpenCase(self):
        if getattr(self, "_working", False): return
        path = qt.QFileDialog.getOpenFileName(None, "保存した症例を開く", casesDir(), "症例 (*.mrb)")
        if not path: return
        if not self._confirmLeave(): return
        self._busy(True)
        try:
            self._say("症例を開いています…")
            self.logic.openCase(path)
            self._say(f"開きました: {os.path.basename(path)}")
            slicer.util.selectModule("CardiacView")
        except Exception as e:
            import traceback; traceback.print_exc(); self._say(f"エラー: {e}")
            slicer.util.errorDisplay(f"症例を開けませんでした。\n{e}", windowTitle=APP_TITLE)
        finally:
            self._busy(False)

    # ------------------------------------------------------------------ ③
    def onPNG(self):
        try:
            p = self.logic.savePNG()
            if not os.path.exists(p): raise RuntimeError("ファイルができませんでした")
            self._say(f"画像を保存しました: {p}")
        except Exception as e:
            import traceback; traceback.print_exc(); self._say(f"エラー: 画像を保存できませんでした（{e}）")

    def _updateCloudNote(self):
        """症例の保存先がクラウドと同期するフォルダの中なら、入口に知らせを出す（知らないうちに患者の画像が院外へ送られないように）"""
        try:
            name = cloudSyncName(casesPath())
            if name:
                msg = f"⚠ 症例の保存先が {name} と同期するフォルダの中です。保存した症例（患者の CT）がクラウドにも送られます。場所は「保存フォルダ」で確かめられます。"
                self.cloudLabel.setText(msg); self.cloudLabel.show()
                import CardiacView; CardiacView.paintStatus(self.cloudLabel, msg)
            else: self.cloudLabel.hide()
            return name
        except Exception as e:
            print("[HeartView] 保存先の確認:", e); return ""

    def _updateLicLabel(self):
        ok = bool(tsLicense())
        self.licButton.setText("AI ライセンス ✓" if ok else "AI ライセンスを登録（無料）")

    def onLicense(self):
        msg = ("左右の心腔の色分けと心筋の断面には、TotalSegmentator の心腔モデル（heartchambers_highres）を使います。\n"
               "このモデルは学術用の無料ライセンスが必要です（各自で申請。番号はこの PC にだけ保存され、外に送りません）。\n\n"
               "申請: https://backend.totalsegmentator.com/license-academic/\n\n"
               "届いたライセンス番号（例: aca_XXXXXXXXXX）を入力してください。")
        txt = qt.QInputDialog.getText(slicer.util.mainWindow(), "AI ライセンスの登録", msg, qt.QLineEdit.Normal, tsLicense() or "")
        if not txt or not str(txt).strip(): return
        try:
            setTsLicense(str(txt).strip()); self._say("ライセンスを登録しました。次に「3D を作る」とき心腔モデルが使われます。")
        except Exception as e:
            slicer.util.errorDisplay(f"登録できませんでした: {e}", windowTitle=APP_TITLE)
        self._updateLicLabel()

    def onSlicerMode(self):
        exitAppMode()
        self._say("通常画面にしました。戻すには Slicer を開き直してください。")


def _tsConfigPath():
    """TotalSegmentator の設定ファイル（持ち運び版は HeartView\\totalseg、通常は ~/.totalsegmentator）"""
    home = os.environ.get("TOTALSEG_HOME_DIR") or os.path.join(os.path.expanduser("~"), ".totalsegmentator")
    return os.path.join(home, "config.json")


def tsLicense():
    import json
    try: return (json.load(open(_tsConfigPath(), encoding="utf-8")).get("license_number") or "").strip()
    except Exception: return ""


def setTsLicense(lic):
    import json
    p = _tsConfigPath(); os.makedirs(os.path.dirname(p), exist_ok=True)
    try: cfg = json.load(open(p, encoding="utf-8"))
    except Exception: cfg = {}
    cfg["license_number"] = lic; cfg["send_usage_stats"] = False; cfg["statistics_disclaimer_shown"] = True
    with open(p, "w", encoding="utf-8") as f: json.dump(cfg, f, indent=2)


_TMPDB_RE = re.compile(r"^\d{8}_\d{6}_TempDICOMDatabase(_del)?$")       # Slicer の openTemporaryDatabase() が付ける名前（＋消しかけの印）
TMPDB_PID = "hucviews_pid.txt"


def _isTmpDicomDir(p, tmpRoot=None):
    """p が、Slicer の一時フォルダの直下にある「取り込み用の一時的な DICOM のデータベース」か（場所と名前の形の両方で見分ける）"""
    if not p: return False
    try:
        root = os.path.normcase(os.path.abspath(tmpRoot or slicer.app.temporaryPath)); q = os.path.normcase(os.path.abspath(str(p)))
        return os.path.dirname(q) == root and bool(_TMPDB_RE.match(os.path.basename(str(p).replace("\\", "/").rstrip("/"))))
    except Exception: return False


def _rmtree(d):
    """フォルダごと消す。書き込み禁止の印の付いたファイル（CD から写したファイルは Windows でそうなる）は、印を外してから消す"""
    import shutil, stat
    def unlock(func, path, exc):
        try: os.chmod(path, stat.S_IWRITE); func(path)
        except Exception: pass
    try: shutil.rmtree(d, onexc=unlock)                                      # Python 3.12 から
    except TypeError: shutil.rmtree(d, onerror=unlock)
    except Exception: pass


def _removeTmpDicomDir(d, tmpRoot=None):
    """一時的な DICOM のデータベース（CD から写した画像と索引。患者の名前が入っている）を消す。戻り値: 消せたか。
    先にフォルダの名前を変える: 中のファイルをどこかが開いていると Windows ではここで失敗する（＝使っているので消さない）"""
    if not _isTmpDicomDir(d, tmpRoot) or not os.path.isdir(d): return False
    dead = d if d.endswith("_del") else d + "_del"
    if dead != d:
        try:
            if os.path.isdir(dead): _rmtree(dead)
            os.rename(d, dead)
        except OSError: return False
    _rmtree(dead)
    return not os.path.exists(dead)


def purgeTmpDicom(keep=None, tmpRoot=None, minAge=24 * 3600):
    """前の回までに残った一時的な DICOM のデータベースを片付ける（前の版は、閉じても消していなかった。途中で落ちた時も残る）。
    keep = 今使っているフォルダ。ほかの HUCViewS・Slicer が使っているものは消さない。戻り値: (消した数, 消した MB, 残した数)"""
    import sys
    root = tmpRoot or slicer.app.temporaryPath; n = left = 0; mb = 0.0
    try: names = [e for e in os.listdir(root) if _TMPDB_RE.match(e) and os.path.isdir(os.path.join(root, e))]
    except Exception: return 0, 0.0, 0
    for e in names:
        d = os.path.join(root, e)
        try:
            if keep and os.path.normcase(os.path.abspath(d)) == os.path.normcase(os.path.abspath(keep)): continue
            if sys.platform != "win32" and not e.endswith("_del"):
                # Windows 以外では、使っている途中のフォルダも名前を変えられてしまう → 持ち主（別の HUCViewS）が動いていないか、十分古いかを確かめる
                pf = os.path.join(d, TMPDB_PID)
                if os.path.exists(pf):
                    try:
                        pid = int((open(pf).read().strip() or "0"))
                        if pid and pid != os.getpid(): os.kill(pid, 0); left += 1; continue    # 動いている
                    except ProcessLookupError: pass
                    except Exception: left += 1; continue
                elif time.time() - os.path.getmtime(d) < minAge: left += 1; continue
            size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(d) for f in fs)
            if _removeTmpDicomDir(d, root): n += 1; mb += size / 1e6
            else: left += 1
        except Exception as ex:
            print("[HeartView] 一時的な DICOM の片付け:", ex); left += 1
    return n, round(mb, 1), left


def fixDicomSetting():
    """Slicer の「DICOM の置き場所」の設定が、取り込み用の一時フォルダを指したままなら直す。
    前の版は、取り込みの時に設定を一時フォルダに替えて、閉じる時に戻していなかった（同じ PC でふつうの Slicer を使うと、DICOM の一覧が空になる）。
    元の場所は分からないので、設定を消して Slicer の既定の場所に戻す。戻り値: 直したか"""
    key = slicer.dicomDatabaseDirectorySettingsKey; st = qt.QSettings(); cur = st.value(key)
    if not _isTmpDicomDir(cur): return False
    try:
        db = slicer.dicomDatabase
        if db is not None and db.isOpen and _isTmpDicomDir(os.path.dirname(db.databaseFilename)): db.closeDatabase()   # 起動の時に Slicer が開いた古い一時フォルダを放す（放さないと消せない）
    except Exception as e: print("[HeartView] DICOM の置き場所:", e)
    st.remove(key); print("[HeartView] DICOM の置き場所の設定が一時フォルダを指していたので、既定に戻しました")
    return True


def cleanupTmpDicom():
    """アプリを終わる時: 今回の取り込みの一時フォルダを閉じて消し、前の回の残りも片付ける。何度呼んでもよい"""
    try:
        w = slicer.modules.heartview.widgetRepresentation().self()
        w.logic._closeTmp()
        r = purgeTmpDicom()
        if r[0] or r[2]: print(f"[HeartView] 一時的な DICOM の片付け: {r[0]} 個（{r[1]} MB）を消しました" + (f"／{r[2]} 個は使用中のため残しました" if r[2] else ""))
        return r
    except Exception as e:
        print("[HeartView] 一時的な DICOM の片付け:", e); return None


def _isRemovable(folder):
    """CD / DVD / USB メモリなら True。Windows はドライブ種別、Mac は /Volumes の下、Linux は /media・/run/media の下"""
    import sys
    p = os.path.abspath(folder)
    if sys.platform == "win32":
        try:
            import ctypes
            drive = os.path.splitdrive(p)[0] + "\\"
            return ctypes.windll.kernel32.GetDriveTypeW(drive) in (2, 5)      # 2 = リムーバブル, 5 = CD-ROM
        except Exception:
            return True
    if sys.platform == "darwin":
        if not p.startswith("/Volumes/"): return False
        vol = "/".join(p.split("/")[:3])                                   # /Volumes/<名前>
        return os.path.realpath(vol) != "/"                                # 起動ディスク（/ への別名）は除く
    return p.startswith("/media/") or p.startswith("/run/media/") or p.startswith("/mnt/")


# ============================================================================ logic
class HeartViewLogic(ScriptedLoadableModuleLogic):
    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        self._tmp = None
        self._tmpDir = None         # 取り込み用の一時的な DICOM のデータベースのフォルダ
        self.caseInfo = {}
        self.casePath = None        # 今の症例のファイル（開いたファイル・作った時に保存したファイル）
        self.savedSig = None        # そのファイルに保存した時点の workSignature()

    # ---- CD / USB を探す
    def findDicomMedia(self):
        import sys
        out = []
        if sys.platform == "win32":
            try:
                import ctypes
                k = ctypes.windll.kernel32; mask = k.GetLogicalDrives()
                for i in range(26):
                    if not (mask >> i) & 1: continue
                    root = f"{chr(65 + i)}:\\"
                    t = k.GetDriveTypeW(root)          # 2=リムーバブル, 5=CD/DVD
                    if t not in (2, 5): continue
                    try:
                        if os.path.exists(os.path.join(root, "DICOMDIR")) or (t == 5 and os.listdir(root)):
                            out.append(root)
                    except Exception: pass
            except Exception as e:
                print("drive scan:", e)
        else:
            # Mac: /Volumes/<CD 名>（起動ディスクは除く）、Linux: /media/<user>/<CD 名> など
            bases = ["/Volumes"] if sys.platform == "darwin" else ["/media/" + os.environ.get("USER", ""), "/media", "/run/media/" + os.environ.get("USER", "")]
            for b in bases:
                try: names = os.listdir(b)
                except Exception: continue
                for n in names:
                    root = os.path.join(b, n)
                    try:
                        if not os.path.isdir(root) or os.path.realpath(root) == "/": continue
                        if os.path.exists(os.path.join(root, "DICOMDIR")): out.append(root)
                    except Exception: pass
        out.sort(key=lambda r: 0 if os.path.exists(os.path.join(r, "DICOMDIR")) else 1)
        return out

    # ---- 取り込み（一時データベース。PC 内のみ）
    def _closeTmp(self):
        """取り込み用の一時的な DICOM のデータベースを閉じて、フォルダごと消す（CD から写した画像と、患者の名前の入った索引）"""
        tmp, d = self._tmp, getattr(self, "_tmpDir", None); self._tmp = None; self._tmpDir = None
        if tmp is not None:
            try: tmp.__exit__(None, None, None)
            except Exception as e: print("tmpdb:", e)
        if d:
            try:
                if not _removeTmpDicomDir(d): print("[HeartView] 一時的な DICOM のフォルダを消せませんでした（次に終わる時にもう一度消します）")
            except Exception as e: print("tmpdb:", e)

    def importFolder(self, folder):
        from DICOMLib import DICOMUtils
        self._closeTmp()
        key = slicer.dicomDatabaseDirectorySettingsKey; st = qt.QSettings(); orig = st.value(key)
        if _isTmpDicomDir(orig): orig = None                                  # 前の版が残した一時フォルダを「元の場所」と思わない
        self._tmp = DICOMUtils.TemporaryDICOMDatabase()
        db = self._tmp.__enter__()
        try:
            self._tmp.originalDatabaseDir = orig                              # 閉じる時に戻す場所（無ければ戻さない）
            self._tmpDir = os.path.dirname(db.databaseFilename)
            if orig: st.setValue(key, orig)                                   # 設定は、すぐ元に戻す（一時フォルダを指したままアプリが終わると、次に Slicer を開いた時の DICOM の置き場所が替わってしまう）
            else: st.remove(key)
            with open(os.path.join(self._tmpDir, TMPDB_PID), "w") as f: f.write(str(os.getpid()))
        except Exception as e: print("tmpdb:", e)
        DICOMUtils.importDicom(folder, db, copyFiles=_isRemovable(folder))   # CD/USB だけ PC 内へコピー（PC 内のフォルダはそのまま読む）
        rows = []; pid = sdate = ""
        for p in db.patients():
            for st in db.studiesForPatient(p):
                for se in db.seriesForStudy(st):
                    files = db.filesForSeries(se)
                    if not files: continue
                    f = files[0]; val = lambda tag: (db.fileValue(f, tag) or "").strip()
                    mod = val("0008,0060"); itype = val("0008,0008").upper()
                    desc = _fixText(val("0008,103E")) or "(説明なし)"; num = val("0020,0011")   # 日本語の説明に混ざる制御文字（ESC）を直す（表が読めない・ファイル名に使えない）
                    try: thick = float(val("0018,0050") or 0)
                    except Exception: thick = 0.0
                    contrast = bool(val("0018,0010")) or desc.upper().startswith("CE")
                    kernel = val("0018,1210")
                    orient = "?"
                    try:
                        iop = [float(x) for x in val("0020,0037").split("\\")]
                        nrm = np.cross(iop[:3], iop[3:6]); ax = int(np.argmax(np.abs(nrm)))
                        orient = ["矢状断", "冠状断", "軸位"][ax]
                    except Exception: pass
                    usable = (mod == "CT" and len(files) >= 30 and "LOCALIZER" not in itype and "SECONDARY" not in itype)
                    score = -1e9
                    if usable:
                        score = (30 if orient == "軸位" else -50) + (20 if contrast else 0) - 10 * (thick or 5)
                        txt = (desc + " " + kernel).upper()
                        if any(k in txt for k in ("CTA", "CARDIAC", "HEART", "心")): score += 15
                        score += min(len(files), 400) / 40.0
                    rpid = val("0010,0020"); rdate = val("0008,0020")
                    pid = pid or rpid; sdate = sdate or rdate
                    # 4D（心電図同期の多位相）: 同じ撮影・同じ範囲で、位相だけ違うシリーズをまとめる
                    def fnum(tag):
                        try: return float(val(tag))
                        except Exception: return None
                    pct = fnum("0020,9241")
                    if pct is None:
                        import re
                        mm = re.search(r"(\d{1,3}(?:\.\d)?)\s*%", desc); pct = float(mm.group(1)) if mm else None
                    tpi = fnum("0020,9128"); tpi = tpi if tpi is not None else fnum("0020,0100"); trig = fnum("0018,1060")
                    phase = pct if pct is not None else (tpi if tpi is not None else trig)
                    plab = f"{pct:.0f}%" if pct is not None else (f"位相 {int(tpi)}" if tpi is not None else (f"{trig:.0f} ms" if trig is not None else ""))
                    gkey = (st, val("0020,0052"), len(files), round(thick, 2), val("0028,0010"), val("0028,0011"), val("0028,0030"), val("0018,1100"), kernel) if (usable and phase is not None) else None
                    rows.append(dict(uid=se, desc=f"{num}: {desc}" if num else desc, n=len(files), thick=thick, contrast=contrast,
                                     orient=orient, usable=usable, score=score, studyDate=rdate, pid=rpid, seriesNumber=num, rawDesc=desc,
                                     gkey=gkey, phase=phase, phaseLab=plab))
        groups = {}
        for r in rows:
            if r.get("gkey") is not None: groups.setdefault(r["gkey"], []).append(r)
        for g in groups.values():
            if len({r["phase"] for r in g}) < 2: continue
            ph = [(r["phaseLab"], r["uid"], r["phase"]) for r in sorted(g, key=lambda r: r["phase"])]
            pcts = [r for r in g if r["phaseLab"].endswith("%")]
            for r in g:
                r["phases"] = ph
                if pcts: r["score"] -= abs(r["phase"] - 75.0) / 100.0             # 3D は拡張中期（75% 付近）で作る
        rows.sort(key=lambda r: -r["score"])
        if rows and rows[0]["usable"]: rows[0]["best"] = True
        fd = lambda d: f"{d[:4]}/{d[4:6]}/{d[6:8]}" if len(d or "") == 8 else (d or "?")
        pids = sorted({r["pid"] for r in rows if r.get("pid")}); dates = sorted({r["studyDate"] for r in rows if r.get("studyDate")})
        if len(pids) > 1:                                                     # 患者が混ざったフォルダ: 前は最初の 1 人の ID だけを出していた（取り違えのもと）→ 行ごとに患者と検査日を出す
            for r in rows: r["desc"] += f"〔ID {r.get('pid') or '?'}・{fd(r.get('studyDate'))}〕"
            info = (f"⚠ 患者 {len(pids)} 人分の検査が入っています（ID: {'、'.join(pids[:3])}{' ほか' if len(pids) > 3 else ''}）。"
                    f"各行の〔 〕で患者を確かめてから選んでください。（{len(rows)} シリーズ）")
        elif len(dates) > 1:                                                  # 同じ患者の、別の日の検査が混ざっている（術前と術後など）
            for r in rows: r["desc"] += f"〔{fd(r.get('studyDate'))}〕"
            info = f"患者ID: {pid or '?'}　⚠ 検査日が {len(dates)} 日分あります（{fd(dates[0])}〜{fd(dates[-1])}）。各行の〔 〕で検査日を確かめてください。（{len(rows)} シリーズ）"
        else:
            info = f"患者ID: {pid or '?'}　検査日: {fd(sdate) if sdate else '?'}　（{len(rows)} シリーズ）"
        self.caseInfo = dict(pid=pid, studyDate=sdate)
        return rows, info

    def loadSeries(self, s):
        from DICOMLib import DICOMUtils
        slicer.mrmlScene.Clear(0)                                  # 前の症例を消してから（取り違え・メモリ不足防止）
        self.casePath = None; self.savedSig = None
        ids = DICOMUtils.loadSeriesByUID([s["uid"]])
        vols = [slicer.mrmlScene.GetNodeByID(i) for i in ids]
        vols = [v for v in vols if v is not None and v.IsA("vtkMRMLScalarVolumeNode")]
        if not vols: raise RuntimeError("この シリーズは CT 画像として読み込めませんでした")
        vol = max(vols, key=lambda v: np.prod(v.GetImageData().GetDimensions()))
        vol.SetName(f"CT_{s.get('studyDate', '')}_{_safe(s.get('seriesNumber', ''), 6)}")
        return vol

    def loadPhase(self, uid):
        """4D の別の位相を読み込む（今の症例は消さない）"""
        from DICOMLib import DICOMUtils
        ids = DICOMUtils.loadSeriesByUID([uid])
        vols = [slicer.mrmlScene.GetNodeByID(i) for i in ids]
        vols = [v for v in vols if v is not None and v.IsA("vtkMRMLScalarVolumeNode")]
        if not vols: raise RuntimeError("位相の CT が読み込めませんでした")
        return max(vols, key=lambda v: np.prod(v.GetImageData().GetDimensions()))

    def preview(self, s):
        """選んだシリーズの真ん中の 1 枚を、右の画面にすぐ出す（シリーズ全体は読まないので一瞬）"""
        import pydicom
        db = slicer.dicomDatabase; files = db.filesForSeries(s["uid"]) if db else []
        if not files: return
        def pos(f):
            v = db.fileValue(f, "0020,0032")
            try: return float(v.split("\\")[2])
            except Exception:
                try: return float(db.fileValue(f, "0020,0013") or 0)
                except Exception: return 0.0
        fs = sorted(files, key=pos); d = pydicom.dcmread(fs[len(fs) // 2])
        a = d.pixel_array
        rgb = int(getattr(d, "SamplesPerPixel", 1) or 1) >= 3
        if rgb: a = a[..., :3].mean(axis=-1)
        elif a.ndim == 3: a = a[a.shape[0] // 2]
        a = a.astype(np.float32)
        if not rgb: a = a * float(getattr(d, "RescaleSlope", 1) or 1) + float(getattr(d, "RescaleIntercept", 0) or 0)
        node = slicer.mrmlScene.GetFirstNodeByName("HV プレビュー")
        if node is None:
            node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "HV プレビュー"); node.SetHideFromEditors(True)
        slicer.util.updateVolumeFromArray(node, a[None])
        try: px = [float(x) for x in d.PixelSpacing]
        except Exception: px = [1.0, 1.0]
        node.SetSpacing(px[1], px[0], 1.0); node.SetOrigin(0, 0, 0)
        m = vtk.vtkMatrix4x4(); m.Identity(); m.SetElement(0, 0, -1); m.SetElement(1, 1, -1); node.SetIJKToRASDirectionMatrix(m)   # DICOM と同じ向き（右が画面の左）
        if node.GetDisplayNode() is None: node.CreateDefaultDisplayNodes()
        dn = node.GetDisplayNode(); dn.SetAutoWindowLevel(False)
        try:
            wc = float(str(d.WindowCenter).split("\\")[0].strip("[]").split(",")[0]); ww = float(str(d.WindowWidth).split("\\")[0].strip("[]").split(",")[0])
        except Exception: wc, ww = (128.0, 255.0) if rgb else (200.0, 800.0)
        if rgb: wc, ww = 128.0, 255.0
        dn.SetWindowLevel(ww, wc)
        lm = slicer.app.layoutManager()
        if lm.layout != slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView: lm.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)
        w = lm.sliceWidget("Red"); cn = w.sliceLogic().GetSliceCompositeNode()
        cn.SetBackgroundVolumeID(node.GetID()); cn.SetForegroundVolumeID(None); cn.SetLabelVolumeID(None)
        w.mrmlSliceNode().SetOrientationToAxial(); w.sliceLogic().FitSliceToAll()
        try:
            ca = w.sliceView().cornerAnnotation(); ca.SetText(2, f"Preview  {s.get('seriesNumber', '')}  {(s.get('phaseLab') or '').replace('位相', 'Phase')}  ({s.get('n', '')} images)")
            ca.GetTextProperty().SetColor(1, 0.9, 0.4); w.sliceView().forceRender()
        except Exception: pass

    def loadPhaseArray(self, uid, ref):
        """4D の別の位相を、Slicer のボリュームを作らずに配列で直接読む（ref と同じ範囲・向きの時だけ。速い）。合わなければ None"""
        import pydicom
        from concurrent.futures import ThreadPoolExecutor
        files = slicer.dicomDatabase.filesForSeries(uid)
        dims = ref.GetImageData().GetDimensions()
        if len(files) != dims[2]: return None
        M = vtk.vtkMatrix4x4(); ref.GetIJKToRASMatrix(M); A = slicer.util.arrayFromVTKMatrix(M); Ainv = np.linalg.inv(A)
        out = np.empty((dims[2], dims[1], dims[0]), np.int16); hit = np.zeros(dims[2], bool)
        def one(f):
            d = pydicom.dcmread(f)
            ras = np.array([-float(d.ImagePositionPatient[0]), -float(d.ImagePositionPatient[1]), float(d.ImagePositionPatient[2]), 1.0])
            ijk = Ainv @ ras
            if abs(ijk[0]) > 0.05 or abs(ijk[1]) > 0.05 or abs(ijk[2] - round(ijk[2])) > 0.05: return None
            a = d.pixel_array.astype(np.float32) * float(getattr(d, "RescaleSlope", 1) or 1) + float(getattr(d, "RescaleIntercept", 0) or 0)
            if a.shape != (dims[1], dims[0]): return None
            return int(round(ijk[2])), a
        with ThreadPoolExecutor(8) as ex:
            for r in ex.map(one, files):
                if r is None: return None
                k, a = r
                if not 0 <= k < dims[2]: return None
                out[k] = np.clip(a, -32768, 32767); hit[k] = True
        return out if hit.all() else None

    def phaseLoader(self, uid, ref):
        def load():
            try:
                a = self.loadPhaseArray(uid, ref)
                if a is not None: return a
            except Exception as e: print("4D 直接読み込み:", e)
            return self.loadPhase(uid)
        return load

    def resetCardiacView(self, cv):
        """CardiacView の状態を新しい症例用にリセット"""
        import CardiacView
        old = cv.logic
        tag = getattr(old, "_viewObsTag", None)
        if tag is not None:
            try: old._view().interactor().RemoveObserver(tag)
            except Exception: pass
        cv.logic = CardiacView.CardiacViewLogic()

    def saveCase(self, s):
        name = f"{s.get('studyDate', '') or time.strftime('%Y%m%d')}_{_safe(s.get('seriesNumber', ''), 6)}_{_safe(s.get('rawDesc', ''), 24)}_{time.strftime('%H%M')}.mrb"
        return self._saveTo(os.path.join(casesDir(), name))

    def caseOpen(self):
        """3D を作った・開いた症例がシーンにあるか（CardiacView の面は、名前が「CV 」で始まるモデル）"""
        try: return any((n.GetName() or "").startswith("CV ") for n in slicer.util.getNodesByClass("vtkMRMLModelNode"))
        except Exception: return False

    def hasUnsaved(self):
        """開いている症例に、保存していない変更（計測・中心線・パッチ）があるか。保存できていない症例は「ある」"""
        if not self.caseOpen(): return False
        return self.savedSig is None or workSignature() != self.savedSig

    def saveCurrent(self):
        """今の症例を、開いたファイル（作った時に保存したファイル）に上書きする。まだファイルが無ければ新しい名前で"""
        return self._saveTo(self.casePath or os.path.join(casesDir(), time.strftime("%Y%m%d_%H%M%S") + ".mrb"))

    def _saveTo(self, path):
        """シーンを症例のファイルに保存する。失敗は例外で知らせる（slicer.util.saveScene は失敗しても例外を出さず False を返すので、
        前は保存できなくても「保存しました」と出ていた）。先に別の名前で書いてから入れ替える（上書きの途中で失敗しても、前のファイルを壊さない）"""
        cleanSceneText()
        tmp = (path[:-4] if path.lower().endswith(".mrb") else path) + ".saving.mrb"
        ok = False
        try: ok = bool(slicer.util.saveScene(tmp))
        except Exception as e: print("[HeartView] saveScene:", e)
        if not ok or not os.path.exists(tmp) or os.path.getsize(tmp) < 1024:
            try:
                if os.path.exists(tmp): os.remove(tmp)
            except Exception: pass
            raise RuntimeError(f"保存できませんでした（{os.path.basename(path)}）。保存先に書き込めるか・空き容量があるかを確かめてください")
        try: os.replace(tmp, path)
        except OSError as e:                                                 # 前のファイルを別のソフトがつかんでいる等: 書いたものは捨てずに、別の名前で残す
            alt = (path[:-4] if path.lower().endswith(".mrb") else path) + time.strftime("_%H%M%S") + ".mrb"
            print(f"[HeartView] {os.path.basename(path)} を入れ替えられません（{e}）。別の名前で保存します: {os.path.basename(alt)}")
            os.replace(tmp, alt); path = alt
        self.casePath = path; self.savedSig = workSignature()
        return path

    def openCase(self, path):
        import CardiacView
        slicer.mrmlScene.Clear(0)
        self.casePath = None; self.savedSig = None                            # 途中で失敗しても、前の症例のファイルを「今の症例」と思ったままにしない（上書き保存で取り違えない）
        cv = slicer.modules.cardiacview.widgetRepresentation().self()
        try:
            try: slicer.util.loadScene(path)
            except RuntimeError as e:
                if "XML" not in str(e) and "Syntax" not in str(e): raise
                print("[HeartView] 症例ファイルの文字を直して開き直します:", os.path.basename(path))
                repairCaseFile(path); slicer.mrmlScene.Clear(0); slicer.util.loadScene(path)
        except Exception as e:                                                # 読めないファイル: 読みかけを残さず、何も開いていない状態に戻してから知らせる
            import traceback; traceback.print_exc()
            try: slicer.mrmlScene.Clear(0); self.resetCardiacView(cv)
            except Exception as e2: print("[HeartView] 片付け:", e2)
            raise RuntimeError(f"このファイルは読み込めませんでした（壊れているか、症例のファイルではありません）: {os.path.basename(path)}") from e
        self.resetCardiacView(cv)
        cv.logic.adoptScene()
        if cv.logic.sourceVolume is not None: cv.volumeSelector.setCurrentNode(cv.logic.sourceVolume)
        try:                                                                   # 開いた症例の点検（元の CT・AI ラベルが結び付いているか）。足りなければ画面に出す
            issues = cv.logic.checkCase()
            if issues: qt.QTimer.singleShot(800, lambda m="⚠ 症例の点検: " + "／".join(issues): cv._status(m))
        except Exception as e: print("[HeartView] 症例の点検:", e)
        cv.logic.setCapOpacity(cv.capSlider.value / 100.0)
        cv.onFourChamber() if cv.logic._findChambers() is not None else cv.onVSD()
        self.casePath = path; self.savedSig = workSignature()                 # ここから後に足したもの（計測・パッチ）が「保存していない変更」
        qt.QTimer.singleShot(400, lambda: (cv.logic._fitParallel(recenter=True), cv.logic._viewSizeWatch(), cv.logic._view().scheduleRender()))   # 画面の大きさに合わせて全体を収める

    def savePNG(self):
        import ScreenCapture
        v = slicer.app.layoutManager().threeDWidget(0).threeDView(); v.forceRender()
        p = os.path.join(casesDir(), "画像", time.strftime("%Y%m%d_%H%M%S") + ".png")
        ScreenCapture.ScreenCaptureLogic().captureImageFromView(v, p)
        return p
