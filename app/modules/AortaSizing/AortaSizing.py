# -*- coding: utf-8 -*-
r"""
AortaSizing — ステントグラフト（EVAR / TEVAR）サイジング（研究・教育用、非医療機器）
画面と操作は 3mensio Vascular の血管ワークフローを手本にしている:
  1. 血管抽出（AI ラベル + 鼠径部までの延長）  2. 中心線（自動 → 点のドラッグ / 追加 / 右クリック削除で修正）
  3. 計測: ストレッチ像のカーソル線 ⇔ 直交断面が連動、断面は自動輪郭（制御点で修正）、Dmax / Dmin / Deq、
     ベースライン（最下位腎動脈など）からの距離、マーカー、内弯 / 外弯の長さ、屈曲角、ネック計測、クロック位置
  4. EVAR / TEVAR のまとめとレポート
計算の土台: 中心線 = VMTK（ExtractCenterline）、断面 = 血管表面を中心線に直交する平面で切る（VMTK Cross-Section Analysis と同じ方式）
"""
import os, time, math, json
import numpy as np
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *

STEP = 0.5          # 中心線の刻み (mm)
HALF = 40.0         # ストレッチ像の半幅 (mm)
NEDIT = 24          # 輪郭の制御点の数
SMOOTH_MM = 3.0     # 中心線をならす強さ (mm)
LAYOUT_ID = 5603
LAYOUT_XML = """
<layout type="horizontal" split="true">
 <item splitSize="330"><view class="vtkMRMLViewNode" singletontag="1"><property name="viewlabel" action="default">1</property></view></item>
 <item splitSize="160"><view class="vtkMRMLSliceNode" singletontag="Green"><property name="orientation" action="default">Coronal</property><property name="viewlabel" action="default">S</property><property name="viewcolor" action="default">#6EB04B</property></view></item>
 <item splitSize="160"><view class="vtkMRMLSliceNode" singletontag="Orange"><property name="orientation" action="default">Coronal</property><property name="viewlabel" action="default">S2</property><property name="viewcolor" action="default">#E8A33D</property></view></item>
 <item splitSize="450">
  <layout type="vertical" split="true">
   <item splitSize="520"><view class="vtkMRMLSliceNode" singletontag="Red"><property name="orientation" action="default">Axial</property><property name="viewlabel" action="default">X</property><property name="viewcolor" action="default">#F34A33</property></view></item>
   <item splitSize="260"><view class="vtkMRMLSliceNode" singletontag="Yellow"><property name="orientation" action="default">Axial</property><property name="viewlabel" action="default">A</property><property name="viewcolor" action="default">#EDD54C</property></view></item>
   <item splitSize="220"><view class="vtkMRMLPlotViewNode" singletontag="PlotView1"><property name="viewlabel" action="default">P</property></view></item>
  </layout>
 </item>
</layout>
"""
FIX_LAYOUT_ID = 5604                 # 中心線を合わせる時の画面: 大きな軸位 ＋ 3D ＋ ストレッチ像
FIX_LAYOUT_XML = """
<layout type="horizontal" split="true">
 <item splitSize="700"><view class="vtkMRMLSliceNode" singletontag="Yellow"><property name="orientation" action="default">Axial</property><property name="viewlabel" action="default">A</property><property name="viewcolor" action="default">#EDD54C</property></view></item>
 <item splitSize="300">
  <layout type="vertical" split="true">
   <item splitSize="500"><view class="vtkMRMLViewNode" singletontag="1"><property name="viewlabel" action="default">1</property></view></item>
   <item splitSize="500"><view class="vtkMRMLSliceNode" singletontag="Green"><property name="orientation" action="default">Coronal</property><property name="viewlabel" action="default">S</property><property name="viewcolor" action="default">#6EB04B</property></view></item>
  </layout>
 </item>
</layout>
"""
LUMEN_KEYS = ("aorta", "iliac artery")
PATH_COLORS = {"大動脈→右腸骨": (1.0, 0.6, 0.2), "大動脈→左腸骨": (0.3, 0.85, 1.0), "大動脈": (1.0, 0.85, 0.2)}
PATH_EN = {"大動脈→右腸骨": "Aorta-R iliac", "大動脈→左腸骨": "Aorta-L iliac", "大動脈": "Aorta"}
BRANCHES = [("腕頭動脈", "BCA", ("brachiocephalic trunk",)), ("左総頸動脈", "LCCA", ("common carotid artery left",)),
            ("左鎖骨下動脈", "LSCA", ("subclavian artery left",))]
TEMPLATES = {
    "EVAR": ["最下位腎動脈", "ネック終端（瘤の始まり）", "瘤の最大径", "大動脈分岐", "右内腸骨起始", "左内腸骨起始", "右遠位（総大腿）", "左遠位（総大腿）"],
    "TEVAR": ["腕頭動脈", "左総頸動脈", "左鎖骨下動脈", "近位ランディング", "瘤 / エントリー", "遠位ランディング", "腹腔動脈"],
    "自由": ["マーカー"],
}


def _ensureDecimation():
    """VMTK の前処理が使う Decimation（Slicer 本体の CLI）。軽量化の設定で外れていたらその場で読み込む"""
    if hasattr(slicer.modules, "decimation"): return
    import glob, qt
    fm = slicer.app.moduleManager().factoryManager()
    try:
        ig = list(fm.modulesToIgnore)
        if "Decimation" in ig: ig.remove("Decimation"); fm.modulesToIgnore = ig
    except Exception as e: print("decimation ignore:", e)
    for exe in glob.glob(os.path.join(slicer.app.slicerHome, "lib", "Slicer-*", "cli-modules", "Decimation*")):
        if os.path.splitext(exe)[1].lower() in ("", ".exe"):
            try: fm.registerModule(qt.QFileInfo(exe)); fm.loadModules(["Decimation"])
            except Exception as e: print("decimation load:", e)
            break


def _ensureVMTK(status=print):
    """中心線の部品（SlicerVMTK 拡張）を用意する。無ければその場でダウンロードし、再起動せずに読み込む"""
    _ensureDecimation()
    try:
        import ExtractCenterline; return ExtractCenterline
    except Exception: pass
    import sys, glob
    em = slicer.app.extensionsManagerModel()
    if not em.isExtensionInstalled("SlicerVMTK"):
        status("初回だけ: 中心線の部品（SlicerVMTK）をダウンロードしています（10 秒ほど）…")
        try: em.interactive = False
        except Exception: pass
        ok = False
        try: ok = bool(em.installExtensionFromServer("SlicerVMTK", False))
        except Exception as e: print("vmtk install:", e)
        if not ok: raise RuntimeError("中心線の部品（SlicerVMTK）を入れられませんでした。ネットにつながる状態でもう一度押すか、Slicer の拡張機能から SlicerVMTK を入れてください。")
    base = em.extensionInstallPath("SlicerVMTK")
    for lib in glob.glob(os.path.join(base, "lib", "Slicer-*")):
        L = os.path.join(lib, "qt-loadable-modules"); S = os.path.join(lib, "qt-scripted-modules")
        for p in (L, os.path.join(L, "Python"), S):
            if os.path.isdir(p) and p not in sys.path: sys.path.insert(0, p)
        if os.path.isdir(L):
            try: os.add_dll_directory(L)
            except Exception: pass
            os.environ["PATH"] = L + os.pathsep + os.environ.get("PATH", "")
    try:
        import ExtractCenterline; return ExtractCenterline
    except Exception as e:
        raise RuntimeError(f"中心線の部品を入れました。Slicer を一度閉じて開き直してください（{e}）")


def _err(where):
    import traceback; tb = traceback.format_exc(); print("[AortaSizing]", where, tb)
    try:
        with open(os.path.join(os.path.expanduser("~"), "AortaSizing_error.log"), "a", encoding="utf-8") as f: f.write(time.strftime("%H:%M:%S ") + where + "\n" + tb + "\n")
    except Exception: pass


def _norm(s): return s.lower().replace("_", " ")


def _match(name, key, exact=False):
    """ラベル名の照合（"left common iliac artery" ⇔ "iliac artery left" のように語の集合で比べる）"""
    n = _norm(name); k = _norm(key)
    if exact: return n == k
    nw, kw = set(n.split()), set(k.split())
    return kw <= nw and not ("vein" in nw and "vein" not in kw)


def _clock(x, y):
    """断面上の点 (x=右手方向, y=前方) → 時計の向き（12 時 = 前）"""
    ang = (math.degrees(math.atan2(x, y)) + 360) % 360
    h = ang / 30.0; hh = int(h) or 12; mm = int(round((h - int(h)) * 60 / 15) * 15)
    if mm == 60: hh, mm = (hh % 12) + 1, 0
    return f"{hh}:{mm:02d}"


# ============================================================================ module
class AortaSizing(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        parent.title = "大動脈サイジング"
        parent.categories = ["HUCVS"]
        parent.dependencies = []
        parent.contributors = ["HUCVS"]
        parent.helpText = "ステントグラフト用の大動脈サイジング（研究・教育用）。3mensio Vascular の操作を手本にしている。"
        parent.acknowledgementText = "中心線: VMTK (SlicerVMTK)。"


STYLE = """
QWidget#saRoot { background:#15171c; }
QWidget#saRoot QLabel { color:#e6e8ec; background:transparent; }
QWidget#saRoot QLabel[role="muted"] { color:#8a909b; font-size:11px; }
QWidget#saRoot QLabel[role="h"] { color:#f2f4f7; font-size:13px; font-weight:bold; }
QWidget#saRoot QLabel[role="big"] { color:#ffffff; font-size:24px; font-weight:bold; }
QWidget#saRoot QLabel[role="val"] { color:#ffffff; font-size:16px; font-weight:bold; }
QWidget#saRoot QLabel[role="colh"] { color:#7d8590; font-size:10px; }
QFrame[role="card"] { background:#1e2128; border:1px solid #2b3039; border-radius:12px; }
QWidget#saRoot QPushButton { background:#262a33; color:#e6e8ec; border:1px solid #343a46; border-radius:8px; padding:6px 10px; font-size:12px; }
QWidget#saRoot QPushButton:hover { background:#2e333e; border-color:#4a5263; }
QWidget#saRoot QPushButton:pressed { background:#363c49; }
QWidget#saRoot QPushButton:checked { background:#173f57; border:1px solid #4cc8f0; color:#ffffff; }
QWidget#saRoot QPushButton:disabled { color:#5d636e; border-color:#2a2e36; }
QWidget#saRoot QPushButton[kind="primary"] { background:#2f7bf6; border:1px solid #2f7bf6; color:white; font-weight:bold; padding:8px 12px; }
QWidget#saRoot QPushButton[kind="primary"]:hover { background:#4a8dff; }
QWidget#saRoot QPushButton[kind="ghost"] { background:transparent; border:none; color:#8a909b; padding:4px 6px; }
QWidget#saRoot QPushButton[kind="ghost"]:hover { color:#ffffff; }
QWidget#saRoot QPushButton[kind="step"] { background:transparent; border:none; border-bottom:2px solid #2b3039; border-radius:0; color:#8a909b; font-weight:bold; padding:8px 4px; }
QWidget#saRoot QPushButton[kind="step"]:checked { color:#ffffff; border-bottom:2px solid #4cc8f0; background:transparent; }
QWidget#saRoot QPushButton[kind="seg"] { border-radius:6px; padding:5px 8px; }
QWidget#saRoot QPushButton[kind="tool"] { padding:7px 4px; font-size:12px; }
QWidget#saRoot QTableWidget, QWidget#saRoot QListWidget, QWidget#saRoot QTextBrowser {
  background:#181b21; alternate-background-color:#1c2027; color:#e6e8ec; border:1px solid #2b3039; border-radius:8px;
  gridline-color:#232730; selection-background-color:#1f4d69; selection-color:#ffffff; font-size:12px; }
QWidget#saRoot QListWidget::item { padding:6px 6px; border-bottom:1px solid #22262e; }
QWidget#saRoot QListWidget::item:selected { background:#1f4d69; }
QWidget#saRoot QHeaderView::section { background:#181b21; color:#7d8590; border:none; border-bottom:1px solid #2b3039; padding:4px 6px; font-size:11px; }
QWidget#saRoot QScrollBar:vertical { background:transparent; width:8px; }
QWidget#saRoot QScrollBar::handle:vertical { background:#3a404c; border-radius:4px; min-height:24px; }
QWidget#saRoot QScrollBar::add-line, QWidget#saRoot QScrollBar::sub-line { height:0; }
QWidget#saRoot QComboBox { background:#262a33; color:#e6e8ec; border:1px solid #343a46; border-radius:8px; padding:5px 8px; }
"""

class AortaSizingWidget(ScriptedLoadableModuleWidget):
    # ---------------------------------------------------------------- 部品
    def _card(self, parent_layout, title=None, sub=None):
        f = qt.QFrame(); f.setProperty("role", "card"); lay = qt.QVBoxLayout(f); lay.setContentsMargins(12, 10, 12, 12); lay.setSpacing(8)
        if title:
            h = qt.QHBoxLayout(); t = qt.QLabel(title); t.setProperty("role", "h"); h.addWidget(t); h.addStretch(1)
            if sub: s = qt.QLabel(sub); s.setProperty("role", "muted"); h.addWidget(s)
            lay.addLayout(h)
        parent_layout.addWidget(f); return f, lay

    def _btn(self, text, kind=None, tip=None, checkable=False):
        b = qt.QPushButton(text)
        if kind: b.setProperty("kind", kind)
        if tip: b.setToolTip(tip)
        b.setCheckable(checkable); b.setCursor(qt.QCursor(qt.Qt.PointingHandCursor)); return b

    def _lab(self, text, role=None):
        l = qt.QLabel(text)
        if role: l.setProperty("role", role)
        if role == "muted" and len(text) > 24: l.setWordWrap(True)           # 長い説明は折り返す（パネルが狭くてもはみ出さない）
        return l

    def _seg(self, items, lay, exclusive=True):
        grp = qt.QButtonGroup(lay.parentWidget() if hasattr(lay, "parentWidget") else None); grp.setExclusive(exclusive)
        row = qt.QHBoxLayout(); row.setSpacing(4); out = []
        for txt in items:
            b = self._btn(txt, "seg", checkable=True); grp.addButton(b); row.addWidget(b); out.append(b)
        lay.addLayout(row); return grp, out

    # ---------------------------------------------------------------- 画面
    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        self.logic = AortaSizingLogic(); L = self.logic
        root = qt.QWidget(); root.setObjectName("saRoot"); root.setStyleSheet(STYLE)
        root.setAttribute(qt.Qt.WA_StyledBackground, True)
        _sc = qt.QScrollArea(); _sc.setWidgetResizable(True); _sc.setFrameShape(qt.QFrame.NoFrame); _sc.setWidget(root)   # パネルを狭くしても使える
        _sc.setStyleSheet("QScrollArea{background:#15171c; border:none}")
        try:
            import CardiacView; _sc.setStyleSheet(CardiacView.SC_STYLE); root.setStyleSheet(STYLE + CardiacView._iconCSS().replace("cvRoot", "saRoot"))
        except Exception: pass
        _sc.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        self.layout.addWidget(_sc); self.layout.setContentsMargins(0, 0, 0, 0)
        v = qt.QVBoxLayout(root); v.setContentsMargins(10, 10, 10, 10); v.setSpacing(10); self.root = root

        # ヘッダー
        h = qt.QHBoxLayout(); v.addLayout(h)
        back = self._btn("‹ 入口", "ghost", "HeartView の入口へ戻る"); h.addWidget(back)
        back.connect("clicked()", lambda: slicer.util.selectModule("HeartView") if hasattr(slicer.modules, "heartview") else None)
        t = self._lab("大動脈サイジング"); t.setStyleSheet("font-size:17px; font-weight:bold; color:#ffffff"); h.addWidget(t); h.addStretch(1)
        h.addWidget(self._lab("研究・教育用", "muted"))

        # ステップ
        sb = qt.QHBoxLayout(); sb.setSpacing(0); v.addLayout(sb); self.stepGrp = qt.QButtonGroup(root); self.stepBtns = []
        for i, txt in enumerate(("1  中心線", "2  計測", "3  TEVAR", "4  出力")):
            b = self._btn(txt, "step", checkable=True); self.stepGrp.addButton(b, i); sb.addWidget(b); self.stepBtns.append(b)
            b.connect("clicked()", lambda i=i: self.showStep(i))

        # 読み取りカード（いつも見える）
        card, c = self._card(v)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.posLabel = self._lab("—", "big"); r.addWidget(self.posLabel)
        self.pathChip = self._lab(""); self.pathChip.setStyleSheet("padding:2px 8px; border-radius:9px; font-size:11px; font-weight:bold; color:#15171c")
        r.addWidget(self.pathChip); r.addStretch(1)
        self.modeGrp, (self.outerBtn, self.lumenBtn) = self._seg(["外周", "内腔"], r)
        self.outerBtn.checked = True; self.outerBtn.setToolTip("径の線（赤・青）を外周で出す  [L]"); self.lumenBtn.setToolTip("径の線を内腔で出す  [L]")
        g = qt.QGridLayout(); g.setHorizontalSpacing(14); g.setVerticalSpacing(2); c.addLayout(g)
        for j, txt in enumerate(("", "Dmax", "Dmin", "Deq", "面積 mm²")): g.addWidget(self._lab(txt, "colh"), 0, j)
        self.vals = {}
        for i, (key, nm, col) in enumerate((("outer", "外周", "#59d0ff"), ("lumen", "内腔", "#ffd84d"))):
            l = self._lab(f"<span style='color:{col}'>●</span> {nm}"); g.addWidget(l, i + 1, 0)
            for j, f in enumerate(("dmax", "dmin", "deq", "area")):
                w = self._lab("—", "val"); g.addWidget(w, i + 1, j + 1); self.vals[(key, f)] = w
        r2 = qt.QHBoxLayout(); c.addLayout(r2)
        self.pinBtn = self._btn("📌 この断面を記録  P", "primary", "今の断面（外周・内腔の径）をマーカーとして残す"); r2.addWidget(self.pinBtn)
        self.baseBtn = self._btn("ここを 0 mm に", None, "ベースライン（距離の基準）にする"); r2.addWidget(self.baseBtn)
        r2 = qt.QHBoxLayout(); c.addLayout(r2)                              # 2 段に（パネルが狭くてもはみ出さない）
        self.editContBtn = self._btn("輪郭を直す", None, "断面の輪郭を点で手直し", checkable=True); r2.addWidget(self.editContBtn)
        self.wlBtn = self._btn("ウィンドウを戻す", None, "断面・ストレッチ像の濃さを最初（血管用 W800/L200）に戻す"); r2.addWidget(self.wlBtn)
        hint = self._lab("断面: ホイール 1 mm（Shift 5 mm）・ストレッチ像（直交 2 方向）: クリック/ドラッグで移動、ホイールで回転・"
                         "Ctrl+クリック 中心線をそこへ（断面・ストレッチ像）・Enter 置く・P 記録・L 外周/内腔・Ctrl+Z 戻す・Esc 中止", "muted"); hint.setWordWrap(True); c.addWidget(hint)

        self.stack = qt.QStackedWidget(); v.addWidget(self.stack, 1)

        # ---- ページ 1: 中心線
        pg = qt.QWidget(); pl = qt.QVBoxLayout(pg); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(10); self.stack.addWidget(pg)
        card, c = self._card(pl, "中心線", "AI ラベル + VMTK")
        self.autoButton = self._btn("自動で中心線を作る（1 分ほど）", "primary"); c.addWidget(self.autoButton)
        c.addWidget(self._lab("経路", "muted"))
        self.pathGrp, (self.rightBtn, self.leftBtn, self.aortaBtn) = self._seg(["右（橙）", "左（水色）", "大動脈のみ"], c)
        self.fixButton = self._btn("中心線を合わせる（大きな軸位でクリック）", "primary", "大きな軸位の画面で、真腔の中心を上から順にクリックしていくだけ。最後に Enter で反映", True); c.addWidget(self.fixButton)
        self.fixHint = self._lab("真腔の中心をクリックすると黄色い点が置かれ、自動で 1 cm 先の高さへ進みます（計算はまだしません）。"
                                 "ずれている所だけクリックすれば OK。ホイールで上下、Enter で反映、Backspace で 1 つ戻す、Esc で終わる（残った点は反映）。", "muted")
        self.fixHint.setWordWrap(True); self.fixHint.hide(); c.addWidget(self.fixHint)
        self.fixRow = qt.QWidget(); fr = qt.QHBoxLayout(self.fixRow); fr.setContentsMargins(0, 0, 0, 0); c.addWidget(self.fixRow)
        fr.addWidget(self._lab("進む幅", "muted")); self.fixStepGrp, self.fixStepBtns = self._seg(["5", "10", "20 mm"], fr); self.fixStepBtns[1].checked = True
        self.fixApply = self._btn("反映して作り直す（0 点）", "primary", "置いた修正点で、中心線をまとめて 1 回だけ作り直す"); fr.addWidget(self.fixApply, 1)
        self.fixClear = self._btn("点を消す", None, "反映していない修正点を全部消す"); fr.addWidget(self.fixClear)
        self.fixRow.hide()
        self.editButton = self._btn("中心線を手で直す（3 断面でクリック / ドラッグ）", "primary", "軸位・矢状断・冠状断のどこでも、中心線の近くをクリックするとそこへ動き、押したままドラッグでずらせます", True); c.addWidget(self.editButton)
        self.editHint = self._lab("3 断面のどこでも: 中心線（線）の近くをクリック → そこへ動く。押したままドラッグ → ずらす。"
                                  "右クリック → 点を消す。ホイール → スライス送り。Ctrl+Z → 戻す。終わったら「完了」か Enter（ここで 1 回だけ作り直します）。", "muted")
        self.editHint.setWordWrap(True); self.editHint.hide(); c.addWidget(self.editHint)
        self.fixButton.hide()
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.addPtButton = self._btn("通る点を追加"); r.addWidget(self.addPtButton); self.addPtButton.hide()
        self.centerHereButton = self._btn("ここを中心に寄せる"); r.addWidget(self.centerHereButton)
        self.centerAllButton = self._btn("全体を中心に寄せる"); r.addWidget(self.centerAllButton)
        c.addWidget(self._lab("3D の線をクリック = 左右の切り替えとその位置へ移動", "muted"))
        c.addWidget(self._lab("細かい修正: 断面やストレッチ像で Ctrl+クリック = その位置の中心線をクリックした所へ（Ctrl+Z で戻す）", "muted"))
        nxt = self._btn("次へ: 計測 ›", "ghost"); nxt.connect("clicked()", lambda: self.showStep(1)); pl.addWidget(nxt, 0, qt.Qt.AlignRight)
        pl.addStretch(1)

        # ---- ページ 2: 計測
        pg = qt.QWidget(); pl = qt.QVBoxLayout(pg); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(10)
        sc = qt.QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(qt.QFrame.NoFrame); sc.setWidget(pg)
        sc.setStyleSheet("QScrollArea{background:transparent} QScrollArea > QWidget > QWidget{background:transparent}"); self.stack.addWidget(sc)
        card, c = self._card(pl, "テンプレート", "順番に置いていくだけ")
        self.tplGrp, self.tplBtns = self._seg(list(TEMPLATES), c)
        self.tplBtns[0].checked = True
        self.stepList = qt.QListWidget(); self.stepList.setMinimumHeight(190); c.addWidget(self.stepList)
        nb = qt.QFrame(); nb.setStyleSheet("QFrame{background:#16324a; border:1px solid #2c6b93; border-radius:10px}"); nl = qt.QVBoxLayout(nb); nl.setContentsMargins(10, 8, 10, 8)
        self.nextLabel = self._lab("—"); self.nextLabel.setStyleSheet("color:#ffffff; font-size:14px; font-weight:bold; border:none"); nl.addWidget(self.nextLabel)
        self.nextHint = self._lab("", "muted"); self.nextHint.setStyleSheet("border:none; color:#a9c7dc; font-size:11px"); self.nextHint.setWordWrap(True); nl.addWidget(self.nextHint)
        c.addWidget(nb)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.placeBtn = self._btn("ここに置く  ⏎", "primary"); r.addWidget(self.placeBtn, 2)
        self.skipBtn = self._btn("スキップ"); r.addWidget(self.skipBtn)
        self.prevBtn = self._btn("‹ 戻る"); r.addWidget(self.prevBtn)
        self.unplaceBtn = self._btn("外す"); r.addWidget(self.unplaceBtn)

        card, c = self._card(pl, "手動計測", "どのビューでも。点はあとからドラッグで直せる")
        tr = qt.QHBoxLayout(); tr.setSpacing(4); c.addLayout(tr); self.toolBtns = {}
        for key, lab, *_ in AortaSizingLogic.MEASURES:
            b = self._btn(lab, "tool", {"line": "2 点の距離", "poly": "折れ線の長さ（右クリック / Enter で終わり）", "curve": "曲線の長さ（右クリック / Enter で終わり）",
                                         "area": "囲んだ面積（右クリック / Enter で終わり）", "angle": "3 点の角度"}[key], True)
            tr.addWidget(b); self.toolBtns[key] = b; b.connect("clicked()", lambda key=key: self.onTool(key))
        self.measTable = qt.QTableWidget(0, 4); self.measTable.setHorizontalHeaderLabels(["名前", "値", "場所", "位置"])
        self._tbl(self.measTable, 120); c.addWidget(self.measTable)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.measDel = self._btn("選んだ計測を消す"); r.addWidget(self.measDel)
        self.measClear = self._btn("全部消す", "ghost"); r.addWidget(self.measClear); r.addStretch(1)
        self.undoBtn = self._btn("↶ 戻す  Ctrl+Z", "ghost"); r.addWidget(self.undoBtn)

        card, c = self._card(pl, "マーカー", "クリックでその位置へ")
        self.markTable = qt.QTableWidget(0, 7)
        self.markTable.setHorizontalHeaderLabels(["マーカー", "側", "位置", "外 Dmax", "外 Dmin", "外 Deq", "内 Deq"])
        self._tbl(self.markTable, 170); c.addWidget(self.markTable)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.delMarkButton = self._btn("選んだマーカーを消す"); r.addWidget(self.delMarkButton)
        self.measureButton = self._btn("2 つの間を測る"); self.measureButton.setToolTip("表で 2 つ選ぶ（Ctrl+クリック）"); r.addWidget(self.measureButton)
        self.neckButton = self._btn("ネック 0/5/10/15"); r.addWidget(self.neckButton)

        card, c = self._card(pl, "結果", "マーカーを置くと自動で更新")
        self.resultBox = qt.QTextBrowser(); self.resultBox.setMinimumHeight(200); c.addWidget(self.resultBox)
        nxt = self._btn("次へ: TEVAR ›", "ghost"); nxt.connect("clicked()", lambda: self.showStep(2)); pl.addWidget(nxt, 0, qt.Qt.AlignRight)
        pl.addStretch(1)

        # ---- ページ 3: TEVAR（仮想グラフト・エントリー・術後との比較）
        pg = qt.QWidget(); pl = qt.QVBoxLayout(pg); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(10)
        sc = qt.QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(qt.QFrame.NoFrame); sc.setWidget(pg); sc.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
        sc.setStyleSheet("QScrollArea{background:transparent} QScrollArea > QWidget > QWidget{background:transparent}"); self.stack.addWidget(sc)
        card, c = self._card(pl, "使い方")
        c.addWidget(self._lab("① 「範囲をドラッグで決める」→ ストレッチ像で近位端から遠位端までドラッグ（白い線をつかむと端だけ動く）"
                              "　② 解離なら「真腔に沿わせる」　③ 断面で穴をクリックしてエントリーを置く　④ 術後 CT があれば「比べる」", "muted"))
        card, c = self._card(pl, "解離（真腔）", "緑の線 = 断面の真腔")
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.tlBtn = self._btn("真腔に沿わせる", None, "中心線の点から、造影された真腔を断面ごとにたどり（フラップで止まる）、グラフトを真腔の中心に置きます", True); r.addWidget(self.tlBtn, 1)
        self.tlShowBtn = self._btn("真腔を 3D に", None, "たどった真腔をうすい水色で 3D に出す", True); self.tlShowBtn.checked = True; r.addWidget(self.tlShowBtn)
        self.tlInfo = self._lab("中心線が真腔を通っていれば、ボタン 1 つで真腔をたどります（数秒）。", "muted"); self.tlInfo.setWordWrap(True); c.addWidget(self.tlInfo)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.flShowBtn = self._btn("偽腔を 3D に（紫）", None, "造影される偽腔を紫で 3D に出す。グラフト（白）が偽腔の入口側をふさいでいるかを見る", True); r.addWidget(self.flShowBtn, 1)
        self.flInfo = self._lab("", "muted"); self.flInfo.setWordWrap(True); c.addWidget(self.flInfo)
        card, c = self._card(pl, "仮想グラフト", "置きたい範囲にカバードステントを描く")
        self.tvRange = self._btn("範囲をドラッグで決める", "primary", "押してから、右のストレッチ像で 近位端 → 遠位端 までドラッグ（1 回で決まります）", True); c.addWidget(self.tvRange)
        c.addWidget(self._lab("ストレッチ像の白い線（Plan P / Plan D）は、つかんでドラッグすると端だけ動きます。", "muted"))
        g = qt.QGridLayout(); g.setHorizontalSpacing(8); g.setVerticalSpacing(6); c.addLayout(g)
        for j, t in enumerate(("", "位置", "径（実測 → グラフト）")): g.addWidget(self._lab(t, "colh"), 0, j)
        self.tvRows = {}
        for r, (key, name) in enumerate((("p", "近位端"), ("d", "遠位端")), 1):
            g.addWidget(self._lab(name, "h"), r, 0)
            pos = self._lab("—"); pos.setStyleSheet("font-size:13px; font-weight:bold; color:#ffffff"); g.addWidget(pos, r, 1)
            dia = self._lab("—"); g.addWidget(dia, r, 2)
            b = self._btn("ここに", None, f"今の断面の位置を{name}にする"); g.addWidget(b, r, 3)
            b.connect("clicked()", lambda key=key: self.onTvHere(key))
            self.tvRows[key] = (pos, dia)
        g.setColumnStretch(2, 1)
        self.tvRound = self._btn("近位端を 左鎖骨下直下の正円部に", None, "左鎖骨下動脈の口を過ぎて、断面が正円（短径/長径 ≥ 0.82）になる所を近位端にする"); c.addWidget(self.tvRound)
        r = qt.QHBoxLayout(); c.addLayout(r); r.addWidget(self._lab("オーバーサイズ", "muted"))
        self.osGrp, self.osBtns = self._seg(["0%", "5%", "10%", "15%", "20%"], r)
        self.osBtns[2].checked = True
        r = qt.QHBoxLayout(); c.addLayout(r); r.addWidget(self._lab("フラップ", "muted"))
        self.flapGrp, self.flapBtns = self._seg(["慢性", "急性", "動かない"], r)
        self.flapBtns[0].checked = True
        self.flapBtns[0].setToolTip("フラップを押して真腔が広がる（径 ≒ 真腔の長径まで）。三日月の両端はガターとして残る。断面の緑の線 = 押されて動くフラップ")
        self.flapBtns[1].setToolTip("フラップがよく動く: 大動脈の壁の中で、グラフトの径まで丸く広がる")
        self.flapBtns[2].setToolTip("フラップは動かない: グラフトは術前の真腔の中だけ（細い角はガター）")
        r = qt.QHBoxLayout(); c.addLayout(r); r.addWidget(self._lab("両端", "muted"))
        self.endGrp, self.endBtns = self._seg(["押し広げる", "あるがまま"], r)
        self.endBtns[0].checked = True
        self.endBtns[0].setToolTip("端までフラップを押して広がる（この症例の術後 CT はこちらに近い）")
        self.endBtns[1].setToolTip("両端の 2 cm で、真腔のあるがままの形へなめらかに戻る（端はフラップを押し広げきらない）")
        r = qt.QHBoxLayout(); c.addLayout(r); r.addWidget(self._lab("径を手で決める", "muted"))
        self.dpSpin = qt.QSpinBox(); self.ddSpin = qt.QSpinBox()
        for sp, tip in ((self.dpSpin, "近位の径（自動 = 実測 × オーバーサイズ）"), (self.ddSpin, "遠位の径（自動 = 実測 × オーバーサイズ）")):
            sp.setRange(0, 60); sp.setSpecialValueText("自動"); sp.setSuffix(" mm"); sp.setToolTip(tip); r.addWidget(sp)
        r.addStretch(1)
        self.tvSummary = self._lab("", "muted"); self.tvSummary.setWordWrap(True); c.addWidget(self.tvSummary)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.tvShowBtn = self._btn("3D に表示", None, "仮想グラフトを出す / 隠す", True); self.tvShowBtn.checked = True; r.addWidget(self.tvShowBtn)
        self.tvGoP = self._btn("近位端へ"); r.addWidget(self.tvGoP)
        self.tvGoD = self._btn("遠位端へ"); r.addWidget(self.tvGoD)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.ovAorta = self._btn("大動脈を重ねる", None, "3D に大動脈（外周）をうすく重ねる", True); self.ovAorta.checked = True; r.addWidget(self.ovAorta)
        self.ovPost = self._btn("術後を重ねる", None, "術後 CT の実際のグラフト（金色）を 3D に重ねる", True); r.addWidget(self.ovPost)
        self.fit3d = self._btn("3D を合わせる", None, "3D をグラフトの範囲に合わせる（左前斜位。押すたびに 左前斜位 → 正面 → 左側面）"); r.addWidget(self.fit3d)
        r = qt.QHBoxLayout(); c.addLayout(r); r.addWidget(self._lab("グラフトの軸", "muted"))
        self.axisGrp, self.axisBtns = self._seg(["中心線", "真腔に合わせる"], r)
        self.axisBtns[0].checked = True
        self.axisBtns[0].setToolTip("作った中心線をグラフトの軸にする（位置を変えたい時は中心線を直す）")
        self.axisBtns[1].setToolTip("断面ごとに、真腔をいちばん多く覆う位置へ軸を動かす")

        card, c = self._card(pl, "遠位端と SINE の目安")
        self.sineLab = qt.QLabel("—"); self.sineLab.setTextFormat(qt.Qt.RichText); self.sineLab.setWordWrap(True)
        self.sineLab.setStyleSheet("font-size:12px; color:#dfe6ee"); self.sineLab.setSizePolicy(qt.QSizePolicy.Ignored, qt.QSizePolicy.Preferred)
        self.sineLab.setMinimumWidth(10); c.addWidget(self.sineLab)
        c.addWidget(self._lab("オーバーサイズ = グラフト ÷ 遠位端の真腔 − 1。ミスマッチ = 広がりの予測 ÷ 2 cm 先の真腔。"
                              "参考 = 単施設の報告の非 SINE 群 / SINE 群の平均（VEITH 2024 抄録、ミスマッチは術後の値）。"
                              "緑 = 非 SINE 群より小・黄 = 間・赤 = SINE 群以上。判定の基準ではありません。", "muted"))
        card, c = self._card(pl, "エントリーと分枝", "緑 覆う・黄 端に近い・赤 覆わない")
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.entryBtn = self._btn("エントリーを置く", "primary", "押してから、断面（X）でエントリーの穴をクリック", True); r.addWidget(self.entryBtn, 1)
        self.entryDel = self._btn("選んだエントリーを消す"); r.addWidget(self.entryDel)
        self.covTable = qt.QTableWidget(0, 4); self.covTable.setHorizontalHeaderLabels(["名前", "位置", "計画", "術後"])
        self._tbl(self.covTable, 170); c.addWidget(self.covTable)

        card, c = self._card(pl, "術後 CT と比べる", "背骨で重ねて、実際の位置を測る")
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.postLoadBtn = self._btn("術後 CT を読み込む", None, "術後 CT の DICOM フォルダを選ぶ（院内 PC の中で読むだけ）"); r.addWidget(self.postLoadBtn, 1)
        self.postCmpBtn = self._btn("比べる", "primary", "重ね合わせ → 金属（ステント）を拾う → 計画とのずれ"); r.addWidget(self.postCmpBtn)
        self.postInfo = self._lab("まだ読み込んでいません", "muted"); self.postInfo.setWordWrap(True); c.addWidget(self.postInfo)
        g2 = qt.QGridLayout(); g2.setHorizontalSpacing(10); g2.setVerticalSpacing(2); c.addLayout(g2); g2.setColumnStretch(3, 1)
        for j, t in enumerate(("", "計画", "術後", "ずれ")): g2.addWidget(self._lab(t, "colh"), 0, j)
        for j in (1, 2, 3): g2.setColumnStretch(j, 1)
        self.cmpLab = {}
        for i, (key, name) in enumerate((("p", "近位端"), ("d", "遠位端"), ("len", "長さ"), ("dia", "径"), ("off", "中心のずれ")), 1):
            g2.addWidget(self._lab(name), i, 0)
            for j, col in enumerate(("plan", "post", "diff"), 1):
                w_ = self._lab("—"); w_.setStyleSheet("font-size:12px; font-weight:bold; color:#ffffff"); w_.setWordWrap(True)
                w_.setSizePolicy(qt.QSizePolicy.Ignored, qt.QSizePolicy.Preferred); w_.setMinimumWidth(10); g2.addWidget(w_, i, j); self.cmpLab[(key, col)] = w_
        self.sameRangeBtn = self._btn("実際と同じ範囲で描いて比べる", None, "仮想グラフトを、術後の実際のグラフトと同じ範囲に置き直して、形（太さ・位置）だけを比べる。もう一度押すと元の計画に戻る", True); c.addWidget(self.sameRangeBtn)
        self.postStretchBtn = self._btn("右のストレッチ像を術後にする", None, "右のストレッチ像（S2）を術後 CT にして、左と同じ向きで並べる", True); c.addWidget(self.postStretchBtn)
        c.addWidget(self._lab("ずれ: ＋ = 計画より遠位（足側）、− = 近位（頭側）。中心線に沿った長さ。術後 CT のスライス間隔の半分ほどの誤差があります。"
                              "径・中心のずれ = 計画と術後が重なる範囲での比較（術後は金属の輪に円を当てはめた値）。断面: 白 = 計画、金色 = 術後、緑 = 術前の真腔。", "muted"))
        nxt = self._btn("次へ: 出力 ›", "ghost"); nxt.connect("clicked()", lambda: self.showStep(3)); pl.addWidget(nxt, 0, qt.Qt.AlignRight)
        pl.addStretch(1)

        # ---- ページ 4: 出力
        pg = qt.QWidget(); pl = qt.QVBoxLayout(pg); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(10); self.stack.addWidget(pg)
        card, c = self._card(pl, "出力", "この PC の ドキュメント\\HeartView症例 に保存")
        self.pdfBtn = self._btn("サイジングシート（PDF）を作る", "primary"); c.addWidget(self.pdfBtn)
        c.addWidget(self._lab("まとめ・マーカー表（外周/内腔）・手動計測・3D・ストレッチ像・各マーカーの断面を A4 に。PNG と CSV も同じフォルダに入ります。", "muted"))
        self.pngBtn = self._btn("高画質画像（PNG）だけ保存"); c.addWidget(self.pngBtn)
        self.secBtn = self._btn("今の断面だけ PNG で保存"); c.addWidget(self.secBtn)
        r = qt.QHBoxLayout(); c.addLayout(r)
        self.outLabel = self._lab("まだ保存していません", "muted"); self.outLabel.setWordWrap(True); r.addWidget(self.outLabel, 1)
        self.openBtn = self._btn("フォルダを開く"); self.openBtn.enabled = False; r.addWidget(self.openBtn)
        pl.addStretch(1)

        self.status = self._lab("", "muted"); self.status.setWordWrap(True); v.addWidget(self.status)

        # ---- つなぎ
        self.autoButton.connect("clicked()", self.onAuto)
        self.rightBtn.connect("clicked()", lambda: self._pick("大動脈→右腸骨"))
        self.leftBtn.connect("clicked()", lambda: self._pick("大動脈→左腸骨"))
        self.aortaBtn.connect("clicked()", lambda: self._pick("大動脈"))
        self.editButton.connect("toggled(bool)", self.onEdit)
        self.fixButton.connect("toggled(bool)", self.onFix)
        self.fixApply.connect("clicked()", lambda: self._busy(L.applyFixes, self._say))
        for b, v in zip(self.fixStepBtns, (5.0, 10.0, 20.0)): b.connect("clicked()", lambda v=v: (setattr(L, "fixStep", v), L._fixHud(True) if getattr(L, "_fixLab", None) else None))
        self.fixClear.connect("clicked()", L.clearFixes)
        L.onFixChanged = self._fixChanged
        self.addPtButton.connect("clicked()", self.onAddPoint)
        self.centerHereButton.connect("clicked()", lambda: self._recenter(False))
        self.centerAllButton.connect("clicked()", lambda: self._recenter(True))
        self.outerBtn.connect("clicked()", lambda: self._mode("outer"))
        self.lumenBtn.connect("clicked()", lambda: self._mode("lumen"))
        self.pinBtn.connect("clicked()", self.onPin)
        self.baseBtn.connect("clicked()", lambda: (L.setBaseline(), self.refreshLists(), self._say("ここを 0 mm（ベースライン）にしました。")))
        self.editContBtn.connect("toggled(bool)", self.onContEdit)
        self.wlBtn.connect("clicked()", self.onResetWL)
        for b in self.tplBtns: b.connect("clicked()", self.onTemplate)
        self.stepList.connect("itemClicked(QListWidgetItem*)", lambda it: self.gotoStep(self.stepList.row(it)))
        self.placeBtn.connect("clicked()", self.onPlace)
        self.skipBtn.connect("clicked()", lambda: self.gotoStep(self._step + 1))
        self.prevBtn.connect("clicked()", lambda: self.gotoStep(self._step - 1))
        self.unplaceBtn.connect("clicked()", self.onUnplace)
        self.measTable.connect("cellClicked(int,int)", lambda r, c: self._measAt(r) and L.jumpToMeasure(self._measAt(r)))
        for k in (qt.QKeySequence.Delete, qt.Qt.Key_Backspace):                 # 表で選んで Delete でも消せる
            sc = qt.QShortcut(qt.QKeySequence(k), self.measTable); sc.setContext(qt.Qt.WidgetShortcut); sc.connect("activated()", self.onMeasDel)
        self.measDel.connect("clicked()", self.onMeasDel)
        self.measClear.connect("clicked()", lambda: (L.clearMeasures(), self._say("計測を全部消しました。")))
        self.undoBtn.connect("clicked()", self.onUndo)
        self.markTable.connect("cellClicked(int,int)", lambda r, c: L.jumpToMarker(r))
        self.delMarkButton.connect("clicked()", self.onDelMark)
        self.measureButton.connect("clicked()", self.onMeasure)
        self.neckButton.connect("clicked()", lambda: self._showText(L.neckMeasurement()))
        self.pdfBtn.connect("clicked()", self.onPDF)
        for b in self.osBtns: b.connect("clicked()", self.onTvOversize)
        for b in self.flapBtns: b.connect("clicked()", self.onTvFlap)
        self.tvRound.connect("clicked()", self.onTvRound)
        self.tvRange.connect("toggled(bool)", self.onTvRange)
        self.flShowBtn.connect("toggled(bool)", self.onFLShow)
        for b in self.axisBtns: b.connect("clicked()", self.onTvAxis)
        for b in self.endBtns: b.connect("clicked()", self.onTvEnds)
        self.ovAorta.connect("toggled(bool)", lambda on: L.showOverlay3D("aorta", on))
        self.ovPost.connect("toggled(bool)", lambda on: L.showOverlay3D("post", on))
        self.fit3d.connect("clicked()", self.onFit3D)
        self.dpSpin.connect("valueChanged(int)", lambda v: self.onTvDiam()); self.ddSpin.connect("valueChanged(int)", lambda v: self.onTvDiam())
        self.tvShowBtn.connect("toggled(bool)", self.onTvShow)
        self.tvGoP.connect("clicked()", lambda: L.setPosition(L.planInit()["p"])); self.tvGoD.connect("clicked()", lambda: L.setPosition(L.planInit()["d"]))
        self.entryBtn.connect("toggled(bool)", self.onEntry); self.entryDel.connect("clicked()", self.onEntryDel)
        self.covTable.connect("cellClicked(int,int)", lambda r, c: L.setPosition(self._covRows[r]["s"]) if r < len(getattr(self, "_covRows", [])) else None)
        self.postLoadBtn.connect("clicked()", self.onPostLoad); self.postCmpBtn.connect("clicked()", self.onPostCompare)
        self.postStretchBtn.connect("toggled(bool)", self.onPostStretch)
        self.sameRangeBtn.connect("toggled(bool)", self.onSameRange)
        self.tlBtn.connect("toggled(bool)", self.onTL)
        self.tlShowBtn.connect("toggled(bool)", lambda on: (lambda m: m and m.GetDisplayNode().SetVisibility(on))(slicer.mrmlScene.GetFirstNodeByName("TEVAR 真腔")))
        self.pngBtn.connect("clicked()", self.onPNG)
        self.secBtn.connect("clicked()", self.onSecPNG)
        self.openBtn.connect("clicked()", lambda: qt.QDesktopServices.openUrl(qt.QUrl.fromLocalFile(self._lastDir)))
        L.onChanged = self.refreshReadout
        L.onListsChanged = self.refreshLists
        L.onPath = self._syncPathButtons
        L.onKey = self.onKey
        L.onStatus = self._say
        self._step = 0; self._lastDir = ""
        inter = slicer.app.applicationLogic().GetInteractionNode()
        self._interTag = inter.AddObserver(inter.InteractionModeChangedEvent, lambda c, e: self._syncTools())
        self.showStep(0); self.onTemplate(); self._syncPathButtons()

    # ---------------------------------------------------------------- TEVAR（仮想グラフト・術後との比較）
    SHORT = {"腕頭動脈": "腕頭", "左総頸動脈": "左総頸", "左鎖骨下動脈": "左鎖骨下", "腹腔動脈": "腹腔", "上腸間膜動脈": "SMA", "最下位腎動脈": "腎動脈"}

    def _tvRef(self, s):
        """位置を「いちばん近い近位の分枝 + mm」で（無ければベースラインから）"""
        L = self.logic; best = None
        for m in L.markers:
            nm = m["name"].replace("（推定）", "")
            if nm in self.SHORT and m["s"] <= s + 0.5 and (best is None or m["s"] > best[1]): best = (nm, m["s"])
        return f"{self.SHORT[best[0]]} +{s - best[1]:.0f} mm" if best else f"{L.rel(s):+.0f} mm"

    def _tvEnter(self):
        L = self.logic
        if L.P is None: self._say("先に中心線を作ってください"); return
        pl0 = getattr(L, "plan", None)
        if pl0 is not None and pl0.get("path") in L.frames and pl0["path"] != L.path:   # 計画を作った経路（右腸骨など）に戻す
            try: L.curS = float(pl0["p"]); self._busy(L.selectPath, pl0["path"], self._say); self._syncPathButtons()
            except Exception as e: print("tv path:", e)
        pl = L.planInit()
        try: self.osBtns[[0.0, 0.05, 0.10, 0.15, 0.20].index(round(pl["os"], 2))].checked = True
        except Exception: pass
        self.tlBtn.blockSignals(True); self.tlBtn.checked = bool(pl.get("tl")); self.tlBtn.blockSignals(False)
        self.flapBtns[{"chronic": 0, "acute": 1, "fixed": 2}.get(pl.get("flap", "chronic"), 0)].checked = True
        self.endBtns[1 if pl.get("ends") == "asis" else 0].checked = True
        self.axisBtns[0 if (pl.get("axis") or ("tl" if pl.get("tl") else "cl")) == "cl" else 1].checked = True
        L.showOverlay3D("aorta", self.ovAorta.checked); L.showOverlay3D("post", self.ovPost.checked)
        if not getattr(self, "_tvFitted", False):
            self._tvFitted = True
            try: qt.QTimer.singleShot(300, lambda: L.fit3DToGraft("lao"))
            except Exception: pass
        for sp, key in ((self.dpSpin, "dp"), (self.ddSpin, "dd")):
            sp.blockSignals(True); sp.value = int(pl.get(key) or 0); sp.blockSignals(False)
        self.tvShowBtn.blockSignals(True); self.tvShowBtn.checked = bool(pl.get("on", True)); self.tvShowBtn.blockSignals(False)
        self._busy(L.planDraw); self._tvRefresh()

    def _tvRefresh(self):
        L = self.logic
        if L.P is None or not hasattr(self, "tvRows"): return
        pl = L.planInit()
        try: (Dp, mp, ap), (Dd, md, ad) = L.planDiams()
        except Exception as e: print("tv:", e); return
        for key, s, D, mD, man in (("p", pl["p"], Dp, mp, ap), ("d", pl["d"], Dd, md, ad)):
            pos, dia = self.tvRows[key]; pos.setText(self._tvRef(s))
            tlt = ""
            if pl.get("tl") and L.tlValid():
                dq = L.tl["deq"][L._k(s)]; tlt = f"・真腔 {dq:.0f}" if np.isfinite(dq) else ""
            dia.setText(("—" if mD is None else f"{mD:.1f}") + tlt + " → " + ("—" if D is None else f"<b>{D:.0f} mm</b>") + ("（手入力）" if man else ""))
        if Dp and Dd:
            gr = getattr(L, "_graftRad", None); ft = ""
            if gr is not None:
                fd = L._planDrawn
                ft = (f"。白い筒 = 広がった形の予測（{('慢性: フラップを押して広がる・ガターが残る' if gr['flap'] == 'chronic' else ('急性: 丸く広がる' if gr['flap'] == 'acute' else 'フラップは動かない: 術前の真腔の中だけ')) if gr['tl'] else '内腔の中で広がる'}）"
                      f" {np.nanmin(fd):.0f}〜{np.nanmax(fd):.0f} mm。断面の白い輪の数字 = 広がった径 / 名目の径")
            self.tvSummary.setText(f"長さ {pl['d'] - pl['p']:.0f} mm・径 {Dp:.0f} → {Dd:.0f} mm（{'テーパー' if abs(Dp - Dd) > 0.5 else 'ストレート'}）"
                                   f"・オーバーサイズ {pl['os'] * 100:.0f}%" + (ft or "　白い筒 = 計画（断面にも輪郭）"))
        self._sineRefresh()
        try: self._flText()
        except Exception: pass
        ac = getattr(L, "actual", None)
        post = {r["name"]: r for r in L.coverage(ac["lo"], ac["hi"])} if ac else {}
        rows = L.coverage(pl["p"], pl["d"]); t = self.covTable; t.setRowCount(len(rows)); self._covRows = rows
        col = {"cover": "#5fd36e", "edge": "#ffcc33", "open": "#ff6b6b", "block": "#ff6b6b", "ok": "#9cc9ff"}
        for i, rw in enumerate(rows):
            vals = [rw["name"], self._tvRef(rw["s"]), rw["text"], post.get(rw["name"], {}).get("text", "")]
            for j, v in enumerate(vals):
                it = qt.QTableWidgetItem(v)
                if j == 2: it.setForeground(qt.QBrush(qt.QColor(col[rw["state"]])))
                if j == 3 and rw["name"] in post: it.setForeground(qt.QBrush(qt.QColor(col[post[rw["name"]]["state"]])))
                t.setItem(i, j, it)
        t.resizeColumnsToContents()
        cmp_ = L.comparePost()
        if cmp_:
            vals = {("p", "plan"): self._tvRef(pl["p"]), ("p", "post"): self._tvRef(ac["lo"]), ("p", "diff"): f"{cmp_['dP']:+.0f} mm",
                    ("d", "plan"): self._tvRef(pl["d"]), ("d", "post"): self._tvRef(ac["hi"]), ("d", "diff"): f"{cmp_['dD']:+.0f} mm",
                    ("len", "plan"): f"{cmp_['planLen']:.0f} mm", ("len", "post"): f"{cmp_['realLen']:.0f} mm", ("len", "diff"): f"{cmp_['realLen'] - cmp_['planLen']:+.0f} mm"}
            if "Dreal" in cmp_:
                vals.update({("dia", "plan"): (f"{cmp_['Dplan']:.0f} mm（名目 {cmp_['Dnom']:.0f}）" if cmp_.get("Dnom") and cmp_["Dnom"] - cmp_["Dplan"] > 0.5 else f"{cmp_['Dplan']:.0f} mm"), ("dia", "post"): f"{cmp_['Dreal']:.0f} mm（{cmp_['DrealMin']:.0f}〜{cmp_['DrealMax']:.0f}）",
                             ("dia", "diff"): f"{round(cmp_['Dreal'] - cmp_['Dplan']) + 0:+.0f} mm",
                             ("off", "plan"): "広がりの予測" if getattr(L, "_graftRad", None) is not None else ("真腔の中心" if pl.get("tl") else "大動脈の中心"), ("off", "post"): f"中央値 {cmp_['offMed']:.0f} mm",
                             ("off", "diff"): f"最大 {cmp_['offMax']:.0f} mm（{self._tvRef(cmp_['offAt'])}）"})
            for k, v in vals.items(): self.cmpLab[k].setText(v)

    def onTL(self, on):
        L = self.logic; pl = L.planInit(); pl["tl"] = bool(on)
        def run():
            if on and not L.tlValid(): L.extractTL(self._say)
            L.planDraw()
        self._busy(run); self._tvRefresh()
        if on and L.tlValid():
            d = L.tl["deq"]; self.tlInfo.setText(f"真腔をたどりました。グラフトは真腔の中心に置いています（真腔の径 {np.nanmin(d):.0f}〜{np.nanmax(d):.0f} mm）。断面の緑の線で確認してください。")
        elif not on: self.tlInfo.setText("大動脈の中心線に沿わせています。")

    def _sineRefresh(self):
        L = self.logic
        try: si = L.sineIdx()
        except Exception as e: print("sine:", e); si = None
        if not si: self.sineLab.setText("解離では「真腔に沿わせる」を押すと出ます。"); return
        ref = L.SINE_REF; g = "color:#9aa7b4; font-size:11px"
        def cell(v, rr):
            if v is None or not np.isfinite(v): return "<td align='right'>—</td>"
            col = "#5fd36e" if v < rr[0] else ("#ffcc33" if v < rr[1] else "#ff6b6b")
            return f"<td align='right' style='color:{col}; font-weight:bold'>{v:.2f}</td>"
        def refrow(r): return f"<tr><td style='{g}'>参考</td>" + "".join(f"<td align='right' style='{g}'>{r[k][0]:g}/{r[k][1]:g}</td>" for k in ("mean", "per", "area")) + "</tr>"
        a = si["tl"]
        h = (f"<b>遠位端の真腔</b>　短径 {a['short']:.1f}・長径 {a['long']:.1f} mm<br>周径 {a['per']:.0f} mm・面積 {a['area']:.0f} mm²<br>"
             f"<b>グラフト遠位</b>　{si['Dd']:.0f} mm（周径 {math.pi * si['Dd']:.0f}）<br>短径比 {si['pre']['short'] * 100:+.0f}%・長径比 {(si['Dd'] / a['long'] - 1) * 100:+.0f}%")
        if "gD" in si: h += f"<br><b>広がりの予測</b>　{si['gD']:.0f} mm（周径 {si['gper']:.0f}）" + (f"<br>ガター {si['gut']:.0f} mm²" if si.get("gut", 0) >= 5 else "")
        h += f"<table width='100%' cellspacing='0' cellpadding='2' style='margin-top:6px'><tr><td></td><td align='right' style='{g}'>平均径</td><td align='right' style='{g}'>周径</td><td align='right' style='{g}'>面積</td></tr>"
        p = si["pre"]; h += "<tr><td>オーバーサイズ</td>" + cell(p["mean"], ref["pre"]["mean"]) + cell(p["per"], ref["pre"]["per"]) + cell(p["area"], ref["pre"]["area"]) + "</tr>" + refrow(ref["pre"])
        if "emr" in si:
            e = si["emr"]; h += "<tr><td>ミスマッチ（予測）</td>" + cell(e["mean"], ref["emr"]["mean"]) + cell(e["per"], ref["emr"]["per"]) + cell(e["area"], ref["emr"]["area"]) + "</tr>" + refrow(ref["emr"])
        h += "</table>"
        self.sineLab.setText(h)

    def onTvHere(self, key):
        self.logic.planSet(**{key: float(self.logic.curS)}); self._tvRefresh()

    def onTvRange(self, on):
        self.logic.rangeMode = bool(on)
        if on: self._say("ストレッチ像で、近位端から遠位端までドラッグしてください。")

    def onTvRound(self):
        L = self.logic; r = L.roundLanding()
        if r is None: self._say("左鎖骨下動脈の印が無いか、直下に正円の所が見つかりませんでした。断面で位置を合わせて「近位端 ここに」を使ってください。"); return
        self._busy(lambda: L.planSet(p=r["s"])); L.setPosition(r["s"]); self._tvRefresh()
        self._say(f"近位端を 左鎖骨下 +{r['s'] - r['lsca']:.1f} mm（真円度 {r['r']:.2f}・径 {r['deq']:.0f} mm）に置きました。正円の所はそこから約 {r['length']:.0f} mm 続きます。")

    def onFLShow(self, on):
        L = self.logic
        if on and not L.flValid(): self._busy(L.extractFL, self._say)
        m = slicer.mrmlScene.GetFirstNodeByName("TEVAR 偽腔")
        if m is not None and m.GetDisplayNode(): m.GetDisplayNode().SetVisibility(bool(on))
        self._flText()

    def _flText(self):
        L = self.logic
        if not L.flValid() or L.fl.get("start") is None: self.flInfo.setText(""); return
        pl = L.planInit(); st = L.fl["start"]; t = f"造影される偽腔は {self._tvRef(st)} から（紫）。"
        if pl["p"] <= st <= pl["d"]: t += f"グラフトはその {st - pl['p']:.0f} mm 近位から覆っています（入口側をふさぐ）。"
        elif st < pl["p"]: t += f"グラフトの近位端より {pl['p'] - st:.0f} mm 近位に偽腔があります（覆っていません）。"
        else: t += "グラフトより遠位です。"
        self.flInfo.setText(t + " 穴（エントリー）は断面で確かめて「エントリーを置く」で印をつけると、覆うかどうかが下の表に出ます。")

    def onTvEnds(self):
        v = "push" if self.endBtns[0].checked else "asis"
        self._busy(lambda: self.logic.planSet(ends=v)); self._tvRefresh()

    def onTvAxis(self):
        v = "cl" if self.axisBtns[0].checked else "tl"
        self._busy(lambda: self.logic.planSet(axis=v)); self._tvRefresh()

    def onFit3D(self):
        views = ("lao", "front", "left"); self._fitIdx = (getattr(self, "_fitIdx", -1) + 1) % 3
        self.logic.fit3DToGraft(views[self._fitIdx])
        self._say({"lao": "3D: 左前斜位", "front": "3D: 正面", "left": "3D: 左側面"}[views[self._fitIdx]])

    def onTvFlap(self):
        v = ("chronic", "acute", "fixed")[[b.checked for b in self.flapBtns].index(True)]
        self._busy(lambda: self.logic.planSet(flap=v)); self._tvRefresh()

    def onTvOversize(self):
        v = [0.0, 0.05, 0.10, 0.15, 0.20][[b.checked for b in self.osBtns].index(True)]
        self._busy(lambda: self.logic.planSet(os=v)); self._tvRefresh()

    def onTvDiam(self):
        self._busy(lambda: self.logic.planSet(dp=self.dpSpin.value or None, dd=self.ddSpin.value or None)); self._tvRefresh()

    def onTvShow(self, on):
        L = self.logic; L.planInit()["on"] = bool(on)
        if on: self._busy(L.planDraw)
        else: L.planShow(False)

    def onEntry(self, on):
        L = self.logic
        if not on: L._entryCb = None; return
        def done(ras):
            name = L.addEntry(ras); self.entryBtn.blockSignals(True); self.entryBtn.checked = False; self.entryBtn.blockSignals(False)
            self._tvRefresh(); self._say(f"{name} を置きました（中心線 {self._tvRef(L.curS)}）。")
        L._entryCb = done; self._say("断面（X）でエントリーの穴をクリックしてください。")

    def onEntryDel(self):
        r = self.covTable.currentRow(); rows = getattr(self, "_covRows", [])
        if 0 <= r < len(rows) and rows[r]["kind"] == "entry": self.logic.removeEntry(rows[r]["name"]); self._tvRefresh()
        else: self._say("表でエントリーを選んでください")

    def onPostLoad(self):
        d = qt.QFileDialog.getExistingDirectory(None, "術後 CT の DICOM フォルダを選ぶ")
        if not d: return
        n = self._busy(self.logic.loadPostFolder, d, self._say)
        if n is not None:
            sp = n.GetSpacing(); self.postInfo.setText(f"術後 CT: {slicer.util.arrayFromVolume(n).shape[0]} 枚・スライス間隔 {sp[2]:.1f} mm。「比べる」を押してください。")

    def onPostCompare(self):
        L = self.logic
        if getattr(L, "post", None) is None or not slicer.mrmlScene.IsNodePresent(L.post):
            self.onPostLoad()
            if getattr(L, "post", None) is None: return
        def run():
            M, rms = L.registerPost(self._say)
            L.extractStent(status=self._say)
            try: L.refinePost(self._say)
            except Exception as e: print("refine:", e)
            return rms
        rms = self._busy(run)
        if rms is None: return
        zr = L.post.GetSpacing()[2]
        ps = getattr(L, "postShift", None); pst = ""
        if ps is not None: pst = f"。そのあと大動脈の外形で合わせ直し（ずれ 中央値 {np.median(ps['mag']):.1f}・最大 {ps['mag'].max():.1f} mm）"
        self.postInfo.setText(f"重ね合わせ（背骨）の誤差 {rms:.1f} mm{pst}・術後 CT のスライス間隔 {zr:.1f} mm（端の位置はおよそ ±{max(zr / 2, rms):.0f} mm）")
        self._tvRefresh()
        c = L.comparePost()
        if c: self._say(f"術後のグラフト: 近位端 {c['dP']:+.0f} mm・遠位端 {c['dD']:+.0f} mm（計画との差。＋ = 遠位へ）")

    def onSameRange(self, on):
        L = self.logic; ac = getattr(L, "actual", None); pl = L.planInit()
        if on:
            if ac is None:
                self.sameRangeBtn.blockSignals(True); self.sameRangeBtn.checked = False; self.sameRangeBtn.blockSignals(False)
                self._say("先に「比べる」を押してください"); return
            self._keepPD = (pl["p"], pl["d"]); self._busy(lambda: L.planSet(p=ac["lo"], d=ac["hi"]))
            L.showOverlay3D("post", True); self.ovPost.blockSignals(True); self.ovPost.checked = True; self.ovPost.blockSignals(False)
            self._say("実際と同じ範囲に置き直しました。断面: 白 = シミュレーション、金色の点 = 実際の金属。もう一度押すと元の計画に戻ります。")
        else:
            kp = getattr(self, "_keepPD", None)
            if kp: self._busy(lambda: L.planSet(p=kp[0], d=kp[1])); self._say("元の計画に戻しました。")
        self._tvRefresh()

    def onPostStretch(self, on):
        L = self.logic
        if on and getattr(L, "postT", None) is None:
            self.postStretchBtn.blockSignals(True); self.postStretchBtn.checked = False; self.postStretchBtn.blockSignals(False)
            self._say("先に「比べる」を押してください"); return
        if on: self._busy(L.postStraight)
        L.orangeOff = 0.0 if on else 90.0; L.showPostStretch(on); L.setRotation(L.rot)

    def _tbl(self, t, h):
        t.setSelectionBehavior(qt.QAbstractItemView.SelectRows); t.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)
        t.verticalHeader().setVisible(False); t.setMinimumHeight(h); t.setAlternatingRowColors(True); t.setShowGrid(False)
        t.horizontalHeader().setStretchLastSection(True); t.verticalHeader().setDefaultSectionSize(26)

    def cleanup(self):
        try:
            inter = slicer.app.applicationLogic().GetInteractionNode(); inter.RemoveObserver(self._interTag)
        except Exception: pass

    def enter(self):
        try:                                                                # Slicer のヘルプ欄はたたんで、画面を広く使う
            hb = slicer.util.mainWindow().findChild(ctk.ctkCollapsibleButton, "HelpCollapsibleButton")
            if hb is not None: hb.collapsed = True
        except Exception: pass
        try: self.logic.resume()
        except Exception: _err("enter")
        qt.QTimer.singleShot(300, self._autoStart)
        if self.stack.currentIndex == 2: qt.QTimer.singleShot(500, lambda: self.showStep(2))   # TEVAR の画面に戻ってきた時も半透明の設定に

    def _autoStart(self):
        """開いたら、中心線がまだ無ければ自動で作って計測の画面にする（ボタンを探さなくてよい）"""
        L = self.logic
        try:
            if slicer.util.selectedModule() != "AortaSizing" or L.P is not None: return
        except Exception: return
        try: vol, seg = L._inputs()
        except Exception as e: self._say(str(e)); return
        if getattr(self, "_autoTried", None) == vol.GetID(): return
        self._autoTried = vol.GetID()
        self._say("中心線を自動で作っています（1 分ほど。開いた時に自動）…")
        self.onAuto()

    def exit(self):
        self.logic._tvMode = False
        try:
            if getattr(self, "_tvRen", None) is not None:
                ren = slicer.app.layoutManager().threeDWidget(0).threeDView().renderWindow().GetRenderers().GetFirstRenderer()
                ren.SetUseDepthPeeling(self._tvRen[0]); ren.SetUseSSAO(self._tvRen[1]); self._tvRen = None
            vm = getattr(self.logic, "vesselModel", None)
            if vm is not None and slicer.mrmlScene.IsNodePresent(vm): vm.GetDisplayNode().SetOpacity(1.0)
        except Exception: pass
        try: self.logic.suspend()
        except Exception: _err("exit")

    def showStep(self, i):
        i = max(0, min(3, i)); self.stack.setCurrentIndex(i); self.stepBtns[i].checked = True
        if i != 0 and getattr(self, "fixButton", None) is not None and self.fixButton.checked: self.fixButton.checked = False
        if i == 1: self.refreshLists()
        self.logic._tvMode = (i == 2)
        if i == 2: self._tvEnter()
        try:                                                                  # TEVAR の時は血管を半透明にして、中のグラフトを見せる
            vm = getattr(self.logic, "vesselModel", None)
            if vm is not None and slicer.mrmlScene.IsNodePresent(vm): vm.GetDisplayNode().SetOpacity(0.3 if i == 2 else 1.0)
            ren = slicer.app.layoutManager().threeDWidget(0).threeDView().renderWindow().GetRenderers().GetFirstRenderer()
            if i == 2 and getattr(self, "_tvRen", None) is None:               # 半透明（血管・グラフトの布）をきちんと描く（重ねた描画層では深さの剥離が効かない）
                self._tvRen = (ren.GetUseDepthPeeling(), ren.GetUseSSAO()); ren.SetUseDepthPeeling(False); ren.SetUseSSAO(False)
            elif i != 2 and getattr(self, "_tvRen", None) is not None:
                ren.SetUseDepthPeeling(self._tvRen[0]); ren.SetUseSSAO(self._tvRen[1]); self._tvRen = None
        except Exception: pass

    def _say(self, m):
        self.status.setText(m); print("[AortaSizing]", m); slicer.app.processEvents()

    def _busy(self, f, *a):
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try: return f(*a)
        except Exception as e:
            import traceback; traceback.print_exc(); self._say(f"エラー: {e}")
        finally: qt.QApplication.restoreOverrideCursor()

    def _syncPathButtons(self):
        cur = self.logic.path or ""; has = self.logic.curves
        for b, key in ((self.rightBtn, "大動脈→右腸骨"), (self.leftBtn, "大動脈→左腸骨"), (self.aortaBtn, "大動脈")):
            b.visible = key in has; b.checked = (cur == key)
        col = {"大動脈→右腸骨": ("#f39a33", "右"), "大動脈→左腸骨": ("#4cc8f0", "左"), "大動脈": ("#e6d54c", "大動脈")}.get(cur)
        self.pathChip.visible = col is not None
        if col: self.pathChip.setText(col[1]); self.pathChip.setStyleSheet(f"padding:2px 8px; border-radius:9px; font-size:11px; font-weight:bold; color:#15171c; background:{col[0]}")

    # ---------------------------------------------------------------- 1 中心線
    def onAuto(self):
        def run():
            paths = self.logic.autoCenterline(self._say)
            first = "大動脈→右腸骨" if "大動脈→右腸骨" in paths else paths[0]
            self.logic.selectPath(first, self._say)
            self._syncPathButtons(); self.refreshReadout(); self.refreshLists()
            self._say(f"できました（全長 {self.logic.length:.0f} mm）。「2 計測」でテンプレートの順に置いていきます。")
            self.showStep(1); self.gotoStep(self._firstOpen())
        self._busy(run)

    def _pick(self, name):
        if name not in self.logic.curves: self._syncPathButtons(); return
        if self.editButton.checked: self.editButton.checked = False
        self._busy(lambda: (self.logic.selectPath(name, self._say), self.refreshReadout(), self.refreshLists()))
        self._syncPathButtons()

    def _fixChanged(self):
        n = len(getattr(self.logic, "pendingFix", []) or [])
        self.fixApply.setText(f"反映して作り直す（{n} 点）"); self.fixApply.enabled = n > 0; self.fixClear.enabled = n > 0
        self.fixRow.setVisible(self.fixButton.checked or n > 0)

    def onFix(self, on):
        L = self.logic
        if L.P is None:
            self.fixButton.blockSignals(True); self.fixButton.checked = False; self.fixButton.blockSignals(False); self._say("先に中心線を作ってください"); return
        if not on and (getattr(L, "pendingFix", None) or []): self._busy(L.applyFixes, self._say)     # 終わる時に残った点は反映
        L.setFixMode(on); self.fixHint.setVisible(on); self._fixChanged()
        self._busy(L.fixLayout, on)
        if on and self.editButton.checked: self.editButton.checked = False
        self._say("中心線を合わせるモード: 軸位（A）か断面（X）で真腔の中心をクリック → ホイールで次の高さへ → … → 「反映して作り直す」。" if on else "合わせるモードを終えました。")

    def onEdit(self, on):
        if self.logic.P is None:
            self.editButton.blockSignals(True); self.editButton.checked = False; self.editButton.blockSignals(False); self._say("先に中心線を作ってください"); return
        self.editHint.setVisible(on); self.editButton.setText("完了（中心線を作り直す）" if on else "中心線を手で直す（3 断面でクリック / ドラッグ）")
        self.addPtButton.setVisible(not on)
        self.logic.editMode(on, self.logic.path)
        if not on and self.logic.path:
            L = self.logic
            def fin():
                L._rebuildKeep(self._say)                                     # 直した所だけ作り直す（広ければ全部）
                L.showLayout(); L.setPosition(min(L.curS, L.length)); self.refreshReadout(); self.refreshLists()
            self._busy(fin)
            self._say("直した中心線で作り直しました。")
        else:
            self._say("3 断面のどこでも、中心線の近くをクリックするとそこへ動きます（押したままドラッグでずらす）。終わったら「完了」。")

    def onAddPoint(self):
        if not self.editButton.checked: self.editButton.checked = True
        self.logic.startAddPoint(self.logic.path, lambda: self._say("点を追加しました。終わったら「中心線を直す」をもう一度。"))
        self._say("通したい所（真腔の中など）を断面でクリックしてください。")

    def _recenter(self, whole):
        s0 = self.logic.curS
        self._busy(lambda: (self.logic.recenter(self.logic.path, None if whole else s0, self._say), self.logic.setPosition(min(s0, self.logic.length)), self.refreshReadout()))

    def _mode(self, m):
        self._busy(lambda: (self.logic.setMode(m), self.refreshReadout()))
        self.outerBtn.checked = (m == "outer"); self.lumenBtn.checked = (m == "lumen")

    def onResetWL(self):
        L = self.logic
        for vn in (L.vol, L.straight):
            d = vn.GetDisplayNode() if vn is not None else None
            if d is not None: d.SetAutoWindowLevel(False); d.SetWindowLevel(800, 200)
        self._say("ウィンドウを最初の値（W800 / L200）に戻しました。")

    def onContEdit(self, on):
        try: self.logic.setContourEdit(on)
        except Exception: _err("contEdit")
        self._say("断面の輪郭の点をドラッグして直します。終わったらもう一度押す。" if on else "輪郭の手直しを終えました。")

    # ---------------------------------------------------------------- 読み取り（毎フレーム、軽く）
    def refreshReadout(self):
        L = self.logic
        if L.P is None: return
        self.posLabel.setText(f"{L.rel(L.curS):+.1f} mm" + ("" if L.baseS is not None else "  "))
        self.posLabel.setToolTip("ベースラインからの距離" if L.baseS is not None else "起点からの距離（ベースライン未設定）")
        for key, m in (("outer", getattr(L, "_mO", None)), ("lumen", getattr(L, "_mL", None))):
            for f in ("dmax", "dmin", "deq", "area"):
                self.vals[(key, f)].setText("—" if not m else (f"{m[f]:.0f}" if f == "area" else f"{m[f]:.1f}"))

    # ---------------------------------------------------------------- 2 テンプレート
    def _tpl(self):
        for b in self.tplBtns:
            if b.checked: return b.text
        return list(TEMPLATES)[0]

    def onTemplate(self):
        self._step = self._firstOpen(); self.refreshLists()

    def _steps(self):
        return [] if self._tpl() == "自由" else TEMPLATES[self._tpl()]

    def _firstOpen(self):
        L = self.logic
        for i, nm in enumerate(self._steps()):
            m = L._mk(nm)
            if m is None or m.get("auto"): return i
        return max(0, len(self._steps()) - 1)

    def gotoStep(self, i):
        st = self._steps()
        if not st: return
        self._step = max(0, min(len(st) - 1, i)); nm = st[self._step]; L = self.logic
        path = L.stepPath(nm)
        sg = L.suggest(nm) if L.P is not None else None
        try:
            if sg is not None:
                s, p = sg; p = path or p
                if p and p != L.path and p in L.curves and s > getattr(L, "sharedLen", 0) + 2: L._switch(p, s)
                else: L.setPosition(s)
            elif path and path != L.path and path in L.curves: L._switch(path, L.curS)
        except Exception: _err("goto")
        self.refreshLists()

    def onPlace(self):
        L = self.logic
        if L.P is None: self._say("先に中心線を作ってください。"); return
        if getattr(L, "_activeMeasure", None) is not None: L.finishMeasure(); return
        st = self._steps()
        if not st: name = L.addMarker("マーカー"); self._say(f"「{name}」を置きました。"); return
        nm = st[self._step]; L.addMarker(nm); self._say(f"「{nm}」を {L.rel(L.curS):+.1f} mm に置きました。")
        nxt = next((i for i in range(self._step + 1, len(st)) if (L._mk(st[i]) is None or L._mk(st[i]).get("auto"))), None)
        if nxt is not None: self.gotoStep(nxt)
        else: self.refreshLists(); self._say("テンプレートの項目が全部そろいました。「3 出力」でサイジングシートを作れます。")

    def onUnplace(self):
        st = self._steps()
        if st: self.logic.removeMarkerByName(st[self._step])

    def onPin(self):
        if self.logic.P is None: return
        nm = self.logic.pinSection(); self._say(f"「{nm}」として記録しました（マーカー表と出力に入ります）。")

    # ---------------------------------------------------------------- 手動計測
    def onTool(self, key):
        L = self.logic
        if not self.toolBtns[key].checked: L.cancelMeasure(); return
        for k, b in self.toolBtns.items(): b.checked = (k == key)
        L.startMeasure(key)
        self._say({"line": "2 点をクリック。", "angle": "3 点をクリック（真ん中が頂点）。"}.get(key, "点を順にクリック。右クリックか Enter で終わり。") + "  Esc で中止。")

    def _syncTools(self):
        if not self.logic._placing():
            for b in self.toolBtns.values(): b.checked = False
            if getattr(self.logic, "_activeMeasure", None) is not None: qt.QTimer.singleShot(0, self.logic.finishMeasure)

    def _measAt(self, r):
        rows = getattr(self, "_measRows", [])
        return rows[r]["node"] if 0 <= r < len(rows) else None

    def onMeasDel(self):
        for r in sorted({i.row() for i in self.measTable.selectedIndexes()}, reverse=True):
            n = self._measAt(r)
            if n is not None: self.logic.deleteMeasure(n)

    def onUndo(self):
        self._say(self.logic.undoLast())

    def onKey(self, cmd):
        if cmd == "tvplan":
            self.tvRange.blockSignals(True); self.tvRange.checked = False; self.tvRange.blockSignals(False)
            self._busy(self.logic.planDraw); self._tvRefresh(); pl = self.logic.plan
            self._say(f"グラフト: {self._tvRef(pl['p'])} → {self._tvRef(pl['d'])}（{pl['d'] - pl['p']:.0f} mm）。白い線をつかむと端だけ動かせます。"); return
        if cmd == "editdone":
            if self.editButton.checked: self.editButton.checked = False
            return
        if cmd == "fixapply": self._busy(self.logic.applyFixes, self._say); return
        if cmd == "fixexit": self.fixButton.checked = False; return
        if cmd == "enter": self.onPlace()
        elif cmd == "pin": self.onPin()
        elif cmd == "mode": self._mode("lumen" if self.logic.mode == "outer" else "outer")
        elif cmd == "undo": self.onUndo()
        elif cmd == "esc":
            self.logic.cancelMeasure()
            for b in self.toolBtns.values(): b.checked = False

    # ---------------------------------------------------------------- マーカー
    def onDelMark(self):
        for r in sorted({i.row() for i in self.markTable.selectedIndexes()}, reverse=True): self.logic.removeMarker(r)

    def onMeasure(self):
        rows = sorted({i.row() for i in self.markTable.selectedIndexes()})
        if len(rows) != 2: self._say("マーカー表で 2 つ選んでください（Ctrl＋クリック）。"); return
        self._showText(self.logic.between(rows[0], rows[1]))

    def _showText(self, txt):
        import html
        self.resultBox.setHtml("<div style='font-family:Consolas,\"Yu Gothic UI\"; font-size:12px; color:#e6e8ec; white-space:pre-wrap'>" + html.escape(txt) + "</div>")

    # ---------------------------------------------------------------- 一覧（変更があった時だけ）
    def refreshLists(self):
        L = self.logic; import html
        if self.stack.currentIndex == 2:
            try: self._tvRefresh()
            except Exception as e: print("tv refresh:", e)
        # テンプレートの手順
        st = self._steps(); self.stepList.clear()
        for i, nm in enumerate(st):
            m = L._mk(nm)
            if m is None: ic, col, val = "○", "#8a909b", ""
            elif m.get("auto"): ic, col, val = "◐", "#ffb547", f"{L.rel(m['s']):+.1f} mm  推定・確認して Enter"
            else:
                o = L._dia(m["s"], m["path"]) if m["path"] in L.frames else None
                ic, col, val = "✓", "#4ade80", f"{L.rel(m['s']):+.1f} mm" + (f"   Ø {o['dmax']:.1f}/{o['dmin']:.1f}" if o else "")
            it = qt.QListWidgetItem(f"{ic}  {i + 1}. {nm}" + (f"      {val}" if val else ""))
            it.setForeground(qt.QBrush(qt.QColor("#ffffff" if i == self._step else col)))
            if i == self._step: it.setBackground(qt.QBrush(qt.QColor("#1f4d69")))
            self.stepList.addItem(it)
        if st:
            nm = st[self._step]; side = {"大動脈→右腸骨": "（右の経路）", "大動脈→左腸骨": "（左の経路）"}.get(L.stepPath(nm), "")
            self.nextLabel.setText(f"{self._step + 1}/{len(st)}   {nm}{side}")
            m = L._mk(nm)
            self.nextHint.setText("自動で推定した位置に合わせました。断面とストレッチ像で確かめて Enter。" if (m and m.get("auto")) else
                                  ("置き済み。位置を変えるなら合わせて Enter（上書き）。" if m else "ストレッチ像のクリックか断面のホイールで位置を合わせて Enter。"))
            self.placeBtn.setText("ここに置く  ⏎")
        else:
            self.nextLabel.setText("自由: 好きな位置にマーカーを置く"); self.nextHint.setText("位置を合わせて Enter（番号付きで残ります）。"); self.placeBtn.setText("マーカーを置く  ⏎")
        for b in (self.skipBtn, self.prevBtn, self.unplaceBtn): b.enabled = bool(st)
        # 手動計測
        self._measRows = L.measureRows(); t = self.measTable; t.setRowCount(len(self._measRows))
        for r, row in enumerate(self._measRows):
            for c, val in enumerate((row["name"], row["value"], row["where"], row["pos"])): t.setItem(r, c, qt.QTableWidgetItem(val))
        t.resizeColumnsToContents()
        # マーカー
        t = self.markTable; rows = L._markerRows() if L.P is not None else []; t.setRowCount(len(rows))
        for r, row in enumerate(rows):
            m = row["m"]; f = lambda q, k: f"{q[k]:.1f}" if q else ""
            vals = [m["name"] + (f"  {m['clock']}" if m.get("clock") else "") + ("  ?" if m.get("auto") else ""), row["side"], f"{L.rel(m['s']):+.1f}",
                    f(row["o"], "dmax"), f(row["o"], "dmin"), f(row["o"], "deq"), f(row["l"], "deq")]
            for c, val in enumerate(vals):
                it = qt.QTableWidgetItem(val)
                if m.get("auto"): it.setForeground(qt.QBrush(qt.QColor("#ffb547")))
                t.setItem(r, c, it)
        t.resizeColumnsToContents()
        # 結果（テンプレートのまとめ）
        if L.P is not None and self._tpl() != "自由":
            try:
                txt = L.summary(self._tpl()); out = []
                for line in txt.splitlines()[1:]:
                    if line.startswith("[全マーカー]"): break
                    if not line.strip(): continue
                    e = html.escape(line)
                    if line.startswith("["):
                        k = e.index("]") + 1; out.append(f"<div style='margin-top:4px'><b style='color:#59d0ff'>{e[:k]}</b>{e[k:]}</div>")
                    elif line.startswith("※"): out.append(f"<div style='color:#ffb547'>{e}</div>")
                    else: out.append(f"<div style='color:#c9ced6; margin-left:10px'>{e.strip()}</div>")
                self.resultBox.setHtml("<div style='font-size:12px; color:#e6e8ec'>" + ("".join(out) or "<span style='color:#8a909b'>マーカーを置くと、ここに径・長さ・角度がまとまります。</span>") + "</div>")
            except Exception: _err("summary")
        self.refreshReadout(); self._syncPathButtons()

    # ---------------------------------------------------------------- 3 出力
    def _done(self, d, what):
        self._lastDir = d; self.openBtn.enabled = True
        self.outLabel.setText(f"{what}: {d}"); self._say(f"{what}を保存しました。")

    def onPDF(self):
        L = self.logic
        if L.P is None: self._say("先に中心線を作ってください。"); return
        keep = (L.curS, L.rot)
        pdf = self._busy(lambda: L.sizingSheet(self._tpl() if self._tpl() != "自由" else "EVAR", self._say))
        L.setRotation(keep[1]); L.setPosition(keep[0])
        if pdf:
            self._done(os.path.dirname(pdf), "サイジングシート")
            qt.QDesktopServices.openUrl(qt.QUrl.fromLocalFile(pdf))

    def onPNG(self):
        L = self.logic
        if L.P is None: return
        r = self._busy(lambda: L.exportImages(None, self._say))
        if r: self._done(r[0], f"画像 {len(r[1])} 枚")

    def onSecPNG(self):
        L = self.logic
        if L.P is None: return
        def run():
            d = L.outDir(); q, _ = L.renderSection(title="断面"); fn = os.path.join(d, f"section_{L.rel(L.curS):+.0f}mm.png"); q.save(fn); return d
        d = self._busy(run)
        if d: self._done(d, "断面の画像")



MARK_EN = {"最下位腎動脈": "Low renal", "ネック終端（瘤の始まり）": "Neck end", "瘤の最大径": "Max sac", "大動脈分岐": "Bifurc",
           "右内腸骨起始": "R IIA", "左内腸骨起始": "L IIA", "右遠位（総大腿）": "R CFA", "左遠位（総大腿）": "L CFA",
           "腕頭動脈": "BCA", "左総頸動脈": "LCCA", "左鎖骨下動脈": "LSCA", "近位ランディング": "Prox LZ",
           "瘤 / エントリー": "Entry", "遠位ランディング": "Dist LZ", "腹腔動脈": "Celiac"}
NPOLY = 96          # 輪郭の内部表現の点数


def _resample(xy, n=NPOLY):
    xy = np.asarray(xy, float)
    if len(xy) > 2 and np.linalg.norm(xy[0] - xy[-1]) < 1e-6: xy = xy[:-1]
    c = np.vstack([xy, xy[:1]])
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(c, axis=0), axis=1))]
    if d[-1] <= 0: return None
    t = np.linspace(0, d[-1], n, endpoint=False)
    out = np.c_[np.interp(t, d, c[:, 0]), np.interp(t, d, c[:, 1])]
    a = 0.5 * (np.dot(out[:, 0], np.roll(out[:, 1], -1)) - np.dot(out[:, 1], np.roll(out[:, 0], -1)))
    return out if a >= 0 else out[::-1]


def _inside(xy, p=(0.0, 0.0)):
    x, y = xy[:, 0], xy[:, 1]; x2, y2 = np.roll(x, -1), np.roll(y, -1)
    c = ((y > p[1]) != (y2 > p[1])) & (p[0] < (x2 - x) * (p[1] - y) / (y2 - y + 1e-12) + x)
    return bool(c.sum() % 2)


def _rasterPoly(xy, nu):
    """断面の輪郭 (u, v) mm → 伸ばした画像の格子（行 = N, 列 = B, 0.5 mm）の塗りつぶし"""
    px = np.c_[(xy[:, 0] + HALF) / STEP, (xy[:, 1] + HALF) / STEP]
    A = px; Bq = np.roll(px, -1, 0); m = np.zeros((nu, nu), bool); cols = np.arange(nu)
    for r in range(nu):
        c = (A[:, 1] <= r) != (Bq[:, 1] <= r)
        if not c.any(): continue
        x = np.sort(A[c, 0] + (r - A[c, 1]) * (Bq[c, 0] - A[c, 0]) / (Bq[c, 1] - A[c, 1]))
        for i in range(0, len(x) - 1, 2): m[r, (cols >= x[i]) & (cols <= x[i + 1])] = True
    return m


def _radAt(Rth, rows, ang):
    """半径の輪 Rth[row, 72]（角度 = B 軸から N 軸へ）を、角度 ang で読む（線形補間）"""
    n = Rth.shape[1]; f = (np.mod(ang, 2 * np.pi) / (2 * np.pi)) * n; i0 = np.floor(f).astype(int) % n; i1 = (i0 + 1) % n; w = f - np.floor(f)
    return Rth[rows, i0] * (1 - w) + Rth[rows, i1] * w


def _polyMetrics(xy):
    xy = np.asarray(xy, float)
    if xy is None or len(xy) < 3 or np.isnan(xy).any(): return None
    x, y = xy[:, 0], xy[:, 1]
    area = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    D = np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(-1)); i, j = np.unravel_index(np.argmax(D), D.shape)
    ang = np.deg2rad(np.arange(0, 180, 1.0)); dirs = np.c_[np.cos(ang), np.sin(ang)]
    proj = xy @ dirs.T; w = proj.max(0) - proj.min(0); a = int(np.argmin(w))
    dvec = dirs[a]; cen = xy.mean(0)
    pmin = cen + dvec * (proj[:, a].min() - cen @ dvec); pmax = cen + dvec * (proj[:, a].max() - cen @ dvec)
    return dict(area=float(area), deq=2 * math.sqrt(area / math.pi), dmax=float(D[i, j]), dmin=float(w[a]),
                maxLine=(xy[i], xy[j]), minLine=(pmin, pmax), centroid=cen)


def _angle(a, b):
    a = a / (np.linalg.norm(a) + 1e-12); b = b / (np.linalg.norm(b) + 1e-12)
    return math.degrees(math.acos(float(np.clip(a @ b, -1, 1))))


class _Overlay:
    """断面の画面に直接描く軽い線と文字（マーカー部品より 100 倍速い。スクロールが滑らか）"""
    def __init__(self, sliceName):
        w = slicer.app.layoutManager().sliceWidget(sliceName)
        self.sv = w.sliceView(); self.sn = w.mrmlSliceNode()
        self.ren = self.sv.renderWindow().GetRenderers().GetFirstRenderer()
        self.pd = vtk.vtkPolyData(); self.mapper = vtk.vtkPolyDataMapper2D(); self.mapper.SetInputData(self.pd)
        self.mapper.SetScalarModeToUseCellData(); self.mapper.SetColorModeToDirectScalars()
        self.actor = vtk.vtkActor2D(); self.actor.SetMapper(self.mapper); self.actor.GetProperty().SetLineWidth(2.0)
        self.ren.AddActor2D(self.actor)
        self.texts = []; self.lines = []; self.labels = []
        self._tag = self.sn.AddObserver(vtk.vtkCommand.ModifiedEvent, lambda c, e: self._project())
        reg = getattr(slicer, "_saOverlays", None)                      # 1 つのビューに 1 つだけ（作り直し・再読み込みで古いものが残らない）
        if reg is None: reg = slicer._saOverlays = {}
        old = reg.get(sliceName)
        if old is not None and old is not self: old.remove()
        reg[sliceName] = self

    def remove(self):
        try: self.sn.RemoveObserver(self._tag)
        except Exception: pass
        try:
            self.ren.RemoveActor2D(self.actor)
            for t in self.texts: self.ren.RemoveActor2D(t)
            self.texts = []
        except Exception: pass

    def set(self, lines, labels=()):
        """lines: [(ras Nx3, (r,g,b), closed)], labels: [(ras 3, text, (r,g,b), size)]"""
        self.lines = list(lines); self.labels = list(labels); self._project()

    def _xy(self, ras):
        M = vtk.vtkMatrix4x4(); M.DeepCopy(self.sn.GetXYToRAS()); M.Invert()
        A = np.array([[M.GetElement(r, c) for c in range(4)] for r in range(4)])
        ras = np.atleast_2d(np.asarray(ras, float))
        return (np.c_[ras, np.ones(len(ras))] @ A.T)[:, :2]

    def _project(self):
        pts = vtk.vtkPoints(); cells = vtk.vtkCellArray(); cols = vtk.vtkUnsignedCharArray(); cols.SetNumberOfComponents(3)
        n = 0
        for ras, col, closed in self.lines:
            xy = self._xy(ras)
            if len(xy) < 2: continue
            ids = list(range(n, n + len(xy))) + ([n] if closed else [])
            for x, y in xy: pts.InsertNextPoint(float(x), float(y), 0.0)
            cells.InsertNextCell(len(ids))
            for i in ids: cells.InsertCellPoint(i)
            cols.InsertNextTuple3(*[int(255 * c) for c in col]); n += len(xy)
        self.pd.SetPoints(pts); self.pd.SetLines(cells); self.pd.GetCellData().SetScalars(cols); self.pd.Modified()
        while len(self.texts) < len(self.labels):
            t = vtk.vtkTextActor(); tp = t.GetTextProperty(); tp.SetFontFamilyToArial(); tp.BoldOn(); tp.ShadowOn()
            self.ren.AddActor2D(t); self.texts.append(t)
        for i, t in enumerate(self.texts):
            if i < len(self.labels):
                ras, txt, col, size = self.labels[i]; x, y = self._xy(ras)[0]
                t.SetInput(txt); t.GetTextProperty().SetColor(*col); t.GetTextProperty().SetFontSize(int(size))
                t.SetDisplayPosition(int(x) + 6, int(y) + 4); t.SetVisibility(True)
            else: t.SetVisibility(False)
        self.sv.scheduleRender()


# ============================================================================ logic
class AortaSizingLogic(ScriptedLoadableModuleLogic):
    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        self.vol = self.seg = None
        self.curves = {}; self.paths = {}
        self.path = None; self.curS = 0.0; self.length = 0.0
        self.P = self.T = self.N = self.B = self.s = None
        self.mode = "outer"; self.rot = 0.0
        self.surf = {}; self._cutters = {}; self.cache = {}; self.override = {}
        self.markers = []; self.baseXYZ = None
        self.straight = None; self.arr = None; self.prof = None
        self.onChanged = lambda: None; self.onPath = lambda: None
        self._iTags = []; self._busyEdit = False; self._clockCb = None; self._drag = False
        self._pending = None; self._pendingRot = None; self._saved = None; self._editing = False
        self._timer = qt.QTimer(); self._timer.setSingleShot(True); self._timer.setInterval(20)
        self._timer.connect("timeout()", self._flush)
        self.contNode = self.dLines = self.posNode = self.cursorNode = self.markG = self.mark3 = None
        self.chart = None; self.extMask = None; self.thr = 180.0

    # ---------------------------------------------------------------- 入力
    def _inputs(self):
        vol = seg = None
        try:
            cv = slicer.modules.cardiacview.widgetRepresentation().self().logic
            vol = getattr(cv, "sourceVolume", None)
            if vol is not None: seg = cv._segFor(vol, "total")
        except Exception: pass
        if seg is None:
            best = None                                   # 腸骨動脈まで入っている全身ラベルを優先（心臓だけの症例と取り違えない）
            for n in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
                sg = n.GetSegmentation()
                names = [_norm(sg.GetNthSegment(i).GetName()) for i in range(sg.GetNumberOfSegments())]
                r = n.GetNodeReference("referenceImageGeometryRef")
                if "aorta" not in names or len(names) <= 20 or r is None or not r.IsA("vtkMRMLScalarVolumeNode"): continue
                score = 10 * sum(any(_match(x, k) for x in names) for k in ("iliac artery right", "iliac artery left")) + len(names) / 1000
                if best is None or score > best[0]: best = (score, n, r)
            if best is not None: seg, vol = best[1], best[2]
        if vol is None or seg is None:
            raise RuntimeError("CT と臓器ラベル（TotalSegmentator）が見つかりません。先に入口で「3D を作る」を行ってください。")
        self.vol, self.seg = vol, seg
        try:
            cv = slicer.modules.cardiacview.widgetRepresentation().self().logic; self.thr = float(cv._cal().get("blood_lo", 180.0))
        except Exception: self.thr = 180.0
        return vol, seg

    def _mask(self, keys, exact=False):
        sg = self.seg.GetSegmentation(); out = None
        for i in range(sg.GetNumberOfSegments()):
            sid = sg.GetNthSegmentID(i); nm = _norm(sg.GetSegment(sid).GetName())
            if any(_match(nm, k, exact) for k in keys):
                a = slicer.util.arrayFromSegmentBinaryLabelmap(self.seg, sid, self.vol) > 0
                out = a if out is None else (out | a)
        return out

    def _ijk2ras(self):
        m = vtk.vtkMatrix4x4(); self.vol.GetIJKToRASMatrix(m)
        return np.array([[m.GetElement(r, c) for c in range(4)] for r in range(4)])

    def _pts(self, mask):
        idx = np.argwhere(mask); A = self._ijk2ras()
        return (np.c_[idx[:, 2], idx[:, 1], idx[:, 0], np.ones(len(idx))] @ A.T)[:, :3]

    # ---------------------------------------------------------------- ① 血管と中心線
    def autoCenterline(self, status=print):
        from scipy import ndimage
        vol, seg = self._inputs()
        _ensureVMTK(status)
        status("1/4 大動脈・腸骨動脈の形を準備中…")
        aorta = self._mask(("aorta",), exact=True)
        if aorta is None or aorta.sum() < 500: raise RuntimeError("大動脈のラベルがありません")
        zz = self._pts(aorta)[:, 2]
        dims = vol.GetImageData().GetDimensions(); fov = min(dims[0] * vol.GetSpacing()[0], dims[1] * vol.GetSpacing()[1])
        if float(zz.max() - zz.min()) < 80 or fov < 220:                      # 心臓だけの撮影（FOV が小さい）では大動脈が少ししか写っていない
            raise RuntimeError(f"この CT は心臓だけの撮影です（撮影範囲 {fov:.0f} mm・大動脈 {zz.max() - zz.min():.0f} mm 分）。"
                               "大動脈サイジングは、胸部〜腹部まで撮った造影 CT で使ってください。")
        ilR = self._mask(("iliac artery right",)); ilL = self._mask(("iliac artery left",))
        status("1/4 鼠径部まで血管をたどっています…")
        ext = {}
        for name, m, fem in (("右腸骨", ilR, ("femur right",)), ("左腸骨", ilL, ("femur left",))):
            if m is None or m.sum() < 200: continue
            e = self._extendToGroin(m, self._mask(fem))
            if e is not None: ext[name] = e
        vessel = aorta.copy()
        for m in (ilR, ilL):
            if m is not None: vessel |= m
        for e in ext.values(): vessel |= e
        self.extMask = None
        for e in ext.values(): self.extMask = e if self.extMask is None else (self.extMask | e)
        # 0.6 mm 等方の表面。5mm 厚でコインを積んだようにならないよう、符号付き距離（mm 単位）で滑らかに作る
        sp = np.array(vol.GetSpacing())[::-1]                                 # (z, y, x) mm
        ISO = 1.0
        f = sp / ISO
        vessel = ndimage.binary_closing(vessel, iterations=2)                 # 延長部のつなぎ目をふさぐ
        vessel = self._bridge(vessel, np.array(vol.GetSpacing())[::-1], status)  # ラベルの途切れ（5mm 厚で多い）を橋渡し
        ix = np.argwhere(vessel); lo = np.maximum(ix.min(0) - 4, 0); hi = np.minimum(ix.max(0) + 5, vessel.shape)
        crop = tuple(slice(int(a), int(b)) for a, b in zip(lo, hi))           # 血管の周りだけで計算（速さ）
        A0 = self._ijk2ras(); A = A0.copy()
        A[:3, 3] = (A0 @ np.r_[lo[2], lo[1], lo[0], 1.0])[:3]
        A[:3, :3] = A0[:3, :3] * (ISO / sp[::-1])
        iso = self._smoothIso(vessel[crop], sp, f)
        lab, n = ndimage.label(iso)
        if n > 1:
            sizes = ndimage.sum(iso, lab, range(1, n + 1)); iso = lab == (1 + int(np.argmax(sizes)))
        self.surf = {"outer": self._surface(iso, A)}
        status("1/4 内腔（造影部分）の表面を作成中…")
        hu = slicer.util.arrayFromVolume(vol)
        lum = vessel & (hu >= self.thr)
        lum = ndimage.binary_opening(lum, iterations=1)
        for k in range(lum.shape[0]): lum[k] = ndimage.binary_fill_holes(lum[k])
        liso = self._smoothIso(lum[crop], sp, f) & iso
        self.surf["lumen"] = self._surface(liso, A) if liso.sum() > 100 else self.surf["outer"]
        self._cutters = {}; self.cache = {}; self.override = {}
        self._models()
        import ExtractCenterline
        ecl = ExtractCenterline.ExtractCenterlineLogic()
        status("2/4 中心線を計算中（VMTK）…")
        pre = ecl.preprocess(self.surf["outer"], 15000, 4.0, False)
        apts = self._pts(aorta); ref = None
        try:
            cv = slicer.modules.cardiacview.widgetRepresentation().self().logic
            hc = cv._segFor(vol, "heartchambers")
            if hc is not None:
                lv = cv._segmentMaskArray(hc, vol, ("left ventricle",))
                if lv is not None and lv.sum() > 100: ref = self._pts(lv).mean(0)
        except Exception: pass
        if ref is None:
            heart = self._mask(("heart",), exact=True)
            ref = self._pts(heart).mean(0) if heart is not None and heart.sum() > 100 else apts[np.argmax(apts[:, 2])]
        d = np.linalg.norm(apts - ref, axis=1); p0 = apts[np.argmin(d)]
        root = apts[np.linalg.norm(apts - p0, axis=1) < 10].mean(0)
        ends = {}
        for name, m in (("右腸骨", ilR), ("左腸骨", ilL)):
            if m is not None and m.sum() > 200:
                mm = (m | ext[name]) if name in ext else m
                pts = self._pts(mm); zmin = pts[:, 2].min(); ends[name] = pts[pts[:, 2] < zmin + 6].mean(0)
        if not ends:
            zmin = apts[:, 2].min(); ends["大動脈"] = apts[apts[:, 2] < zmin + 6].mean(0)
        from vtk.util.numpy_support import vtk_to_numpy as _v2n
        from scipy.spatial import cKDTree as _KD
        sp_surf = _v2n(pre.GetPoints().GetData()); stree = _KD(sp_surf)
        def snap(p):
            d, i = stree.query(p); return sp_surf[i], float(d)
        root, _ = snap(root)
        good = {}
        for k, p in ends.items():
            q, d = snap(p)
            if d > 25:                                    # 表面から大きく外れた端点は信用しない（延長失敗）
                lab = ilR if "右" in k else (ilL if "左" in k else None)
                base = self._pts(lab) if lab is not None and lab.any() else apts         # 腸骨が無い時は大動脈ラベルの下端
                status(f"注意: {k} の端点が血管表面から {d:.0f} mm 離れていたため、{'腸骨' if lab is not None else '大動脈'}ラベルの下端を使います")
                near = sp_surf[_KD(base).query(sp_surf)[0] < 8.0]               # その側の腸骨ラベルに沿った表面だけ
                if len(near): q = near[np.argmin(near[:, 2])]                 # その中で一番下 = 取れている範囲の末端
                else: q, _ = snap(base[base[:, 2] < base[:, 2].min() + 6].mean(0))
            good[k] = q
        ends = good
        ep = slicer.mrmlScene.GetFirstNodeByName("SA 端点") or slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "SA 端点")
        ep.RemoveAllControlPoints(); ep.GetDisplayNode().SetVisibility(False)
        ep.AddControlPoint(vtk.vtkVector3d(*root))
        for k, p in ends.items(): ep.AddControlPoint(vtk.vtkVector3d(*p))
        cl, _vor = ecl.extractCenterline(pre, ep, 1.0)
        status("3/4 経路を整理中…")
        lines = self._lines(cl)
        self._dbg = dict(pre=pre, ep=ep, root=root, ends=dict(ends), lines=[(l[0], l[-1], len(l)) for l in lines])
        if not lines: raise RuntimeError("中心線を作れませんでした（ラベルが途切れている可能性）")
        paths = {}; used = []
        for k, p in ends.items():
            scored = sorted(lines, key=lambda L: min(np.linalg.norm(L[0] - p), np.linalg.norm(L[-1] - p)))
            best = None
            for cand in scored:
                dend = min(np.linalg.norm(cand[0] - p), np.linalg.norm(cand[-1] - p))
                if dend > 30: break
                if any(cand is u for u in used): continue
                best = cand; break
            if best is None:
                status(f"注意: {k} 側の中心線が端点まで届きませんでした。中心線を手で追加してください。"); continue
            used.append(best)
            if np.linalg.norm(best[0] - root) > np.linalg.norm(best[-1] - root): best = best[::-1]
            name = "大動脈→" + k if k != "大動脈" else "大動脈"
            # 同じ線が二度選ばれたら（分岐が片方しか取れていない）重複を避ける
            dup = any(len(b) == len(best) and np.allclose(b, best) for b in paths.values())
            if dup and len(paths) >= 1:
                status(f"注意: {k} 側の中心線を分離できませんでした（分岐がうまく取れていません）。3D で確認してください。")
                continue
            paths[name] = best
        for n in list(slicer.util.getNodesByClass("vtkMRMLMarkupsCurveNode")):
            if n.GetName().startswith("SA 中心線"): slicer.mrmlScene.RemoveNode(n)
        self.curves = {}; self.frames = {}; self._built = {}; self.markers = []; self.baseS = None
        for name, pts in paths.items():
            c = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsCurveNode", f"SA 中心線 {name}")
            s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
            for t in np.arange(0, s[-1], 10.0).tolist() + [s[-1]]:
                q = np.array([np.interp(t, s, pts[:, i]) for i in range(3)]); c.AddControlPoint(vtk.vtkVector3d(*q))
            col = PATH_COLORS.get(name, (1.0, 0.85, 0.2))
            d = c.GetDisplayNode(); d.SetSelectedColor(*col); d.SetColor(*col); d.SetActiveColor(*col)
            d.SetGlyphScale(1.6); d.SetLineThickness(0.4); d.SetPointLabelsVisibility(False); d.SetVisibility(False)
            try: d.SetOccludedVisibility(True); d.SetOccludedOpacity(0.55)          # 血管の中の中心線も透けて見える
            except Exception: pass
            try: d.SetPropertiesLabelVisibility(False)
            except Exception: pass
            c.SetCurveTypeToCardinalSpline(); c.SetLocked(True)
            self.curves[name] = c
        status("4/4 中心線ができました（経路 {} 本）".format(len(paths)))
        self._autoMarkers = True
        return list(paths.keys())

    def _bridge(self, mask, sp, status=print, maxGap=25.0, r=2.5):
        """離れたラベルの破片を、一番近い点どうしを細い円柱でつないで本体に合流させる"""
        from scipy import ndimage
        from scipy.spatial import cKDTree
        lab, n = ndimage.label(mask)
        if n <= 1: return mask
        sizes = ndimage.sum(mask, lab, range(1, n + 1)); main = 1 + int(np.argmax(sizes))
        out = mask.copy(); joined = 0
        def border(m):
            b = m & ~ndimage.binary_erosion(m)
            return np.argwhere(b)
        body = border(lab == main) * sp
        for c in np.argsort(-sizes):
            c = int(c) + 1
            if c == main or sizes[c - 1] < 30: continue
            pc = border(lab == c) * sp
            if len(pc) == 0: continue
            d, i = cKDTree(body).query(pc)
            j = int(np.argmin(d))
            if d[j] > maxGap: continue
            a, b = pc[j], body[i[j]]
            nstep = int(np.ceil(np.linalg.norm(b - a) / 0.3)) + 1
            ball = np.ceil(r / sp).astype(int)
            for t in np.linspace(0, 1, nstep):
                q = np.round((a + (b - a) * t) / sp).astype(int)
                lo = np.maximum(q - ball, 0); hi = np.minimum(q + ball + 1, mask.shape)
                zz, yy, xx = np.ogrid[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]]
                ok = ((zz - q[0]) * sp[0]) ** 2 + ((yy - q[1]) * sp[1]) ** 2 + ((xx - q[2]) * sp[2]) ** 2 <= r * r
                out[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]] |= ok
            body = np.vstack([body, pc]); joined += 1
        if joined: status(f"1/4 途切れていた血管ラベル {joined} か所をつなぎました")
        return out

    def _extendToGroin(self, iliac, femur, maxLen=120.0):
        """腸骨ラベルの下端から、造影された血管を下へたどる（総大腿動脈まで）"""
        from scipy import ndimage
        arr = slicer.util.arrayFromVolume(self.vol); thr = self.thr
        A = self._ijk2ras(); sp = np.array(self.vol.GetSpacing())
        pts = self._pts(iliac); zmin = pts[:, 2].min(); end = pts[pts[:, 2] < zmin + 6].mean(0)
        zstop = zmin - maxLen
        if femur is not None and femur.sum() > 500:
            fz = self._pts(femur)[:, 2]; zstop = max(zstop, fz.max() - 70.0)
        Ainv = np.linalg.inv(A)
        def ijk(p): return (Ainv @ np.r_[p, 1])[:3]
        c = ijk(end); rad = np.array([30 / sp[0], 30 / sp[1]])
        kz = [ijk(np.r_[end[:2], z])[2] for z in (end[2] + 5, zstop)]
        k0, k1 = int(max(0, min(kz))), int(min(arr.shape[0] - 1, max(kz)))
        if k1 - k0 < 2: return None
        i0, i1 = int(max(0, c[0] - rad[0])), int(min(arr.shape[2] - 1, c[0] + rad[0]))
        j0, j1 = int(max(0, c[1] - rad[1])), int(min(arr.shape[1] - 1, c[1] + rad[1]))
        box = np.zeros(arr.shape, bool); box[k0:k1 + 1, j0:j1 + 1, i0:i1 + 1] = True
        blood = (arr >= thr) & (arr <= 1500) & box
        lab, n = ndimage.label(blood | (iliac & box))
        seeds = np.unique(lab[iliac & box]); seeds = seeds[seeds > 0]
        if len(seeds) == 0: return None
        grown = np.isin(lab, seeds) & ~iliac
        if grown.sum() < 30: return None
        return ndimage.binary_opening(grown, iterations=1) | (grown & ndimage.binary_erosion(grown))

    def _smoothIso(self, mask, sp, f):
        """5mm 厚のマスクを、mm 単位の符号付き距離で等方アップサンプルして滑らかな面にする"""
        from scipy import ndimage
        if mask.sum() < 10: return ndimage.zoom(mask.astype(np.float32), f, order=1) > 0.5
        din = ndimage.distance_transform_edt(mask, sampling=sp).astype(np.float32)
        dout = ndimage.distance_transform_edt(~mask, sampling=sp).astype(np.float32)
        sdf = dout - din                                                      # 内側が負、mm 単位
        sdf = ndimage.gaussian_filter(sdf, sigma=(2.5 / sp[0], 0.6, 0.6))     # z 方向（厚い軸）を強めにならす
        up = ndimage.zoom(sdf, f, order=1)
        return up < 0

    def _surface(self, binary, ijk2ras):
        from vtk.util.numpy_support import numpy_to_vtk
        PAD = 3                                                               # 画像の端で面が開かないよう、周りを 0 で囲む
        binary = np.pad(binary, PAD); ijk2ras = ijk2ras.copy(); ijk2ras[:3, 3] -= ijk2ras[:3, :3] @ np.array([PAD, PAD, PAD], float)
        img = vtk.vtkImageData(); img.SetDimensions(binary.shape[2], binary.shape[1], binary.shape[0])
        img.AllocateScalars(vtk.VTK_FLOAT, 1)
        img.GetPointData().SetScalars(numpy_to_vtk(np.ascontiguousarray(binary.astype(np.float32).ravel()), deep=True))
        gs = vtk.vtkImageGaussianSmooth(); gs.SetInputData(img); gs.SetStandardDeviations(0.6, 0.6, 0.6); gs.Update()
        mc = vtk.vtkFlyingEdges3D(); mc.SetInputConnection(gs.GetOutputPort()); mc.SetValue(0, 0.4987); mc.ComputeNormalsOff(); mc.Update()
        m = vtk.vtkMatrix4x4()
        for r in range(4):
            for c in range(4): m.SetElement(r, c, float(ijk2ras[r, c]))
        tr = vtk.vtkTransform(); tr.SetMatrix(m)
        tp = vtk.vtkTransformPolyDataFilter(); tp.SetInputConnection(mc.GetOutputPort()); tp.SetTransform(tr); tp.Update()
        sm = vtk.vtkWindowedSincPolyDataFilter(); sm.SetInputConnection(tp.GetOutputPort()); sm.SetNumberOfIterations(30); sm.SetPassBand(0.05)
        sm.BoundarySmoothingOff(); sm.FeatureEdgeSmoothingOff(); sm.NonManifoldSmoothingOn(); sm.NormalizeCoordinatesOn()
        cf = vtk.vtkPolyDataConnectivityFilter(); cf.SetInputConnection(sm.GetOutputPort()); cf.SetExtractionModeToLargestRegion()
        cl = vtk.vtkCleanPolyData(); cl.SetInputConnection(cf.GetOutputPort())
        nm = vtk.vtkPolyDataNormals(); nm.SetInputConnection(cl.GetOutputPort()); nm.SplittingOff(); nm.AutoOrientNormalsOn(); nm.Update()
        out = vtk.vtkPolyData(); out.DeepCopy(nm.GetOutput()); out.GetPointData().SetScalars(None); return out

    def _lines(self, pd):
        from vtk.util.numpy_support import vtk_to_numpy
        P = vtk_to_numpy(pd.GetPoints().GetData()).astype(float)
        out = []; ids = vtk.vtkIdList(); lines = pd.GetLines(); lines.InitTraversal()
        while lines.GetNextCell(ids):
            idx = [ids.GetId(i) for i in range(ids.GetNumberOfIds())]
            if len(idx) > 5: out.append(P[idx])
        return out

    def _models(self):
        """3D 用の血管モデル（外周は半透明、内腔は見せない）"""
        for n in list(slicer.util.getNodesByClass("vtkMRMLModelNode")):
            if n.GetName() == "SA 血管": slicer.mrmlScene.RemoveNode(n)
        sm = vtk.vtkWindowedSincPolyDataFilter(); sm.SetInputData(self.surf["outer"])     # 見た目用はもっとなめらかに（計測には使わない）
        sm.SetNumberOfIterations(80); sm.SetPassBand(0.005); sm.NormalizeCoordinatesOn(); sm.NonManifoldSmoothingOn()
        sm.BoundarySmoothingOff(); sm.FeatureEdgeSmoothingOff()
        nm = vtk.vtkPolyDataNormals(); nm.SetInputConnection(sm.GetOutputPort()); nm.SplittingOff(); nm.ConsistencyOn(); nm.AutoOrientNormalsOn(); nm.Update()
        pd = vtk.vtkPolyData(); pd.DeepCopy(nm.GetOutput())
        m = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", "SA 血管"); m.SetAndObservePolyData(pd)
        m.CreateDefaultDisplayNodes(); d = m.GetDisplayNode()
        d.SetColor(0.86, 0.36, 0.33); d.SetOpacity(1.0); d.SetScalarVisibility(False); d.SetVisibility2D(False); d.SetBackfaceCulling(False)
        d.SetInterpolation(1)                                                 # Gouraud（なめらかな陰影）
        d.SetAmbient(0.18); d.SetDiffuse(0.72); d.SetSpecular(0.55); d.SetPower(22); d.SetEdgeVisibility(False)
        d.RemoveAllViewNodeIDs(); d.AddViewNodeID("vtkMRMLViewNode1")
        self.vesselModel = m

    # ---------------------------------------------------------------- フレームと伸ばした画像
    def _frames(self, pts):
        from scipy import ndimage
        s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
        keep = np.r_[True, np.diff(s) > 1e-6]; pts, s = pts[keep], s[keep]
        t = np.arange(0, s[-1], STEP)
        P = np.stack([np.interp(t, s, pts[:, i]) for i in range(3)], 1)
        P = ndimage.gaussian_filter1d(P, sigma=SMOOTH_MM / STEP, axis=0, mode="nearest")
        T = np.gradient(P, axis=0); T /= np.linalg.norm(T, axis=1, keepdims=True) + 1e-12
        up = np.array([0, 1.0, 0])
        if abs(T[0] @ up) > 0.9: up = np.array([0, 0, 1.0])
        n = up - (up @ T[0]) * T[0]; n /= np.linalg.norm(n)
        N = np.zeros_like(P); N[0] = n
        for i in range(len(P) - 1):                                # 回転最小フレーム
            v1 = P[i + 1] - P[i]; c1 = v1 @ v1
            if c1 < 1e-12: N[i + 1] = N[i]; continue
            rL = N[i] - (2 / c1) * (v1 @ N[i]) * v1; tL = T[i] - (2 / c1) * (v1 @ T[i]) * v1
            v2 = T[i + 1] - tL; c2 = v2 @ v2
            N[i + 1] = rL - (2 / c2) * (v2 @ rL) * v2 if c2 > 1e-12 else rL
            N[i + 1] /= np.linalg.norm(N[i + 1])
        B = np.cross(T, N)
        return dict(P=P, T=T, N=N, B=B, s=t, length=float(t[-1]) if len(t) else 0.0)

    def _use(self, name):
        F = self.frames[name]
        self.P, self.T, self.N, self.B, self.s, self.length = F["P"], F["T"], F["N"], F["B"], F["s"], F["length"]

    def _reseat(self, c):
        ts = list(np.arange(0, self.length, 10.0)) + [self.length]
        wasMod = c.StartModify(); c.RemoveAllControlPoints()
        for t in ts:
            k = min(int(round(t / STEP)), len(self.P) - 1); c.AddControlPoint(vtk.vtkVector3d(*self.P[k]))
        c.EndModify(wasMod)

    def _straighten(self, name):
        from scipy import ndimage
        if self.arr is None:
            self.arr = slicer.util.arrayFromVolume(self.vol).astype(np.float32)
            self.arrF = ndimage.spline_filter(self.arr, order=3, mode="nearest")      # 3次スプラインの前処理（1回だけ）
        out = self._straightArr(self.P, self.N, self.B)
        return self._straightNode(name, out)

    def _straightArr(self, PP, NN, BB):
        """中心線のフレーム（P, N, B）に沿って元の CT を切り出し、伸ばした画像の配列（K × nu × nu）を作る"""
        from scipy import ndimage
        A = np.linalg.inv(self._ijk2ras())
        u = np.arange(-HALF, HALF + 1e-6, STEP); nu = len(u)
        UU, VV = np.meshgrid(u, u)
        K = len(PP); out = np.zeros((K, nu, nu), np.int16)
        for k0 in range(0, K, 64):
            k1 = min(K, k0 + 64)
            P = PP[k0:k1, None, None, :]; Nn = NN[k0:k1, None, None, :]; Bb = BB[k0:k1, None, None, :]
            Q = P + UU[None, :, :, None] * Bb + VV[None, :, :, None] * Nn
            H = Q.reshape(-1, 3) @ A[:3, :3].T + A[:3, 3]
            out[k0:k1] = ndimage.map_coordinates(self.arrF, [H[:, 2], H[:, 1], H[:, 0]], order=3, prefilter=False, mode="nearest").reshape(k1 - k0, nu, nu).astype(np.int16)
        return out

    def _straightNode(self, name, out):
        node = slicer.mrmlScene.GetFirstNodeByName("SA stretched " + PATH_EN.get(name, name))
        if node is None: node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "SA stretched " + PATH_EN.get(name, name))
        slicer.util.updateVolumeFromArray(node, out)
        node.SetSpacing(STEP, STEP, STEP); node.SetOrigin(-HALF, -HALF, 0.0)
        m = vtk.vtkMatrix4x4(); m.Identity(); m.SetElement(2, 2, -1.0); node.SetIJKToRASDirectionMatrix(m)
        node.CreateDefaultDisplayNodes(); dn = node.GetDisplayNode(); dn.SetAutoWindowLevel(False); dn.SetWindowLevel(800, 200)
        return node

    def selectPath(self, name, status=print):
        if name not in self.curves: return
        for k, c in self.curves.items(): c.GetDisplayNode().SetLineThickness(0.7 if k == name else 0.3)
        self.rebuild(name, status)
        try: self.onPath()
        except Exception: pass

    def rebuild(self, name, status=print):
        c = self.curves.get(name)
        if c is None: raise RuntimeError("中心線がありません")
        cp = slicer.util.arrayFromMarkupsCurvePoints(c, world=True).astype(float)
        self.path = name
        built = self._built.get(name)
        if built is not None and built["n"] == c.GetNumberOfControlPoints() and np.allclose(built["cp"], slicer.util.arrayFromMarkupsControlPoints(c, world=True)):
            self.frames[name] = built["frames"]; self._use(name); self.straight = built["vol"]
        else:
            status("中心線をならして、伸ばした画像を作成中…")
            self.frames[name] = self._frames(cp); self._use(name); self._reseat(c)
            self.frames[name] = self._frames(slicer.util.arrayFromMarkupsCurvePoints(c, world=True).astype(float)); self._use(name)   # 点を置き直した曲線そのものに合わせる（後の部分修正と一致させる）
            for key in [k for k in self.cache if name in k[:2]]: self.cache.pop(key)
            self.straight = self._straighten(name)
            self._built[name] = dict(n=c.GetNumberOfControlPoints(), cp=slicer.util.arrayFromMarkupsControlPoints(c, world=True), frames=self.frames[name], vol=self.straight)
        self.sharedLen = self._sharedLength()
        status("断面を計算中…")
        self._profile()
        if getattr(self, "_autoMarkers", False):
            self._autoMarkers = False; self._prefillMarkers()
        self.curS = min(self.curS, self.length)
        self.showLayout()
        self.setRotation(0.0)

    def _sharedLength(self):
        others = [k for k in self.curves if k != self.path]
        if not others: return self.length
        o = others[0]
        pts = self.frames[o]["P"] if o in self.frames else slicer.util.arrayFromMarkupsCurvePoints(self.curves[o], world=True)
        from scipy.spatial import cKDTree
        d, _ = cKDTree(pts).query(self.P[::4])
        far = np.where(d > 4.0)[0]
        return float(self.s[far[0] * 4]) if len(far) else self.length

    # ---------------------------------------------------------------- 断面（表面を平面で切る）
    def _cutter(self, mode):
        c = self._cutters.get(mode)
        if c is None:
            pl = vtk.vtkPlane(); cut = vtk.vtkCutter(); cut.SetInputData(self.surf[mode]); cut.SetCutFunction(pl)
            con = vtk.vtkPolyDataConnectivityFilter(); con.SetInputConnection(cut.GetOutputPort()); con.SetExtractionModeToClosestPointRegion()
            st = vtk.vtkStripper(); st.SetInputConnection(con.GetOutputPort()); st.JoinContiguousSegmentsOn()
            c = self._cutters[mode] = (pl, con, st)
        return c

    def _section(self, k, mode=None, path=None):
        """断面の輪郭（2D 座標、mm）。手直しがあればそれ。無ければ AI ラベルの輪郭を目安に、元の CT 上で縁を正確化"""
        mode = mode or self.mode; path = path or self.path
        key = (path, mode, int(k))
        ov = self.override.get(key)
        if ov is not None: return ov
        if key in self.cache: return self.cache[key]
        xy = None
        if getattr(self, "precise", True):
            try:
                gl = self._sectionSurf(k, "lumen", path); go = self._sectionSurf(k, "outer", path)
                both = self._edgeContour(int(k), path, "both", gl, go)
                if both is not None:
                    for md, v in zip(("lumen", "outer"), both):
                        kk = (path, md, int(k))
                        if kk not in self.cache and v is not None: self.cache[kk] = v
                    xy = both[0] if mode == "lumen" else both[1]
            except Exception as e:
                print("edge:", e); xy = None
        if xy is None: xy = self._sectionSurf(k, mode, path)
        self.cache[key] = xy
        return xy

    def _sectionSurf(self, k, mode, path):
        """AI ラベルから作った血管表面を、中心線に直交する面で切った輪郭（目安）"""
        key = ("surf", path, mode, int(k))
        if key in self.cache: return self.cache[key]
        F = self.frames[path]; P, T, N, B = F["P"][k], F["T"][k], F["N"][k], F["B"][k]
        pl, con, st = self._cutter(mode)
        pl.SetOrigin(*P); pl.SetNormal(*T); con.SetClosestPoint(*P)
        cut = con.GetInputAlgorithm(); cut.Update(); xy = None
        if cut.GetOutput().GetNumberOfPoints() == 0:                       # 何も切れない（その面に血管表面が無い）→ VTK の警告を出さない
            self.cache[key] = None; return None
        st.Update(); pd = st.GetOutput()
        if pd.GetNumberOfLines():
            from vtk.util.numpy_support import vtk_to_numpy
            pts = vtk_to_numpy(pd.GetPoints().GetData()); ids = vtk.vtkIdList(); best = None
            lines = pd.GetLines(); lines.InitTraversal()
            while lines.GetNextCell(ids):
                idx = [ids.GetId(i) for i in range(ids.GetNumberOfIds())]
                if best is None or len(idx) > len(best): best = idx
            q = pts[best] - P
            xy = _resample(np.c_[q @ B, q @ N])
            if xy is not None and (np.hypot(*xy.mean(0)) > 25 or _polyMetrics(xy)["dmax"] > 2 * HALF): xy = None
        self.cache[key] = xy
        return xy

    # ---------------------------------------------------------------- 正確な輪郭: 元の CT 上で、中心から放射状に「濃さが一番急に変わる所」を探す（サブピクセル）
    NRAY = 120
    RAY_DR = 0.15

    def _ensureArrF(self):
        if getattr(self, "arrF", None) is None:
            from scipy import ndimage
            self.arr = slicer.util.arrayFromVolume(self.vol).astype(np.float32)
            self.arrF = ndimage.spline_filter(self.arr, order=3, mode="nearest")
        if getattr(self, "_rasToIjk", None) is None: self._rasToIjk = np.linalg.inv(self._ijk2ras())

    @staticmethod
    def _polar(xy, c, th):
        q = xy - c; a = np.arctan2(q[:, 1], q[:, 0]); r = np.hypot(q[:, 0], q[:, 1])
        o = np.argsort(a); a, r = a[o], r[o]
        return np.interp(th, a, r, period=2 * np.pi)

    def _rays(self, P, B, N, c, th, R):
        from scipy import ndimage
        d = np.c_[np.cos(th), np.sin(th)]                                   # 断面内の向き
        X = c[None, None, :] + R[None, :, None] * d[:, None, :]              # (ray, r, 2)
        W = P + X[..., :1] * B + X[..., 1:] * N                              # 世界座標
        A = self._rasToIjk; H = W.reshape(-1, 3) @ A[:3, :3].T + A[:3, 3]
        prof = ndimage.map_coordinates(self.arrF, [H[:, 2], H[:, 1], H[:, 0]], order=3, prefilter=False, mode="nearest").reshape(len(th), len(R))
        return ndimage.gaussian_filter(prof, (0.8, 1.0)), d

    def _cleanRadii(self, r, ref):
        from scipy import ndimage
        med = ndimage.median_filter(r, size=9, mode="wrap")
        bad = np.abs(r - med) > np.maximum(1.5, 0.15 * med)
        r = np.where(bad, med, r)
        r = ndimage.gaussian_filter1d(r, 1.2, mode="wrap")
        return np.clip(r, 0.3 * ref.min(), None)

    def _blobGuide(self, P, B, N, c0, rlim):
        """元の CT で、中心線のそばの造影された塊（内腔）を直接さがして目安の円にする（ラベルが細い・ずれている時）"""
        from scipy import ndimage
        h = 0.25; u = np.arange(-rlim, rlim + 1e-6, h); UU, VV = np.meshgrid(u, u)
        W = P + (c0[0] + UU)[..., None] * B + (c0[1] + VV)[..., None] * N
        A = self._rasToIjk; H = W.reshape(-1, 3) @ A[:3, :3].T + A[:3, 3]
        img = ndimage.map_coordinates(self.arrF, [H[:, 2], H[:, 1], H[:, 0]], order=1, prefilter=False, mode="nearest").reshape(UU.shape)
        m = ndimage.binary_opening((img > self.thr) & (img < 1200) & (UU ** 2 + VV ** 2 <= rlim ** 2), iterations=2)
        lab, n = ndimage.label(m)
        if n == 0: return None
        ii = np.argwhere(m); d2 = (UU[m] ** 2 + VV[m] ** 2)
        j = int(np.argmin(d2))
        if d2[j] > 6.0 ** 2: return None                                    # 中心線から 6 mm 以内に造影の塊が無い
        comp = lab == lab[tuple(ii[j])]
        area = comp.sum() * h * h
        cx, cy = UU[comp].mean() + c0[0], VV[comp].mean() + c0[1]
        return np.array([cx, cy]), math.sqrt(area / math.pi), area

    def _edgeContour(self, k, path, mode, gl, go):
        """gl / go: AI ラベル由来の内腔 / 外周の輪郭（目安）。戻り値: 正確化した輪郭 (NPOLY, 2) か None"""
        self._ensureArrF()
        F = self.frames[path]; P, B, N = F["P"][k], F["B"][k], F["N"][k]
        ref = gl if gl is not None else go
        c0 = ref.mean(0) if ref is not None else np.zeros(2)
        rg = math.sqrt(_polyMetrics(ref)["area"] / math.pi) if ref is not None else 0.0
        bl = self._blobGuide(P, B, N, c0, float(min(max(2.5 * rg + 8.0, 14.0), 30.0)))
        if bl is not None:
            cb, rb, ab = bl
            small = rg < 6.0                                                   # 腸骨など細い所はラベルが細く・ずれやすい
            use = gl is None or (small and (ab > 1.6 * math.pi * rg * rg or np.linalg.norm(cb - c0) > max(1.5, 0.4 * rg)))
            if use and (gl is None or ab < 5.0 * math.pi * rg * rg + 60.0):     # ラベルより造影の塊を信じる（大きすぎる塊＝骨などは除く）
                t = np.linspace(-np.pi, np.pi, NPOLY, endpoint=False)
                gl = cb + rb * np.c_[np.cos(t), np.sin(t)]
                if go is None or _polyMetrics(go)["area"] < 1.1 * ab: go = cb + (rb + 1.0) * np.c_[np.cos(t), np.sin(t)]
        if gl is None: return None
        th = np.linspace(-np.pi, np.pi, self.NRAY, endpoint=False)
        c = gl.mean(0)
        rgl = self._polar(gl, c, th); rgo = self._polar(go, c, th) if go is not None else rgl * 1.15
        rmax = float(min(1.5 * max(rgo.max(), rgl.max()) + 6.0, 60.0))
        R = np.arange(0.0, rmax, self.RAY_DR)
        prof, d = self._rays(P, B, N, c, th, R)
        dr = self.RAY_DR; g = np.gradient(prof, dr, axis=1)
        center = prof[:, R < max(1.0, 0.35 * rgl.min())]
        Ilum = float(np.median(center)) if center.size else float(np.median(prof[:, :5]))
        calcT = Ilum + max(150.0, 0.35 * abs(Ilum))
        rl = rgl.copy(); okL = np.zeros(len(th), bool)
        for j in range(len(th)):                                             # 内腔: 半値（内腔とすぐ外の組織の中間）を最初に下回る所
            lo, hi = 0.3 * rgl[j], 1.35 * rgl[j] + 3.0
            w = np.where((R >= lo) & (R <= hi))[0]
            if len(w) < 4: continue
            pj = prof[j, w]
            T0 = 0.5 * (Ilum + 60.0)
            cal = np.where(pj > calcT)[0]; bel = np.where(pj < T0)[0]
            if len(cal) and (not len(bel) or cal[0] < bel[0]):              # 先に石灰化に当たる → 立ち上がりの中点が内腔の縁
                ic = cal[0]; peak = pj[ic:ic + int(2.0 / dr)].max(); half = 0.5 * (Ilum + peak)
                rise = np.where(pj[:ic + 1] >= half)[0]
                if len(rise):
                    i = rise[0]
                    if i > 0: rl[j] = R[w[i - 1]] + (half - pj[i - 1]) / max(pj[i] - pj[i - 1], 1e-6) * dr
                    else: rl[j] = R[w[i]]
                    okL[j] = True
                continue
            if not len(bel): continue
            ri = R[w[bel[0]]]
            outside = prof[j, (R >= ri + 1.0) & (R <= ri + 2.5)]
            Iout = float(min(np.median(outside), 150.0)) if outside.size else 60.0
            if Ilum - Iout < 80.0: continue                                  # コントラストが足りない → 目安のまま
            T = 0.5 * (Ilum + Iout); b2 = np.where(pj < T)[0]
            if not len(b2): continue
            i = b2[0]
            if i > 0: rl[j] = R[w[i - 1]] + (pj[i - 1] - T) / max(pj[i - 1] - pj[i], 1e-6) * dr   # 線形補間でサブピクセル
            else: rl[j] = R[w[i]]
            okL[j] = True
        if okL.mean() < 0.4: return None if mode != "both" else None
        rl = self._cleanRadii(np.where(okL, rl, rgl), rgl)
        lum = _resample(c + rl[:, None] * d)
        if mode == "lumen": return lum
        ro = rgo.copy(); okO = np.zeros(len(th), bool)
        for j in range(len(th)):
            lo, hi = rl[j] + 0.5, max(rgo[j], rl[j] + 1.0) + 2.5               # 目安（ラベル）から 2.5mm 以内だけ探す
            w = np.where((R >= lo) & (R <= hi))[0]
            if len(w) < 4: continue
            gj = g[j, w]; pj = prof[j, w]
            after = np.r_[pj[int(1.0 / dr):], np.full(int(1.0 / dr), pj[-1])][:len(pj)]
            cand = np.where((after < 20.0) & (gj < -30.0))[0]                # 外は脂肪・肺（低い CT 値）へ落ちる所
            if not len(cand): continue
            i = cand[np.argmin(np.abs(R[w[cand]] - rgo[j]) + 0.02 * gj[cand])]  # 目安に近く、変化が急な所
            ro[j] = R[w[i]]; okO[j] = True
        if okO.mean() < 0.4: out = _resample(c + np.maximum(rgo, rl + 0.5)[:, None] * d) if go is not None else None
        else:
            ro = self._cleanRadii(np.where(okO, ro, rgo), rgo)
            out = _resample(c + np.maximum(ro, rl + 0.3)[:, None] * d)
        return (lum, out) if mode == "both" else out

    def _metK(self, k, mode=None, path=None):
        xy = self._section(k, mode, path)
        m = _polyMetrics(xy) if xy is not None else None
        if m is not None:
            m["xy"] = xy; m["edited"] = (path or self.path, mode or self.mode, int(k)) in self.override
        return m

    def _k(self, s=None, path=None):
        F = self.frames[path or self.path]
        return int(min(max(round((self.curS if s is None else s) / STEP), 0), len(F["P"]) - 1))

    def metricsAt(self, s=None, path=None):
        if not self.frames or self.path is None: return None
        path = path or self.path
        if path not in self.frames: return None
        m = self._metK(self._k(s, path), None, path)
        if m is None: return None
        return dict(area=m["area"], deq=m["deq"], dmax=m["dmax"], dmin=m["dmin"], edited=m["edited"])

    def rel(self, s):
        return float(s) - (self.baseS if self.baseS is not None else 0.0)

    def _profile(self, reuse=None):
        K = len(self.s); ks = np.arange(0, K, 4)
        res = np.full((K, 4), np.nan)
        if reuse is not None:                                          # 局所の修正: 変わっていない所は前の値をそのまま使う
            old, a, b, shift = reuse
            res[:a] = old[:a]; res[b + 1:] = old[b + 1 - shift:]
            ks = np.arange(a - a % 4, b + 1, 4)
        for k in ks:
            m = self._metK(int(k))
            if m: res[k] = (m["area"], m["deq"], m["dmax"], m["dmin"])
        for i in range(4):                                             # 2 mm ごとの値を 0.5 mm に補間（グラフ用）
            ok = ~np.isnan(res[:, i])
            if ok.sum() > 1: res[:, i] = np.interp(self.s, self.s[ok], res[ok, i])
        self.prof = res
        tbl = slicer.mrmlScene.GetFirstNodeByName("SA 径の推移") or slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "SA 径の推移")
        from vtk.util.numpy_support import numpy_to_vtk
        vt = vtk.vtkTable()                                                    # 列を消してから足すとグラフが一瞬「列なし」になり警告が出るので、表ごと差し替える
        for name, data in (("s", self.s), ("Max", res[:, 2]), ("Min", res[:, 3]), ("Deq", res[:, 1])):
            a = numpy_to_vtk(np.ascontiguousarray(np.nan_to_num(data[::4], nan=0.0), dtype=np.float32), deep=True); a.SetName(name)
            vt.AddColumn(a)
        tbl.SetAndObserveTable(vt)
        chart = slicer.mrmlScene.GetFirstNodeByName("SA 径グラフ") or slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotChartNode", "SA 径グラフ")
        if chart.GetNumberOfPlotSeriesNodes() == 0:
            for n in list(slicer.util.getNodesByClass("vtkMRMLPlotSeriesNode")):
                if n.GetAttribute("SA"): slicer.mrmlScene.RemoveNode(n)
            for col, rgb in (("Max", (0.85, 0.25, 0.2)), ("Min", (0.2, 0.45, 0.85)), ("Deq", (0.45, 0.45, 0.45))):
                ps = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode", col); ps.SetAttribute("SA", col)
                ps.SetAndObserveTableNodeID(tbl.GetID()); ps.SetXColumnName("s"); ps.SetYColumnName(col)
                ps.SetPlotType(ps.PlotTypeScatter); ps.SetMarkerStyle(ps.MarkerStyleNone); ps.SetLineStyle(ps.LineStyleSolid); ps.SetColor(*rgb); ps.SetLineWidth(2)
                chart.AddAndObservePlotSeriesNodeID(ps.GetID())
            chart.SetXAxisTitle("Distance from origin (mm)"); chart.SetYAxisTitle("Diameter (mm)")
        chart.SetLegendVisibility(False); chart.SetXAxisRangeAuto(False); chart.SetXAxisRange(0.0, max(self.length, 1.0)); chart.SetYAxisRangeAuto(True)
        chart.SetTitle(f"{PATH_EN.get(self.path, '')}  {'outer' if self.mode == 'outer' else 'lumen'}   red=Max  blue=Min  gray=Deq")
        tbl.Modified(); self.chart = chart

    def setMode(self, mode):
        self.mode = mode
        if self.prof is not None: self._profile(); self._showContour()

    def undoContour(self):
        self.override.pop((self.path, self.mode, self._k()), None)
        self._refreshK(self._k())

    def _refreshK(self, k):
        m = self._metK(k)
        if m and self.prof is not None: self.prof[k] = (m["area"], m["deq"], m["dmax"], m["dmin"])
        self._showContour()

    # ---------------------------------------------------------------- 画面
    def _sliceOnly(self, node, ids):
        d = node.GetDisplayNode()
        if d is None: return
        d.RemoveAllViewNodeIDs()
        for i in ids: d.AddViewNodeID(i)

    def _node(self, cls, name, views, color, glyph=1.5, line=0.3, text=0.0, locked=True):
        n = slicer.mrmlScene.GetFirstNodeByName(name)
        if n is None or not n.IsA(cls): n = slicer.mrmlScene.AddNewNodeByClass(cls, name)
        n.SetLocked(locked); d = n.GetDisplayNode()
        d.SetSelectedColor(*color); d.SetColor(*color); d.SetActiveColor(*color); d.SetGlyphScale(glyph); d.SetLineThickness(line)
        d.SetTextScale(text); d.SetPointLabelsVisibility(text > 0)
        try: d.SetPropertiesLabelVisibility(False); d.SetOccludedVisibility(True); d.SetOccludedOpacity(0.6)
        except Exception: pass
        self._sliceOnly(n, views); return n

    def _ensureNodes(self):
        RED, GREEN, YEL, V3 = "vtkMRMLSliceNodeRed", "vtkMRMLSliceNodeGreen", "vtkMRMLSliceNodeYellow", "vtkMRMLViewNode1"
        self.contNode = self._node("vtkMRMLMarkupsClosedCurveNode", "SA 輪郭", (RED,), (1.0, 0.85, 0.2), glyph=1.3, line=0.25, locked=False)
        self.contNode.SetCurveTypeToCardinalSpline()
        if not getattr(self, "_contTag", None):
            self.contNode.RemoveObservers(slicer.vtkMRMLMarkupsNode.PointEndInteractionEvent)
            self._contTag = self.contNode.AddObserver(slicer.vtkMRMLMarkupsNode.PointEndInteractionEvent, self._onContourEdited)
        self.dLines = [self._node("vtkMRMLMarkupsLineNode", "Dmax", (RED,), (0.95, 0.35, 0.3), glyph=0.8, line=0.15, text=2.5),
                       self._node("vtkMRMLMarkupsLineNode", "Dmin", (RED,), (0.3, 0.6, 1.0), glyph=0.8, line=0.15, text=2.5)]
        for ln in self.dLines:
            if ln.GetNumberOfControlPoints() < 2:
                ln.RemoveAllControlPoints(); ln.AddControlPoint(vtk.vtkVector3d(0, 0, 0)); ln.AddControlPoint(vtk.vtkVector3d(0, 0, 0))
        self.cursorNode = self._node("vtkMRMLMarkupsLineNode", "SA cursor", (GREEN,), (1.0, 0.3, 0.25), glyph=1.0, line=0.35)
        if self.cursorNode.GetNumberOfControlPoints() < 2:
            self.cursorNode.RemoveAllControlPoints(); self.cursorNode.AddControlPoint(vtk.vtkVector3d(0, 0, 0)); self.cursorNode.AddControlPoint(vtk.vtkVector3d(0, 0, 0))
        self.posNode = self._node("vtkMRMLMarkupsFiducialNode", "SA 現在位置", (V3, YEL), (1.0, 0.3, 0.2), glyph=4.0)
        if self.posNode.GetNumberOfControlPoints() < 1: self.posNode.AddControlPoint(vtk.vtkVector3d(0, 0, 0)); self.posNode.SetNthControlPointLabel(0, "")
        self.markG = self._node("vtkMRMLMarkupsFiducialNode", "SA markers S", (GREEN,), (0.3, 0.9, 0.9), glyph=1.6, text=2.6)
        self.mark3 = self._node("vtkMRMLMarkupsFiducialNode", "SA markers 3D", (V3,), (0.3, 0.9, 0.9), glyph=2.5, text=3.0)
        self.baseG = self._node("vtkMRMLMarkupsLineNode", "SA baseline", (GREEN,), (0.4, 1.0, 0.4), glyph=1.0, line=0.3, text=2.6)
        if self.baseG.GetNumberOfControlPoints() < 2:
            self.baseG.RemoveAllControlPoints(); self.baseG.AddControlPoint(vtk.vtkVector3d(0, 0, 0)); self.baseG.AddControlPoint(vtk.vtkVector3d(0, 0, 0))
        self.clockNode = self._node("vtkMRMLMarkupsFiducialNode", "SA clock", (RED,), (0.4, 1.0, 0.4), glyph=2.0, text=3.0)

    def showLayout(self):
        if self.straight is None: return
        lm = slicer.app.layoutManager()
        lm.layoutLogic().GetLayoutNode().AddLayoutDescription(LAYOUT_ID, LAYOUT_XML)
        lm.setLayout(LAYOUT_ID)
        self._editing = False
        for nm, volNode in (("Red", self.vol), ("Yellow", self.vol), ("Green", self.straight), ("Orange", self.straight)):
            w = lm.sliceWidget(nm)
            if w is None: continue
            cn = w.sliceLogic().GetSliceCompositeNode(); cn.SetBackgroundVolumeID(volNode.GetID()); cn.SetForegroundVolumeID(None); cn.SetLabelVolumeID(None)
            w.sliceController().setVisible(False)
        dn = self.vol.GetDisplayNode(); dn.SetAutoWindowLevel(False); dn.SetWindowLevel(800, 200)
        for vn in (self.vol, self.straight):
            d = vn.GetDisplayNode()
            if d is not None: d.SetInterpolate(True)
        for nm in ("Red", "Green", "Orange", "Yellow"):                         # 画像を曲線補間でなめらかに（元が5mm厚でもカクつかない）
            try:
                sl = lm.sliceWidget(nm).sliceLogic()
                for layer in (sl.GetBackgroundLayer(), sl.GetForegroundLayer()):
                    r = layer.GetReslice()
                    if r is not None: r.SetInterpolationModeToCubic()
            except Exception: pass
        for m in slicer.util.getNodesByClass("vtkMRMLModelNode"):
            if m.GetName().startswith("CV ") and m.GetDisplayNode() is not None: m.GetDisplayNode().SetVisibility2D(False)
        for d in slicer.util.getNodesByClass("vtkMRMLSegmentationDisplayNode"):
            try: d.SetVisibility2D(False)
            except Exception: pass
        try:
            for dn2 in slicer.util.getNodesByClass("vtkMRMLSliceDisplayNode"): dn2.SetIntersectingSlicesVisibility(False)
        except Exception: pass
        pv = lm.plotWidget(0)
        if pv is not None and self.chart is not None: pv.mrmlPlotViewNode().SetPlotChartNodeID(self.chart.GetID())
        for k, c in self.curves.items():
            c.SetLocked(True); c.GetDisplayNode().SetVisibility(True); self._sliceOnly(c, ("vtkMRMLViewNode1",))
        self._ensureNodes()
        for n in (self.posNode, self.mark3, self.clockNode): n.GetDisplayNode().SetVisibility(True)
        for n in [self.cursorNode, self.markG, self.baseG] + list(self.dLines or []): n.GetDisplayNode().SetVisibility(False)   # 軽い描画（_Overlay）に置き換え
        self.contNode.GetDisplayNode().SetVisibility(bool(getattr(self, "contourEdit", False)))
        for ov in ("ovRed", "ovGreen", "ovOrange"):
            o = getattr(self, ov, None)
            if o is not None: o.remove()
        self.ovRed = _Overlay("Red"); self.ovGreen = _Overlay("Green")
        self.ovOrange = _Overlay("Orange") if lm.sliceWidget("Orange") is not None else None
        self._saveCV()                                                     # 心臓の画面の 3D の状態を覚えてから変える
        rn = lm.sliceWidget("Red").mrmlSliceNode(); rn.SetSliceVisible(True)
        for nm in ("Green", "Orange", "Yellow"):
            if lm.sliceWidget(nm) is not None: lm.sliceWidget(nm).mrmlSliceNode().SetSliceVisible(False)
        self._fit3D(); self._fitViews(); self._watch(); self._drawMarkers()

    def _fitViews(self):
        lm = slicer.app.layoutManager()
        def fit(sn, fy):
            d = sn.GetDimensions(); asp = (d[0] / max(d[1], 1)) if d[1] else 1.0
            sn.SetFieldOfView(fy * asp, fy, 1.0); sn.SetXYZOrigin(0, 0, 0)
        fit(lm.sliceWidget("Green").mrmlSliceNode(), self.length * 1.04 + 10)
        if lm.sliceWidget("Orange") is not None: fit(lm.sliceWidget("Orange").mrmlSliceNode(), self.length * 1.04 + 10)
        fit(lm.sliceWidget("Red").mrmlSliceNode(), 60.0)
        fit(lm.sliceWidget("Yellow").mrmlSliceNode(), 160.0)

    def _fit3D(self):
        try:
            cv = slicer.modules.cardiacview.widgetRepresentation().self().logic
            for name, on in (("心臓壁", False), ("心筋", False), ("軟部組織", False), ("骨", False), ("血液・血管", False)):
                cv.setLayerVisible(name, on)
            cv._clearCuts()
            for k, m in cv.layerModels.items():
                if m is not None and m.GetDisplayNode() is not None: m.GetDisplayNode().SetVisibility(False)
        except Exception: pass
        v3 = slicer.app.layoutManager().threeDWidget(0).threeDView()
        vn = slicer.app.layoutManager().threeDWidget(0).mrmlViewNode()
        try:
            vn.SetBackgroundColor(0.11, 0.13, 0.17); vn.SetBackgroundColor2(0.02, 0.02, 0.03)   # 落ち着いた濃紺のグラデ
            vn.SetBoxVisible(False); vn.SetAxisLabelsVisible(False)
            vn.SetOrientationMarkerType(vn.OrientationMarkerTypeHuman) if hasattr(vn, "OrientationMarkerTypeHuman") else None
        except Exception: pass
        try:
            ren = v3.renderWindow().GetRenderers().GetFirstRenderer()
            ren.SetUseDepthPeeling(True); ren.SetMaximumNumberOfPeels(8); ren.SetOcclusionRatio(0.1)
            ren.SetUseSSAO(True); ren.SetSSAORadius(12.0); ren.SetSSAOBias(0.01); ren.SetSSAOKernelSize(32); ren.SetSSAOBlur(True)
            v3.renderWindow().SetMultiSamples(8)                               # アンチエイリアスで輪郭をなめらかに
            if getattr(self, "_tvMode", False): ren.SetUseDepthPeeling(False); ren.SetUseSSAO(False)   # TEVAR: 半透明（血管・グラフトの布）を描くため
        except Exception: pass
        if self.P is None: return
        allp = np.vstack([slicer.util.arrayFromMarkupsCurvePoints(c, world=True) for c in self.curves.values()])
        lo, hi = allp.min(0), allp.max(0); cen = (lo + hi) / 2; ext = float(np.max(hi - lo))
        cam = slicer.modules.cameras.logic().GetViewActiveCameraNode(slicer.app.layoutManager().threeDWidget(0).mrmlViewNode())
        cam.SetFocalPoint(*cen); cam.SetPosition(*(cen + np.array([0, -1.0, 0]) * ext * 2.1)); cam.SetViewUp(0, 0, 1)
        cam.GetCamera().SetViewAngle(30); cam.ResetClippingRange()

    def _inplane(self, k=None):
        k = self._k() if k is None else k; th = math.radians(self.rot)
        B, N = self.B[k], self.N[k]
        return math.cos(th) * B + math.sin(th) * N, -math.sin(th) * B + math.cos(th) * N

    def setPosition(self, s):
        if self.P is None: return
        s = float(np.clip(s, 0, self.length)); self.curS = s; k = self._k()
        lm = slicer.app.layoutManager()
        rn = lm.sliceWidget("Red").mrmlSliceNode()
        X, Y = self._inplane(k); T = self.T[k]; P = self.P[k]
        M = rn.GetSliceToRAS()
        for r in range(3): M.SetElement(r, 0, X[r]); M.SetElement(r, 1, Y[r]); M.SetElement(r, 2, T[r]); M.SetElement(r, 3, P[r])
        self._resliceMode(False)
        rn.UpdateMatrices()
        self._drawGreen()
        self._showContour(exact=False)
        try: self._prefetchTimer.stop()
        except Exception: pass
        self._settleLater()                                              # 軸位・3D の位置は、動きが止まってから

    def _resliceMode(self, cubic):
        """断面の補間: 動かしている間は線形（速い）、止まったら 3 次（なめらか）"""
        if getattr(self, "_cubicNow", None) == cubic: return
        self._cubicNow = cubic
        for nm in ("Red", "Green", "Orange", "Yellow"):
            try:
                sl = slicer.app.layoutManager().sliceWidget(nm).sliceLogic()
                r = sl.GetBackgroundLayer().GetReslice()
                if r is None: continue
                (r.SetInterpolationModeToCubic if cubic else r.SetInterpolationModeToLinear)()
                if cubic: sl.GetBackgroundLayer().Modified(); slicer.app.layoutManager().sliceWidget(nm).sliceView().scheduleRender()
            except Exception: pass

    def _settleLater(self):
        t = getattr(self, "_settleTimer", None)
        if t is None:
            t = self._settleTimer = qt.QTimer(); t.setSingleShot(True); t.setInterval(120); t.connect("timeout()", self._settle)
        t.start()

    def _settle(self):
        if self.P is None: return
        k = self._k(); P = self.P[k]
        try:
            yn = slicer.app.layoutManager().sliceWidget("Yellow").mrmlSliceNode()
            if yn.GetOrientation() != "Axial": yn.SetOrientationToAxial()
            if not getattr(self, "fixMode", False): yn.JumpSliceByCentering(P[0], P[1], P[2])
            if self.posNode is not None: self.posNode.SetNthControlPointPosition(0, *P)
            self._drawAxialCenters()
            self._resliceMode(True)
            if getattr(self, "_approx", False): self._showContour()
            self._prefetchStart()
        except Exception as e: print("settle:", e)

    def _prefetchStart(self):
        """手が止まっている間に、今の位置から外側へ向かって断面を先回りで計算しておく（次のスクロールが速い）"""
        t = getattr(self, "_prefetchTimer", None)
        if t is None:
            t = self._prefetchTimer = qt.QTimer(); t.setInterval(5); t.connect("timeout()", self._prefetchTick)
        k0 = self._k(); K = len(self.s)
        order = [k0]
        for d in range(1, K): order += [k for k in (k0 + d, k0 - d) if 0 <= k < K]
        self._pfQueue = order; self._pfPath = self.path; t.start()

    def _prefetchTick(self):
        import time as _t
        if self.path != getattr(self, "_pfPath", None) or not getattr(self, "_pfQueue", None):
            self._prefetchTimer.stop(); return
        t0 = _t.time()
        while self._pfQueue and _t.time() - t0 < 0.012:                 # 1 回 12 ms まで（操作をじゃましない）
            k = self._pfQueue.pop(0)
            if (self.path, "outer", k) in self.cache and (self.path, "lumen", k) in self.cache: continue
            try: self._section(k, "outer")
            except Exception: pass

    def setRotation(self, deg):
        self.rot = float(deg) % 360.0; th = math.radians(self.rot); c, s = math.cos(th), math.sin(th)
        gn = slicer.app.layoutManager().sliceWidget("Green").mrmlSliceNode()
        gn.SetSliceToRASByNTP(-s, c, 0, -c, -s, 0, 0, 0, -self.length / 2, 0)
        ow = slicer.app.layoutManager().sliceWidget("Orange")                # もう 1 枚のストレッチ像は 90° 回した向き（直交 2 方向を同時に見る）
        if ow is not None:
            off = math.radians(getattr(self, "orangeOff", 90.0)); c2, s2 = math.cos(th + off), math.sin(th + off)
            ow.mrmlSliceNode().SetSliceToRASByNTP(-s2, c2, 0, -c2, -s2, 0, 0, 0, -self.length / 2, 0)
        self._fitViews()
        self.setPosition(self.curS); self._drawMarkers()

    LUMEN_COL = (1.0, 0.85, 0.2); OUTER_COL = (0.35, 0.85, 1.0)

    def _metFast(self, k, md):
        """動かしている最中: その位置が未計算なら、近くの計算済み断面（±2 mm 以内）で代用して描画を止めない"""
        key = (self.path, md, int(k))
        if key in self.override or key in self.cache: return self._metK(k, md), False
        for d in range(1, 5):
            for kk in (k - d, k + d):
                kk2 = (self.path, md, int(kk))
                if kk2 in self.override or kk2 in self.cache: return self._metK(kk, md), True
        return self._metK(k, md), False

    def _showContour(self, exact=True):
        if self.prof is None or self.contNode is None: return
        k = self._k(); P, B, N = self.P[k], self.B[k], self.N[k]
        if exact: mL = self._metK(k, "lumen"); mO = self._metK(k, "outer"); ap = False
        else:
            (mL, a1), (mO, a2) = self._metFast(k, "lumen"), self._metFast(k, "outer"); ap = a1 or a2
        self._approx = ap
        m = mL if self.mode == "lumen" else mO
        W = lambda xy: P + np.outer(xy[:, 0], B) + np.outer(xy[:, 1], N)
        edit = bool(getattr(self, "contourEdit", False))
        lines, labels = [], []
        for mm, col, md in ((mO, self.OUTER_COL, "outer"), (mL, self.LUMEN_COL, "lumen")):
            if mm is None or (edit and md == self.mode): continue
            lines.append((W(mm["xy"]), col, True))
        try:
            gr = getattr(self, "_graftRad", None)
            if gr is not None and gr["path"] == self.path and gr["ks"][0] <= k <= gr["ks"][-1] and (getattr(self, "plan", None) or {}).get("on", True):
                i = k - gr["ks"][0]; Rt = gr["Rth"][i]; th = np.linspace(0, 2 * np.pi, len(Rt), endpoint=False)
                xy = np.c_[gr["cu"][i] + Rt * np.cos(th), gr["cv"][i] + Rt * np.sin(th)]
                a_ = 0.5 * abs(np.dot(xy[:, 0], np.roll(xy[:, 1], -1)) - np.dot(xy[:, 1], np.roll(xy[:, 0], -1)))
                lines.append((W(xy), (0.95, 0.97, 1.0), True))
                labels.append((W(xy[27:28])[0], f"Plan {2 * math.sqrt(a_ / math.pi):.0f} ({2 * gr['Rn'][i]:.0f})", (0.95, 0.97, 1.0), 14))
                if gr["gut"][i] >= 5: labels.append((W(xy[45:46])[0], f"Gutter {gr['gut'][i]:.0f} mm2", (0.95, 0.97, 1.0), 13))
                if gr["tl"] and gr["flap"] != "fixed" and self.tlValid():          # グラフトが術前の真腔の外へ広がる所 = フラップが押されて動く所
                    tm = self.tl["masks"][k]; nn = tm.shape[0]
                    rr_ = np.clip(np.round((xy[:, 1] + HALF) / STEP).astype(int), 0, nn - 1); cc_ = np.clip(np.round((xy[:, 0] + HALF) / STEP).astype(int), 0, nn - 1)
                    o = ~tm[rr_, cc_]
                    if o.any() and not o.all():
                        idx = np.roll(np.arange(len(xy)), -int(np.argmin(o))); segs, cur = [], []
                        for ii in idx:
                            if o[ii]: cur.append(ii)
                            elif cur: segs.append(cur); cur = []
                        if cur: segs.append(cur)
                        for sg in segs:
                            if len(sg) >= 2: lines.append((W(xy[sg]), (0.3, 1.0, 0.45), False))
                        sg = max(segs, key=len)
                        if len(sg) >= 4: labels.append((W(xy[sg[len(sg) // 2]:sg[len(sg) // 2] + 1])[0], "Flap pushed", (0.3, 1.0, 0.45), 13))
        except Exception as e: print("plan ring:", e)
        try:
            ac = getattr(self, "actual", None)
            if ac is not None and ac.get("C") is not None and ac["path"] == self.path and ac["ks"][0] <= k <= ac["ks"][-1]:
                i = k - ac["ks"][0]; cc_ = ac["C"][i] - P; th = np.linspace(0, 2 * np.pi, 72, endpoint=False)
                xy = np.c_[cc_ @ B + ac["R"][i] * np.cos(th), cc_ @ N + ac["R"][i] * np.sin(th)]
                lines.append((W(xy), (1.0, 0.72, 0.2), True)); labels.append((W(xy[54:55])[0], f"Post {2 * ac['R'][i]:.0f}", (1.0, 0.72, 0.2), 14))
            if ac is not None and ac.get("path") == self.path:                          # 実際の金属（この断面の前後 2.5 mm）を金色の点で
                Tk = np.cross(B, N); dX = ac["pts"] - P; mm_ = np.abs(dX @ Tk) <= 2.5
                if mm_.any():
                    q = dX[mm_]; uu, vv = q @ B, q @ N
                    if len(uu) > 400: j_ = np.random.default_rng(0).choice(len(uu), 400, replace=False); uu, vv = uu[j_], vv[j_]
                    for a_, b_ in zip(uu, vv):
                        lines.append((W(np.array([[a_ - 0.5, b_], [a_ + 0.5, b_]])), (1.0, 0.8, 0.25), False))
                        lines.append((W(np.array([[a_, b_ - 0.5], [a_, b_ + 0.5]])), (1.0, 0.8, 0.25), False))
        except Exception as e: print("post ring:", e)
        try:
            if self.tlValid():
                xy = self._tlXY(k)
                if xy is not None:
                    lines.append((W(xy), (0.3, 1.0, 0.45), True)); d = self.tl["deq"][k]
                    if np.isfinite(d): labels.append((W(xy[24:25])[0], f"TL {d:.1f}", (0.3, 1.0, 0.45), 14))
        except Exception as e: print("tl contour:", e)
        if m is not None:
            for key, lab, col in (("maxLine", "dmax", (1.0, 0.35, 0.3)), ("minLine", "dmin", (0.35, 0.65, 1.0))):
                a, b = m[key]; ab = W(np.array([a, b]))
                lines.append((ab, col, False)); labels.append((ab[1], f"{m[lab]:.1f}", col, 15))
        if getattr(self, "ovRed", None) is not None: self.ovRed.set(lines, labels)
        if edit:                                                          # 手直し中だけ、点をつかめる曲線を出す
            self._busyEdit = True
            wasMod = self.contNode.StartModify(); self.contNode.RemoveAllControlPoints()
            if m is not None:
                xy = m["xy"]; idx = np.linspace(0, len(xy), NEDIT, endpoint=False).astype(int)
                for x, y in xy[idx]: self.contNode.AddControlPoint(vtk.vtkVector3d(*(P + x * B + y * N)))
            self.contNode.EndModify(wasMod); self._busyEdit = False
        self._mL, self._mO = mL, mO
        self._annotate(k, m)
        try: self.onChanged()
        except Exception: pass

    def setContourEdit(self, on):
        self.contourEdit = bool(on)
        if self.contNode is not None: self.contNode.GetDisplayNode().SetVisibility(self.contourEdit)
        self._showContour()

    def _greenRAS(self, s, frac=1.0, rot=None):
        th = math.radians(self.rot if rot is None else rot); t = np.array([-math.cos(th), -math.sin(th), 0.0])
        return np.array([t * (HALF - 1) * frac + np.array([0, 0, -s]), -t * (HALF - 1) * frac + np.array([0, 0, -s])])

    def _drawGreen(self):
        """ストレッチ像: 現在位置（赤）・ベースライン（緑）・マーカー（水色）・マウスの位置（白）を軽く描く"""
        if self.P is None or getattr(self, "_editing", False): return
        for ovn, vn, rot in (("ovGreen", "Green", self.rot), ("ovOrange", "Orange", self.rot + getattr(self, "orangeOff", 90.0))):
            o = getattr(self, ovn, None)
            if o is not None: self._drawStretch(o, vn, rot)

    def _drawStretch(self, o, vn, rot):
        G = lambda s, frac=1.0: self._greenRAS(s, frac, rot)
        lines, labels = [], []
        if self.baseS is not None:
            ab = G(self.baseS); lines.append((ab, (0.4, 1.0, 0.45), False)); labels.append((ab[0], "0", (0.4, 1.0, 0.45), 12))
        try:
            sn = slicer.app.layoutManager().sliceWidget(vn).mrmlSliceNode(); mmpp = sn.GetFieldOfView()[1] / max(sn.GetDimensions()[1], 1)
        except Exception: mmpp = 1.0
        lastLab = -1e9
        for mk in sorted(self.markers, key=lambda m: m["s"]):
            if not self._onPath(mk): continue
            ab = G(mk["s"], 0.55); lines.append((ab, (0.3, 0.9, 0.95), False))
            sl = max(mk["s"], lastLab + 15 * mmpp); lastLab = sl                # 近いマーカーの文字が重ならないよう下へずらす
            lab = MARK_EN.get(mk["name"].replace("（推定）", ""), "Sec" + mk["name"][2:] if mk["name"].startswith("断面") else "M") + ("?" if mk.get("auto") else "")
            if vn == "Green": labels.append((G(sl, 0.55)[0], f"{lab} {self.rel(mk['s']):+.0f}", (0.3, 0.9, 0.95), 12))
        hs = getattr(self, "_hoverS", None)
        if hs is not None and self.prof is not None:
            kk = int(min(max(round(hs / STEP), 0), len(self.prof) - 1)); dmax, dmin = self.prof[kk, 2], self.prof[kk, 3]
            ab = G(hs); lines.append((ab, (0.85, 0.85, 0.85), False))
            if np.isfinite(dmax): labels.append((ab[1], f"{self.rel(hs):+.0f} mm  {dmax:.1f}/{dmin:.1f}", (1, 1, 1), 13))
        pl = getattr(self, "plan", None)
        if pl is not None and pl.get("on", True) and pl.get("path") == self.path:
            for sx, nm in ((pl["p"], "Plan P"), (pl["d"], "Plan D")):
                ab = G(sx); lines.append((ab, (0.95, 0.95, 1.0), False))
                if vn == "Green": labels.append((ab[1], nm, (0.95, 0.95, 1.0), 12))
        ac = getattr(self, "actual", None)
        if ac is not None and ac.get("path") == self.path:
            for sx, nm in ((ac["lo"], "Post P"), (ac["hi"], "Post D")):
                ab = G(sx); lines.append((ab, (1.0, 0.72, 0.2), False))
                if vn != "Green" or getattr(self, "orangeOff", 90.0) != 0: labels.append((ab[0], nm, (1.0, 0.72, 0.2), 12))
        if pl is not None:
            st = {r["name"]: r["state"] for r in self.coverage(pl["p"], pl["d"]) if r["kind"] == "entry"}
            for e in getattr(self, "entries", []):
                if e.get("path") == self.path or e["s"] <= getattr(self, "sharedLen", 0) + 2:
                    lines.append((G(e["s"], 0.3), self.STATE_COL.get(st.get(e["name"], "open")), False))
        ab = G(self.curS); lines.append((ab, (1.0, 0.3, 0.25), False))
        o.set(lines, labels)

    def _annotate(self, k, m):
        lm = slicer.app.layoutManager()
        try:
            red = lm.sliceWidget("Red").sliceView(); ca = red.cornerAnnotation()
            mode = "Outer" if self.mode == "outer" else "Lumen"
            base = f"{self.rel(self.s[k]):+.1f} mm from baseline" if self.baseS is not None else f"{self.s[k]:.1f} mm from origin"
            mL, mO = getattr(self, "_mL", None), getattr(self, "_mO", None)
            def fmt(q, nm):
                return (f"{nm}  Dmax {q['dmax']:.1f}  Dmin {q['dmin']:.1f}  Deq {q['deq']:.1f} mm" + (" *" if q.get("edited") else "")) if q else f"{nm}  -"
            txt = base + "\n" + fmt(mO, "Outer") + "\n" + fmt(mL, "Lumen")
            ca.SetText(2, txt); ca.GetTextProperty().SetColor(1, 0.9, 0.3); ca.GetTextProperty().SetFontSize(16); red.scheduleRender()
            g = lm.sliceWidget("Green").sliceView(); c2 = g.cornerAnnotation()
            c2.SetText(2, f"{PATH_EN.get(self.path, '')}\n{base}\nrot {self.rot:.0f} deg"); c2.GetTextProperty().SetColor(1, 0.9, 0.3); g.scheduleRender()
            ow = lm.sliceWidget("Orange")
            if ow is not None:
                c4 = ow.sliceView().cornerAnnotation(); c4.SetText(2, f"rot {(self.rot + getattr(self, 'orangeOff', 90.0)) % 360:.0f} deg" + ("  POST-OP" if getattr(self, "orangeOff", 90.0) == 0 else "")); c4.GetTextProperty().SetColor(1, 0.75, 0.35); ow.sliceView().scheduleRender()
            y = lm.sliceWidget("Yellow").sliceView(); c3 = y.cornerAnnotation(); c3.SetText(2, "Axial (original)"); c3.GetTextProperty().SetColor(1, 0.9, 0.3)
        except Exception as e:
            print("annotate:", e)

    def _onContourEdited(self, caller=None, event=None):
        if self._busyEdit or self.prof is None: return
        k = self._k(); P, B, N = self.P[k], self.B[k], self.N[k]
        ctrl = slicer.util.arrayFromMarkupsControlPoints(self.contNode, world=True)
        if ctrl is None or len(ctrl) < 3: return
        base = self._section(k)
        q = ctrl - P; cxy = np.c_[q @ B, q @ N]
        if base is not None and len(base) == NPOLY and len(ctrl) == NEDIT:
            idx = np.linspace(0, NPOLY, NEDIT, endpoint=False).astype(int)
            disp = cxy - base[idx]
            pos = np.arange(NPOLY) / (NPOLY / NEDIT)
            i0 = np.floor(pos).astype(int) % NEDIT; i1 = (i0 + 1) % NEDIT; f = (pos - np.floor(pos))[:, None]
            new = base + (1 - f) * disp[i0] + f * disp[i1]
        else: new = _resample(cxy)
        self.override[(self.path, self.mode, k)] = new
        self._refreshK(k)

    # ---------------------------------------------------------------- マウス操作
    @staticmethod
    def _only(fn):
        """大動脈サイジングを開いている時だけ動く（心臓の画面のホイールや MPR を横取りしない）"""
        def cb(c, e):
            try:
                if slicer.util.selectedModule() != "AortaSizing": return
            except Exception: return
            return fn(c, e)
        return cb

    def suspend(self):
        """ほかの画面へ移る時: マウス操作の横取り・断面の上の線・3D の線や点をすべて引っ込める（戻ったら元どおり）"""
        for it, tag in list(self._iTags) + list(getattr(slicer, "_saITags", None) or []):
            try: it.RemoveObserver(tag)
            except Exception: pass
        self._iTags = []; slicer._saITags = self._iTags
        for t in ("_settleTimer", "_prefetchTimer", "_timer", "_lcTimer"):
            try: getattr(self, t).stop()
            except Exception: pass
        for ov in ("ovRed", "ovGreen", "ovOrange"):
            o = getattr(self, ov, None)
            if o is not None:
                try: o.remove()
                except Exception: pass
            setattr(self, ov, None)
        reg = getattr(slicer, "_saOverlays", None) or {}
        for k, o in list(reg.items()):
            try: o.remove()
            except Exception: pass
            reg.pop(k, None)
        hidden = getattr(self, "_hiddenNodes", None) or []
        for n in list(slicer.util.getNodesByClass("vtkMRMLDisplayableNode")):
            try:
                if not (n.GetName().startswith(("SA ", "TEVAR ")) or n.GetAttribute("SA.measure")): continue
                d = n.GetDisplayNode()
                if d is not None and d.GetVisibility(): d.SetVisibility(False); hidden.append(n)
            except Exception: pass
        self._hiddenNodes = hidden
        self._restoreCV()                                                  # 心臓の画面の 3D（面・カメラ・切断面）を元に戻す
        try:
            lm = slicer.app.layoutManager()
            for nm in ("Red", "Green", "Orange", "Yellow"):
                w = lm.sliceWidget(nm)
                if w is not None: w.sliceView().cornerAnnotation().SetText(2, ""); w.sliceView().scheduleRender()
        except Exception: pass

    def _saveCV(self):
        """心臓の画面の 3D の状態（面の表示・VR・カメラ・背景・切断面）を覚える。大動脈から戻る時に元に戻す"""
        if getattr(self, "_cvState", None) is not None: return
        try:
            cv = slicer.modules.cardiacview.widgetRepresentation().self().logic
            lm = slicer.app.layoutManager(); vn = lm.threeDWidget(0).mrmlViewNode()
            cam = slicer.modules.cameras.logic().GetViewActiveCameraNode(vn).GetCamera()
            ren = lm.threeDWidget(0).threeDView().renderWindow().GetRenderers().GetFirstRenderer()
            self._cvState = dict(
                visible=dict(getattr(cv, "visible", {}) or {}),
                models={k: m.GetDisplayNode().GetVisibility() for k, m in (getattr(cv, "layerModels", {}) or {}).items() if m is not None and m.GetDisplayNode() is not None},
                cam=(cam.GetPosition(), cam.GetFocalPoint(), cam.GetViewUp(), cam.GetParallelProjection(), cam.GetParallelScale(), cam.GetViewAngle()),
                bg=(vn.GetBackgroundColor(), vn.GetBackgroundColor2()), ssao=ren.GetUseSSAO(),
                cut=(getattr(cv, "cutAxis", None), getattr(cv, "cutFrac", 0.5), getattr(cv, "_lockN", None)),
                sliceVis={nm: lm.sliceWidget(nm).mrmlSliceNode().GetSliceVisible() for nm in ("Red", "Yellow", "Green") if lm.sliceWidget(nm) is not None})
        except Exception as e: print("saveCV:", e); self._cvState = None

    def _restoreCV(self):
        st = getattr(self, "_cvState", None); self._cvState = None
        if not st: return
        try:
            cv = slicer.modules.cardiacview.widgetRepresentation().self().logic
            lm = slicer.app.layoutManager(); vn = lm.threeDWidget(0).mrmlViewNode()
            for name, on in st["visible"].items():
                try: cv.setLayerVisible(name, on)
                except Exception: pass
            for k, on in st["models"].items():
                m = cv.layerModels.get(k)
                if m is not None and m.GetDisplayNode() is not None: m.GetDisplayNode().SetVisibility(on)
            camN = slicer.modules.cameras.logic().GetViewActiveCameraNode(vn); cam = camN.GetCamera()
            pos, fp, up, par, scale, ang = st["cam"]
            cam.SetParallelProjection(par); cam.SetParallelScale(scale); cam.SetViewAngle(ang)
            camN.SetPosition(*pos); camN.SetFocalPoint(*fp); camN.SetViewUp(*up); camN.ResetClippingRange()
            vn.SetBackgroundColor(*st["bg"][0]); vn.SetBackgroundColor2(*st["bg"][1])
            try: lm.threeDWidget(0).threeDView().renderWindow().GetRenderers().GetFirstRenderer().SetUseSSAO(st["ssao"])
            except Exception: pass
            for nm, v in st["sliceVis"].items():
                try: lm.sliceWidget(nm).mrmlSliceNode().SetSliceVisible(v)
                except Exception: pass
            axis, frac, lockN = st["cut"]
            if axis is not None:
                if axis == "LOCK" and lockN is not None: cv._lockN = lockN
                cv.setCut(axis, frac)
            lm.threeDWidget(0).threeDView().scheduleRender()
        except Exception as e: print("restoreCV:", e)

    def resume(self):
        for n in getattr(self, "_hiddenNodes", None) or []:
            try:
                if slicer.mrmlScene.IsNodePresent(n): n.GetDisplayNode().SetVisibility(True)
            except Exception: pass
        self._hiddenNodes = []
        if self.straight is not None and self.vol is not None and slicer.mrmlScene.IsNodePresent(self.vol): self.showLayout()

    def _watch(self):
        lm = slicer.app.layoutManager()
        old = getattr(slicer, "_saITags", None) or []                         # アプリ全体で 1 組だけ（再読み込み・開き直しで古い操作が残らない）
        for it, tag in list(self._iTags) + list(old):
            try: it.RemoveObserver(tag)
            except Exception: pass
        self._iTags = []; slicer._saITags = self._iTags
        E = vtk.vtkCommand
        for nm in ("Red", "Green", "Orange", "Yellow"):
            if lm.sliceWidget(nm) is None: continue
            sv = lm.sliceWidget(nm).sliceView(); io = sv.interactorObserver()
            io.SetActionEnabled(io.BrowseSlice, False)
            # 普通の DICOM ビューアのように、左ドラッグでウィンドウ（濃さ・コントラスト）を変えられる。
            # 断面位置を左ドラッグで動かす Green だけは切る（そのぶんウィンドウは Red / 軸位で変え、全ビューに反映）。
            wl = nm not in ("Green", "Orange")
            io.SetActionEnabled(io.AdjustWindowLevelBackground, wl); io.SetActionEnabled(io.AdjustWindowLevelForeground, wl)
            try:
                siw = sv.displayableManagerByClassName("vtkMRMLCrosshairDisplayableManager").GetSliceIntersectionWidget()
                for act in (siw.ActionBrowseSlice, siw.ActionTranslateSliceIntersection, siw.ActionRotateSliceIntersection, siw.ActionSetCrosshairPosition):
                    siw.SetActionEnabled(act, False)
            except Exception: pass
            it = sv.interactor()
            def add(ev, fn, it=it): self._iTags.append((it, it.AddObserver(ev, self._only(fn), 1.0)))
            if nm == "Red":
                add(E.MouseWheelForwardEvent, lambda c, e: self._wheelRed(c, -1)); add(E.MouseWheelBackwardEvent, lambda c, e: self._wheelRed(c, +1))
                add(E.KeyPressEvent, lambda c, e: self._keyRed(c))
                add(E.LeftButtonPressEvent, lambda c, e: self._clickRed(c))
            elif nm in ("Green", "Orange"):
                add(E.MouseWheelForwardEvent, lambda c, e: self._wheelGreen(c, +1)); add(E.MouseWheelBackwardEvent, lambda c, e: self._wheelGreen(c, -1))
                add(E.LeftButtonPressEvent, lambda c, e, nm=nm: self._pressGreen(c, nm)); add(E.MouseMoveEvent, lambda c, e, nm=nm: self._moveGreen(c, nm))
                add(E.LeftButtonReleaseEvent, lambda c, e: self._releaseGreen(c))
                add(E.LeaveEvent, lambda c, e: self._leaveGreen(c))
            else:                                   # Yellow 軸位: ホイールは断面位置に合わせる（勝手にスクロールさせない）
                add(E.MouseWheelForwardEvent, lambda c, e: self._wheelAx(c, +1)); add(E.MouseWheelBackwardEvent, lambda c, e: self._wheelAx(c, -1))
                add(E.LeftButtonPressEvent, lambda c, e: self._pressAx(c)); add(E.MouseMoveEvent, lambda c, e: self._moveAx(c))
                add(E.LeftButtonReleaseEvent, lambda c, e: self._releaseAx(c))
        for nm in [n for n in ("Red", "Green", "Orange", "Yellow") if lm.sliceWidget(n) is not None] + ["3D"]:   # どのビューで操作したか（計測の置き場所）と、共通のキー
            it = lm.threeDWidget(0).threeDView().interactor() if nm == "3D" else lm.sliceWidget(nm).sliceView().interactor()
            self._iTags.append((it, it.AddObserver(E.LeftButtonPressEvent, self._only(lambda c, e, nm=nm: setattr(self, "_lastView", nm)), 5.0)))
            self._iTags.append((it, it.AddObserver(E.KeyPressEvent, self._only(lambda c, e: self._keyAny(c)), 5.0)))
        self._linkWindowLevel()
        it3 = lm.threeDWidget(0).threeDView().interactor()
        self._iTags.append((it3, it3.AddObserver(E.LeftButtonPressEvent, self._only(lambda c, e: self._press3D(c)), 1.0)))
        self._iTags.append((it3, it3.AddObserver(E.LeftButtonReleaseEvent, self._only(lambda c, e: self._release3D(c)), 1.0)))

    def _linkWindowLevel(self):
        """元画像でウィンドウを変えたら、伸ばした画像（Green）にも同じ値を反映する"""
        d = self.vol.GetDisplayNode()
        if getattr(self, "_wlTag", None) is not None:
            try: self._wlSrc.RemoveObserver(self._wlTag)
            except Exception: pass
        self._wlSrc = d
        def onWL(caller=None, ev=None):
            if self.straight is None: return
            sd = self.straight.GetDisplayNode()
            if sd is None: return
            sd.SetAutoWindowLevel(False); sd.SetWindowLevel(d.GetWindow(), d.GetLevel())
        self._wlTag = d.AddObserver(vtk.vtkCommand.ModifiedEvent, onWL)

    def _abort(self, it):
        for i, tag in self._iTags:
            if i is it:
                try: it.GetCommand(tag).SetAbortFlag(1)
                except Exception: pass

    def _queue(self, s=None, rot=None):
        if s is not None: self._pending = s
        if rot is not None: self._pendingRot = rot
        if not self._timer.isActive(): self._timer.start()

    def _flush(self):
        try:
            if self._pendingRot is not None:
                r = self._pendingRot; self._pendingRot = None; self.setRotation(r)
            if self._pending is not None:
                s = self._pending; self._pending = None; self.setPosition(s)
        except Exception: _err("flush")

    def _wheelRed(self, it, d):
        if self.P is None or self._editing: return
        step = 5.0 if it.GetShiftKey() else 1.0
        self._queue(s=float(np.clip((self._pending if self._pending is not None else self.curS) + d * step, 0, self.length)))
        self._abort(it)

    def _keyAny(self, it):
        key = it.GetKeySym() or ""; ctrl = bool(it.GetControlKey())
        cmd = None
        if getattr(self, "fixMode", False) and key in ("Return", "KP_Enter", "BackSpace", "Delete", "Escape"):
            cmd = {"Return": "fixapply", "KP_Enter": "fixapply", "BackSpace": "undo", "Delete": "undo", "Escape": "fixexit"}[key]
            try: getattr(self, "onKey", lambda c: None)(cmd)
            except Exception: _err("key")
            self._abort(it); return
        if key in ("Return", "KP_Enter"): cmd = "enter"
        elif key in ("p", "P") and not ctrl: cmd = "pin"
        elif key in ("l", "L") and not ctrl: cmd = "mode"
        elif key in ("z", "Z") and ctrl: cmd = "undo"
        elif key == "Escape": cmd = "esc"
        if cmd is None: return
        try: getattr(self, "onKey", lambda c: None)(cmd)
        except Exception: _err("key")
        if cmd != "esc": self._abort(it)

    def _keyRed(self, it):
        key = it.GetKeySym() or ""
        d = {"Up": -1, "Down": 1, "Prior": -5, "Next": 5}.get(key)
        if d is not None and self.P is not None:
            self._queue(s=float(np.clip(self.curS + d, 0, self.length))); self._abort(it)

    def _clickRed(self, it):
        if getattr(self, "_entryCb", None) is not None and self.P is not None:      # TEVAR: エントリーを断面のクリックで置く
            x, y = it.GetEventPosition(); sn = slicer.app.layoutManager().sliceWidget("Red").mrmlSliceNode()
            M = sn.GetXYToRAS(); ras = np.array([sum(M.GetElement(r, c) * v for c, v in enumerate((x, y, 0, 1))) for r in range(3)])
            cb = self._entryCb; self._entryCb = None
            try: cb(ras)
            except Exception as e: print("entry:", e)
            self._abort(it); return
        if self.P is not None and (it.GetControlKey() or getattr(self, "fixMode", False)) and self._clockCb is None and not self._editing and not self._placing():
            p = self._rasAt(it, "Red"); k = self._k()                    # Ctrl+クリック: この断面の中心をクリックした所へ
            self._abort(it)
            if getattr(self, "fixMode", False) and not it.GetControlKey(): self.queueFix(k, p); return
            qt.QTimer.singleShot(0, lambda: self._ctrlMove(k, p)); return
        if self._clockCb is None or self.P is None: return
        x, y = it.GetEventPosition(); sn = slicer.app.layoutManager().sliceWidget("Red").mrmlSliceNode()
        M = sn.GetXYToRAS(); ras = np.array([sum(M.GetElement(r, c) * v for c, v in enumerate((x, y, 0, 1))) for r in range(3)])
        cb = self._clockCb; self._clockCb = None
        try: cb(self._setClock(ras))
        except Exception as e: print("clock:", e)
        self._abort(it)

    def _wheelGreen(self, it, d):
        if self.P is None: return
        base = self._pendingRot if self._pendingRot is not None else self.rot
        self._queue(rot=(base + d * (15.0 if it.GetShiftKey() else 5.0)) % 360.0); self._abort(it)

    def _rasAt(self, it, nm):
        x, y = it.GetEventPosition(); M = slicer.app.layoutManager().sliceWidget(nm).mrmlSliceNode().GetXYToRAS()
        return np.array([sum(M.GetElement(r, c) * v for c, v in enumerate((x, y, 0, 1))) for r in range(3)])

    def _sGreen(self, it, nm="Green"):
        return float(np.clip(-self._rasAt(it, nm)[2], 0, self.length))

    def _pressGreen(self, it, nm="Green"):
        if self.P is None or self._placing() or self._editing: return
        if it.GetControlKey() or getattr(self, "fixMode", False):         # Ctrl+クリック（合わせるモードではクリック）: その高さの中心線を、クリックした所へ動かす
            q = self._rasAt(it, nm); s = float(np.clip(-q[2], 0, self.length)); k = self._k(s)
            p = self.P[k] + q[0] * self.B[k] + q[1] * self.N[k]
            self._abort(it)
            if getattr(self, "fixMode", False) and not it.GetControlKey(): self.queueFix(k, p); return
            qt.QTimer.singleShot(0, lambda: self._ctrlMove(k, p)); return
        if it.GetShiftKey(): return
        pl = getattr(self, "plan", None)
        if getattr(self, "_tvMode", False) and pl is not None and pl.get("path") == self.path:   # TEVAR: 範囲をドラッグ / 白い線（近位・遠位端）をつかんで動かす
            sC = self._sGreen(it, nm)
            if getattr(self, "rangeMode", False): self._tvDrag = ("range", sC); pl["p"] = pl["d"] = sC; self._drawGreen(); self._abort(it); return
            near = min((("p", abs(sC - pl["p"])), ("d", abs(sC - pl["d"]))), key=lambda t: t[1])
            if near[1] <= 4.0: self._tvDrag = (near[0], sC); self._abort(it); return
        self._drag = True; self._queue(s=self._sGreen(it, nm)); self._abort(it)

    def _moveGreen(self, it, nm="Green"):
        td = getattr(self, "_tvDrag", None)
        if td is not None:
            sC = self._sGreen(it, nm); pl = self.plan
            if td[0] == "range": pl["p"], pl["d"] = min(td[1], sC), max(td[1], sC)
            else: pl[td[0]] = sC
            st = getattr(self, "onStatus", None)
            if st: st(f"範囲: {self.rel(pl['p']):.0f} → {self.rel(pl['d']):.0f} mm（長さ {pl['d'] - pl['p']:.0f} mm）。離すとグラフトを描きます。")
            self._drawGreen(); self._abort(it); return
        if self._drag: self._queue(s=self._sGreen(it, nm)); self._abort(it); return
        if self.P is not None:                                           # マウスを乗せた所の径をその場で表示（クリック不要）
            self._hoverS = self._sGreen(it, nm); self._drawGreen()

    # ---- 中心線を合わせる（軸位でクリック / 赤い点をドラッグ）
    def setFixMode(self, on):
        self.fixMode = bool(on)
        try: self._drawAxialCenters()
        except Exception: pass

    def _axNodes(self):
        YEL = "vtkMRMLSliceNodeYellow"
        a = self._node("vtkMRMLMarkupsFiducialNode", "SA 軸位の中心線", (YEL,), (0.3, 0.9, 1.0), glyph=3.2)
        g = self._node("vtkMRMLMarkupsFiducialNode", "SA 移動先", (YEL,), (1.0, 0.9, 0.2), glyph=3.0)
        return a, g

    def _drawAxialCenters(self):
        """軸位の今の高さを中心線が通る所（水色の点）。赤い点 = 今の位置"""
        if self.P is None: return
        a, g = self._axNodes(); fix = getattr(self, "fixMode", False)
        z = self._axZ() if fix else self.P[self._k()][2]
        wasMod = a.StartModify(); a.RemoveAllControlPoints()
        for p in self._crossings(z):
            if not fix and np.linalg.norm(p - self.P[self._k()]) < 3: continue
            a.AddControlPoint(vtk.vtkVector3d(*p))
        a.EndModify(wasMod)

    def _crossings(self, z):
        dz = self.P[:, 2] - z; idx = np.where(np.sign(dz[:-1]) != np.sign(dz[1:]))[0]; out = []
        for i in idx:
            t = dz[i] / (dz[i] - dz[i + 1] + 1e-9); out.append(self.P[i] + t * (self.P[i + 1] - self.P[i]))
        return out

    def _axZ(self):
        return float(slicer.app.layoutManager().sliceWidget("Yellow").mrmlSliceNode().GetSliceOffset())

    def fixLayout(self, on):
        """合わせるモードの画面: 大きな軸位で、上から順にクリックしていく"""
        lm = slicer.app.layoutManager()
        if on:
            ln = lm.layoutLogic().GetLayoutNode()
            if not ln.IsLayoutDescription(FIX_LAYOUT_ID): ln.AddLayoutDescription(FIX_LAYOUT_ID, FIX_LAYOUT_XML)
            lm.setLayout(FIX_LAYOUT_ID); slicer.app.processEvents()
            yw = lm.sliceWidget("Yellow"); yn = yw.mrmlSliceNode(); yn.SetOrientationToAxial(); yw.sliceController().setVisible(False)
            cn = yw.sliceLogic().GetSliceCompositeNode(); cn.SetBackgroundVolumeID(self.vol.GetID()); cn.SetForegroundVolumeID(None); cn.SetLabelVolumeID(None)
            fov = yn.GetFieldOfView(); r = fov[1] / max(fov[0], 1e-6); yn.SetFieldOfView(170.0, 170.0 * r, fov[2])
            self._fixDir = -1.0; self.fixStep = getattr(self, "fixStep", 10.0)
            p = self.P[self._k()]; yn.JumpSliceByCentering(p[0], p[1], p[2])
            if getattr(self, "posNode", None) is not None: self.posNode.GetDisplayNode().SetVisibility(False)
            self._watch(); self._drawAxialCenters(); self._fixHud(True)
        else:
            self._fixHud(False)
            if getattr(self, "posNode", None) is not None: self.posNode.GetDisplayNode().SetVisibility(True)
            self.showLayout()
            try: self.setPosition(self.curS)
            except Exception: pass

    def _fixHud(self, on):
        lab = getattr(self, "_fixLab", None)
        if not on:
            if lab is not None:
                try: lab.hide(); lab.setParent(None); lab.deleteLater()
                except Exception: pass
            self._fixLab = None; return
        try:
            v = slicer.app.layoutManager().sliceWidget("Yellow").sliceView()
            if lab is None:
                lab = qt.QLabel(v); lab.setAttribute(qt.Qt.WA_TransparentForMouseEvents, True); lab.setTextFormat(qt.Qt.RichText)
                lab.setStyleSheet("QLabel{background:rgba(14,16,20,190); color:#e6e8ec; border-radius:8px; padding:8px 12px; font-size:13px;}")
                self._fixLab = lab
            n = len(getattr(self, "pendingFix", []) or [])
            lab.setText(f"<b style='color:#ffd84d'>真腔の中心をクリック</b>　→ 自動で {getattr(self, 'fixStep', 10.0):.0f} mm {'足側' if self._fixDir < 0 else '頭側'}へ<br>"
                        f"<span style='color:#9aa3ad'>水色の点 = 今の中心線　ホイール: 上下に移動（Shift で 1 cm）<br>"
                        f"Enter: 反映して作り直す　Backspace: 1 つ戻す　Esc: 終わる</span><br><b>置いた点: {n}</b>")
            lab.adjustSize(); lab.move(10, 10); lab.show(); lab.raise_()
        except Exception as e: print("fix hud:", e)

    def _wheelAx(self, it, d):
        if not getattr(self, "fixMode", False): self._wheelRed(it, -d); return
        yn = slicer.app.layoutManager().sliceWidget("Yellow").mrmlSliceNode()
        step = 10.0 if it.GetShiftKey() else max(1.0, float(self.vol.GetSpacing()[2]))
        yn.SetSliceOffset(yn.GetSliceOffset() + d * step); self._fixDir = 1.0 if d > 0 else -1.0
        self._drawAxialCenters(); self._fixHud(True); self._abort(it)

    def _fixAdvance(self, near):
        """クリックしたら、同じ向きへ少し進めて、次の中心を画面の真ん中に"""
        yn = slicer.app.layoutManager().sliceWidget("Yellow").mrmlSliceNode()
        z = self._axZ() + self._fixDir * getattr(self, "fixStep", 10.0); pts = self._crossings(z)
        if pts:
            c = min(pts, key=lambda q: np.linalg.norm(q[:2] - near[:2])); yn.JumpSliceByCentering(c[0], c[1], z)
        else: yn.SetSliceOffset(z)
        self._drawAxialCenters(); self._fixHud(True)

    def _nearestK(self, p):
        near = np.where(np.abs(self.P[:, 2] - p[2]) < 2.0)[0]
        if len(near) == 0: return int(np.argmin(np.linalg.norm(self.P - p, axis=1)))
        return int(near[np.argmin(np.linalg.norm(self.P[near, :2] - p[:2], axis=1))])

    def _pressAx(self, it):
        if self.P is None or self._placing() or self._editing: return
        if not (it.GetControlKey() or getattr(self, "fixMode", False)): return
        self._axPress = (it.GetEventPosition(), self._rasAt(it, "Yellow")); self._abort(it)

    def _moveAx(self, it):
        pr = getattr(self, "_axPress", None)
        if pr is None: return
        q = self._rasAt(it, "Yellow"); _, g = self._axNodes()
        if g.GetNumberOfControlPoints() < 1: g.AddControlPoint(vtk.vtkVector3d(*q))
        else: g.SetNthControlPointPosition(0, *q)
        self._abort(it)

    def _releaseAx(self, it):
        pr = getattr(self, "_axPress", None)
        if pr is None: return
        self._axPress = None; (x0, y0), p0 = pr; x1, y1 = it.GetEventPosition(); p1 = self._rasAt(it, "Yellow")
        _, g = self._axNodes(); g.RemoveAllControlPoints()
        drag = math.hypot(x1 - x0, y1 - y0) > 6
        k = self._nearestK(p0 if drag else p1)                          # ドラッグ: つかんだ所の中心線を離した所へ / クリック: いちばん近い中心線をそこへ
        self._abort(it)
        if getattr(self, "fixMode", False) and not it.GetControlKey():
            self.queueFix(k, p1); self._fixAdvance(p1); return
        def go():
            s0 = float(self.s[k]); self._ctrlMove(k, p1)
            try: self.setPosition(s0)
            except Exception: pass
        qt.QTimer.singleShot(0, go)

    def _ctrlMove(self, k, p):
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try: self.moveCenterTo(k, p, getattr(self, "onStatus", None) or print)
        except Exception: _err("ctrlMove")
        finally: qt.QApplication.restoreOverrideCursor()

    def moveCenterTo(self, k, p, status=print):
        """中心線のその位置（k）を点 p へ動かして作り直す。回転・位置はそのまま"""
        c = self.curves.get(self.path)
        if c is None or self.P is None: return
        k = int(np.clip(k, 0, len(self.P) - 1)); P0 = self.P[k]; off = np.asarray(p, float) - P0
        if np.linalg.norm(off) > 45: status("中心から遠すぎます（血管の中をクリック）"); return
        cps = slicer.util.arrayFromMarkupsControlPoints(c, world=True)
        self._hist = getattr(self, "_hist", []); self._hist.append(("center", (self.path, cps.copy())))
        self._offsetCurve(c, P0, off)
        self._rebuildKeep(status)
        status(f"中心線を {np.linalg.norm(off):.1f} mm 動かしました（Ctrl+Z で戻す）")

    def _offsetCurve(self, c, P0, off):
        cps = slicer.util.arrayFromMarkupsControlPoints(c, world=True)
        d = np.linalg.norm(cps - P0, axis=1); i = int(np.argmin(d))
        if d[i] < 3: c.SetNthControlPointPositionWorld(i, *(cps[i] + off))
        else:
            best, bi = 1e9, 0
            for j in range(len(cps) - 1):
                a, b = cps[j], cps[j + 1]; ab = b - a; t = np.clip((P0 - a) @ ab / max(ab @ ab, 1e-9), 0, 1)
                dd = np.linalg.norm(a + t * ab - P0)
                if dd < best: best, bi = dd, j
            c.InsertControlPoint(bi + 1, vtk.vtkVector3d(*(P0 + off)))

    # ---- 合わせるモード: クリックは「修正点」を置くだけ（すぐ計算しない）。「反映」でまとめて 1 回作り直す
    def queueFix(self, k, p, status=None):
        status = status or getattr(self, "onStatus", None) or print
        k = int(np.clip(k, 0, len(self.P) - 1)); p = np.asarray(p, float); off = p - self.P[k]
        if np.linalg.norm(off) > 60: status("今の中心線から 6 cm 以上離れています（大動脈の中をクリック）"); return
        pend = self.__dict__.setdefault("pendingFix", [])
        sk = float(self.s[k]); pend[:] = [q for q in pend if abs(q[2] - sk) > 4.0]          # 近い高さの点は置き換え
        pend.append((k, p, sk)); self._drawPending()
        if getattr(self, "_fixLab", None) is not None: self._fixHud(True)
        status(f"修正点 {len(pend)} 個（まだ計算していません）。ホイールで次の高さへ → クリック … 最後に「反映」")
        cb = getattr(self, "onFixChanged", None)
        if cb: cb()

    def clearFixes(self):
        self.pendingFix = []; self._drawPending()
        if getattr(self, "_fixLab", None) is not None: self._fixHud(True)
        cb = getattr(self, "onFixChanged", None)
        if cb: cb()

    def applyFixes(self, status=print):
        pend = list(getattr(self, "pendingFix", []) or [])
        c = self.curves.get(self.path)
        if not pend or c is None: return 0
        cps = slicer.util.arrayFromMarkupsControlPoints(c, world=True)
        self._hist = getattr(self, "_hist", []); self._hist.append(("center", (self.path, cps.copy())))
        for k, p, sk in sorted(pend, key=lambda q: q[2]): self._offsetCurve(c, self.P[k], p - self.P[k])
        self.pendingFix = []; self._drawPending()
        s0 = self.curS
        try: self._rebuildKeep(status)
        finally:
            cb = getattr(self, "onFixChanged", None)
            if cb: cb()
        try: self.setPosition(min(s0, self.length))
        except Exception: pass
        if getattr(self, "fixMode", False): self._drawAxialCenters(); self._fixHud(True)
        status(f"修正点 {len(pend)} 個で中心線を作り直しました（Ctrl+Z で戻す）")
        return len(pend)

    def _drawPending(self):
        n = self._node("vtkMRMLMarkupsFiducialNode", "SA 修正点", ("vtkMRMLViewNode1", "vtkMRMLSliceNodeYellow", "vtkMRMLSliceNodeRed"), (1.0, 0.85, 0.15), glyph=3.0)
        wasMod = n.StartModify(); n.RemoveAllControlPoints()
        for i, (k, p, sk) in enumerate(getattr(self, "pendingFix", []) or []):
            j = n.AddControlPoint(vtk.vtkVector3d(*p)); n.SetNthControlPointLabel(j, "")
        n.EndModify(wasMod)

    def _rebuildKeep(self, status=print):
        rot0, s0 = self.rot, self.curS
        try: done = self._rebuildLocal(self.path, status)
        except Exception: _err("rebuildLocal"); done = False
        if not done: self.rebuild(self.path, status); self.curS = min(s0, self.length)
        self.setRotation(rot0)
        self._drawMarkers(); self._listsChanged()

    def _rebuildLocal(self, name, status=print):
        """中心線の一部だけ直した時の作り直し（数秒）。変わった範囲だけ切り出し・断面を計算し、それ以外は前の結果を使う。
        下流のねじれ（フレームの回転）は修正範囲の中で少しずつ吸収して、下流は前と同じフレームのまま"""
        c = self.curves.get(name); old = self.frames.get(name); vol = self.straight
        if c is None or old is None or vol is None or self.path != name or self.prof is None or self.arr is None: return False
        cp = slicer.util.arrayFromMarkupsCurvePoints(c, world=True).astype(float)
        new = self._frames(cp)
        Po, Pn = old["P"], new["P"]; Ko, Kn = len(Po), len(Pn); shift = Kn - Ko; m = min(Ko, Kn)
        bad = np.nonzero(np.linalg.norm(Pn[:m] - Po[:m], axis=1) > 0.05)[0]
        a = int(bad[0]) if len(bad) else m
        j = np.arange(Kn); jo = j - shift; ok = (jo >= 0) & (jo < Ko)
        dd = np.full(Kn, np.inf); dd[ok] = np.linalg.norm(Pn[ok] - Po[jo[ok]], axis=1)
        far = np.nonzero(dd > 0.35)[0]
        b = int(far[-1]) if len(far) else a
        a = max(0, a - 8); b = min(Kn - 1, max(b, a) + 8)
        if b - a > 0.6 * Kn or (b + 1 < Kn and b + 1 - shift < 0): return False
        status("直した所だけ作り直しています…")
        P, T, N, B = Pn.copy(), new["T"].copy(), new["N"].copy(), new["B"].copy()
        if b + 1 < Kn:
            ko = b + 1 - shift; n1, n0 = N[b + 1], old["N"][ko]
            phi = math.atan2(np.cross(n1, n0) @ T[b + 1], n1 @ n0)
            for k in range(a, b + 1):
                f = phi * (k - a) / (b + 1 - a); Nk = N[k] * math.cos(f) + np.cross(T[k], N[k]) * math.sin(f)
                N[k] = Nk / np.linalg.norm(Nk); B[k] = np.cross(T[k], N[k])
            for arr, src in ((P, Po), (T, old["T"]), (N, old["N"]), (B, old["B"])): arr[b + 1:] = src[ko:]
        new.update(P=P, T=T, N=N, B=B)
        oldArr = slicer.util.arrayFromVolume(vol).copy()
        out = np.empty((Kn,) + oldArr.shape[1:], np.int16)
        out[:a] = oldArr[:a]; out[a:b + 1] = self._straightArr(P[a:b + 1], N[a:b + 1], B[a:b + 1])
        if b + 1 < Kn: out[b + 1:] = oldArr[b + 1 - shift:]
        oldProf = self.prof
        def remap(d):
            r = {}
            for key, v in d.items():
                if isinstance(key, tuple) and len(key) >= 3 and name in key[:3] and isinstance(key[-1], (int, np.integer)):
                    k = int(key[-1])
                    if k < a: r[key] = v
                    elif k + shift > b: r[key[:-1] + (k + shift,)] = v
                else: r[key] = v
            return r
        self.cache = remap(self.cache); self.override = remap(self.override)
        ds = shift * STEP; lim = b * STEP
        for mk in self.markers:
            if mk.get("path") == name and mk["s"] > lim: mk["s"] += ds
        if self.baseS is not None and self.baseS > lim: self.baseS += ds
        if self.curS > lim: self.curS += ds
        self.frames[name] = new; self._use(name)
        d0 = vol.GetDisplayNode(); wl = (d0.GetWindow(), d0.GetLevel()) if d0 is not None else None
        self.straight = self._straightNode(name, out)
        if wl: self.straight.GetDisplayNode().SetWindowLevel(*wl)              # 見ていたウィンドウはそのまま
        self._built[name] = dict(n=c.GetNumberOfControlPoints(), cp=slicer.util.arrayFromMarkupsControlPoints(c, world=True), frames=new, vol=self.straight)
        self.sharedLen = self._sharedLength()
        status("断面を計算中…")
        self._profile(reuse=(oldProf, a, b, shift))
        self.curS = float(np.clip(self.curS, 0, self.length))
        return True

    def _leaveGreen(self, it):
        self._hoverS = None; self._drawGreen()

    def _releaseGreen(self, it):
        if getattr(self, "_tvDrag", None) is not None:
            self._tvDrag = None; self.rangeMode = False; pl = self.plan
            if pl["d"] < pl["p"] + 10.0: pl["d"] = min(pl["p"] + 10.0, self.length - 1.0)
            self._abort(it); cb = getattr(self, "onKey", None)
            if cb: qt.QTimer.singleShot(0, lambda: cb("tvplan"))
            return
        if self._drag: self._drag = False; self._abort(it)

    def _press3D(self, it): self._p3 = it.GetEventPosition()

    def _release3D(self, it):
        p0 = getattr(self, "_p3", None); p1 = it.GetEventPosition()
        if p0 is None or abs(p0[0] - p1[0]) + abs(p0[1] - p1[1]) > 3 or self.P is None or self._editing or self._placing(): return
        v3 = slicer.app.layoutManager().threeDWidget(0).threeDView(); ren = v3.renderWindow().GetRenderers().GetFirstRenderer()
        x, y = p1; W = []
        for z in (0.0, 1.0):
            ren.SetDisplayPoint(x, y, z); ren.DisplayToWorld(); w = ren.GetWorldPoint(); W.append(np.array(w[:3]) / (w[3] or 1.0))
        d = W[1] - W[0]; d /= np.linalg.norm(d) + 1e-9
        best = (1e9, None, None)
        for name, c in self.curves.items():
            pts = slicer.util.arrayFromMarkupsCurvePoints(c, world=True)
            dist = np.linalg.norm(np.cross(pts - W[0], d), axis=1)
            s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
            i = int(np.argmin(dist))
            if dist[i] < best[0]: best = (float(dist[i]), name, float(s[i]))
        dist, name, s = best
        if name is None or dist > 15: return
        if name != self.path and getattr(self, "_tvMode", False): return              # TEVAR: 計画の経路のまま
        if name != self.path and s > getattr(self, "sharedLen", 0) + 2:
            qt.QTimer.singleShot(0, lambda: self._switch(name, s))
        else: self._queue(s=s)

    def _switch(self, name, s):
        qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
        try:
            self.curS = s; self.selectPath(name)
        except Exception: _err("switch")
        finally: qt.QApplication.restoreOverrideCursor()

    # ---------------------------------------------------------------- マーカー・ベースライン
    def _xyzAt(self, s, path=None):
        F = self.frames[path or self.path]; return F["P"][self._k(s, path)]

    def addMarker(self, name, s=None, path=None, auto=False, clock=None):
        s = self.curS if s is None else float(s); path = path or self.path
        if name == "マーカー":                                            # 自由なマーカーは上書きせず、番号を振って残す
            name = "マーカー{}".format(1 + sum(1 for m in self.markers if m["name"].startswith("マーカー")))
        prev = self._mk(name)
        self.markers = [m for m in self.markers if m["name"] != name]
        self.markers.append(dict(name=name, s=s, path=path, xyz=self._xyzAt(s, path).tolist(), auto=auto, clock=clock))
        self.markers.sort(key=lambda m: m["s"])
        if not auto: self._hist = getattr(self, "_hist", []); self._hist.append(("marker", (name, prev)))
        self._drawMarkers()
        return name

    def removeMarker(self, r):
        if 0 <= r < len(self.markers): self.markers.pop(r); self._drawMarkers()

    def removeMarkerByName(self, name):
        self.markers = [m for m in self.markers if m["name"] != name]; self._drawMarkers()

    def jumpToMarker(self, r):
        if not (0 <= r < len(self.markers)): return
        m = self.markers[r]
        if m["path"] != self.path and m["s"] > getattr(self, "sharedLen", 0) + 2: self._switch(m["path"], m["s"])
        else: self.setPosition(m["s"])

    def setBaseline(self):
        self.baseS = float(self.curS); self._drawMarkers(); self._showContour()

    def _onPath(self, m):
        return m["path"] == self.path or m["s"] <= getattr(self, "sharedLen", 0) + 2

    def _drawMarkers(self):
        if self.mark3 is None: return
        wasMod = self.mark3.StartModify(); self.mark3.RemoveAllControlPoints()
        for m in self.markers:
            lab = MARK_EN.get(m["name"].replace("（推定）", ""), m["name"][:8]) + (" " + m["clock"] if m.get("clock") else "") + ("?" if m.get("auto") else "")
            i = self.mark3.AddControlPoint(vtk.vtkVector3d(*m["xyz"])); self.mark3.SetNthControlPointLabel(i, lab)
        self.mark3.EndModify(wasMod)
        self._drawGreen(); self._listsChanged()

    def _prefillMarkers(self):
        from scipy.spatial import cKDTree
        tree = cKDTree(self.P)
        for name, abbr, keys in BRANCHES:
            m = self._mask(keys)
            if m is None or m.sum() < 30: continue
            pts = self._pts(m)
            if len(pts) > 20000: pts = pts[np.random.default_rng(0).choice(len(pts), 20000, replace=False)]
            d, i = tree.query(pts)
            if d.min() > 25: continue
            self.addMarker(name, float(self.s[i[np.argmin(d)]]), auto=True)
        lowest = None
        for keys in (("kidney right",), ("kidney left",)):
            m = self._mask(keys)
            if m is None or m.sum() < 100: continue
            pts = self._pts(m); d, i = tree.query(pts)
            if d.min() > 60: continue
            s = float(self.s[i[np.argmin(d)]]); lowest = s if lowest is None else max(lowest, s)
        if lowest is not None: self.addMarker("最下位腎動脈", lowest, auto=True)
        if len(self.curves) >= 2 and getattr(self, "sharedLen", 0) < self.length: self.addMarker("大動脈分岐", self.sharedLen, auto=True)

    # ---------------------------------------------------------------- 手動計測（画面に残る・一覧・出力に入る）
    MEASURES = [("line", "直線", "vtkMRMLMarkupsLineNode", "L", (1.0, 0.85, 0.2)),
                ("poly", "連続線", "vtkMRMLMarkupsCurveNode", "P", (0.45, 1.0, 0.6)),
                ("curve", "カーブ", "vtkMRMLMarkupsCurveNode", "C", (0.4, 0.9, 1.0)),
                ("area", "面積", "vtkMRMLMarkupsClosedCurveNode", "A", (1.0, 0.55, 0.9)),
                ("angle", "角度", "vtkMRMLMarkupsAngleNode", "Ang", (1.0, 0.7, 0.3))]
    VIEW_JA = {"Red": "断面", "Yellow": "軸位", "Green": "ストレッチ", "3D": "3D"}

    def _placing(self):
        inter = slicer.app.applicationLogic().GetInteractionNode()
        return inter.GetCurrentInteractionMode() == inter.Place

    def measureNodes(self):
        self.measures = [n for n in getattr(self, "measures", []) if slicer.mrmlScene.IsNodePresent(n)]
        return self.measures

    def startMeasure(self, kind):
        """直線 / 連続線 / カーブ / 面積 / 角度。どのビューでもクリックで置く。置いた後も点はドラッグで直せる"""
        self.cancelMeasure()
        key, lab, cls, pre, col = next(m for m in self.MEASURES if m[0] == kind)
        num = 1 + max([int(n.GetAttribute("SA.num") or 0) for n in self.measureNodes() if n.GetAttribute("SA.measure") == kind] + [0])
        n = slicer.mrmlScene.AddNewNodeByClass(cls, f"{pre}{num}")
        for a, v in (("SA.measure", kind), ("SA.num", str(num)), ("SA.label", f"{lab} {num}"), ("SA.s", f"{self.curS:.2f}"),
                     ("SA.path", self.path or ""), ("SA.rot", f"{self.rot:.1f}"), ("SA.view", "")):
            n.SetAttribute(a, v)
        if kind == "poly": n.SetCurveTypeToLinear()
        try:
            if kind in ("line", "poly", "curve"): n.GetMeasurement("length").SetEnabled(True)
            if kind == "angle": n.GetMeasurement("angle").SetEnabled(True)
            if kind == "area": n.GetMeasurement("area").SetEnabled(False); n.GetMeasurement("length").SetEnabled(False)
        except Exception: pass
        d = n.GetDisplayNode()
        d.SetSelectedColor(*col); d.SetColor(*col); d.SetActiveColor(1.0, 1.0, 1.0)
        d.SetTextScale(2.6); d.SetGlyphScale(1.3); d.SetLineThickness(0.25); d.SetPointLabelsVisibility(False)
        try: d.SetPropertiesLabelVisibility(True); d.SetOccludedVisibility(True); d.SetOccludedOpacity(0.5)
        except Exception: pass
        V = slicer.vtkMRMLMarkupsNode
        for ev in (V.PointPositionDefinedEvent, V.PointModifiedEvent, V.PointRemovedEvent, V.PointEndInteractionEvent):
            n.AddObserver(ev, lambda c, e, n=n: self._measChanged(n))
        self.measureNodes().append(n); self._activeMeasure = n
        self._hist = getattr(self, "_hist", []); self._hist.append(("measure", n))
        sel = slicer.app.applicationLogic().GetSelectionNode()
        sel.SetReferenceActivePlaceNodeClassName(cls); sel.SetActivePlaceNodeID(n.GetID())
        inter = slicer.app.applicationLogic().GetInteractionNode()
        inter.SetPlaceModePersistence(1 if kind in ("poly", "curve", "area") else 0)   # 多点は右クリック / Enter で終わり
        inter.SetCurrentInteractionMode(inter.Place)
        return n

    def finishMeasure(self):
        inter = slicer.app.applicationLogic().GetInteractionNode()
        if inter.GetCurrentInteractionMode() == inter.Place: inter.SetCurrentInteractionMode(inter.ViewTransform)
        n = getattr(self, "_activeMeasure", None); self._activeMeasure = None
        if n is not None and slicer.mrmlScene.IsNodePresent(n):
            need = {"line": 2, "poly": 2, "curve": 2, "area": 3, "angle": 3}[n.GetAttribute("SA.measure")]
            if n.GetNumberOfDefinedControlPoints() < need: slicer.mrmlScene.RemoveNode(n)
        self._listsChanged()

    def cancelMeasure(self):
        if getattr(self, "_activeMeasure", None) is not None: self.finishMeasure()

    def _measChanged(self, n):
        if not slicer.mrmlScene.IsNodePresent(n): return
        if not n.GetAttribute("SA.view") and n.GetNumberOfDefinedControlPoints() >= 1:
            v = getattr(self, "_lastView", "Red") or "Red"
            n.SetAttribute("SA.view", v)
            if v == "Orange": v = "Green"; n.SetAttribute("SA.view", v)
            ids = {"Green": ["vtkMRMLSliceNodeGreen", "vtkMRMLSliceNodeOrange"]}.get(v, ["vtkMRMLSliceNodeRed", "vtkMRMLSliceNodeYellow", "vtkMRMLViewNode1"])
            n.GetDisplayNode().SetViewNodeIDs(ids)               # ストレッチ像の上の計測は、別の座標なのでそこだけに出す
            if v == "Red": n.SetAttribute("SA.s", f"{self.curS:.2f}"); n.SetAttribute("SA.rot", f"{self.rot:.1f}"); n.SetAttribute("SA.path", self.path or "")
        if n.GetAttribute("SA.measure") == "area":
            v = self.measureValue(n)
            nm = f"A{n.GetAttribute('SA.num')} {v[0]:.0f} mm2" if v else n.GetName()
            if n.GetName() != nm: n.SetName(nm)
        kind = n.GetAttribute("SA.measure")
        need = {"line": 2, "angle": 3}.get(kind)
        if need and n.GetNumberOfDefinedControlPoints() >= need and getattr(self, "_activeMeasure", None) is n:
            qt.QTimer.singleShot(0, self.finishMeasure)
        self._listsChanged()

    def measureValue(self, n):
        """(数値, 単位, 表示用の文字)"""
        kind = n.GetAttribute("SA.measure"); nd = n.GetNumberOfDefinedControlPoints()
        try:
            if kind == "line" and nd >= 2:
                v = float(n.GetLineLengthWorld()); return v, "mm", f"{v:.1f} mm"
            if kind in ("poly", "curve") and nd >= 2:
                v = float(n.GetCurveLengthWorld()); return v, "mm", f"{v:.1f} mm"
            if kind == "angle" and nd >= 3:
                v = float(n.GetAngleDegrees()); return v, "°", f"{v:.0f}°"
            if kind == "area" and nd >= 3:
                P = slicer.util.arrayFromMarkupsCurvePoints(n, world=True)
                c = P.mean(0); _, _, vt = np.linalg.svd(P - c, full_matrices=False)
                q = (P - c) @ vt[:2].T; x, y = q[:, 0], q[:, 1]
                a = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
                return a, "mm²", f"{a:.0f} mm² (Deq {2 * math.sqrt(a / math.pi):.1f})"
        except Exception as e: print("measure:", e)
        return None

    def measureRows(self):
        rows = []
        for n in self.measureNodes():
            v = self.measureValue(n); kind = n.GetAttribute("SA.measure")
            lab = next((m[1] for m in self.MEASURES if m[0] == kind), kind)
            where = self.VIEW_JA.get(n.GetAttribute("SA.view") or "", "—")
            try: s = float(n.GetAttribute("SA.s"))
            except Exception: s = None
            rows.append(dict(node=n, name=n.GetAttribute("SA.label") or n.GetName(), kind=lab, value=v[2] if v else "（置いている途中）",
                             num=v[0] if v else None, where=where, s=s, pos=(f"{self.rel(s):+.1f} mm" if (s is not None and where == "断面") else "")))
        return rows

    def jumpToMeasure(self, n):
        v = n.GetAttribute("SA.view")
        try:
            if v == "Red":
                p = n.GetAttribute("SA.path")
                if p and p != self.path and p in self.curves: self._switch(p, float(n.GetAttribute("SA.s")))
                self.setRotation(float(n.GetAttribute("SA.rot") or 0)); self.setPosition(float(n.GetAttribute("SA.s")))
            elif n.GetNumberOfControlPoints():
                c = np.mean([n.GetNthControlPointPositionWorld(i) for i in range(n.GetNumberOfControlPoints())], axis=0)
                if v == "Yellow": slicer.app.layoutManager().sliceWidget("Yellow").mrmlSliceNode().JumpSliceByCentering(*c)
        except Exception as e: print("jump:", e)

    def deleteMeasure(self, n):
        if getattr(self, "_activeMeasure", None) is n: self._activeMeasure = None
        if slicer.mrmlScene.IsNodePresent(n): slicer.mrmlScene.RemoveNode(n)
        self._listsChanged()

    def clearMeasures(self):
        self.cancelMeasure()
        for n in list(self.measureNodes()): slicer.mrmlScene.RemoveNode(n)
        self.measures = []; self._listsChanged()

    def undoLast(self):
        pend = getattr(self, "pendingFix", None)
        if pend:
            pend.pop(); self._drawPending()
            if getattr(self, "_fixLab", None) is not None: self._fixHud(True)
            cb = getattr(self, "onFixChanged", None)
            if cb: cb()
            return "最後の修正点を消しました"
        """最後にしたこと（計測 or マーカー）を 1 つ戻す"""
        hist = getattr(self, "_hist", [])
        while hist:
            kind, obj = hist.pop()
            if kind == "measure" and slicer.mrmlScene.IsNodePresent(obj): self.deleteMeasure(obj); return "計測を 1 つ戻しました"
            if kind == "center":
                path, cps = obj; c = self.curves.get(path)
                if c is None or path != self.path: continue
                c.RemoveAllControlPoints()
                for q in cps: c.AddControlPoint(vtk.vtkVector3d(*q))
                self._rebuildKeep(); return "中心線の修正を 1 つ戻しました"
            if kind == "marker":
                name, prev = obj
                self.markers = [m for m in self.markers if m["name"] != name]
                if prev is not None: self.markers.append(prev); self.markers.sort(key=lambda m: m["s"])
                self._drawMarkers(); return f"「{name}」を戻しました"
        n = (self.measureNodes() or [None])[-1]
        if n is not None: self.deleteMeasure(n); return "計測を 1 つ戻しました"
        return "戻せるものがありません"

    def _listsChanged(self):
        t = getattr(self, "_lcTimer", None)
        if t is None:
            t = self._lcTimer = qt.QTimer(); t.setSingleShot(True); t.setInterval(60)
            t.connect("timeout()", lambda: getattr(self, "onListsChanged", lambda: None)())
        t.start()

    # ---------------------------------------------------------------- 断面を記録（ピン）
    def pinSection(self):
        n = 1 + max([int(m["name"][2:]) for m in self.markers if m["name"].startswith("断面") and m["name"][2:].isdigit()] + [0])
        self.addMarker(f"断面{n}"); return f"断面{n}"

    # ---------------------------------------------------------------- テンプレートの手順
    def stepPath(self, name):
        if name.startswith("右") and "大動脈→右腸骨" in self.curves: return "大動脈→右腸骨"
        if name.startswith("左") and "大動脈→左腸骨" in self.curves: return "大動脈→左腸骨"
        return None

    def suggest(self, name):
        """その項目の、だいたいの位置（mm）。わからなければ None"""
        m = self._mk(name)
        if m is not None: return m["s"], m["path"]
        path = self.stepPath(name) or self.path
        try:
            if name == "瘤の最大径":
                a = self._mk("ネック終端（瘤の始まり）") or self._mk("最下位腎動脈"); b = self._mk("大動脈分岐")
                if a and b and self.prof is not None:
                    k0, k1 = sorted((self._k(a["s"]), self._k(b["s"])))
                    if k1 > k0: k = k0 + int(np.nanargmax(self.prof[k0:k1, 2])); return float(self.s[k]), self.path
            if name == "ネック終端（瘤の始まり）":
                r = self._mk("最下位腎動脈"); b = self._mk("大動脈分岐")
                if r and b and self.prof is not None:
                    k0, k1 = self._k(r["s"]), self._k(b["s"]); base = np.nanmedian(self.prof[k0:k0 + int(10 / STEP), 1])
                    for k in range(k0 + int(5 / STEP), k1):
                        if self.prof[k, 1] > base * 1.15: return float(self.s[k]), self.path
            if name.endswith("遠位（総大腿）") and path in self.frames:
                fem = self._mask(("femur right",) if name.startswith("右") else ("femur left",))
                if fem is not None and fem.sum() > 500:
                    ztop = self._pts(fem)[:, 2].max(); P = self.frames[path]["P"]
                    k = int(np.argmin(np.abs(P[:, 2] - (ztop - 10)))); return float(k * STEP), path
            if name == "近位ランディング":
                l = self._mk("左鎖骨下動脈")
                if l: return l["s"] + 10.0, self.path
        except Exception as e: print("suggest:", e)
        return None

    # ================================================================ TEVAR 計画（仮想グラフト）と術後 CT との比較
    # 中心線の上に、置きたい範囲（近位端〜遠位端）でカバードステントを描く。エントリー・分枝を覆うかを色で示す。
    # 術後 CT は背骨で術前に重ね合わせ、金属（ステントの骨組み）から実際のグラフトの範囲を出して、計画とのずれを中心線に沿って測る。
    OVERSIZE = 0.10
    BRANCH_NAMES = ("腕頭動脈", "左総頸動脈", "左鎖骨下動脈", "腹腔動脈", "上腸間膜動脈", "最下位腎動脈", "右腎動脈", "左腎動脈")
    STATE_COL = {"cover": (0.25, 0.85, 0.35), "edge": (1.0, 0.8, 0.2), "open": (1.0, 0.3, 0.3), "block": (1.0, 0.3, 0.3), "ok": (0.6, 0.8, 1.0)}

    def planInit(self, force=False):
        """計画の初期値: テンプレートの近位/遠位ランディング（無ければ左鎖骨下 +10 mm から 150 mm）"""
        pl = getattr(self, "plan", None)
        if pl is not None and not force and pl.get("path") in self.frames: return pl
        p = self._mk("近位ランディング"); d = self._mk("遠位ランディング"); l = self._mk("左鎖骨下動脈")
        sp = p["s"] if p else ((l["s"] + 10.0) if l else float(self.curS))
        sd = d["s"] if d else sp + 150.0
        sd = min(max(sd, sp + 20.0), self.length - 1.0)
        self.plan = dict(path=self.path, p=float(sp), d=float(sd), os=self.OVERSIZE, dp=None, dd=None, on=True)
        return self.plan

    def _landD(self, s, path=None):
        """ランディング部の外径（Deq、前後 5 mm の中央値）"""
        vals = []
        F = self.frames[path or self.path]
        for x in np.arange(s - 5.0, s + 5.01, 2.5):
            try:
                m = self._dia(float(np.clip(x, 0, F["length"])), path, "outer")
                if m and np.isfinite(m["deq"]): vals.append(m["deq"])
            except Exception: pass
        return float(np.median(vals)) if vals else None

    def planDiams(self):
        """[(近位の径, 実測径, 手入力か), (遠位 …)]  径はオーバーサイズを掛けて 2 mm 刻みに切り上げ"""
        pl = self.plan; out = []
        for key, s in (("dp", pl["p"]), ("dd", pl["d"])):
            base = self._landD(s, pl["path"])
            if pl.get(key): out.append((float(pl[key]), base, True)); continue
            nom = None if base is None else 2.0 * math.ceil(base * (1.0 + pl["os"]) / 2.0)
            out.append((nom, base, False))
        return out

    def planSet(self, **kw):
        pl = self.planInit()
        for k, v in kw.items():
            if k in ("p", "d") and v is not None: v = float(np.clip(v, 0.0, self.frames[pl["path"]]["length"]))
            pl[k] = v
        if pl["d"] < pl["p"] + 10: pl["d"] = pl["p"] + 10
        self.planDraw()

    def _tubePD(self, P, N, B, R, nseg=56):
        from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray
        n = len(P); th = np.linspace(0, 2 * np.pi, nseg, endpoint=False)
        pts = (P[:, None, :] + R[:, None, None] * (np.cos(th)[None, :, None] * N[:, None, :] + np.sin(th)[None, :, None] * B[:, None, :])).reshape(-1, 3)
        i = np.arange(n - 1)[:, None]; j = np.arange(nseg)[None, :]; j2 = (j + 1) % nseg
        q = np.stack([i * nseg + j, i * nseg + j2, (i + 1) * nseg + j2, (i + 1) * nseg + j], -1).reshape(-1, 4)
        cells = np.c_[np.full(len(q), 4), q].astype(np.int64).ravel()
        vp = vtk.vtkPoints(); vp.SetData(numpy_to_vtk(np.ascontiguousarray(pts, np.float64), deep=True))
        ca = vtk.vtkCellArray(); ca.SetCells(len(q), numpy_to_vtkIdTypeArray(cells, deep=True))
        pd = vtk.vtkPolyData(); pd.SetPoints(vp); pd.SetPolys(ca)
        nm = vtk.vtkPolyDataNormals(); nm.SetInputData(pd); nm.SplittingOff(); nm.ConsistencyOn(); nm.Update()
        return nm.GetOutput()

    def _zStentsPD(self, F, ks, R, pitch=17.0, height=12.0, apices=5, C=None, Rth=None):
        """Z 型ステント（金属の骨組み）を、グラフトの筒の上に輪で並べる"""
        s = F["s"]; s0, s1 = s[ks[0]], s[ks[-1]]
        app = vtk.vtkAppendPolyData(); c = s0 + 1.0 + height / 2
        th = np.linspace(0, 2 * np.pi, apices * 24, endpoint=False)
        u = th * apices / (2 * np.pi); tri = 4.0 * np.abs(u - np.floor(u) - 0.5) - 1.0
        while c + height / 2 <= s1 - 0.5:
            ss = c + tri * height / 2
            kk = np.clip(np.round(ss / STEP).astype(int), ks[0], ks[-1]); rr = R[kk - ks[0]] * 1.01
            if Rth is not None: rr = _radAt(Rth, kk - ks[0], np.arctan2(np.cos(th), np.sin(th))) * 1.01 + 0.3
            pts = (F["P"] if C is None else C)[kk] + rr[:, None] * (np.cos(th)[:, None] * F["N"][kk] + np.sin(th)[:, None] * F["B"][kk])
            vp = vtk.vtkPoints()
            for p in pts: vp.InsertNextPoint(*p)
            pl = vtk.vtkPolyLine(); pl.GetPointIds().SetNumberOfIds(len(pts) + 1)
            for i in range(len(pts)): pl.GetPointIds().SetId(i, i)
            pl.GetPointIds().SetId(len(pts), 0)
            ca = vtk.vtkCellArray(); ca.InsertNextCell(pl); pd = vtk.vtkPolyData(); pd.SetPoints(vp); pd.SetLines(ca)
            tf = vtk.vtkTubeFilter(); tf.SetInputData(pd); tf.SetRadius(0.4); tf.SetNumberOfSides(8); tf.Update()
            app.AddInputData(tf.GetOutput()); c += pitch
        for k, sgn in ((ks[0], 1), (ks[-1], -1)):                            # 両端の金のマーカー（X 線で見える印）
            kk = int(np.clip(k + sgn * int(1.5 / STEP), ks[0], ks[-1]))
            for a in (0, np.pi / 2, np.pi, 3 * np.pi / 2):
                ra = R[kk - ks[0]] if Rth is None else float(_radAt(Rth, np.array([kk - ks[0]]), np.array([math.atan2(math.cos(a), math.sin(a))]))[0])
                p = (F["P"] if C is None else C)[kk] + ra * 1.02 * (np.cos(a) * F["N"][kk] + np.sin(a) * F["B"][kk])
                sp = vtk.vtkSphereSource(); sp.SetCenter(*p); sp.SetRadius(1.1); sp.SetThetaResolution(12); sp.SetPhiResolution(8); sp.Update()
                app.AddInputData(sp.GetOutput())
        app.Update(); return app.GetOutput()

    def _model(self, name, pd, color, opacity=1.0, slice2D=False, spec=0.3):
        m = slicer.mrmlScene.GetFirstNodeByName(name)
        if m is None or not m.IsA("vtkMRMLModelNode"):
            m = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLModelNode", name); m.CreateDefaultDisplayNodes()
        m.SetAndObservePolyData(pd); d = m.GetDisplayNode()
        d.SetColor(*color); d.SetOpacity(opacity); d.SetScalarVisibility(False); d.SetBackfaceCulling(False)
        d.SetSpecular(spec); d.SetPower(30); d.SetAmbient(0.15); d.SetDiffuse(0.8)
        d.SetVisibility2D(bool(slice2D)); d.SetSliceIntersectionThickness(2)
        d.RemoveAllViewNodeIDs(); d.AddViewNodeID("vtkMRMLViewNode1")
        if slice2D: d.AddViewNodeID("vtkMRMLSliceNodeRed")
        d.SetVisibility(True); return m

    # ================================================================ 仮想グラフトの「広がった形」
    #  慢性（フラップが硬い）: グラフトは真腔の周径に沿って広がる。三日月の真腔ではフラップが伸びて平らになる所まで
    #     → 径 ≒ 真腔の長径（グラフトの径が上限）。壁の中で真腔をいちばん多く覆う位置。三日月の両端は残る（ガター）。
    #     この症例の術後 CT で確かめた: 径の誤差 中央値 2.4 mm、中心のずれ 4.3 mm
    #  急性（フラップが動く）: 壁の中で丸く広がる（グラフトの径まで、大動脈の内側が上限）
    #  解離でない所（真腔 = 内腔全体）は、内腔の中で径まで広がり、楕円の所は壁に押されて沿う
    GRAFT_END_MM = 20.0      # 「端はあるがまま」の時、両端のこの長さで、押し広げた形から真腔のあるがままの形へなめらかに戻る
    ELL_RATIO = 0.82         # 解離（慢性）: 広がったグラフトの短径/長径。この症例の術後 CT で中央値 0.82（0.76〜0.86）
    ELL_PLUS = 3.0           # 長径 = 真腔の長径 + 3 mm（同じく術後 CT で +2.9 mm）。グラフトの径が上限
    GRAFT_WALL_MM = 1.5      # 外周（壁の外側）から、この厚みぶん内側までしかグラフトは広がらない
    NTH = 72

    def _aortaIn(self, k, path):
        """断面 k の大動脈の内側までの距離（mm、外周 − 壁の厚み。外は負）。伸ばした画像の格子で"""
        from scipy import ndimage
        cache = self.__dict__.setdefault("_aoInCache", {})
        kq = int(min(max(4 * round(k / 4.0), 0), len(self.frames[path]["P"]) - 1))
        xy = self._section(kq, "outer", path)
        if xy is None or len(xy) < 6: return None
        key = (path, kq, id(xy))
        if key in cache: return cache[key][1]
        if len(cache) > 3000: cache.clear()
        nu = int(round(2 * HALF / STEP)) + 1
        E = ndimage.distance_transform_edt(_rasterPoly(np.asarray(xy, float), nu)) * STEP - self.GRAFT_WALL_MM
        cache[key] = (xy, E); return E

    def _deploy(self, k, Rn, path, flap, useTL, axis="cl"):
        """断面 k で広がったグラフト: (中心 u, v, 半径の輪 Rth[72], ガター mm², 名目の半径)"""
        from scipy.signal import fftconvolve
        E = self._aortaIn(k, path)
        if E is None: return None
        Ai = E > 0; Emax = float(E.max())
        if Emax < 2.0: return None
        TLm = self.tl["masks"][k] if useTL else None
        if TLm is None or TLm.shape != Ai.shape or TLm.sum() < 8: TLm = Ai; useTL = False
        if useTL and flap == "fixed": return self._deployFixed(k, Rn, path, TLm, Ai, E)
        r = Rn; ell = None
        if useTL and flap == "chronic":
            xy = self._tlXY(k); mt = _polyMetrics(xy) if xy is not None else None
            if mt and mt["dmin"] / max(mt["dmax"], 1e-6) < 0.8:                 # 三日月・楕円の真腔: 楕円のまま広がる（長軸は真腔の長径の向き）
                a_, b_ = mt["maxLine"]; phi = math.atan2(b_[1] - a_[1], b_[0] - a_[0])
                A = min(Rn, (mt["dmax"] + self.ELL_PLUS) / 2.0); ell = (A, A * self.ELL_RATIO, phi); r = A
        r = float(max(r, 2.0))                                                   # 壁より大きい所は、壁に当たって沿う（下の放射で切る）
        key = (path, int(k), round(r, 1), useTL, id(E), axis, None if ell is None else (round(ell[1], 1), round(ell[2], 2)))
        cache = self.__dict__.setdefault("_depCache", {})
        if key in cache: return cache[key]
        if len(cache) > 6000: cache.clear()
        nu = Ai.shape[0]
        def shapeK():
            kr = int(math.ceil(r / STEP)); yy, xx = np.mgrid[-kr:kr + 1, -kr:kr + 1]
            if ell is None: return ((xx * xx + yy * yy) * STEP * STEP <= r * r).astype(np.float32)
            A, Bm, ph = ell; xu = (xx * math.cos(ph) + yy * math.sin(ph)) * STEP; yv = (-xx * math.sin(ph) + yy * math.cos(ph)) * STEP
            return ((xu / A) ** 2 + (yv / Bm) ** 2 <= 1.0).astype(np.float32)
        if ell is not None:                                                      # 楕円: 壁の中に入る中心だけ
            for _ in range(8):                                                   # 壁の中に入らなければ、少しずつ小さくする
                Kd = shapeK(); feasE = fftconvolve((~Ai).astype(np.float32), Kd, mode="same") < 0.5
                if feasE.any() or r < 4: break
                ell = (ell[0] * 0.92, ell[1] * 0.92, ell[2]); r = ell[0]
        if axis == "cl":                                                         # 作った中心線を軸にする。壁に当たる分だけ、近い所へずらす
            r0 = c0 = HALF / STEP
            ok0 = feasE[int(r0), int(c0)] if ell is not None else E[int(r0), int(c0)] >= r - 0.3
            if not ok0:
                feas = feasE if ell is not None else E >= r - 0.3
                if not feas.any(): feas = E >= E.max() - 0.3
                pts = np.argwhere(feas); j = pts[np.argmin(((pts - (r0, c0)) ** 2).sum(1))]; r0, c0 = float(j[0]), float(j[1])
        else:                                                                    # 真腔をいちばん多く覆う位置へ動かす
            Kd = shapeK()
            ov = fftconvolve(TLm.astype(np.float32), Kd, mode="same")
            feas = feasE if ell is not None else E >= r - 0.3
            if not feas.any(): feas = E >= E.max() - 0.3
            ov[~feas] = -1
            rc, cc = np.argwhere(TLm).mean(0); best = ov.max()
            cand = np.argwhere(ov >= best - max(abs(best) * 0.01, 1e-3)); j = cand[np.argmin(((cand - (rc, cc)) ** 2).sum(1))]   # 同じなら真腔の中心に近い方
            r0, c0 = float(j[0]), float(j[1])
        th = np.linspace(0, 2 * np.pi, self.NTH, endpoint=False); rs = np.arange(0, r + 0.26, 0.25)
        R_ = r0 + np.sin(th)[:, None] * rs[None] / STEP; C_ = c0 + np.cos(th)[:, None] * rs[None] / STEP
        ok = (R_ >= 0) & (R_ <= nu - 1) & (C_ >= 0) & (C_ <= nu - 1)
        ins = np.zeros(ok.shape, bool); ins[ok] = Ai[np.round(R_[ok]).astype(int), np.round(C_[ok]).astype(int)]
        first = np.argmax(~ins, axis=1); first[ins.all(1)] = len(rs) - 1
        Rth = np.maximum(rs[np.maximum(first - 1, 0)], 1.0)                  # 壁に当たる所は壁に沿う
        gy, gx = np.mgrid[0:nu, 0:nu]
        if ell is not None:
            A, Bm, ph = ell; Rth = np.minimum(Rth, A * Bm / np.sqrt((Bm * np.cos(th - ph)) ** 2 + (A * np.sin(th - ph)) ** 2))
            xu = ((gx - c0) * math.cos(ph) + (gy - r0) * math.sin(ph)) * STEP; yv = (-(gx - c0) * math.sin(ph) + (gy - r0) * math.cos(ph)) * STEP
            G = Ai & ((xu / A) ** 2 + (yv / Bm) ** 2 <= 1.0)
        else: G = Ai & (((gy - r0) ** 2 + (gx - c0) ** 2) * STEP * STEP <= r * r)
        gut = float((TLm & ~G).sum() * STEP * STEP) if useTL else 0.0
        out = (c0 * STEP - HALF, r0 * STEP - HALF, Rth, gut, Rn)
        cache[key] = out; return out

    def _deployFixed(self, k, Rn, path, TLm, Ai, E):
        """フラップは動かない: グラフトは術前の真腔の中だけ（細い角はガターとして残る）"""
        from scipy import ndimage
        key = (path, int(k), round(Rn, 1), "fixed", id(E), id(TLm))
        cache = self.__dict__.setdefault("_depCache", {})
        if key in cache: return cache[key]
        G0 = TLm & Ai; rr = max(1, int(round(2.0 / STEP))); yy, xx = np.mgrid[-rr:rr + 1, -rr:rr + 1]
        G = ndimage.binary_opening(G0, structure=(xx * xx + yy * yy) <= rr * rr)
        if G.sum() < 8: G = G0
        D = ndimage.distance_transform_edt(G); j = np.unravel_index(int(np.argmax(D)), D.shape); r0, c0 = float(j[0]), float(j[1])
        nu = G.shape[0]; th = np.linspace(0, 2 * np.pi, self.NTH, endpoint=False); rs = np.arange(0, Rn + 0.26, 0.25)
        R_ = r0 + np.sin(th)[:, None] * rs[None] / STEP; C_ = c0 + np.cos(th)[:, None] * rs[None] / STEP
        ok = (R_ >= 0) & (R_ <= nu - 1) & (C_ >= 0) & (C_ <= nu - 1)
        ins = np.zeros(ok.shape, bool); ins[ok] = G[np.round(R_[ok]).astype(int), np.round(C_[ok]).astype(int)]
        first = np.argmax(~ins, axis=1); first[ins.all(1)] = len(rs) - 1
        Rth = np.maximum(rs[np.maximum(first - 1, 0)], 1.0)
        X = np.c_[Rth * np.cos(th), Rth * np.sin(th)]; ga = 0.5 * abs(np.dot(X[:, 0], np.roll(X[:, 1], -1)) - np.dot(X[:, 1], np.roll(X[:, 0], -1)))
        gut = max(float(TLm.sum() * STEP * STEP) - ga, 0.0)
        out = (c0 * STEP - HALF, r0 * STEP - HALF, Rth, gut, Rn); cache[key] = out; return out

    def _rayLimit(self, k, path, u, v):
        """中心 (u, v) から壁の内側までの距離（72 方向、mm）"""
        E = self._aortaIn(k, path); nu = E.shape[0]; r0, c0 = (v + HALF) / STEP, (u + HALF) / STEP
        th = np.linspace(0, 2 * np.pi, self.NTH, endpoint=False); rs = np.arange(0, 45.0, 0.25)
        R_ = r0 + np.sin(th)[:, None] * rs[None] / STEP; C_ = c0 + np.cos(th)[:, None] * rs[None] / STEP
        ok = (R_ >= 0) & (R_ <= nu - 1) & (C_ >= 0) & (C_ <= nu - 1)
        ins = np.zeros(ok.shape, bool); ins[ok] = E[np.round(R_[ok]).astype(int), np.round(C_[ok]).astype(int)] > 0
        first = np.argmax(~ins, axis=1); first[ins.all(1)] = len(rs) - 1
        return np.maximum(rs[np.maximum(first - 1, 0)], 1.0)

    def _graftGeom(self, lo, hi, Dp, Dd, path):
        """仮想グラフトの形。R = 断面ごとの相当半径、C = 中心。self._graftRad に半径の輪（広がった形）も置く"""
        from scipy import ndimage
        F = self.frames[path]; k0, k1 = self._k(lo, path), self._k(hi, path); ks = np.arange(k0, k1 + 1); n = len(ks)
        t = np.linspace(0.0, 1.0, n); Rn = (Dp + (Dd - Dp) * t) / 2.0
        C = F["P"].copy(); R = Rn.copy(); self._graftRad = None; self._graftNominal = Rn
        pl = getattr(self, "plan", None) or {}
        if path == self.path and self.straight is not None and n >= 2:
            try:
                useTL = bool(pl.get("tl")) and self.tlValid(); flap = pl.get("flap", "chronic")
                samp = list(range(0, n, 2))
                if samp[-1] != n - 1: samp.append(n - 1)
                axis = pl.get("axis") or ("tl" if useTL else "cl")              # 解離: ワイヤーは真腔を通るので、真腔に合わせる
                res = [(i, self._deploy(int(ks[i]), float(Rn[i]), path, flap, useTL, axis)) for i in samp]
                res = [(i, r) for i, r in res if r is not None]
                END = self.GRAFT_END_MM if pl.get("ends") == "asis" else 0.0
                if useTL and flap != "fixed" and END > 0 and res:                 # 端: フラップを押し広げきらず、真腔のあるがままの形へなめらかに戻る
                    sL = (ks - ks[0]) * STEP; dEnd = np.minimum(sL, sL[-1] - sL); new = []
                    for i, r in res:
                        wgt = 1.0 if dEnd[i] >= END else 0.5 - 0.5 * math.cos(math.pi * dEnd[i] / END)
                        if wgt < 0.999:
                            f = self._deploy(int(ks[i]), float(Rn[i]), path, "fixed", useTL, axis)
                            if f is not None: r = tuple(wgt * a + (1 - wgt) * b for a, b in zip(r[:4], f[:4])) + (r[4],)
                        new.append((i, r))
                    res = new
                if len(res) >= 2:
                    idx = np.array([i for i, _ in res]); x = np.arange(n)
                    sm = lambda a, sg: ndimage.gaussian_filter1d(a, sg / STEP, axis=0, mode="nearest")
                    cu = sm(np.interp(x, idx, [r[0] for _, r in res]), 2.0); cv = sm(np.interp(x, idx, [r[1] for _, r in res]), 2.0)
                    if flap == "fixed" and useTL:                                    # 真腔の中だけ: 真腔の形に合わせる
                        cu = sm(np.interp(x, idx, [r[0] for _, r in res]), 1.0); cv = sm(np.interp(x, idx, [r[1] for _, r in res]), 1.0)
                    else:                                                            # グラフトは硬い筒: 軸はなめらかに
                        cu = sm(np.interp(x, idx, [r[0] for _, r in res]), 5.0); cv = sm(np.interp(x, idx, [r[1] for _, r in res]), 5.0)
                    Rs = np.array([r[2] for _, r in res]); Rth = np.stack([np.interp(x, idx, Rs[:, j]) for j in range(Rs.shape[1])], 1)
                    Rth = ndimage.gaussian_filter1d(sm(Rth, 1.5), 1.0, axis=1, mode="wrap"); Rth = np.minimum(Rth, Rn[:, None])
                    lim = np.stack([self._rayLimit(int(ks[i]), path, cu[i], cv[i]) for i in idx])          # なめらかにした後も、壁は越えない
                    Rth = np.minimum(Rth, np.stack([np.interp(x, idx, lim[:, j]) for j in range(lim.shape[1])], 1))
                    C[ks] = F["P"][ks] + cu[:, None] * F["B"][ks] + cv[:, None] * F["N"][ks]
                    R = np.sqrt((Rth ** 2).mean(1))
                    self._graftRad = dict(path=path, ks=ks, Rth=Rth, cu=cu, cv=cv, Rn=Rn, flap=flap, tl=useTL,
                                          gut=np.interp(x, idx, [r[3] for _, r in res]))
            except Exception as e:
                import traceback; print("graft deploy:", traceback.format_exc())
        return F, ks, R, C

    def roundLanding(self, span=30.0, rmin=0.82):
        """左鎖骨下動脈の直下で、断面が正円になる所（分枝の口を過ぎて 短径/長径 ≥ rmin）。その長さも"""
        l = self._mk("左鎖骨下動脈")
        if not l: return None
        rows = []
        for x in np.arange(l["s"], min(l["s"] + span, self.length - 1.0) + 1e-6, 0.5):
            k = self._k(x); m = None
            if self.tlValid():
                xy = self._tlXY(k); m = _polyMetrics(xy) if xy is not None else None
            if m is None: m = self._metK(int(4 * round(k / 4.0)), "lumen")
            if m: rows.append((float(x), m["dmin"] / max(m["dmax"], 1e-6), m["deq"]))
        st = next((i for i, r in enumerate(rows) if r[1] >= rmin and r[0] - l["s"] >= 1.0), None)
        if st is None: return None
        en = st
        while en + 1 < len(rows) and rows[en + 1][1] >= rmin - 0.04: en += 1
        return dict(s=rows[st][0], r=rows[st][1], deq=rows[st][2], length=rows[en][0] - rows[st][0], lsca=l["s"])

    def fit3DToGraft(self, view="lao"):
        """3D をグラフトの範囲（前後 3 cm）に合わせる。lao = 左前斜位、front = 正面、left = 左側面"""
        pl = self.planInit(); F = self.frames[pl["path"]]
        k0, k1 = self._k(pl["p"] - 30.0, pl["path"]), self._k(pl["d"] + 30.0, pl["path"])
        Pk = F["P"][k0:k1 + 1]; ctr = (Pk.min(0) + Pk.max(0)) / 2.0; ext = float(np.ptp(Pk, 0).max()) + 30.0
        v = slicer.app.layoutManager().threeDWidget(0).threeDView()
        cam = slicer.modules.cameras.logic().GetViewActiveCameraNode(v.mrmlViewNode())
        dv = {"lao": (-0.64, 0.77, 0.0), "front": (0.0, 1.0, 0.0), "left": (-1.0, 0.0, 0.0)}[view]
        dv = np.array(dv) / np.linalg.norm(dv); asp = max(v.width, 1) / max(v.height, 1)
        c = cam.GetCamera(); half = ext / 2.0 / min(1.0, asp)
        if c.GetParallelProjection(): c.SetParallelScale(half * 1.05); dist = ext * 2.0
        else: dist = half / math.tan(math.radians(c.GetViewAngle() / 2.0)) * 1.05
        cam.SetFocalPoint(*ctr); cam.SetPosition(*(ctr + dv * dist)); cam.SetViewUp(0, 0, 1); cam.ResetClippingRange()

    def showOverlay3D(self, what, on):
        if what == "aorta":
            vm = getattr(self, "vesselModel", None)
            if vm is not None and slicer.mrmlScene.IsNodePresent(vm):
                d = vm.GetDisplayNode(); d.SetVisibility(bool(on)); d.SetOpacity(0.2)
        elif what == "post":
            for nm, op in (("TEVAR 術後（範囲）", 0.15), ("TEVAR 術後（金属）", 1.0)):   # 実際のステント = 金属そのもの（金色の点）。筒は当てはめた目安（うすく）
                m = slicer.mrmlScene.GetFirstNodeByName(nm)
                if m is not None and m.GetDisplayNode():
                    d = m.GetDisplayNode(); d.SetVisibility(bool(on)); d.SetOpacity(op)
                    if nm.endswith("（金属）"): d.SetPointSize(3.0)

    def _tubeRadPD(self, Cs, B, N, Rth):
        """半径の輪 Rth[k, 72]（角度 = B → N）で、断面の形どおりの筒"""
        from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray
        n, ns = Rth.shape; th = np.linspace(0, 2 * np.pi, ns, endpoint=False)
        pts = (Cs[:, None, :] + Rth[:, :, None] * (np.cos(th)[None, :, None] * B[:, None, :] + np.sin(th)[None, :, None] * N[:, None, :])).reshape(-1, 3)
        i = np.arange(n - 1)[:, None]; j = np.arange(ns)[None, :]; j2 = (j + 1) % ns
        q = np.stack([i * ns + j, i * ns + j2, (i + 1) * ns + j2, (i + 1) * ns + j], -1).reshape(-1, 4)
        cells = np.c_[np.full(len(q), 4), q].astype(np.int64).ravel()
        vp = vtk.vtkPoints(); vp.SetData(numpy_to_vtk(np.ascontiguousarray(pts, np.float64), deep=True))
        ca = vtk.vtkCellArray(); ca.SetCells(len(q), numpy_to_vtkIdTypeArray(cells, deep=True))
        pd = vtk.vtkPolyData(); pd.SetPoints(vp); pd.SetPolys(ca)
        nm = vtk.vtkPolyDataNormals(); nm.SetInputData(pd); nm.SplittingOff(); nm.ConsistencyOn(); nm.Update()
        return nm.GetOutput()

    # SINE の目安: 遠位端での真腔とグラフトの比（参考: 単施設の報告の群の平均。判定基準ではない）
    SINE_REF = dict(pre=dict(mean=(0.61, 0.94), per=(0.50, 0.77), area=(1.98, 4.00)),
                    emr=dict(mean=(1.22, 1.48), per=(1.18, 1.43), area=(1.58, 2.39)))

    def _tlMet(self, s):
        k = self._k(s)
        if not self.tlValid(): return None
        xy = self._tlXY(k)
        if xy is None: return None
        m = _polyMetrics(xy)
        if m is None: return None
        per = float(np.linalg.norm(np.diff(np.r_[xy, xy[:1]], axis=0), axis=1).sum())
        return dict(short=m["dmin"], long=m["dmax"], mean=(m["dmin"] + m["dmax"]) / 2.0, per=per, area=m["area"], s=float(s))

    def sineIdx(self):
        """遠位端: 真腔の短径・長径・周径・面積と、グラフトとの比（術前のオーバーサイズ / 予測した広がりのミスマッチ）"""
        pl = self.planInit()
        if pl["path"] != self.path or not self.tlValid(): return None
        (Dp, _, _), (Dd, _, _) = self.planDiams()
        if not Dd: return None
        a = self._tlMet(pl["d"]); b = self._tlMet(min(pl["d"] + 20.0, self.length - 1.0))
        if a is None: return None
        out = dict(tl=a, tl2=b, Dd=Dd,
                   pre=dict(mean=Dd / a["mean"] - 1, per=math.pi * Dd / a["per"] - 1, area=(math.pi * Dd * Dd / 4) / a["area"] - 1, short=Dd / a["short"] - 1))
        gr = getattr(self, "_graftRad", None)
        if gr is not None and gr["path"] == self.path:
            Rth = gr["Rth"][-1]; th = np.linspace(0, 2 * np.pi, len(Rth), endpoint=False); X = np.c_[Rth * np.cos(th), Rth * np.sin(th)]
            ga = 0.5 * abs(np.dot(X[:, 0], np.roll(X[:, 1], -1)) - np.dot(X[:, 1], np.roll(X[:, 0], -1)))
            gp = float(np.linalg.norm(np.diff(np.r_[X, X[:1]], axis=0), axis=1).sum()); gD = 2 * math.sqrt(ga / math.pi)
            out.update(gD=gD, gper=gp, garea=ga, gut=float(gr["gut"][-1]))
            if b is not None: out["emr"] = dict(mean=gD / b["mean"], per=gp / b["per"], area=ga / b["area"])
        return out

    def planDraw(self):
        pl = self.planInit()
        if not pl.get("on", True): self.planShow(False); return
        (Dp, _, _), (Dd, _, _) = self.planDiams()
        if not Dp or not Dd: return
        if pl.get("tl") and pl["path"] == self.path and not self.tlValid(): self.extractTL(getattr(self, "onStatus", None) or print)
        F, ks, R, C = self._graftGeom(pl["p"], pl["d"], Dp, Dd, pl["path"])
        if len(ks) < 4: return
        self._planDrawn = 2 * R; gr = getattr(self, "_graftRad", None)
        tube = self._tubeRadPD(C[ks], F["B"][ks], F["N"][ks], gr["Rth"]) if gr is not None else self._tubePD(C[ks], F["N"][ks], F["B"][ks], R)
        self._model("TEVAR 計画（布）", tube, (0.88, 0.93, 1.0), 0.45, slice2D=True, spec=0.15)
        self._model("TEVAR 計画（ステント）", self._zStentsPD(F, ks, R, C=C, Rth=None if gr is None else gr["Rth"]), (0.78, 0.8, 0.85), 1.0, spec=0.8)
        self._drawEntries(); self._drawGreen()

    def planShow(self, on):
        for nm in ("TEVAR 計画（布）", "TEVAR 計画（ステント）"):
            m = slicer.mrmlScene.GetFirstNodeByName(nm)
            if m is not None and m.GetDisplayNode(): m.GetDisplayNode().SetVisibility(bool(on))

    # ================================================================ 真腔（解離）: 伸ばした画像の各断面で、中心線から造影された内腔をたどる（フラップで止まる）
    def tlValid(self):
        tl = getattr(self, "tl", None)
        return tl is not None and tl.get("path") == self.path and tl.get("K") == len(self.P) and tl.get("vol") is self.straight

    def extractTL(self, status=print):
        """真腔: 断面ごとに、中心線の点から造影された内腔を広げる。細いすき間（フラップの切れ目・エントリー）は 1 mm の「開き」で切って偽腔へ漏れないようにする"""
        from scipy import ndimage
        if self.straight is None: raise RuntimeError("先に中心線を作ってください")
        a = slicer.util.arrayFromVolume(self.straight); K, nu, _ = a.shape; c0 = nu // 2
        thr = max(120.0, float(self.thr) - 20.0)
        rr, cc = np.mgrid[-2:3, -2:3]; disk = (rr ** 2 + cc ** 2) <= 4
        masks = np.zeros(a.shape, bool); cen = np.full((K, 2), np.nan); area = np.zeros(K)
        prev = (c0, c0); t0 = time.time(); hist = []
        for k in range(K):
            im = a[k]
            pr, pc = int(prev[0]), int(prev[1])
            cv = float(np.median(im[c0 - 2:c0 + 3, c0 - 2:c0 + 3]))
            if cv < thr: cv = float(np.median(im[max(pr - 2, 0):pr + 3, max(pc - 2, 0):pc + 3]))
            if cv < thr: continue
            comp = None
            for f in (0.7, 0.8, 0.88):                                       # 真腔の明るさの 7 割で区切る（フラップの部分容積で漏れない）。急に広がったら上げる
                m = im > max(thr, f * cv)
                lab, n = ndimage.label(ndimage.binary_opening(m, structure=disk))
                if n == 0: break
                l = lab[c0, c0] or lab[pr, pc]
                if not l:
                    idx = np.argwhere(lab > 0); d = ((idx - (c0, c0)) ** 2).sum(1); j = int(np.argmin(d))
                    if d[j] > (10.0 / STEP) ** 2: break
                    l = lab[tuple(idx[j])]
                comp = ndimage.binary_fill_holes(ndimage.binary_dilation(lab == l, structure=disk) & m)
                ref = np.median(hist[-40:]) if len(hist) >= 10 else None
                if ref is None or comp.sum() < 1.8 * ref: break
            if comp is None or not comp.any(): continue
            masks[k] = comp; r_, c_ = np.nonzero(comp); cen[k] = (r_.mean(), c_.mean()); area[k] = comp.sum() * STEP * STEP; prev = cen[k]; hist.append(comp.sum())
            if k % 200 == 0: status(f"真腔をたどっています… {100 * k // K}%")
        ok = np.isfinite(cen[:, 0])
        if ok.sum() < 10: raise RuntimeError("真腔が見つかりませんでした（中心線が真腔を通っているか確認）")
        for j in range(2): cen[:, j] = ndimage.gaussian_filter1d(np.interp(np.arange(K), np.where(ok)[0], cen[ok, j]), 3.0 / STEP)
        u = cen[:, 1] * STEP - HALF; v = cen[:, 0] * STEP - HALF
        C = self.P + u[:, None] * self.B + v[:, None] * self.N
        deq = np.sqrt(4 * area / np.pi); deq[~ok] = np.nan
        self.tl = dict(path=self.path, K=K, vol=self.straight, masks=masks, cen2=cen, C=C, deq=deq)
        status(f"真腔をたどりました（{time.time() - t0:.0f} 秒）。緑の線 = 断面の真腔")
        self._drawTL(); self._showContour(exact=False)
        return self.tl

    def _tlXY(self, k):
        """断面 k の真腔の輪郭（中心からの放射でふち）。(u, v) mm"""
        tl = self.tl; m = tl["masks"][k]
        if not m.any(): return None
        r0, c0 = tl["cen2"][k] if np.isfinite(tl["cen2"][k][0]) else np.argwhere(m).mean(0)
        if not (0 <= int(r0) < m.shape[0] and 0 <= int(c0) < m.shape[1]) or not m[int(r0), int(c0)]:
            r0, c0 = np.argwhere(m).mean(0)
        th = np.linspace(0, 2 * np.pi, 96, endpoint=False); out = []
        for t in th:
            dr, dc = math.sin(t), math.cos(t); s_ = 0.0
            while True:
                r, c = int(round(r0 + dr * (s_ + 0.5))), int(round(c0 + dc * (s_ + 0.5)))
                if not (0 <= r < m.shape[0] and 0 <= c < m.shape[1]) or not m[r, c]: break
                s_ += 0.5
            out.append(((c0 + dc * s_) * STEP - HALF, (r0 + dr * s_) * STEP - HALF))
        return np.array(out)

    def extractFL(self, status=print):
        """造影される偽腔: 伸ばした画像で、大動脈の壁の内側・真腔の外にある造影された所"""
        from scipy import ndimage
        if not self.tlValid(): self.extractTL(status)
        a = slicer.util.arrayFromVolume(self.straight); K, nu, _ = a.shape
        thr = max(120.0, float(self.thr) - 20.0); fl = np.zeros(a.shape, bool); area = np.zeros(K)
        for k in range(K):
            E = self._aortaIn(k, self.path)
            if E is None: continue
            m = (a[k] > thr) & (E > 0) & ~ndimage.binary_dilation(self.tl["masks"][k], iterations=2)
            if m.sum() < 16: continue
            lab, n = ndimage.label(ndimage.binary_opening(m))
            if n == 0: continue
            sz = np.bincount(lab.ravel()); keep = np.where(sz >= 16)[0]; keep = keep[keep > 0]
            fl[k] = np.isin(lab, keep); area[k] = fl[k].sum() * STEP * STEP
            if k % 300 == 0: status(f"偽腔をたどっています… {100 * k // K}%")
        on = area >= 20.0; run = np.convolve(on.astype(int), np.ones(6, int), "same") >= 6
        st = int(np.argmax(run)) if run.any() else None
        self.fl = dict(path=self.path, K=K, vol=self.straight, masks=fl, area=area, start=(float(self.s[max(st - 3, 0)]) if st is not None else None))
        self._drawMask(fl, "TEVAR 偽腔", (0.72, 0.42, 0.95), 0.3)
        return self.fl

    def flValid(self):
        fl = getattr(self, "fl", None)
        return fl is not None and fl.get("path") == self.path and fl.get("K") == len(self.P) and fl.get("vol") is self.straight

    def _drawMask(self, masks, name, color, opacity):
        from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy
        from scipy import ndimage
        m = ndimage.binary_closing(masks, iterations=1).astype(np.uint8)
        img = vtk.vtkImageData(); K, nu, _ = m.shape; img.SetDimensions(nu, nu, K)
        img.GetPointData().SetScalars(numpy_to_vtk(m.ravel(), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR))
        fe = vtk.vtkDiscreteFlyingEdges3D(); fe.SetInputData(img); fe.SetValue(0, 1); fe.Update()
        sm = vtk.vtkWindowedSincPolyDataFilter(); sm.SetInputConnection(fe.GetOutputPort()); sm.SetNumberOfIterations(25); sm.SetPassBand(0.05); sm.NormalizeCoordinatesOn(); sm.Update()
        pd = sm.GetOutput()
        if pd.GetNumberOfPoints() == 0: return
        X = vtk_to_numpy(pd.GetPoints().GetData()).astype(float)
        kf = np.clip(X[:, 2], 0, K - 1); k0 = np.floor(kf).astype(int); k1 = np.minimum(k0 + 1, K - 1); f = (kf - k0)[:, None]
        lerp = lambda A: A[k0] * (1 - f) + A[k1] * f
        Q = lerp(self.P) + (X[:, 0] * STEP - HALF)[:, None] * lerp(self.B) + (X[:, 1] * STEP - HALF)[:, None] * lerp(self.N)
        pd.GetPoints().SetData(numpy_to_vtk(np.ascontiguousarray(Q), deep=True))
        nm = vtk.vtkPolyDataNormals(); nm.SetInputData(pd); nm.SplittingOff(); nm.ConsistencyOn(); nm.AutoOrientNormalsOn(); nm.Update()
        self._model(name, nm.GetOutput(), color, opacity, spec=0.2)

    def _drawTL(self):
        """真腔の 3D（うすい水色）"""
        tl = getattr(self, "tl", None)
        if tl is None: return
        from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy
        from scipy import ndimage
        m = ndimage.binary_closing(tl["masks"], iterations=1).astype(np.uint8)
        img = vtk.vtkImageData(); K, nu, _ = m.shape; img.SetDimensions(nu, nu, K)
        img.GetPointData().SetScalars(numpy_to_vtk(m.ravel(), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR))
        fe = vtk.vtkDiscreteFlyingEdges3D(); fe.SetInputData(img); fe.SetValue(0, 1); fe.Update()
        sm = vtk.vtkWindowedSincPolyDataFilter(); sm.SetInputConnection(fe.GetOutputPort()); sm.SetNumberOfIterations(25); sm.SetPassBand(0.05); sm.NormalizeCoordinatesOn(); sm.Update()
        pd = sm.GetOutput()
        if pd.GetNumberOfPoints() == 0: return
        X = vtk_to_numpy(pd.GetPoints().GetData()).astype(float)          # (列, 行, k) → 3D
        kf = np.clip(X[:, 2], 0, K - 1); k0 = np.floor(kf).astype(int); k1 = np.minimum(k0 + 1, K - 1); f = (kf - k0)[:, None]
        lerp = lambda A: A[k0] * (1 - f) + A[k1] * f
        Q = lerp(self.P) + (X[:, 0] * STEP - HALF)[:, None] * lerp(self.B) + (X[:, 1] * STEP - HALF)[:, None] * lerp(self.N)
        pd.GetPoints().SetData(numpy_to_vtk(np.ascontiguousarray(Q), deep=True))
        nm = vtk.vtkPolyDataNormals(); nm.SetInputData(pd); nm.SplittingOff(); nm.ConsistencyOn(); nm.AutoOrientNormalsOn(); nm.Update()
        self._model("TEVAR 真腔", nm.GetOutput(), (0.35, 0.75, 1.0), 0.35, spec=0.2)

    # ---- エントリー（断面をクリックして置く）
    def addEntry(self, ras):
        es = self.__dict__.setdefault("entries", [])
        name = f"エントリー{len(es) + 1}"
        es.append(dict(name=name, s=float(self.curS), path=self.path, xyz=[float(x) for x in ras]))
        self._drawEntries(); self._listsChanged(); return name

    def removeEntry(self, name):
        self.entries = [e for e in getattr(self, "entries", []) if e["name"] != name]
        for i, e in enumerate(self.entries): e["name"] = f"エントリー{i + 1}"
        self._drawEntries(); self._listsChanged()

    def coverage(self, lo, hi):
        """エントリー・分枝を、範囲 lo〜hi（中心線の mm）のグラフトが覆うか"""
        rows = []
        for e in getattr(self, "entries", []):
            s = e["s"]
            if lo <= s <= hi:
                m = min(s - lo, hi - s)
                rows.append(dict(kind="entry", name=e["name"], s=s, state="cover" if m >= 10 else "edge",
                                 text=f"覆う（端まで {m:.0f} mm）" if m >= 10 else f"覆うが端に近い（{m:.0f} mm）"))
            else:
                rows.append(dict(kind="entry", name=e["name"], s=s, state="open", text=f"覆わない（{(lo - s) if s < lo else (s - hi):.0f} mm 外）"))
        for mk in self.markers:
            nm = mk["name"].replace("（推定）", "")
            if not (nm in self.BRANCH_NAMES or (nm.endswith("動脈") and not nm.startswith("入口"))): continue
            s = mk["s"]
            if lo <= s <= hi: rows.append(dict(kind="branch", name=nm, s=s, state="block", text="この分枝を覆う"))
            else:
                gap = (lo - s) if s < lo else (s - hi)
                rows.append(dict(kind="branch", name=nm, s=s, state="ok", text=f"{'近位端' if s < lo else '遠位端'}まで {gap:.0f} mm"))
        rows.sort(key=lambda r: r["s"]); return rows

    def _drawEntries(self):
        pl = getattr(self, "plan", None); lo, hi = (pl["p"], pl["d"]) if pl else (1e9, -1e9)
        st = {e["name"]: r["state"] for r in self.coverage(lo, hi) for e in getattr(self, "entries", []) if r["name"] == e["name"]}
        for state, label in (("cover", "覆う"), ("edge", "端"), ("open", "覆わない")):
            n = self._node("vtkMRMLMarkupsFiducialNode", f"TEVAR エントリー（{label}）", ("vtkMRMLViewNode1", "vtkMRMLSliceNodeRed"),
                           self.STATE_COL[state], glyph=3.0, text=3.0)
            wasMod = n.StartModify(); n.RemoveAllControlPoints()
            for e in getattr(self, "entries", []):
                if st.get(e["name"], "open") == state:
                    i = n.AddControlPoint(vtk.vtkVector3d(*e["xyz"])); n.SetNthControlPointLabel(i, "E" + e["name"][len("エントリー"):])
            n.EndModify(wasMod)

    # ---- 術後 CT
    def loadPostFolder(self, folder, status=print):
        """術後 CT のフォルダから、造影・軸位で一番薄いシリーズを選んで読み込む（院内 PC の中だけ）"""
        import pydicom
        from concurrent.futures import ThreadPoolExecutor
        files = [os.path.join(dp, f) for dp, dn, fn in os.walk(folder) for f in fn]
        status(f"術後 CT: {len(files)} ファイルを調べています…")
        def hdr(p):
            try:
                d = pydicom.dcmread(p, stop_before_pixels=True, force=True)
                it = str(getattr(d, "ImageType", ""))
                if "LOCALIZER" in it or "SECONDARY" in it or str(getattr(d, "Modality", "")) != "CT": return None
                iop = [float(x) for x in d.ImageOrientationPatient]
                if abs(iop[0]) < 0.9 or abs(iop[4]) < 0.9: return None             # 軸位だけ
                return (p, str(d.SeriesInstanceUID), bool(str(getattr(d, "ContrastBolusAgent", "")).strip()), "ORIGINAL" in it,
                        float(getattr(d, "SliceThickness", 0) or 0), int(d.Rows))
            except Exception: return None
        with ThreadPoolExecutor(8) as ex: H = [h for h in ex.map(hdr, files) if h]
        by = {}
        for h in H: by.setdefault(h[1], []).append(h)
        cand = [(v[0][2], -v[0][4], len(v) * max(v[0][4], 0.5), v[0][3], uid) for uid, v in by.items() if len(v) >= 30 and v[0][5] >= 256]
        if not cand: raise RuntimeError("術後 CT の軸位シリーズが見つかりませんでした")
        cand.sort(reverse=True); uid = cand[0][-1]; paths = [h[0] for h in by[uid]]
        status(f"術後 CT: {len(paths)} 枚（{-cand[0][1]:g} mm）を読み込み中…")
        def rd(p):
            d = pydicom.dcmread(p, force=True)
            a = d.pixel_array.astype(np.float32) * float(getattr(d, "RescaleSlope", 1) or 1) + float(getattr(d, "RescaleIntercept", 0) or 0)
            return [float(x) for x in d.ImagePositionPatient], [float(x) for x in d.PixelSpacing], [float(x) for x in d.ImageOrientationPatient], np.clip(a, -1024, 4000).astype(np.int16)
        with ThreadPoolExecutor(8) as ex: S = list(ex.map(rd, paths))
        r = np.array(S[0][2][:3]); c = np.array(S[0][2][3:]); n = np.cross(r, c)
        S.sort(key=lambda x: float(np.dot(x[0], n)))
        pos = np.array([float(np.dot(x[0], n)) for x in S]); dz = float(np.median(np.diff(pos))) if len(S) > 1 else 1.0
        arr = np.stack([x[3] for x in S]); ps = S[0][1]; o = np.array(S[0][0])
        M = np.eye(4); M[:3, 0] = r * ps[1]; M[:3, 1] = c * ps[0]; M[:3, 2] = n * dz; M[:3, 3] = o
        M = np.diag([-1, -1, 1, 1]) @ M                                              # LPS → RAS
        node = slicer.mrmlScene.GetFirstNodeByName("術後 CT")
        if node is None: node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "術後 CT")
        slicer.util.updateVolumeFromArray(node, arr)
        m = vtk.vtkMatrix4x4()
        for i in range(4):
            for j in range(4): m.SetElement(i, j, float(M[i, j]))
        node.SetIJKToRASMatrix(m); node.CreateDefaultDisplayNodes()
        dn = node.GetDisplayNode(); dn.SetAutoWindowLevel(False); dn.SetWindowLevel(800, 200)
        self.post = node; self.postT = None
        status(f"術後 CT を読み込みました（{arr.shape[0]} 枚・{dz:.1f} mm 間隔）")
        return node

    @staticmethod
    def _volPts(vol, mask, stride=(1, 1, 1)):
        idx = np.argwhere(mask) * np.array(stride)
        m = vtk.vtkMatrix4x4(); vol.GetIJKToRASMatrix(m)
        A = np.array([[m.GetElement(r, c) for c in range(4)] for r in range(4)])
        return idx[:, ::-1] @ A[:3, :3].T + A[:3, 3]

    def registerPost(self, status=print):
        """術後 CT を術前に重ねる（グラフトのまわりの背骨・肋骨で剛体の位置合わせ）。戻り値: 4×4（術後 → 術前）と誤差 mm"""
        from scipy.spatial import cKDTree
        post = getattr(self, "post", None)
        if post is None: raise RuntimeError("先に術後 CT を読み込んでください")
        pl = self.planInit(); F = self.frames[pl["path"]]
        def stride(vol):
            sp = vol.GetSpacing(); return tuple(int(max(1, round(2.0 / x))) for x in (sp[2], sp[1], sp[0]))
        a0 = slicer.util.arrayFromVolume(self.vol); s0 = stride(self.vol)
        a1 = slicer.util.arrayFromVolume(post); s1 = stride(post)
        bo = self._boneRaw()                                                          # 術前は AI の骨ラベルの中だけ（造影された血管・心臓を骨と取り違えない）
        m0 = a0[::s0[0], ::s0[1], ::s0[2]] > 400
        if bo is not None: m0 &= bo[::s0[0], ::s0[1], ::s0[2]]
        B0 = self._volPts(self.vol, m0, s0)
        B1 = self._volPts(post, a1[::s1[0], ::s1[1], ::s1[2]] > 400, s1)             # 術後は皮質骨くらいの高さ（造影の血管より上）
        self._regPts = (B0, B1)
        lo, hi = max(0.0, pl["p"] - 60.0), min(F["length"], pl["d"] + 60.0)
        C = F["P"][self._k(lo, pl["path"]):self._k(hi, pl["path"]) + 1:4]
        d0, _ = cKDTree(C).query(B0, distance_upper_bound=90.0); T0 = B0[np.isfinite(d0)]          # グラフトのまわり 9 cm の骨
        if len(T0) < 500: raise RuntimeError("位置合わせに使う骨が足りません")
        status(f"位置合わせ: 骨の点 術前 {len(T0)} / 術後 {len(B1)}")
        # 1) 体軸方向のずれ: 骨の量の縦の分布をずらして合わせる
        bins = np.arange(-1500, 3000, 5.0)
        h0 = np.histogram(B0[:, 2], bins)[0].astype(float); h1 = np.histogram(B1[:, 2], bins)[0].astype(float)
        h0 = (h0 - h0.mean()) / (h0.std() + 1e-9); h1 = (h1 - h1.mean()) / (h1.std() + 1e-9)
        best = max(range(-140, 141), key=lambda k: float(np.dot(h0, np.roll(h1, k))))
        dz = best * 5.0
        zlo, zhi = T0[:, 2].min() - dz, T0[:, 2].max() - dz
        S1 = B1[(B1[:, 2] > zlo - 40) & (B1[:, 2] < zhi + 40)]
        t = np.array([np.median(T0[:, 0]) - np.median(S1[:, 0]), np.median(T0[:, 1]) - np.median(S1[:, 1]), dz])
        Rm = np.eye(3); tree = cKDTree(T0)
        if len(S1) > 60000: S1 = S1[np.random.default_rng(0).choice(len(S1), 60000, replace=False)]
        # 2) ICP（近い点どうしを少しずつ合わせる。遠い点は外す）
        rms = None
        for it in range(60):
            X = S1 @ Rm.T + t; d, j = tree.query(X)
            lim = max(4.0, 25.0 * (0.92 ** it)); ok = d < lim
            if ok.sum() < 200: break
            ok &= d <= np.percentile(d[ok], 85)
            A, Bq = X[ok], T0[j[ok]]; ca, cb = A.mean(0), Bq.mean(0)
            U, _, Vt = np.linalg.svd((A - ca).T @ (Bq - cb)); D = np.diag([1, 1, np.sign(np.linalg.det(Vt.T @ U.T))])
            dR = Vt.T @ D @ U.T; Rm = dR @ Rm; t = dR @ (t - ca) + cb
            rms = float(np.sqrt(np.mean(d[ok] ** 2)))
        M = np.eye(4); M[:3, :3] = Rm; M[:3, 3] = t
        self.postT = M; self.postRms = rms
        tn = slicer.mrmlScene.GetFirstNodeByName("術後→術前") or slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode", "術後→術前")
        vm = vtk.vtkMatrix4x4()
        for i in range(4):
            for j in range(4): vm.SetElement(i, j, float(M[i, j]))
        tn.SetMatrixTransformToParent(vm); post.SetAndObserveTransformNodeID(tn.GetID())
        status(f"位置合わせ: 骨のずれ {rms:.1f} mm（体軸方向 {dz:.0f} mm 移動）")
        return M, rms

    @staticmethod
    def _icp(S, tree, T0, Rm, t, iters=40, lim0=25.0):
        rms = None
        for it in range(iters):
            X = S @ Rm.T + t; d, j = tree.query(X)
            lim = max(3.0, lim0 * (0.9 ** it)); ok = d < lim
            if ok.sum() < 150: return Rm, t, None
            ok &= d <= np.percentile(d[ok], 85)
            A, Bq = X[ok], T0[j[ok]]; ca, cb = A.mean(0), Bq.mean(0)
            U, _, Vt = np.linalg.svd((A - ca).T @ (Bq - cb)); D = np.diag([1, 1, np.sign(np.linalg.det(Vt.T @ U.T))])
            dR = Vt.T @ D @ U.T; Rm = dR @ Rm; t = dR @ (t - ca) + cb
            rms = float(np.sqrt(np.mean(d[ok] ** 2)))
        return Rm, t, rms

    def extractStent(self, thr=450.0, status=print):
        """術後 CT の金属（ステントの骨組み）を拾い、中心線に沿った範囲を出す。
        体の曲がり方は術前と術後で少し違うので、中心線に沿って 4 cm ごとに背骨で合わせ直してから拾う（区間ごとの剛体）"""
        from scipy.spatial import cKDTree
        post = self.post; M = self.postT; pl = self.planInit(); path = pl["path"]; F = self.frames[path]
        B0, B1 = self._regPts
        a1 = slicer.util.arrayFromVolume(post)
        Y = self._volPts(post, a1 > thr)                                             # 術後の座標の金属・骨の候補
        Xg = Y @ M[:3, :3].T + M[:3, 3]
        dg, kg = cKDTree(F["P"]).query(Xg); sg = F["s"][kg]
        self._ensureArrF(); A = self._rasToIjk; aoD, boD = self._tvMasks(); sh = self.arr.shape
        t0 = cKDTree(B0); B1g = B1 @ M[:3, :3].T + M[:3, 3]
        keepX, keepS, segs = [], [], []
        L_ = F["length"]; c = 0.0
        while c < L_:
            lo, hi = c - 20.0, c + 20.0; c += 30.0
            sel = (sg >= lo) & (sg < hi) & (dg < 45.0)
            if sel.sum() == 0: continue
            k0, k1 = self._k(max(lo, 0), path), self._k(min(hi, L_), path); C = F["P"][k0:k1 + 1:4]
            cT = cKDTree(C); dT, _ = cT.query(B0, distance_upper_bound=80.0); T0 = B0[np.isfinite(dT)]
            dS, _ = cT.query(B1g, distance_upper_bound=95.0); S = B1[np.isfinite(dS)]
            if len(T0) < 300 or len(S) < 300: continue
            if len(S) > 30000: S = S[np.random.default_rng(1).choice(len(S), 30000, replace=False)]
            Rm, t, rms = self._icp(S, cKDTree(T0), T0, M[:3, :3].copy(), M[:3, 3].copy(), iters=30, lim0=8.0)
            segs.append((c - 30.0, rms)); self.__dict__.setdefault("_segT", {})[c - 30.0] = (Rm, t)
            if rms is None or rms > 3.5: continue                                     # この区間は骨が合わない → 使わない
            X = Y[sel] @ Rm.T + t
            I = np.round(X @ A[:3, :3].T + A[:3, 3]).astype(int)
            inb = (I[:, 0] >= 0) & (I[:, 0] < sh[2]) & (I[:, 1] >= 0) & (I[:, 1] < sh[1]) & (I[:, 2] >= 0) & (I[:, 2] < sh[0])
            X, I = X[inb], I[inb]
            ok = self.arr[I[:, 2], I[:, 1], I[:, 0]] < 600.0                           # 術前から高い所（骨・石灰化）は除く
            if aoD is not None: ok &= aoD[I[:, 2], I[:, 1], I[:, 0]]                    # 術前の大動脈（少し広げる）の中だけ
            if boD is not None: ok &= ~boD[I[:, 2], I[:, 1], I[:, 0]]                   # 骨（少し広げる）は除く
            X = X[ok]
            if len(X) == 0: continue
            d, k = cKDTree(F["P"]).query(X); s = F["s"][k]; m = (s >= c - 45.0) & (s < c - 15.0)    # 区間の真ん中 3 cm だけ使う（重なりなし）
            keepX.append(X[m]); keepS.append(s[m])
        self._segRms = segs
        if not keepX or sum(len(x) for x in keepX) < 30: raise RuntimeError("術後 CT にステントの金属が見つかりませんでした")
        X = np.concatenate(keepX); s = np.concatenate(keepS)
        # 中心線に沿って 2 mm ごとに数え、すき間 20 mm 以内でつながる、いちばん点の多い範囲をグラフトとする
        b = np.floor(s / 2.0).astype(int); cnt = np.bincount(b, minlength=b.max() + 1); occ = np.where(cnt >= 3)[0]
        runs = []; st = occ[0]; pv = occ[0]
        for x in occ[1:]:
            if (x - pv) * 2.0 > 20.0: runs.append((st, pv)); st = x
            pv = x
        runs.append((st, pv)); r0, r1 = max(runs, key=lambda r: cnt[r[0]:r[1] + 1].sum())
        lo, hi = r0 * 2.0, (r1 + 1) * 2.0
        sel = (s >= lo - 2) & (s <= hi + 2); X, s = X[sel], s[sel]
        self.actual = dict(lo=float(lo), hi=float(hi), pts=X, s=s, path=path)
        bad = [f"{a:.0f}" for a, r in segs if r is None or r > 3.5]
        status(f"術後のグラフト: 中心線 {lo:.0f}〜{hi:.0f} mm（{hi - lo:.0f} mm）・金属 {len(X)} 点" + (f"（骨が合わない区間 {len(bad)} か所は除外）" if bad else ""))
        self._drawActual(); self._drawGreen()
        return self.actual

    def _tvMasks(self):
        if getattr(self, "_tvMask", None) is None or self._tvMask[2] is not self.vol:
            from scipy import ndimage
            sp = self.vol.GetSpacing(); it = lambda mm, ax: max(1, int(round(mm / sp[ax])))
            def dil(m, mm):
                if m is None: return None
                st = np.zeros((3, 3, 3), bool); st[1, 1, :] = st[1, :, 1] = st[:, 1, 1] = True
                out = m
                for _ in range(max(it(mm, 0), it(mm, 2))): out = ndimage.binary_dilation(out, st)
                return out
            ao = self._mask(("aorta",))
            bo = self._mask(("vertebra", "rib", "sternum", "clavicula", "scapula", "hip", "sacrum", "femur", "humerus", "costal"))
            self._tvMask = (dil(ao, 3.0), dil(bo, 1.5), self.vol, bo)
        return self._tvMask[0], self._tvMask[1]

    def _boneRaw(self):
        self._tvMasks(); return self._tvMask[3]

    def _drawActual(self):
        ac = getattr(self, "actual", None)
        if ac is None: return
        from vtk.util.numpy_support import numpy_to_vtk
        vp = vtk.vtkPoints(); vp.SetData(numpy_to_vtk(np.ascontiguousarray(ac["pts"], np.float64), deep=True))
        pd = vtk.vtkPolyData(); pd.SetPoints(vp)
        vg = vtk.vtkVertexGlyphFilter(); vg.SetInputData(pd); vg.Update()
        m = self._model("TEVAR 術後（金属）", vg.GetOutput(), (1.0, 0.72, 0.2), 1.0, spec=0.6)
        d = m.GetDisplayNode(); d.SetPointSize(4.0)
        try: d.SetRepresentation(d.PointsRepresentation)
        except Exception: pass
        try: d.SetRenderPointsAsSpheres(True)
        except Exception: pass
        # 実際のグラフトの筒（うすい金色）: 断面ごとに金属の輪へ円を当てはめた中心と径。計画の白い筒と並べて比べる
        self._fitRings()
        if ac.get("C") is not None:
            F = self.frames[ac["path"]]; ks = ac["ks"]
            self._model("TEVAR 術後（範囲）", self._tubePD(ac["C"], F["N"][ks], F["B"][ks], ac["R"] + 0.6), (1.0, 0.75, 0.3), 0.25, spec=0.1)

    def _fitRings(self):
        """術後の金属を、中心線の各断面（前後 4 mm）で円に当てはめる → 実際のグラフトの中心と半径"""
        ac = self.actual; F = self.frames[ac["path"]]
        from scipy.spatial import cKDTree
        from scipy import ndimage
        k0, k1 = self._k(ac["lo"], ac["path"]), self._k(ac["hi"], ac["path"]); ks = np.arange(k0, k1 + 1)
        X = ac["pts"]; _, kk = cKDTree(F["P"]).query(X)
        d = X - F["P"][kk]; u = (d * F["B"][kk]).sum(1); v = (d * F["N"][kk]).sum(1)
        cu = np.full(len(ks), np.nan); cv = np.full(len(ks), np.nan); rr = np.full(len(ks), np.nan); w = int(4.0 / STEP)
        for i in range(0, len(ks), 4):
            m = np.abs(kk - ks[i]) <= w
            if m.sum() < 12: continue
            A = np.c_[u[m], v[m], np.ones(m.sum())]; b = u[m] ** 2 + v[m] ** 2
            try: sol = np.linalg.lstsq(A, b, rcond=None)[0]
            except Exception: continue
            x0, y0 = sol[0] / 2, sol[1] / 2; r = math.sqrt(max(sol[2] + x0 * x0 + y0 * y0, 0))
            ang = np.sort(np.arctan2(v[m] - y0, u[m] - x0)); gap = np.max(np.diff(np.r_[ang, ang[0] + 2 * np.pi]))
            if 6.0 <= r <= 30.0 and gap < np.pi * 0.8: cu[i], cv[i], rr[i] = x0, y0, r      # 輪の半分以上に金属がある時だけ
        ok = np.isfinite(rr)
        if ok.sum() < 3: ac["C"] = None; return
        idx = np.arange(len(ks)); sm = lambda a: ndimage.gaussian_filter1d(np.interp(idx, idx[ok], a[ok]), 3.0 / STEP, mode="nearest")
        cu, cv, rr = sm(cu), sm(cv), sm(rr)
        ac.update(ks=ks, C=F["P"][ks] + cu[:, None] * F["B"][ks] + cv[:, None] * F["N"][ks], R=rr, fitOK=ok)

    def comparePost(self):
        """計画と術後の違い（中心線に沿った mm。＋ は遠位＝足側へずれた）"""
        pl = self.planInit(); ac = getattr(self, "actual", None)
        if ac is None: return None
        lo, hi = ac["lo"], ac["hi"]
        out = dict(dP=lo - pl["p"], dD=hi - pl["d"], planLen=pl["d"] - pl["p"], realLen=hi - lo, rms=getattr(self, "postRms", None),
                   zres=float(self.post.GetSpacing()[2]) if getattr(self, "post", None) is not None else None,
                   rows=self.coverage(lo, hi))
        try:
            if ac.get("C") is not None and pl["path"] == ac["path"]:
                (Dp, _, _), (Dd, _, _) = self.planDiams()
                F, ksP, Rp, Cp = self._graftGeom(pl["p"], pl["d"], Dp, Dd, pl["path"])
                both = np.intersect1d(ksP, ac["ks"])
                if len(both) > 4:
                    iP = both - ksP[0]; iA = both - ac["ks"][0]
                    off = np.linalg.norm(Cp[both] - ac["C"][iA], axis=1)
                    Rn = getattr(self, "_graftNominal", None)
                    if Rn is not None and len(Rn) == len(Rp): out["Dnom"] = float(np.median(2 * Rn[iP]))
                    out.update(Dplan=float(np.median(2 * Rp[iP])), Dreal=float(np.median(2 * ac["R"][iA])),
                               DrealMin=float(np.min(2 * ac["R"][iA])), DrealMax=float(np.max(2 * ac["R"][iA])),
                               offMed=float(np.median(off)), offMax=float(np.max(off)), offAt=float(self.frames[pl["path"]]["s"][both[int(np.argmax(off))]]))
        except Exception as e: print("compare geom:", e)
        return out

    def _postShiftAt(self, ks):
        """断面 ks での、大動脈の外形で合わせ直したずれ（術前の座標で 3D のベクトル、mm）。無ければ 0"""
        ps = getattr(self, "postShift", None)
        if ps is None or ps.get("path") != self.path: return np.zeros((len(ks), 3))
        x = self.s[np.asarray(ks)]
        return np.stack([np.interp(x, ps["s"], ps["t"][:, j]) for j in range(3)], 1)

    def refinePost(self, status=print, lo=None, hi=None, seg=15.0, half=20.0):
        """背骨で合わせた術後 CT を、中心線に沿った区間ごとに大動脈の外形でもう一度合わせる（3D の平行移動、区間どうしはなめらかに）。
        呼吸・体位で大動脈は背骨に対して数 mm〜1 cm ずれ、弓部では頭尾方向にもずれるため。金属（実際のグラフト）もこの合わせ方で拾い直す"""
        from scipy import ndimage
        self.postShift = None
        post = self.post; a = np.clip(slicer.util.arrayFromVolume(post).astype(np.float32), -150, 150)
        m = vtk.vtkMatrix4x4(); post.GetIJKToRASMatrix(m)
        A = np.linalg.inv(np.array([[m.GetElement(r, c) for c in range(4)] for r in range(4)])) @ np.linalg.inv(self.postT)
        ac = getattr(self, "actual", None); pl = getattr(self, "plan", None) or {}
        lo = lo if lo is not None else min([v for v in (ac and ac["lo"], pl.get("p")) if v is not None] or [0.0]) - 30.0
        hi = hi if hi is not None else max([v for v in (ac and ac["hi"], pl.get("d")) if v is not None] or [self.length]) + 30.0
        lo, hi = max(lo, 0.0), min(hi, self.length - 1.0)
        nu = int(round(2 * HALF / STEP)) + 1; g = np.arange(nu) * STEP - HALF; rng = np.random.default_rng(0)
        IN, SH, KK = [], [], []                                                       # 断面ごとに、外周の内側（壁 1.5 mm を除く）と外側 2〜6 mm の点
        for k in range(self._k(lo), self._k(hi) + 1, 4):
            xy = self._section(k, "outer")
            if xy is None or len(xy) < 6: continue
            Mk = _rasterPoly(np.asarray(xy, float), nu); Din = ndimage.distance_transform_edt(Mk) * STEP; Dout = ndimage.distance_transform_edt(~Mk) * STEP
            for msk, lst in (((Din > 1.5), IN), (((Dout > 2) & (Dout < 6)), SH)):
                rc = np.argwhere(msk)
                if len(rc) > 150: rc = rc[rng.choice(len(rc), 150, replace=False)]
                lst.append(self.P[k] + g[rc[:, 1]][:, None] * self.B[k] + g[rc[:, 0]][:, None] * self.N[k])
            KK.append(k)
        if len(KK) < 5: status("大動脈の外形で合わせ直せませんでした（背骨の重ね合わせのまま）"); return None
        kin = np.repeat(KK, [len(x) for x in IN]); ksh = np.repeat(KK, [len(x) for x in SH]); IN = np.concatenate(IN); SH = np.concatenate(SH)
        def val(X, t):
            H = (X + t) @ A[:3, :3].T + A[:3, 3]
            return ndimage.map_coordinates(a, [H[:, 2], H[:, 1], H[:, 0]], order=1, mode="nearest")
        out = []; t_prev = np.zeros(3)
        for c in np.arange(lo + half, hi - half + 1e-6, seg) if hi - lo > 2 * half else [0.5 * (lo + hi)]:
            mi = np.abs(self.s[kin] - c) <= half; ms = np.abs(self.s[ksh] - c) <= half
            if mi.sum() < 200 or ms.sum() < 200: continue
            Xi, Xs = IN[mi], SH[ms]
            sc = lambda t: val(Xi, t).mean() - val(Xs, t).mean()
            kc = self._k(c); Bc, Nc = self.B[kc], self.N[kc]                          # 断面の中だけで動かす（長さ方向は外形では決まらないので背骨合わせのまま）
            s0 = sc(np.zeros(3)); best = (s0, np.zeros(3), 0.0, 0.0)
            for step, span in ((1.5, 12.0), (0.5, 1.5)):
                c0u, c0v = best[2], best[3]; ax = np.arange(-span, span + 1e-6, step)
                for du in ax:
                    for dv in ax:
                        t = (c0u + du) * Bc + (c0v + dv) * Nc; v = sc(t)
                        if v > best[0]: best = (v, t, c0u + du, c0v + dv)
            if best[0] - s0 < 3.0: best = (s0, np.zeros(3), 0.0, 0.0)                # はっきり良くならなければ動かさない
            out.append((c, *best[1], best[0] - s0)); status(f"大動脈の外形で合わせ直しています… {self.rel(c):.0f} mm")
        if len(out) < 2: status("大動脈の外形で合わせ直せませんでした（背骨の重ね合わせのまま）"); return None
        O = np.array(out); T = O[:, 1:4]
        if len(T) >= 3: T = ndimage.median_filter(T, size=(3, 1), mode="nearest")
        T = ndimage.gaussian_filter1d(T, 1.0, axis=0, mode="nearest")
        self.postShift = dict(path=self.path, s=O[:, 0], t=T, mag=np.linalg.norm(T, axis=1))
        mag = self.postShift["mag"]
        status(f"術後 CT を大動脈の外形で合わせ直しました（背骨合わせからのずれ 中央値 {np.median(mag):.1f} mm・最大 {mag.max():.1f} mm）")
        self._restent(status)
        return self.postShift

    def _restent(self, status=print, thr=450.0):
        """金属（ステント）を拾い直す: 術後 CT の金属の画素を、背骨の重ね合わせ → 大動脈の外形で合わせ直したずれ の順に術前の座標へ"""
        from scipy.spatial import cKDTree
        ac = getattr(self, "actual", None)
        if ac is None or ac.get("path") != self.path: return
        if "pts0" not in ac: ac["pts0"] = ac["pts"]
        M = self.postT; a1 = slicer.util.arrayFromVolume(self.post)
        Y = self._volPts(self.post, a1 > thr); X = Y @ M[:3, :3].T + M[:3, 3]
        d, k = cKDTree(self.P).query(X); sel = (d < 45.0) & (self.s[k] >= ac["lo"] - 4.0) & (self.s[k] <= ac["hi"] + 4.0)
        X, k = X[sel], k[sel]
        X = X - self._postShiftAt(k)
        self._ensureArrF(); A = self._rasToIjk; aoD, boD = self._tvMasks(); shp = self.arr.shape
        I = np.round(X @ A[:3, :3].T + A[:3, 3]).astype(int)
        inb = (I[:, 0] >= 0) & (I[:, 0] < shp[2]) & (I[:, 1] >= 0) & (I[:, 1] < shp[1]) & (I[:, 2] >= 0) & (I[:, 2] < shp[0])
        X, I = X[inb], I[inb]
        ok = self.arr[I[:, 2], I[:, 1], I[:, 0]] < 600.0
        if aoD is not None: ok &= aoD[I[:, 2], I[:, 1], I[:, 0]]
        if boD is not None: ok &= ~boD[I[:, 2], I[:, 1], I[:, 0]]
        X = X[ok]
        if len(X) < 30: status("金属を拾い直せませんでした（前の結果のまま）"); return
        ac["pts"] = X; _, kk = cKDTree(self.P).query(X); ss = self.s[kk]; ac["s"] = ss
        b_ = np.floor(ss / 2.0).astype(int); cnt = np.bincount(b_, minlength=b_.max() + 1)   # 端も合わせ直した金属で測り直す（まばらな点は端に数えない）
        occ = np.where(cnt >= max(3, 0.2 * np.median(cnt[cnt > 0])))[0]
        if len(occ):
            runs = []; st = pv = occ[0]
            for x_ in occ[1:]:
                if (x_ - pv) * 2.0 > 20.0: runs.append((st, pv)); st = x_
                pv = x_
            runs.append((st, pv)); r0, r1 = max(runs, key=lambda r: cnt[r[0]:r[1] + 1].sum())
            if (r1 + 1 - r0) * 2.0 > 0.5 * (ac["hi"] - ac["lo"]): ac["lo"], ac["hi"] = r0 * 2.0, (r1 + 1) * 2.0
        self._drawActual(); self._drawGreen()
        status(f"金属を拾い直しました（{len(X)} 点）")

    def postStraight(self):
        """術後 CT を、術前の中心線に沿って伸ばした画像（術前と同じ位置で並べて見られる）"""
        from scipy import ndimage
        post = self.post; Minv = np.linalg.inv(self.postT)
        a = slicer.util.arrayFromVolume(post).astype(np.float32)
        m = vtk.vtkMatrix4x4(); post.GetIJKToRASMatrix(m)
        A = np.linalg.inv(np.array([[m.GetElement(r, c) for c in range(4)] for r in range(4)])) @ Minv
        u = np.arange(-HALF, HALF + 1e-6, STEP); nu = len(u); UU, VV = np.meshgrid(u, u)
        K = len(self.P); out = np.zeros((K, nu, nu), np.int16)
        for k0 in range(0, K, 64):
            k1 = min(K, k0 + 64)
            sh = self._postShiftAt(np.arange(k0, k1))                                  # 大動脈の外形で合わせ直したずれ（3D）
            Q = self.P[k0:k1, None, None, :] + UU[None, :, :, None] * self.B[k0:k1, None, None, :] + VV[None, :, :, None] * self.N[k0:k1, None, None, :] + sh[:, None, None, :]
            H = Q.reshape(-1, 3) @ A[:3, :3].T + A[:3, 3]
            out[k0:k1] = ndimage.map_coordinates(a, [H[:, 2], H[:, 1], H[:, 0]], order=1, mode="nearest").reshape(k1 - k0, nu, nu).astype(np.int16)
        node = slicer.mrmlScene.GetFirstNodeByName("SA stretched post") or slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "SA stretched post")
        slicer.util.updateVolumeFromArray(node, out)
        node.SetSpacing(STEP, STEP, STEP); node.SetOrigin(-HALF, -HALF, 0.0)
        mm = vtk.vtkMatrix4x4(); mm.Identity(); mm.SetElement(2, 2, -1.0); node.SetIJKToRASDirectionMatrix(mm)
        node.CreateDefaultDisplayNodes(); dn = node.GetDisplayNode(); dn.SetAutoWindowLevel(False); dn.SetWindowLevel(800, 200)
        return node

    def showPostStretch(self, on):
        """右のストレッチ像（S2）を術後 CT にする / 戻す"""
        try:
            cn = slicer.app.layoutManager().sliceWidget("Orange").mrmlSliceCompositeNode()
            if on:
                n = slicer.mrmlScene.GetFirstNodeByName("SA stretched post") or self.postStraight()
                cn.SetBackgroundVolumeID(n.GetID()); self.orangeRot = getattr(self, "orangeRot", None)
            else:
                st = self.straight; cn.SetBackgroundVolumeID(st.GetID() if st is not None else None)
        except Exception as e: print("post stretch:", e)

    # ---------------------------------------------------------------- クロック位置
    def startClock(self, cb):
        self._clockCb = cb

    def _setClock(self, ras):
        k = self._k(); T = self.T[k]; v = ras - self.P[k]
        ant = np.array([0, 1.0, 0]); ant -= (ant @ T) * T; ant /= np.linalg.norm(ant) + 1e-9
        left = np.array([-1.0, 0, 0]); left -= (left @ T) * T; left /= np.linalg.norm(left) + 1e-9
        clk = _clock(float(v @ left), float(v @ ant))
        self.clockNode.RemoveAllControlPoints(); i = self.clockNode.AddControlPoint(vtk.vtkVector3d(*ras)); self.clockNode.SetNthControlPointLabel(i, clk)
        near = [m for m in self.markers if self._onPath(m) and abs(m["s"] - self.curS) < 5]
        if near: near[0]["clock"] = clk; name = near[0]["name"]
        else: self.addMarker(f"入口 {clk}", clock=clk); name = f"入口 {clk}"
        self._drawMarkers()
        return f"クロック位置 {clk}（12 時 = 前、3 時 = 患者の左）を「{name}」に記録しました。"

    # ---------------------------------------------------------------- 計測
    def _curveLengths(self, s0, s1, path=None):
        """中心線・内弯・外弯の長さ（内弯 = 曲がりの内側）"""
        F = self.frames[path or self.path]; P, T = F["P"], F["T"]
        k0, k1 = self._k(s0, path), self._k(s1, path)
        if k1 - k0 < 2: return 0.0, 0.0, 0.0
        seg = slice(k0, k1 + 1)
        from scipy import ndimage
        Tm = ndimage.gaussian_filter1d(T, sigma=10 / STEP, axis=0, mode="nearest")
        kap = np.gradient(Tm, STEP, axis=0)
        r = np.array([(self.prof[k, 1] if self.prof is not None and not np.isnan(self.prof[k, 1]) else 20.0) / 2 for k in range(k0, k1 + 1)])
        kv = kap[seg]; kn = np.linalg.norm(kv, axis=1, keepdims=True); khat = np.where(kn > 1e-6, kv / (kn + 1e-12), 0)
        inner = P[seg] + r[:, None] * khat; outer = P[seg] - r[:, None] * khat
        L = lambda X: float(np.linalg.norm(np.diff(X, axis=0), axis=1).sum())
        return L(P[seg]), L(inner), L(outer)

    def _tangent(self, s0, s1, path=None):
        F = self.frames[path or self.path]; k0, k1 = sorted((self._k(s0, path), self._k(s1, path)))
        t = F["T"][k0:k1 + 1].mean(0); return t / (np.linalg.norm(t) + 1e-12)

    def between(self, r1, r2):
        a, b = self.markers[r1], self.markers[r2]
        if a["s"] > b["s"]: a, b = b, a
        path = b["path"] if b["s"] > getattr(self, "sharedLen", 0) else a["path"]
        if path not in self.frames: return "この経路はまだ作っていません。3D で線をクリックして切り替えてください。"
        cl, inn, out = self._curveLengths(a["s"], b["s"], path)
        ang = _angle(self._tangent(a["s"] - 10, a["s"], path), self._tangent(b["s"], b["s"] + 10, path))
        d = np.linalg.norm(np.array(a["xyz"]) - np.array(b["xyz"]))
        ma, mb = self.metricsAt(a["s"], path), self.metricsAt(b["s"], path)
        txt = [f"{a['name']} → {b['name']}（{PATH_EN.get(path, path)}）",
               f"中心線の長さ {cl:.1f} mm　直線距離 {d:.1f} mm", f"内弯 {inn:.1f} mm　外弯 {out:.1f} mm",
               f"屈曲角（両端の向きの差） {ang:.0f}°"]
        if ma: txt.append(f"{a['name']}: Dmax {ma['dmax']:.1f} / Dmin {ma['dmin']:.1f} / Deq {ma['deq']:.1f} mm")
        if mb: txt.append(f"{b['name']}: Dmax {mb['dmax']:.1f} / Dmin {mb['dmin']:.1f} / Deq {mb['deq']:.1f} mm")
        return "\n".join(txt)

    def neckMeasurement(self):
        if self.P is None: return "中心線がありません"
        s0 = self.curS; lines = [f"ネック計測（{self.rel(s0):+.1f} mm から遠位へ）", "  位置    外周 Dmax / Dmin / Deq      内腔 Dmax / Dmin / Deq"]
        for d in (0, 5, 10, 15):
            o = self.metricsAt(s0 + d); l = self._metK(self._k(s0 + d), "lumen")
            so = f"{o['dmax']:.1f} / {o['dmin']:.1f} / {o['deq']:.1f}" if o else "—"
            sl = f"{l['dmax']:.1f} / {l['dmin']:.1f} / {l['deq']:.1f}" if l else "—"
            lines.append(f"  +{d:2d} mm   {so:22s} {sl}")
        return "\n".join(lines)

    def _mk(self, name):
        for m in self.markers:
            if m["name"] == name: return m
        return None

    def _dia(self, s, path=None, mode="outer"):
        if path is not None and path not in self.frames: return None
        return self._metK(self._k(s, path), mode, path)

    def _maxIn(self, s0, s1, path=None):
        best = None
        for s in np.arange(min(s0, s1), max(s0, s1) + 0.01, 2.0):
            m = self._dia(s, path)
            if m and (best is None or m["dmax"] > best[1]["dmax"]): best = (float(s), m)
        return best

    def summary(self, tpl):
        if self.P is None: return "中心線がありません"
        out = [f"=== {tpl} まとめ（研究・教育用。最終判断は元画像で）==="]
        need = [m for m in self.markers if m.get("auto")]
        if need: out.append("※ 自動で置いた（要確認）マーカー: " + "、".join(m["name"] for m in need))
        ren, ne, sac, bif = self._mk("最下位腎動脈"), self._mk("ネック終端（瘤の始まり）"), self._mk("瘤の最大径"), self._mk("大動脈分岐")
        if tpl == "EVAR":
            if ren:
                out.append(f"[ネック] 最下位腎動脈 {self.rel(ren['s']):+.1f} mm")
                for d in (0, 10, 15):
                    m = self._dia(ren["s"] + d)
                    if m: out.append(f"  +{d:2d} mm: Dmax {m['dmax']:.1f} / Dmin {m['dmin']:.1f} / Deq {m['deq']:.1f} mm")
                if ne:
                    cl, inn, o = self._curveLengths(ren["s"], ne["s"])
                    out.append(f"  ネック長 {cl:.1f} mm（内弯 {inn:.1f} / 外弯 {o:.1f}）")
                    a = _angle(self._tangent(ren["s"] - 20, ren["s"]), self._tangent(ren["s"], ne["s"]))
                    out.append(f"  腎上角 α {a:.0f}°")
                    if bif:
                        b = _angle(self._tangent(ren["s"], ne["s"]), self._tangent(ne["s"], bif["s"]))
                        out.append(f"  腎下角 β（ネック↔瘤の軸） {b:.0f}°")
            if ne and bif:
                mx = self._maxIn(ne["s"], bif["s"])
                if mx: out.append(f"[瘤] 最大径 Dmax {mx[1]['dmax']:.1f} mm（{self.rel(mx[0]):+.1f} mm、外周）")
            if sac:
                m = self._dia(sac["s"])
                if m: out.append(f"[瘤] マーカー位置の径 Dmax {m['dmax']:.1f} / Dmin {m['dmin']:.1f} / Deq {m['deq']:.1f} mm")
            if ren and bif:
                cl, inn, o = self._curveLengths(ren["s"], bif["s"])
                out.append(f"[長さ] 最下位腎動脈 → 分岐 {cl:.1f} mm（内弯 {inn:.1f} / 外弯 {o:.1f}）")
            for side, pth in (("右", "大動脈→右腸骨"), ("左", "大動脈→左腸骨")):
                iia, cfa = self._mk(f"{side}内腸骨起始"), self._mk(f"{side}遠位（総大腿）")
                if pth not in self.frames:
                    if iia or cfa: out.append(f"[{side}] 経路がまだ作られていません（3D で{side}の線をクリック）")
                    continue
                if ren and iia:
                    cl, inn, o = self._curveLengths(ren["s"], iia["s"], pth)
                    out.append(f"[{side}] 最下位腎動脈 → 内腸骨起始 {cl:.1f} mm（内弯 {inn:.1f} / 外弯 {o:.1f}）")
                if bif and iia:
                    m = self._dia(iia["s"] - 5, pth)
                    if m: out.append(f"[{side}] 総腸骨（内腸骨の 5 mm 手前）: Dmax {m['dmax']:.1f} / Dmin {m['dmin']:.1f} / Deq {m['deq']:.1f} mm")
                    cl, _, _ = self._curveLengths(bif["s"], iia["s"], pth); out.append(f"[{side}] 総腸骨の長さ {cl:.1f} mm")
                if iia and cfa:
                    best = None
                    for s in np.arange(iia["s"] + 5, cfa["s"], 2.0):
                        m = self._dia(s, pth, "lumen")
                        if m and (best is None or m["dmin"] < best[1]["dmin"]): best = (s, m)
                    if best:
                        o = self._dia(best[0], pth)
                        out.append(f"[{side}] アクセス（外腸骨）最小内腔径 Dmin {best[1]['dmin']:.1f}（Deq {best[1]['deq']:.1f}）mm　{self.rel(best[0]):+.0f} mm"
                                   + (f"　外周 Dmin {o['dmin']:.1f}" if o else ""))
                if cfa:
                    m = self._dia(cfa["s"], pth)
                    if m: out.append(f"[{side}] 遠位（総大腿）: Dmax {m['dmax']:.1f} / Dmin {m['dmin']:.1f} / Deq {m['deq']:.1f} mm")
                    if ren:
                        cl, _, _ = self._curveLengths(ren["s"], cfa["s"], pth); out.append(f"[{side}] 最下位腎動脈 → 遠位 {cl:.1f} mm")
        elif tpl == "TEVAR":
            bca, lcca, lsca = self._mk("腕頭動脈"), self._mk("左総頸動脈"), self._mk("左鎖骨下動脈")
            pz, ent, dz, cel = self._mk("近位ランディング"), self._mk("瘤 / エントリー"), self._mk("遠位ランディング"), self._mk("腹腔動脈")
            for nm, m in (("腕頭動脈", bca), ("左総頸動脈", lcca), ("左鎖骨下動脈", lsca), ("腹腔動脈", cel)):
                if m: out.append(f"[分枝] {nm} {self.rel(m['s']):+.1f} mm" + (f"　{m['clock']}" if m.get("clock") else ""))
            if pz:
                zone = "?"
                if bca and pz["s"] < bca["s"]: zone = "0"
                elif lcca and pz["s"] < lcca["s"]: zone = "1"
                elif lsca and pz["s"] < lsca["s"]: zone = "2"
                elif lsca and pz["s"] < lsca["s"] + 20: zone = "3"
                elif lsca: zone = "4"
                out.append(f"[近位ランディング] {self.rel(pz['s']):+.1f} mm　Zone {zone}")
                for d in (0, 10, 20):
                    m = self._dia(pz["s"] + d)
                    if m: out.append(f"  +{d:2d} mm: Dmax {m['dmax']:.1f} / Dmin {m['dmin']:.1f} / Deq {m['deq']:.1f} mm")
                if lsca and pz["s"] >= lsca["s"]:
                    cl, inn, o = self._curveLengths(lsca["s"], pz["s"]); out.append(f"  左鎖骨下動脈 → 近位ランディング {cl:.1f} mm（内弯 {inn:.1f} / 外弯 {o:.1f}）")
            if dz:
                out.append(f"[遠位ランディング] {self.rel(dz['s']):+.1f} mm")
                for d in (0, -10, -20):
                    m = self._dia(dz["s"] + d)
                    if m: out.append(f"  {d:+3d} mm: Dmax {m['dmax']:.1f} / Dmin {m['dmin']:.1f} / Deq {m['deq']:.1f} mm")
                if cel: cl, _, _ = self._curveLengths(dz["s"], cel["s"]); out.append(f"  遠位ランディング → 腹腔動脈 {cl:.1f} mm")
            if pz and dz:
                cl, inn, o = self._curveLengths(pz["s"], dz["s"])
                out.append(f"[長さ] 近位 → 遠位ランディング: 中心線 {cl:.1f} mm　内弯 {inn:.1f} mm　外弯 {o:.1f} mm")
                mx = self._maxIn(pz["s"], dz["s"])
                if mx: out.append(f"[瘤] 区間内の最大径 Dmax {mx[1]['dmax']:.1f} mm（{self.rel(mx[0]):+.1f} mm）")
                a = _angle(self._tangent(pz["s"] - 10, pz["s"] + 10), self._tangent(dz["s"] - 10, dz["s"] + 10))
                out.append(f"[屈曲] 近位↔遠位の向きの差 {a:.0f}°")
            if ent:
                m = self._dia(ent["s"]); out.append(f"[エントリー] {self.rel(ent['s']):+.1f} mm" + (f"　Dmax {m['dmax']:.1f} mm" if m else "") + (f"　{ent['clock']}" if ent.get("clock") else ""))
        out.append(""); out.append("[全マーカー]")
        for m in self.markers:
            mm = self.metricsAt(m["s"], m["path"])
            out.append(f"  {m['name']:16s} {self.rel(m['s']):+7.1f} mm" + (f"  Dmax {mm['dmax']:.1f} / Dmin {mm['dmin']:.1f} / Deq {mm['deq']:.1f}" if mm else "") + (f"  {m['clock']}" if m.get("clock") else ""))
        return "\n".join(out)

    # ---------------------------------------------------------------- 出力（高画質 PNG / サイジングシート PDF）
    def _wl(self):
        d = self.vol.GetDisplayNode(); return float(d.GetWindow()), float(d.GetLevel())

    @staticmethod
    def _qimageGray(a8):
        """uint8 の 2 次元配列 → QImage（ARGB32、描き込める形）"""
        from vtk.util.numpy_support import numpy_to_vtk
        h, w = a8.shape
        img = vtk.vtkImageData(); img.SetDimensions(w, h, 1); img.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
        img.GetPointData().SetScalars(numpy_to_vtk(np.ascontiguousarray(a8[::-1]).ravel(), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR))
        wr = vtk.vtkPNGWriter(); wr.SetInputData(img); wr.WriteToMemoryOn(); wr.Write()
        from vtk.util.numpy_support import vtk_to_numpy
        q = qt.QImage(); q.loadFromData(qt.QByteArray(vtk_to_numpy(wr.GetResult()).tobytes()), "PNG")
        return q.convertToFormat(qt.QImage.Format_ARGB32)

    @staticmethod
    def _font(px, bold=False):
        f = qt.QFont("Yu Gothic UI"); f.setPixelSize(int(px)); f.setBold(bold); return f

    def _pill(self, p, x, y, text, col, px=26, anchor="lt"):
        p.setFont(self._font(px, True)); fm = qt.QFontMetrics(p.font())
        w = fm.horizontalAdvance(text) if hasattr(fm, "horizontalAdvance") else fm.width(text); h = fm.height()
        if "r" in anchor: x -= w + 16
        if "b" in anchor: y -= h + 8
        p.setPen(qt.QPen(qt.QColor(0, 0, 0, 0))); p.setBrush(qt.QBrush(qt.QColor(10, 12, 16, 200))); p.drawRoundedRect(qt.QRectF(x, y, w + 16, h + 8), 8, 8)
        p.setPen(qt.QPen(qt.QColor(*[int(255 * c) for c in col]))); p.drawText(qt.QPointF(x + 8, y + 4 + fm.ascent()), text)

    def renderSection(self, s=None, path=None, size=1400, title=""):
        """断面の高画質画像（元 CT を 3 次補間で切り直し、輪郭と径を描き込む）"""
        from scipy import ndimage
        path = path or self.path; F = self.frames[path]; s = self.curS if s is None else float(s)
        k = self._k(s, path); P, T = F["P"][k], F["T"][k]
        if path == self.path: X, Y = self._inplane(k)
        else: X, Y = F["B"][k], F["N"][k]
        mO = self._metK(k, "outer", path); mL = self._metK(k, "lumen", path)
        dm = max([m["dmax"] for m in (mO, mL) if m] + [20.0]); fov = float(np.clip(dm * 2.0, 36.0, 100.0))
        u = (np.arange(size) + 0.5) / size * fov - fov / 2
        UU, VV = np.meshgrid(u, -u)
        Q = P + UU[..., None] * X + VV[..., None] * Y
        A = np.linalg.inv(self._ijk2ras()); H = Q.reshape(-1, 3) @ A[:3, :3].T + A[:3, 3]
        if getattr(self, "arrF", None) is None: self.arrF = ndimage.spline_filter(slicer.util.arrayFromVolume(self.vol).astype(np.float32), order=3, mode="nearest")
        img = ndimage.map_coordinates(self.arrF, [H[:, 2], H[:, 1], H[:, 0]], order=3, prefilter=False, mode="nearest").reshape(size, size)
        win, lev = self._wl(); a8 = np.clip((img - (lev - win / 2)) / max(win, 1) * 255, 0, 255).astype(np.uint8)
        q = self._qimageGray(a8); p = qt.QPainter(q); p.setRenderHint(qt.QPainter.Antialiasing, True); p.setRenderHint(qt.QPainter.TextAntialiasing, True)
        Fk = self.frames[path]; Bk, Nk = Fk["B"][k], Fk["N"][k]
        def px(xy):                                                        # 断面の 2D 座標 (B, N) → 画像のピクセル
            Wd = P + np.outer(xy[:, 0], Bk) + np.outer(xy[:, 1], Nk) - P
            return np.c_[(Wd @ X + fov / 2) / fov * size, (fov / 2 - Wd @ Y) / fov * size]
        def poly(xy, col, w, closed=True):
            pts = px(xy); pg = qt.QPolygonF()
            for x, y in pts: pg.append(qt.QPointF(float(x), float(y)))
            if closed and len(pts): pg.append(qt.QPointF(float(pts[0, 0]), float(pts[0, 1])))
            pen = qt.QPen(qt.QColor(*[int(255 * c) for c in col])); pen.setWidthF(w); pen.setCapStyle(qt.Qt.RoundCap); pen.setJoinStyle(qt.Qt.RoundJoin)
            p.setPen(pen); p.setBrush(qt.QBrush()); p.drawPolyline(pg)
            return pts
        sc = size / 1400.0
        if mO: poly(mO["xy"], self.OUTER_COL, 3.2 * sc)
        if mL: poly(mL["xy"], self.LUMEN_COL, 2.6 * sc)
        m = mO if self.mode == "outer" else mL
        if m:
            for key, val, col in (("maxLine", "dmax", (1.0, 0.35, 0.3)), ("minLine", "dmin", (0.35, 0.65, 1.0))):
                a, b = m[key]; pts = poly(np.array([a, b]), col, 3.0 * sc, closed=False)
                self._pill(p, pts[1, 0] + 8, pts[1, 1] - 20 * sc, f"{m[val]:.1f}", col, 30 * sc)
        # 目盛り（10 mm）
        L10 = 10.0 / fov * size; x0, y0 = 40 * sc, size - 50 * sc
        pen = qt.QPen(qt.QColor(255, 255, 255)); pen.setWidthF(4 * sc); p.setPen(pen)
        p.drawLine(qt.QPointF(x0, y0), qt.QPointF(x0 + L10, y0))
        for xx in (x0, x0 + L10): p.drawLine(qt.QPointF(xx, y0 - 10 * sc), qt.QPointF(xx, y0 + 10 * sc))
        p.setFont(self._font(24 * sc, True)); p.drawText(qt.QPointF(x0, y0 - 18 * sc), "10 mm")
        # 見出しと値
        pos = f"{self.rel(s):+.1f} mm" + (" from baseline" if self.baseS is not None else "")
        self._pill(p, 24 * sc, 24 * sc, (title + "   " if title else "") + pos, (1, 1, 1), 32 * sc)
        y = 90 * sc
        for mm, nm, col in ((mO, "外周", self.OUTER_COL), (mL, "内腔", self.LUMEN_COL)):
            if mm: self._pill(p, 24 * sc, y, f"{nm}  Dmax {mm['dmax']:.1f}  Dmin {mm['dmin']:.1f}  Deq {mm['deq']:.1f} mm  ({mm['area']:.0f} mm²)", col, 26 * sc); y += 52 * sc
        p.end()
        return q, dict(outer=mO, lumen=mL, s=s, path=path)

    def renderStretched(self, pxmm=4.0):
        """ストレッチ像（今の回転角）を高画質で。マーカー・ベースライン・現在位置を描き込む"""
        from scipy import ndimage
        sn = slicer.app.layoutManager().sliceWidget("Green").mrmlSliceNode()
        M = slicer.util.arrayFromVTKMatrix(sn.GetSliceToRAS())
        a = slicer.util.arrayFromVolume(self.straight).astype(np.float32)
        R2I = vtk.vtkMatrix4x4(); self.straight.GetRASToIJKMatrix(R2I); R2I = slicer.util.arrayFromVTKMatrix(R2I)
        # 画面の Green と同じ平面。横 ±HALF、縦は経路全体
        ends = [np.linalg.inv(M) @ np.r_[r, 1] for r in (self._greenRAS(0.0)[0], self._greenRAS(0.0)[1], self._greenRAS(self.length)[0], self._greenRAS(self.length)[1])]
        xs = [e[0] for e in ends]; ys = [e[1] for e in ends]
        x0, x1 = min(xs) - 2, max(xs) + 2; y0, y1 = min(ys) - 4, max(ys) + 4
        nx, ny = int((x1 - x0) * pxmm), int((y1 - y0) * pxmm)
        xx = x0 + (np.arange(nx) + 0.5) / pxmm; yy = y1 - (np.arange(ny) + 0.5) / pxmm
        XX, YY = np.meshgrid(xx, yy)
        R = (M[:3, :3] @ np.stack([XX.ravel(), YY.ravel(), np.zeros(XX.size)])).T + M[:3, 3]
        I = R @ R2I[:3, :3].T + R2I[:3, 3]
        img = ndimage.map_coordinates(a, [I[:, 2], I[:, 1], I[:, 0]], order=1, mode="constant", cval=-1000).reshape(ny, nx)
        win, lev = self._wl(); a8 = np.clip((img - (lev - win / 2)) / max(win, 1) * 255, 0, 255).astype(np.uint8)
        src = self._qimageGray(a8); G = 330                                   # 右側にラベル用の余白
        q = qt.QImage(nx + G, ny + 60, qt.QImage.Format_ARGB32); q.fill(qt.QColor(20, 22, 26))
        p = qt.QPainter(q); p.setRenderHint(qt.QPainter.Antialiasing, True); p.setRenderHint(qt.QPainter.TextAntialiasing, True)
        p.drawImage(qt.QPointF(0, 60), src)
        p.setFont(self._font(24, True)); p.setPen(qt.QPen(qt.QColor(235, 238, 242)))
        p.drawText(qt.QPointF(10, 38), f"ストレッチ像  {PATH_EN.get(self.path, '')}  rot {self.rot:.0f}°")
        Minv = np.linalg.inv(M)
        def pix(r):
            v = Minv @ np.r_[r, 1]; return qt.QPointF((v[0] - x0) * pxmm, (y1 - v[1]) * pxmm + 60)
        def hline(sv, col, w, dash=False):
            ab = self._greenRAS(sv); a, b = pix(ab[0]), pix(ab[1]); y = (a.y() + b.y()) / 2
            pen = qt.QPen(qt.QColor(*[int(255 * c) for c in col])); pen.setWidthF(w)
            if dash: pen.setStyle(qt.Qt.DashLine)
            p.setPen(pen); p.drawLine(qt.QPointF(0, y), qt.QPointF(nx + 14, y)); return y
        items = []
        if self.baseS is not None: items.append((hline(self.baseS, (0.4, 1.0, 0.45), 2.5), "ベースライン 0", (0.4, 1.0, 0.45)))
        for mk in self.markers:
            if not self._onPath(mk): continue
            o = self._dia(mk["s"]); txt = f"{mk['name']}  {self.rel(mk['s']):+.0f} mm" + (f"  Ø{o['deq']:.1f}" if o else "")
            items.append((hline(mk["s"], (0.3, 0.9, 0.95), 2.0, dash=True), txt, (0.3, 0.9, 0.95)))
        items.sort(key=lambda t: t[0]); last = -1e9
        for y, txt, col in items:                                            # ラベルが重ならないよう少しずらす
            ly = max(y - 16, last + 36); last = ly
            pen = qt.QPen(qt.QColor(*[int(255 * c) for c in col])); pen.setWidthF(1.5); p.setPen(pen)
            p.drawLine(qt.QPointF(nx + 14, y), qt.QPointF(nx + 26, ly + 16))
            self._pill(p, nx + 28, ly, txt, col, 20)
        L50 = 50 * pxmm; yb = ny + 40
        pen = qt.QPen(qt.QColor(255, 255, 255)); pen.setWidthF(3); p.setPen(pen)
        p.drawLine(qt.QPointF(nx + 30, yb), qt.QPointF(nx + 30, yb - L50)); p.setFont(self._font(18, True)); p.drawText(qt.QPointF(nx + 40, yb - L50 / 2), "50 mm")
        p.end()
        return q

    def render3D(self, scale=1):
        v3 = slicer.app.layoutManager().threeDWidget(0).threeDView(); rw = v3.renderWindow()
        v3.forceRender()
        f = vtk.vtkWindowToImageFilter(); f.SetInput(rw); f.SetScale(scale, scale); f.ReadFrontBufferOff(); f.ShouldRerenderOn(); f.Update()
        wr = vtk.vtkPNGWriter(); wr.SetInputConnection(f.GetOutputPort()); wr.WriteToMemoryOn(); wr.Write()
        from vtk.util.numpy_support import vtk_to_numpy
        q = qt.QImage(); q.loadFromData(qt.QByteArray(vtk_to_numpy(wr.GetResult()).tobytes()), "PNG")
        v3.forceRender(); return q

    def outDir(self):
        base = os.path.join(os.path.expanduser("~"), "Documents", "HeartView症例")
        d = os.path.join(base, "サイジング_" + time.strftime("%Y%m%d_%H%M%S")); os.makedirs(d, exist_ok=True)
        return d

    def exportImages(self, d=None, status=print):
        """高画質 PNG: 3D・ストレッチ像・各マーカーの断面（＋今の断面）"""
        d = d or self.outDir(); files = []
        keep = (self.curS, self.path)
        status("3D を書き出し中…"); q = self.render3D(); fn = os.path.join(d, "01_3D.png"); q.save(fn); files.append(("3D", fn))
        status("ストレッチ像を書き出し中…"); q = self.renderStretched(); fn = os.path.join(d, "02_stretched.png"); q.save(fn); files.append(("ストレッチ像", fn))
        q, _ = self.renderSection(title="現在位置"); fn = os.path.join(d, "03_current_section.png"); q.save(fn); files.append(("現在の断面", fn))
        for i, mk in enumerate(self.markers):
            if mk["path"] not in self.frames: continue
            status(f"断面を書き出し中… {mk['name']}")
            q, _ = self.renderSection(mk["s"], mk["path"] if mk["path"] in self.frames else None, title=mk["name"])
            safe = "".join(ch for ch in mk["name"] if ch not in '\\/:*?"<>|（）() ')
            fn = os.path.join(d, f"{10 + i:02d}_section_{safe}.png"); q.save(fn); files.append((mk["name"], fn))
        self.exported = files
        return d, files

    def _markerRows(self):
        rows = []
        for m in self.markers:
            o = self._dia(m["s"], m["path"]) if m["path"] in self.frames else None
            l = self._dia(m["s"], m["path"], "lumen") if m["path"] in self.frames else None
            rows.append(dict(m=m, o=o, l=l, side={"大動脈→右腸骨": "右", "大動脈→左腸骨": "左"}.get(m["path"], "")
                             if m["s"] > getattr(self, "sharedLen", 0) + 2 else "共通"))
        return rows

    def writeCSV(self, d):
        import csv
        with open(os.path.join(d, "markers.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f); w.writerow(["マーカー", "経路", "位置 mm", "外周 Dmax", "外周 Dmin", "外周 Deq", "外周 面積", "内腔 Dmax", "内腔 Dmin", "内腔 Deq", "内腔 面積", "クロック", "自動"])
            for r in self._markerRows():
                m = r["m"]; f2 = lambda q, k: f"{q[k]:.1f}" if q else ""
                w.writerow([m["name"], r["side"], f"{self.rel(m['s']):.1f}"] + [f2(r["o"], k) for k in ("dmax", "dmin", "deq", "area")]
                           + [f2(r["l"], k) for k in ("dmax", "dmin", "deq", "area")] + [m.get("clock") or "", "要確認" if m.get("auto") else ""])
        with open(os.path.join(d, "measurements.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f); w.writerow(["名前", "種類", "値", "場所", "位置"])
            for r in self.measureRows(): w.writerow([r["name"], r["kind"], r["value"], r["where"], r["pos"]])
        with open(os.path.join(d, "profile.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f); w.writerow(["距離 mm", "ベースラインから mm", "面積", "Deq", "Dmax", "Dmin"])
            if self.prof is not None:
                for k in range(0, len(self.s), 4): w.writerow([f"{self.s[k]:.1f}", f"{self.rel(self.s[k]):.1f}"] + [f"{x:.1f}" for x in self.prof[k]])

    def sizingSheet(self, tpl, status=print):
        """サイジングシート（A4 の PDF）: まとめ・マーカー表・手動計測・画像。CSV と PNG も同じフォルダへ"""
        import html as _h
        d, files = self.exportImages(None, status)
        status("サイジングシート（PDF）を作成中…")
        summ = self.summary(tpl); self.writeCSV(d)
        open(os.path.join(d, "summary.txt"), "w", encoding="utf-8").write(summ)
        doc = qt.QTextDocument(); doc.setDefaultFont(self._font(11))
        for i, (nm, fn) in enumerate(files): doc.addResource(qt.QTextDocument.ImageResource, qt.QUrl(f"img{i}.png"), qt.QImage(fn))
        E = _h.escape
        css = ("<style>body{font-family:'Yu Gothic UI','Meiryo';color:#1d2026} h1{font-size:22px;margin:0} .mut{color:#6b7280;font-size:10px}"
               "h2{font-size:13px;color:#0f5c8c;margin:10px 0 4px 0;border-bottom:1px solid #cfd6de}"
               "td,th{padding:3px 6px;font-size:11px} th{background:#eef2f6;color:#334155;text-align:left} .num{text-align:right}</style>")
        H = [f"<html><head><meta charset='utf-8'>{css}</head><body>"]
        H.append(f"<table width='100%'><tr><td><h1>大動脈サイジングシート　{E(tpl)}</h1>"
                 f"<span class='mut'>{E(self.vol.GetName() if self.vol else '')}　作成 {time.strftime('%Y-%m-%d %H:%M')}　HUCViewS AortaSizing</span></td>"
                 f"<td align='right' class='mut'>研究・教育用（非医療機器）<br>最終判断は元画像で</td></tr></table>")
        H.append("<h2>まとめ</h2><table width='100%' cellspacing='0'>")
        for line in summ.splitlines()[1:]:
            if line.startswith("[全マーカー]"): break
            if not line.strip(): continue
            b = line.startswith("[") or line.startswith("※")
            H.append(f"<tr><td>{'<b>' if b else ''}{E(line.strip())}{'</b>' if b else ''}</td></tr>")
        H.append("</table>")
        H.append("<h2>マーカー（外周 / 内腔）</h2><table width='100%' cellspacing='0' border='0'><tr><th>マーカー</th><th>側</th><th class='num'>位置 mm</th>"
                 "<th class='num'>外周 Dmax</th><th class='num'>Dmin</th><th class='num'>Deq</th><th class='num'>内腔 Dmax</th><th class='num'>Dmin</th><th class='num'>Deq</th><th>クロック</th></tr>")
        for i, r in enumerate(self._markerRows()):
            m = r["m"]; f2 = lambda q, k: f"{q[k]:.1f}" if q else "—"; bg = "#ffffff" if i % 2 == 0 else "#f7f9fb"
            H.append(f"<tr style='background:{bg}'><td>{E(m['name'])}{' <span class=mut>(自動・要確認)</span>' if m.get('auto') else ''}</td><td>{r['side']}</td>"
                     f"<td class='num'>{self.rel(m['s']):+.1f}</td>" + "".join(f"<td class='num'>{f2(r['o'], k)}</td>" for k in ("dmax", "dmin", "deq"))
                     + "".join(f"<td class='num'>{f2(r['l'], k)}</td>" for k in ("dmax", "dmin", "deq")) + f"<td>{E(m.get('clock') or '')}</td></tr>")
        H.append("</table>")
        mr = self.measureRows()
        if mr:
            H.append("<h2>手動計測</h2><table width='100%' cellspacing='0'><tr><th>名前</th><th>種類</th><th>値</th><th>場所</th><th>位置</th></tr>")
            for r in mr: H.append(f"<tr><td>{E(r['name'])}</td><td>{E(r['kind'])}</td><td><b>{E(r['value'])}</b></td><td>{E(r['where'])}</td><td>{E(r['pos'])}</td></tr>")
            H.append("</table>")
        def sz(i, w=None, h=None):
            im = qt.QImage(files[i][1]); iw, ih = max(im.width(), 1), max(im.height(), 1)
            if w is None: w = h * iw / ih
            if h is None: h = w * ih / iw
            return f"width='{int(w)}' height='{int(h)}'"
        H.append("<h2 style='page-break-before:always'>画像</h2><table cellspacing='6'><tr>"
                 f"<td valign='top'><img src='img0.png' {sz(0, w=300)}></td><td valign='top'><img src='img1.png' {sz(1, h=560)}></td>"
                 f"<td valign='top'><img src='img2.png' {sz(2, w=210)}></td></tr></table>")
        secs = list(enumerate(files))[3:]
        if secs:
            H.append("<h2>マーカー位置の断面</h2><table cellspacing='6'>")
            for j in range(0, len(secs), 3):
                H.append("<tr>" + "".join(f"<td><img src='img{i}.png' width='215' height='215'></td>" for i, _ in secs[j:j + 3]) + "</tr>")
            H.append("</table>")
        H.append("</body></html>")
        doc.setHtml("".join(H))
        pdf = os.path.join(d, "sizing_sheet.pdf")
        w = qt.QPdfWriter(pdf); w.setPageSize(qt.QPageSize(qt.QPageSize.A4)); w.setResolution(200)
        try: w.setPageMargins(qt.QMarginsF(10, 10, 10, 10), qt.QPageLayout.Millimeter)
        except Exception: pass
        w.setTitle("Aortic sizing sheet"); w.setCreator("HUCViewS AortaSizing")
        getattr(doc, "print")(w)
        self.lastOut = d
        return pdf

    def saveReport(self, tpl):
        import csv
        base = os.path.join(os.path.expanduser("~"), "Documents", "HeartView症例")
        d = os.path.join(base, "サイジング_" + time.strftime("%Y%m%d_%H%M")); os.makedirs(d, exist_ok=True)
        txt = self.summary(tpl)
        with open(os.path.join(d, "summary.txt"), "w", encoding="utf-8") as f: f.write(txt)
        with open(os.path.join(d, "markers.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f); w.writerow(["マーカー", "経路", "ベースラインからの距離 mm", "Dmax", "Dmin", "Deq", "面積 mm2", "クロック", "自動"])
            for m in self.markers:
                mm = self.metricsAt(m["s"], m["path"]) or {}
                w.writerow([m["name"], m["path"], f"{self.rel(m['s']):.1f}"] + [f"{mm[k]:.1f}" if k in mm else "" for k in ("dmax", "dmin", "deq", "area")] + [m.get("clock") or "", "要確認" if m.get("auto") else ""])
        with open(os.path.join(d, "profile.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f); w.writerow(["距離 mm", "ベースラインから mm", "面積", "Deq", "Dmax", "Dmin"])
            if self.prof is not None:
                for k in range(0, len(self.s), 4):
                    w.writerow([f"{self.s[k]:.1f}", f"{self.rel(self.s[k]):.1f}"] + [f"{x:.1f}" for x in self.prof[k]])
        slicer.util.mainWindow().grab().save(os.path.join(d, "screen.png"))
        shots = []
        for m in self.markers:
            if not self._onPath(m): continue
            self.setPosition(m["s"]); slicer.app.processEvents()
            fn = f"marker_{len(shots) + 1}_{MARK_EN.get(m['name'], 'mk')}.png".replace(" ", "_").replace("/", "")
            slicer.app.layoutManager().sliceWidget("Red").sliceView().grab().save(os.path.join(d, fn)); shots.append((m["name"], fn))
        html = ["<html><head><meta charset='utf-8'><title>Sizing report</title></head><body style='font-family:sans-serif'>",
                f"<h2>大動脈サイジング（{tpl}）</h2><p style='color:#888'>研究・教育用。最終判断は元画像で。{time.strftime('%Y-%m-%d %H:%M')}</p>",
                "<pre>" + txt.replace("<", "&lt;") + "</pre>", "<img src='screen.png' width='900'>"]
        for name, fn in shots: html.append(f"<h4>{name}</h4><img src='{fn}' width='400'>")
        html.append("</body></html>")
        with open(os.path.join(d, "report.html"), "w", encoding="utf-8") as f: f.write("\n".join(html))
        return d

    # ---------------------------------------------------------------- 中心線の修正
    def recenter(self, name, s=None, status=print):
        c = self.curves.get(name)
        if c is None or self.prof is None: return
        def offsetAt(k):
            m = self._metK(k, "outer")
            if m is None: return None
            cx, cy = m["centroid"]
            if math.hypot(cx, cy) > 20: return None
            return cx * self.B[k] + cy * self.N[k]
        if s is not None:
            k = self._k(s); off = offsetAt(k)
            if off is None: raise RuntimeError("この断面では輪郭が取れません")
            cps = slicer.util.arrayFromMarkupsControlPoints(c, world=True)
            d = np.linalg.norm(cps - self.P[k], axis=1); i = int(np.argmin(d))
            if d[i] < 6: c.SetNthControlPointPositionWorld(i, *(cps[i] + off))
            else:
                best, bi = 1e9, 0
                for j in range(len(cps) - 1):
                    a, b = cps[j], cps[j + 1]; ab = b - a; t = np.clip((self.P[k] - a) @ ab / max(ab @ ab, 1e-9), 0, 1)
                    dd = np.linalg.norm(a + t * ab - self.P[k])
                    if dd < best: best, bi = dd, j
                c.InsertControlPoint(bi + 1, vtk.vtkVector3d(*(self.P[k] + off)))
        else:
            from scipy import ndimage
            ts = np.arange(0, self.length, 5.0); ks = [self._k(t) for t in ts]
            offs = np.array([offsetAt(k) if offsetAt(k) is not None else np.full(3, np.nan) for k in ks], float)
            ok = ~np.isnan(offs[:, 0])
            if ok.sum() < 3: raise RuntimeError("輪郭が取れず、中心を合わせられません")
            for i in range(3): offs[:, i] = np.interp(ts, ts[ok], offs[ok, i])
            offs = ndimage.median_filter(offs, size=(5, 1), mode="nearest"); offs = ndimage.gaussian_filter1d(offs, sigma=2, axis=0, mode="nearest")
            c.RemoveAllControlPoints()
            for t, k, o in zip(ts, ks, offs):
                if t % 10 < 1e-6 or t == ts[-1]: c.AddControlPoint(vtk.vtkVector3d(*(self.P[k] + o)))
        self.rebuild(name, status)

    def editMode(self, on, name):
        lm = slicer.app.layoutManager(); c = self.curves.get(name)
        if on:
            self._editing = True
            for n in (getattr(self, 'contNode', None), getattr(self, 'cursorNode', None), getattr(self, 'clockNode', None)):
                if n is not None: n.GetDisplayNode().SetVisibility(False)
            for ln in (self.dLines or []): ln.GetDisplayNode().SetVisibility(False)
            lm.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
            slicer.util.setSliceViewerLayers(background=self.vol, foreground=None, label=None, fit=True)
            for nm in ("Red", "Green", "Yellow"):
                w = lm.sliceWidget(nm); sn = w.mrmlSliceNode()
                sn.SetOrientation({"Red": "Axial", "Green": "Coronal", "Yellow": "Sagittal"}[nm]); w.sliceController().setVisible(True)
                io = w.sliceView().interactorObserver()
                for act in (io.BrowseSlice, io.AdjustWindowLevelBackground): io.SetActionEnabled(act, True)
            for it, tag in self._iTags:
                try: it.RemoveObserver(tag)
                except Exception: pass
            self._iTags = []
            for k, cc in self.curves.items():
                d = cc.GetDisplayNode(); d.RemoveAllViewNodeIDs(); d.SetVisibility(k == name); cc.SetLocked(True)   # つまみは Slicer に触らせない（下の自前の操作で動かす）
                if k == name: d.SetLineThickness(0.6); d.SetGlyphScale(2.2); d.SetPointLabelsVisibility(False)
            if c is not None and c.GetNumberOfControlPoints():
                p = self.P[self._k()] if self.P is not None else [0, 0, 0]
                slicer.modules.markups.logic().JumpSlicesToLocation(p[0], p[1], p[2], True)
            self._editTags = []
            for nm in ("Red", "Green", "Yellow"):
                it = lm.sliceWidget(nm).sliceView().interactor()
                self._editTags.append((it, it.AddObserver(vtk.vtkCommand.RightButtonPressEvent, lambda cl, e, nm=nm: self._rightDelete(cl, nm), 1.0)))
                E = vtk.vtkCommand
                self._editTags.append((it, it.AddObserver(E.LeftButtonPressEvent, lambda cl, e, nm=nm: self._edPress(cl, nm), 2.0)))
                self._editTags.append((it, it.AddObserver(E.MouseMoveEvent, lambda cl, e, nm=nm: self._edMove(cl, nm), 2.0)))
                self._editTags.append((it, it.AddObserver(E.LeftButtonReleaseEvent, lambda cl, e, nm=nm: self._edRelease(cl, nm), 2.0)))
                self._editTags.append((it, it.AddObserver(E.KeyPressEvent, lambda cl, e: self._edKey(cl), 2.0)))
            self._edHist = []; self._edDrag = None; self._edAnchors = set()
            for m in slicer.util.getNodesByClass("vtkMRMLModelNode"):          # TEVAR の筒の輪郭は 3 断面では出さない（まぎらわしい）
                if m.GetName().startswith("TEVAR ") and m.GetDisplayNode() is not None: m.GetDisplayNode().SetVisibility2D(False)
            self._edShadow(c)                                                   # 矢状断・冠状断に中心線の全体をうすく出す
            for ov in ("ovRed", "ovGreen", "ovOrange"):                      # 計測用の線・文字は消す（3 断面では意味がない）
                o = getattr(self, ov, None)
                if o is not None:
                    try: o.set([], [])
                    except Exception: pass
            p = self.P[self._k()] if self.P is not None else np.zeros(3)
            for nm, fw in (("Red", 160.0), ("Green", 300.0), ("Yellow", 300.0)):   # 今の位置を真ん中に、見やすい大きさで
                w = lm.sliceWidget(nm); sn = w.mrmlSliceNode()
                try: w.sliceView().cornerAnnotation().ClearAllTexts()
                except Exception: pass
                fov = sn.GetFieldOfView(); r = fov[1] / max(fov[0], 1e-6)
                sn.SetFieldOfView(fw, fw * r, fov[2]); sn.JumpSliceByCentering(float(p[0]), float(p[1]), float(p[2]))
        else:
            for it, tag in getattr(self, "_editTags", []):
                try: it.RemoveObserver(tag)
                except Exception: pass
            self._editTags = []
            for cc in self.curves.values():
                cc.SetLocked(True)
                try: cc.GetDisplayNode().SetSliceProjection(False)
                except Exception: pass
            self._editing = False; self._edDrag = None
            self._edShadow(None)

    def _edShadow(self, c):
        """中心線の全体の通り道を、矢状断・冠状断にうすく描く（編集した点にすぐついていく）"""
        old = getattr(self, "_shadowTag", None)
        if old is not None:
            try: old[0].RemoveObserver(old[1])
            except Exception: pass
            self._shadowTag = None
        for o in getattr(self, "_edOv", []) or []:
            try: o.remove()
            except Exception: pass
        self._edOv = []
        if c is None: return
        from vtk.util.numpy_support import vtk_to_numpy
        self._edOv = [_Overlay(nm) for nm in ("Green", "Yellow") if slicer.app.layoutManager().sliceWidget(nm) is not None]
        def sync(caller=None, ev=None):
            try:
                cp = c.GetCurvePointsWorld()
                if cp is None or cp.GetNumberOfPoints() < 2: return
                pts = vtk_to_numpy(cp.GetData()).astype(float)
                for o in self._edOv: o.set([(pts, (1.0, 0.72, 0.25), False)])
            except Exception as e: print("shadow:", e)
        sync(); self._shadowTag = (c, c.AddObserver(vtk.vtkCommand.ModifiedEvent, sync))

    def _edAbort(self, it):
        for tt, tag in getattr(self, "_editTags", []):
            if tt is it:
                try: it.GetCommand(tag).SetAbortFlag(1)
                except Exception: pass

    def _edPress(self, it, nm):
        """クリック = 近くの中心線をそこへ。押したままドラッグ = ずらす。中心線から遠い所は普段どおり（ウィンドウ）"""
        c = self.curves.get(self.path)
        if c is None or it.GetShiftKey() or it.GetControlKey(): return
        from vtk.util.numpy_support import vtk_to_numpy
        sn = slicer.app.layoutManager().sliceWidget(nm).mrmlSliceNode(); ras = self._rasAt(it, nm)
        M = sn.GetSliceToRAS(); n = np.array([M.GetElement(i, 2) for i in range(3)]); n /= np.linalg.norm(n) + 1e-9
        cp = c.GetCurvePointsWorld()
        if cp is None or cp.GetNumberOfPoints() < 2: return
        pts = vtk_to_numpy(cp.GetData()).astype(float)
        off = (pts - ras) @ n; inpl = pts - np.outer(off, n)
        axial = sn.GetOrientation() == "Axial"
        cand = np.where(np.abs(off) < 6.0)[0] if axial else np.arange(len(pts))     # 矢状断・冠状断は、見えている線（全体）のどこでもつかめる
        if len(cand) == 0: return
        d = np.linalg.norm(inpl[cand] - ras, axis=1); j = int(cand[np.argmin(d)])
        if d.min() > (40.0 if axial else 20.0): return
        q = pts[j]; cps = slicer.util.arrayFromMarkupsControlPoints(c, world=True)
        anc = self.__dict__.setdefault("_edAnchors", set())
        self._edHist.append((cps.copy(), [k for k in range(len(cps)) if c.GetNthControlPointID(k) in anc]))
        dc = np.linalg.norm(cps - q, axis=1); i = int(np.argmin(dc))
        if dc[i] > 6.0:                                                              # 近くに点が無ければ、そこに点を足す
            best, bi = 1e9, 0
            for t_ in range(len(cps) - 1):
                a, b = cps[t_], cps[t_ + 1]; ab = b - a; tt = np.clip((q - a) @ ab / max(ab @ ab, 1e-9), 0, 1)
                dd = np.linalg.norm(a + tt * ab - q)
                if dd < best: best, bi = dd, t_
            c.InsertControlPoint(bi + 1, vtk.vtkVector3d(*q)); i = bi + 1
        keep = 0.0 if axial else float((q - ras) @ n)                                 # 矢状断・冠状断では奥行きはそのまま（見えている線を横にずらす）
        base = slicer.util.arrayFromMarkupsControlPoints(c, world=True)
        w = self._edWeights(c, base, i)                                               # まわりの点もなめらかについてくる（自分で置いた点は動かさない）
        anc.add(c.GetNthControlPointID(i))
        self._edDrag = (i, nm, keep, n, base, w); self._edApply(c, ras + keep * n); self._edAbort(it)

    SOFT_MM = 22.0          # 動かした点のまわりが、どのくらいの長さ一緒についてくるか

    def _edWeights(self, c, base, i):
        """動かす点 i のまわりの点の「ついてくる割合」。自分で置いた点（アンカー）で止まり、その間はなめらかに減る"""
        n = len(base); a = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(base, axis=0), axis=1))]
        anc = getattr(self, "_edAnchors", set()); isA = np.array([c.GetNthControlPointID(k) in anc for k in range(n)])
        w = np.zeros(n); w[i] = 1.0; sig = self.SOFT_MM
        for side in (-1, 1):
            rng = range(i - 1, -1, -1) if side < 0 else range(i + 1, n)
            stop = next((k for k in rng if isA[k]), None)
            span = abs(a[stop] - a[i]) if stop is not None else None
            for k in (range(i - 1, -1, -1) if side < 0 else range(i + 1, n)):
                if stop is not None and (k <= stop if side < 0 else k >= stop): break
                dist = abs(a[k] - a[i])
                if span is not None and span < 2.5 * sig: w[k] = 0.5 * (1 + math.cos(math.pi * min(dist / span, 1.0)))
                else: w[k] = math.exp(-(dist / sig) ** 2)
                if w[k] < 0.01: break
        w[0] = 0.0 if i != 0 else 1.0; w[-1] = 0.0 if i != n - 1 else 1.0          # 両端（起始・末梢）は動かさない
        return w

    def _edApply(self, c, target):
        i, _, keep, n, base, w = self._edDrag
        off = np.asarray(target, float) - base[i]
        wasMod = c.StartModify()
        for k in np.nonzero(w > 0)[0]: c.SetNthControlPointPositionWorld(int(k), *(base[k] + w[k] * off))
        c.EndModify(wasMod)

    def _edMove(self, it, nm):
        dr = getattr(self, "_edDrag", None)
        if dr is None or dr[1] != nm: return
        keep, n = dr[2], dr[3]; c = self.curves.get(self.path); self._edApply(c, self._rasAt(it, nm) + keep * n); self._edAbort(it)

    def _edRelease(self, it, nm):
        if getattr(self, "_edDrag", None) is None: return
        self._edDrag = None; self._edAbort(it)
        st = getattr(self, "onStatus", None)
        if st: st(f"中心線を動かしました（{len(self._edHist)} 回）。続けてクリック / ドラッグ。終わったら「完了」か Enter。Ctrl+Z で戻す。")

    def _edKey(self, it):
        key = it.GetKeySym() or ""
        if (key in ("z", "Z") and it.GetControlKey()) or key in ("BackSpace",):
            if self._edHist:
                c = self.curves.get(self.path); cps, ai = self._edHist.pop()
                wasMod = c.StartModify(); c.RemoveAllControlPoints()
                for q in cps: c.AddControlPoint(vtk.vtkVector3d(*q))
                c.EndModify(wasMod)
                self._edAnchors = {c.GetNthControlPointID(k) for k in ai if k < c.GetNumberOfControlPoints()}
            self._edAbort(it)
        elif key in ("Return", "KP_Enter", "Escape"):
            cb = getattr(self, "onKey", None)
            if cb: qt.QTimer.singleShot(0, lambda: cb("editdone"))
            self._edAbort(it)

    def _rightDelete(self, it, nm):
        c = self.curves.get(self.path)
        if c is None: return
        x, y = it.GetEventPosition(); sn = slicer.app.layoutManager().sliceWidget(nm).mrmlSliceNode()
        M = sn.GetXYToRAS(); ras = np.array([sum(M.GetElement(r, cc) * v for cc, v in enumerate((x, y, 0, 1))) for r in range(3)])
        cps = slicer.util.arrayFromMarkupsControlPoints(c, world=True)
        if len(cps) < 4: return
        d = np.linalg.norm(cps - ras, axis=1); i = int(np.argmin(d))
        fov = sn.GetFieldOfView(); dims = sn.GetDimensions(); mmpp = fov[0] / max(dims[0], 1)
        if d[i] < 10 * mmpp + 1.0:
            c.RemoveNthControlPoint(i)
            for tt, tag in self._editTags:
                if tt is it:
                    try: it.GetCommand(tag).SetAbortFlag(1)
                    except Exception: pass

    def startAddPoint(self, name, done=lambda: None):
        c = self.curves.get(name)
        if c is None: return
        tmp = slicer.mrmlScene.GetFirstNodeByName("SA 追加点") or slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "SA 追加点")
        tmp.RemoveAllControlPoints()
        def onDefined(caller, ev):
            if tmp.GetNumberOfControlPoints() == 0: return
            p = [0, 0, 0]; tmp.GetNthControlPointPositionWorld(0, p); p = np.array(p)
            cps = slicer.util.arrayFromMarkupsControlPoints(c, world=True)
            best, bi = 1e9, 0
            for i in range(len(cps) - 1):
                a, b = cps[i], cps[i + 1]; ab = b - a; t = np.clip((p - a) @ ab / max(ab @ ab, 1e-9), 0, 1)
                d = np.linalg.norm(a + t * ab - p)
                if d < best: best, bi = d, i
            c.InsertControlPoint(bi + 1, vtk.vtkVector3d(*p))
            tmp.RemoveObserver(self._addTag); tmp.RemoveAllControlPoints()
            slicer.app.applicationLogic().GetInteractionNode().SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.ViewTransform)
            done()
        self._addTag = tmp.AddObserver(slicer.vtkMRMLMarkupsNode.PointPositionDefinedEvent, onDefined)
        sel = slicer.app.applicationLogic().GetSelectionNode(); sel.SetReferenceActivePlaceNodeClassName("vtkMRMLMarkupsFiducialNode")
        sel.SetActivePlaceNodeID(tmp.GetID())
        slicer.app.applicationLogic().GetInteractionNode().SetCurrentInteractionMode(slicer.vtkMRMLInteractionNode.Place)
