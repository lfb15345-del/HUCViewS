# -*- coding: utf-8 -*-
"""心臓の画面（CardiacView）: 定数・色合い・画面の見た目（スタイル）・小さな関数・画面の上の表示（_Hud）
部品（CardiacViewLib/*.py）は from .common import * で、ここの名前を全部（_ で始まる名前も）使う。
ただし LIVE_NAMES（色合いを選ぶと置き換わる名前など）は写さない: 部品は common.名前 で今の値を読む。"""
import os, sys, math, time, re, json
import numpy as np
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *

MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # CardiacView のフォルダ（この部品の 1 つ上）

DEFAULT_LAYERS = [
    # name,        lo,    hi,   color,                 smooth, visible
    ("軟部組織",   -150,  170, (0.86, 0.66, 0.42), 2, False),
    ("血液・血管",  180, 3000, (0.93, 0.42, 0.50), 1, True),
]
BONE_COLOR = (0.88, 0.86, 0.80)
WALL_COLOR = (0.91, 0.80, 0.58)
EPI_COLOR  = (0.84, 0.72, 0.64)   # 心外膜（外側）: くすんだベージュ（黄色を抑える）
ENDO_COLOR = (0.94, 0.76, 0.72)   # 左心系の内膜: 淡いピンク（内腔は明るく＝空洞に見える）
ENDO_R_COLOR = (0.74, 0.80, 0.94) # 右心系の内膜: 淡い青
SYNTH_COLOR = (0.60, 0.61, 0.64)  # 補った壁（CT 値の裏付けなし）: 冷たいグレー
MYO_CUT_COLOR = (0.64, 0.17, 0.15)  # 心筋の切り口（実質）
MYO_COLOR = (0.55, 0.15, 0.14)    # 心筋（左室＋中隔＋右室自由壁）: 濃い筋肉の赤（実質＝詰まっている）   # 心筋・血管壁（Viewtify 風の黄色）
# 血管の色分け（TotalSegmentator のラベル名に含まれる文字列 → 色）
# 色は2系統だけ: 動脈血（赤系）と静脈血（青系）。彩度を落として落ち着かせる
VESSEL_GROUPS = [
    ("血管:大動脈系", ("aorta", "brachiocephalic trunk", "subclavian artery", "common carotid artery", "iliac artery"), (0.74, 0.14, 0.16)),
    ("血管:体静脈",   ("vena cava", "brachiocephalic vein", "subclavian vein", "jugular vein", "portal vein", "azygos", "iliac vena"), (0.24, 0.34, 0.60)),
    ("血管:肺静脈",   ("pulmonary vein",),                                     (0.84, 0.40, 0.36)),
    ("血管:心臓",     ("heart", "atrial appendage", "atrium", "ventricle", "myocardium"), (0.66, 0.28, 0.32)),
]
VESSEL_OTHER = ("血管:肺動脈ほか", (0.40, 0.52, 0.78))
LEGEND_WALL = [("外膜", (0.84, 0.72, 0.64)), ("左心系の内膜", (0.94, 0.76, 0.72)), ("右心系の内膜", (0.74, 0.80, 0.94)),
               ("補った壁（CT値の裏付けなし）", (0.60, 0.61, 0.64)), ("心筋（AIラベル）", (0.64, 0.17, 0.15))]
IMPLANT_COLOR = (0.80, 0.83, 0.90)  # 人工物（金属: 人工弁のリング・ステント・クリップなど）: 銀
CALC_COLOR = (1.00, 0.92, 0.55)     # 石灰化: 明るい黄白
WIRE_COLOR = (0.96, 0.56, 0.20)     # 胸骨ワイヤー（金属）: 銅色（骨の白と見分ける）
PATCH_COLOR = (0.96, 0.88, 0.64)    # パッチ: 淡いクリーム（心膜・線維組織のような生体らしい色で、心臓の赤・桃・紫と見分けやすい。ミントはカビに見える。真っ白だとまぶしい・浮く。石灰化の黄白・金属の銀とは別）
LEGEND = [("石灰化", CALC_COLOR), ("人工物(金属・胸骨ワイヤー)", IMPLANT_COLOR), ("パッチの範囲（自動）", PATCH_COLOR), ("大動脈", (0.74, 0.14, 0.16)), ("肺静脈", (0.84, 0.40, 0.36)), ("心腔", (0.66, 0.28, 0.32)),
          ("肺動脈", (0.40, 0.52, 0.78)), ("上下大静脈", (0.24, 0.34, 0.60)), ("心筋・壁", (0.91, 0.80, 0.58))]
# ---- 色合い（設定 → 見た目 → 色合い）。分け方（どの部屋・血管を何色の系統にするか）は同じで、色の濃さ・光沢だけ変える
#   リアル: 動脈系 = 深紅（少し青みのある赤）、静脈系・右心系 = 薄紫、心筋・脂肪 = 金色。シネマティック表示に近い色（光沢やや強め）
#   赤と青: 動脈系 = 深い赤、静脈系 = 濃い青（教科書の色）
#   落ち着いた: これまでの色（彩度を落とした色）
PALETTES = {
    "リアル": dict(aorta=(0.74, 0.18, 0.28), sysvein=(0.60, 0.52, 0.78), pv=(0.82, 0.32, 0.40), heart=(0.72, 0.17, 0.27), heartR=(0.50, 0.40, 0.70), la=(0.86, 0.42, 0.48), ra=(0.70, 0.62, 0.84), pa=(0.48, 0.38, 0.68),
                 myo=(0.84, 0.56, 0.58), myocut=(0.86, 0.60, 0.60), epi=(0.86, 0.70, 0.42), endo=(0.88, 0.58, 0.52), endoR=(0.70, 0.62, 0.84),
                 bone=(0.94, 0.91, 0.84), calc=(1.00, 0.95, 0.72),
                 vr=[(0.70, 0.12, 0.20), (0.80, 0.26, 0.33), (0.72, 0.12, 0.20), (0.78, 0.22, 0.30), (0.80, 0.26, 0.33),
                     (0.40, 0.30, 0.62), (0.52, 0.42, 0.72), (0.38, 0.28, 0.60), (0.46, 0.38, 0.68)], vrN=(0.84, 0.60, 0.60),
                 vrPale=0.5, vrSeptum=(0.55, 0.16, 0.45),                       # 中隔の心筋は赤紫（左室の壁・右室の壁と区別）                                                   # VR: 心筋の濃さの所は、その部屋の色を淡くした色（左室の壁 = 淡い深紅、右室の壁 = 淡い紫）。造影された血液は部屋の色
                 spec=0.45, power=35.0, amb=0.15, dif=0.90),
    "赤と青": dict(aorta=(0.70, 0.16, 0.17), sysvein=(0.23, 0.24, 0.50), pv=(0.76, 0.24, 0.22), heart=(0.65, 0.17, 0.18), heartR=(0.28, 0.32, 0.61), la=(0.80, 0.40, 0.28), ra=(0.40, 0.54, 0.76), pa=(0.29, 0.33, 0.63),
                 myo=(0.52, 0.13, 0.12), myocut=(0.59, 0.17, 0.15), epi=(0.82, 0.72, 0.54), endo=(0.77, 0.35, 0.31), endoR=(0.41, 0.45, 0.72),
                 bone=(0.94, 0.91, 0.84), calc=(1.00, 0.95, 0.70),
                 vr=[(0.76, 0.24, 0.23), (0.82, 0.34, 0.30), (0.80, 0.20, 0.20), (0.84, 0.32, 0.28), (0.82, 0.34, 0.30),
                     (0.32, 0.36, 0.69), (0.38, 0.43, 0.74), (0.31, 0.34, 0.67), (0.34, 0.38, 0.71)], vrN=(0.82, 0.53, 0.46),
                 spec=0.35, power=30.0, amb=0.18, dif=0.85),
    "落ち着いた": dict(aorta=(0.74, 0.14, 0.16), sysvein=(0.24, 0.34, 0.60), pv=(0.84, 0.40, 0.36), heart=(0.66, 0.28, 0.32), heartR=(0.46, 0.54, 0.80), la=(0.86, 0.52, 0.42), ra=(0.60, 0.70, 0.90), pa=(0.40, 0.52, 0.78),
                  myo=(0.55, 0.15, 0.14), myocut=(0.64, 0.17, 0.15), epi=(0.84, 0.72, 0.64), endo=(0.94, 0.76, 0.72), endoR=(0.74, 0.80, 0.94),
                  bone=(0.88, 0.86, 0.80), calc=(1.00, 0.92, 0.55),
                  vr=[(0.88, 0.44, 0.40), (0.95, 0.62, 0.50), (0.93, 0.30, 0.28), (0.95, 0.55, 0.45), (0.95, 0.62, 0.50),
                      (0.45, 0.58, 0.90), (0.58, 0.68, 0.93), (0.42, 0.50, 0.88), (0.50, 0.62, 0.92)], vrN=(0.88, 0.72, 0.62),
                  spec=0.40, power=35.0, amb=0.12, dif=0.82),
}
PALETTE_KEY = "HUCViewS/palette"
CUR_PALETTE = "リアル"
_VG_BASE = [(g[0], g[1]) for g in VESSEL_GROUPS]


def _setPalette(name):
    """モジュールの色（新しく作る面・凡例・壁の色表）を、選んだ色合いに置き換える"""
    global BONE_COLOR, EPI_COLOR, ENDO_COLOR, ENDO_R_COLOR, MYO_CUT_COLOR, MYO_COLOR, CALC_COLOR, VESSEL_GROUPS, VESSEL_OTHER, LEGEND, LEGEND_WALL, CUR_PALETTE
    if name not in PALETTES: name = "リアル"
    p = PALETTES[name]; CUR_PALETTE = name
    BONE_COLOR, EPI_COLOR, ENDO_COLOR, ENDO_R_COLOR = p["bone"], p["epi"], p["endo"], p["endoR"]
    MYO_CUT_COLOR, MYO_COLOR, CALC_COLOR = p["myocut"], p["myo"], p["calc"]
    VESSEL_GROUPS = [(nm, keys, p[k]) for (nm, keys), k in zip(_VG_BASE, ("aorta", "sysvein", "pv", "heart"))]
    VESSEL_OTHER = ("血管:肺動脈ほか", p["pa"])
    LEGEND = [("石灰化", CALC_COLOR), ("人工物(金属・胸骨ワイヤー)", IMPLANT_COLOR), ("パッチの範囲（自動）", PATCH_COLOR), ("大動脈", p["aorta"]), ("肺静脈", p["pv"]),
              ("左房", p["la"]), ("左室", p["heart"]), ("右房", p["ra"]), ("右室", p["heartR"]), ("肺動脈", p["pa"]), ("上下大静脈", p["sysvein"]), ("心筋・壁", p["epi"])]
    LEGEND_WALL = [("外膜", p["epi"]), ("左心系の内膜", p["endo"]), ("右心系の内膜", p["endoR"]), ("補った壁（CT値の裏付けなし）", SYNTH_COLOR), ("心筋（AIラベル）", p["myocut"])]
    return p


try: _setPalette(str(qt.QSettings().value(PALETTE_KEY) or "リアル"))
except Exception: pass

CV_LAYOUT_CUT = 5711          # 3D（左・大）＋ 切っている面の断面（右）
CV_LAYOUT_CUT_XML = """
<layout type="horizontal" split="true">
 <item splitSize="600"><view class="vtkMRMLViewNode" singletontag="1"><property name="viewlabel" action="default">1</property></view></item>
 <item splitSize="420"><view class="vtkMRMLSliceNode" singletontag="Red"><property name="orientation" action="default">Axial</property><property name="viewlabel" action="default">C</property><property name="viewcolor" action="default">#F39A33</property></view></item>
</layout>
"""
CV_LAYOUT_FOUR = 5712         # 4 画面（2×2 を必ず等分）: 左上 横断 / 右上 3D / 左下 矢状断 / 右下 冠状断
CV_LAYOUT_FOUR_XML = """
<layout type="vertical" split="true">
 <item splitSize="500"><layout type="horizontal" split="true">
  <item splitSize="500"><view class="vtkMRMLSliceNode" singletontag="Red"><property name="orientation" action="default">Axial</property><property name="viewlabel" action="default">R</property><property name="viewcolor" action="default">#F34A33</property></view></item>
  <item splitSize="500"><view class="vtkMRMLViewNode" singletontag="1"><property name="viewlabel" action="default">1</property></view></item>
 </layout></item>
 <item splitSize="500"><layout type="horizontal" split="true">
  <item splitSize="500"><view class="vtkMRMLSliceNode" singletontag="Yellow"><property name="orientation" action="default">Sagittal</property><property name="viewlabel" action="default">Y</property><property name="viewcolor" action="default">#EDD54C</property></view></item>
  <item splitSize="500"><view class="vtkMRMLSliceNode" singletontag="Green"><property name="orientation" action="default">Coronal</property><property name="viewlabel" action="default">G</property><property name="viewcolor" action="default">#6EB04B</property></view></item>
 </layout></item>
</layout>
"""
BONE_KEYWORDS = ("rib", "sternum", "vertebra", "clavicula", "scapula", "costal", "humerus", "hip", "sacrum")
MAX_TRIS = 400000          # 1レイヤーあたりの三角形数の上限（操作の軽さ優先）


def _bbox3(mask, pad=0):
    """mask の 0 でない所を含む範囲（各軸を pad 個ずつ広げ、配列の中に収める）を slice の組で返す。無ければ None。
    面づくり・ぼかしをこの範囲の中だけで行うのに使う（外はいつも 0 なので、余白がぼかしの半径より広ければ結果は 1 ビットも同じ）"""
    sl = []
    for ax in range(mask.ndim):
        nz = np.flatnonzero(mask.any(axis=tuple(i for i in range(mask.ndim) if i != ax)))
        if len(nz) == 0: return None
        sl.append(slice(max(int(nz[0]) - pad, 0), min(int(nz[-1]) + 1 + pad, mask.shape[ax])))
    return tuple(sl)
CUT_MODES = [("切らない", None), ("画面の正面から", "VIEW"), ("前後（冠状断）", 1), ("左右（矢状断）", 0), ("上下（横断）", 2)]


CV_STYLE = """
QWidget#cvRoot { background:#15171c; }
QWidget#cvRoot QLabel { color:#e6e8ec; background:transparent; font-size:12px; }
QWidget#cvRoot QLabel[role="muted"] { color:#8a909b; font-size:11px; }
QWidget#cvRoot QLabel[role="h"] { color:#f2f4f7; font-size:12px; font-weight:bold; }
QWidget#cvRoot QLabel[role="title"] { color:#ffffff; font-size:16px; font-weight:bold; }
QWidget#cvRoot QLabel[role="accent"] { color:#4cc8f0; font-size:12px; font-weight:bold; }
QWidget#cvRoot QLabel[role="colh"] { color:#7d8590; font-size:10px; }
QWidget#cvRoot QFrame[role="card"] { background:#1e2128; border:1px solid #2b3039; border-radius:10px; }
QWidget#cvRoot QPushButton { background:#262a33; color:#e6e8ec; border:1px solid #343a46; border-radius:7px; padding:5px 8px; font-size:12px; }
QWidget#cvRoot QPushButton:hover { background:#2e333e; border-color:#4a5263; }
QWidget#cvRoot QPushButton:pressed { background:#363c49; }
QWidget#cvRoot QPushButton:checked { background:#173f57; border:1px solid #4cc8f0; color:#ffffff; font-weight:bold; }
QWidget#cvRoot QPushButton:disabled { color:#5d636e; border-color:#2a2e36; }
QWidget#cvRoot QPushButton[kind="primary"] { background:#2f7bf6; border:1px solid #2f7bf6; color:white; font-weight:bold; padding:8px 12px; font-size:13px; }
QWidget#cvRoot QPushButton[kind="primary"]:hover { background:#4a8dff; }
QWidget#cvRoot QPushButton[kind="primary"]:disabled { background:#2a3a55; border-color:#2a3a55; color:#8a909b; }
QWidget#cvRoot QPushButton[kind="ghost"] { background:transparent; border:none; color:#8a909b; padding:4px 6px; }
QWidget#cvRoot QPushButton[kind="ghost"]:hover { color:#ffffff; }
QWidget#cvRoot QPushButton[kind="step"] { background:transparent; border:none; border-bottom:2px solid #2b3039; border-radius:0; color:#8a909b; font-weight:bold; padding:7px 2px; }
QWidget#cvRoot QPushButton[kind="step"]:hover { color:#cfd3da; }
QWidget#cvRoot QPushButton[kind="step"]:checked { color:#ffffff; border-bottom:2px solid #4cc8f0; background:transparent; }
QWidget#cvRoot QPushButton[kind="seg"] { border-radius:6px; padding:5px 4px; }
QWidget#cvRoot QPushButton[kind="tool"] { padding:6px 2px; }
QWidget#cvRoot QPushButton[kind="vr"] { padding:5px 4px; }
QWidget#cvRoot QPushButton[kind="vr"]:checked { background:#4a2a20; border:1px solid #e8916f; color:#ffffff; }
QWidget#cvRoot QPushButton[kind="play"] { font-weight:bold; font-size:13px; }
QWidget#cvRoot QPushButton[kind="play"]:checked { background:#2f7bf6; border:1px solid #2f7bf6; }
QWidget#cvRoot QCheckBox { color:#e6e8ec; background:transparent; spacing:6px; font-size:12px; }
QWidget#cvRoot QCheckBox:disabled { color:#5d636e; }
QWidget#cvRoot QCheckBox::indicator { width:14px; height:14px; border:1px solid #5a6273; border-radius:4px; background:#262a33; }
QWidget#cvRoot QCheckBox::indicator:hover { border-color:#4cc8f0; }
QWidget#cvRoot QCheckBox::indicator:checked { background:#2f7bf6; border:1px solid #4a8dff; }
QWidget#cvRoot QAbstractSpinBox::up-button, QWidget#cvRoot QAbstractSpinBox::down-button { subcontrol-origin:border; width:16px; background:#2e333e; border:none; }
QWidget#cvRoot QAbstractSpinBox::up-button { subcontrol-position:top right; border-top-right-radius:6px; }
QWidget#cvRoot QAbstractSpinBox::down-button { subcontrol-position:bottom right; border-bottom-right-radius:6px; }
QWidget#cvRoot QAbstractSpinBox::up-button:hover, QWidget#cvRoot QAbstractSpinBox::down-button:hover { background:#3a404c; }
QWidget#cvRoot QComboBox::drop-down { border:none; width:18px; }
QWidget#cvRoot QComboBox { background:#262a33; color:#e6e8ec; border:1px solid #343a46; border-radius:7px; padding:4px 8px; font-size:12px; }
QWidget#cvRoot QComboBox QAbstractItemView { background:#1e2128; color:#e6e8ec; selection-background-color:#1f4d69; }
QWidget#cvRoot QSpinBox, QWidget#cvRoot QDoubleSpinBox, QWidget#cvRoot QLineEdit { background:#262a33; color:#e6e8ec; border:1px solid #343a46; border-radius:6px; padding:2px 4px; selection-background-color:#1f4d69; font-size:12px; }
QWidget#cvRoot QSlider::groove:horizontal { height:4px; background:#343a46; border-radius:2px; }
QWidget#cvRoot QSlider::sub-page:horizontal { background:#2f7bf6; border-radius:2px; }
QWidget#cvRoot QSlider::handle:horizontal { background:#e6e8ec; width:14px; height:14px; margin:-5px 0; border-radius:7px; }
QWidget#cvRoot QScrollBar:vertical { background:transparent; width:8px; }
QWidget#cvRoot QScrollBar::handle:vertical { background:#3a404c; border-radius:4px; min-height:24px; }
QWidget#cvRoot QScrollBar::add-line, QWidget#cvRoot QScrollBar::sub-line { height:0; }
"""

_APP_VER = None


def appVer():
    """入っている版（app\\version.txt の「年月日-時分」）。性能の記録に入れて、どの PC がどの版で動いているかを離れた所から分かるようにする。読めなければ """""
    global _APP_VER
    if _APP_VER is None:
        v = ""
        for d in (os.environ.get("HEARTVIEW_HOME") or "", os.path.dirname(os.path.dirname(MODULE_DIR))):
            try:
                if d and os.path.exists(os.path.join(d, "version.txt")): v = open(os.path.join(d, "version.txt"), encoding="ascii").read().strip()[:20]; break
            except Exception: pass
        _APP_VER = v
    return _APP_VER


def statusKind(msg):
    """画面の文の種類: "err"（失敗）/ "warn"（注意）/ ""（ふつう）"""
    m = str(msg or "")
    if re.match(r"\s*(?:\S{1,6} ?)?エラー", m): return "err"                 # 「エラー: …」「VR エラー: …」「読み込みエラー: …」
    return "warn" if ("⚠" in m or "失敗" in m) else ""


STATUS_CSS = {"err": "color:#ff8f85; font-size:12px;", "warn": "color:#f2c66d; font-size:12px;"}


def paintStatus(label, msg):
    """失敗・注意の文は色と大きさを変える（前は、ふつうの案内と同じ小さい灰色の字で、見落としやすかった）"""
    try:
        css = STATUS_CSS.get(statusKind(msg), "")
        if css != (label.styleSheet or ""): label.setStyleSheet(css)
    except Exception: pass


def _iconCSS():
    """スピン・コンボの矢印とチェックの印（SVG を一時フォルダに書いて使う）"""
    try:
        d = os.path.join(qt.QDir.tempPath(), "hucviews_ui"); os.makedirs(d, exist_ok=True)
        svg = {"up": "<path d='M1 6 L5 1 L9 6' stroke='#c3c8d1' stroke-width='1.6' fill='none'/>",
               "down": "<path d='M1 1 L5 6 L9 1' stroke='#c3c8d1' stroke-width='1.6' fill='none'/>",
               "check": "<path d='M2 6 L5 9 L10 2' stroke='#ffffff' stroke-width='2' fill='none' stroke-linecap='round' stroke-linejoin='round'/>"}
        size = {"up": (10, 7), "down": (10, 7), "check": (12, 11)}
        u = {}
        for k, body in svg.items():
            w, h = size[k]; f = os.path.join(d, k + ".svg")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}'>{body}</svg>")
            u[k] = f.replace("\\", "/")
        return (f"QWidget#cvRoot QAbstractSpinBox::up-arrow {{ image:url({u['up']}); width:10px; height:7px; }}\n"
                f"QWidget#cvRoot QAbstractSpinBox::down-arrow {{ image:url({u['down']}); width:10px; height:7px; }}\n"
                f"QWidget#cvRoot QComboBox::down-arrow {{ image:url({u['down']}); width:10px; height:7px; }}\n"
                f"QWidget#cvRoot QCheckBox::indicator:checked {{ image:url({u['check']}); }}\n")
    except Exception as e:
        print("ui icons:", e); return ""


SC_STYLE = ("QScrollArea{background:#15171c; border:none}"
            "QScrollBar:vertical{background:#15171c; width:10px; margin:0}"
            "QScrollBar::handle:vertical{background:#3a404c; border-radius:4px; min-height:30px; margin:2px}"
            "QScrollBar::handle:vertical:hover{background:#4a5263}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{height:0}"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical{background:none}")

HELP_TEXT = ("3D 画面の操作\n"
             "・左ドラッグ: 回転\n"
             "・右ドラッグ: 「右ドラッグ」で選んだ機能（拡大・ウィンドウ・移動・切る位置）\n"
             "・中ボタンドラッグ: 移動\n"
             "・ホイール: 切る位置（1 mm、Shift で 5 mm）。切っていない時は拡大縮小\n"
             "・Ctrl+ホイール: 拡大縮小\n"
             "・左右ボタン同時ドラッグ: VR のウィンドウ\n"
             "4画面\n"
             "・Shift+マウス移動: 3 断面の十字が追従\n"
             "・断面の左ドラッグ: ウィンドウ\n"
             "・ダブルクリック: 1 画面に拡大")


WL_PRESETS = [("心臓・血管（造影）", 800, 200), ("縦隔・軟部", 400, 40), ("石灰化・ステント", 1500, 450), ("骨", 2000, 500), ("肺", 1500, -600)]

TB_STYLE = """
QToolBar#HUCViewSToolBar { background:#15171c; border:none; border-bottom:1px solid #2b3039; spacing:1px; padding:3px 8px; }
QToolBar#HUCViewSToolBar::separator { background:#2b3039; width:1px; margin:6px 7px; }
QToolBar#HUCViewSToolBar QToolButton { color:#c9ced6; background:transparent; border:1px solid transparent; border-radius:7px; padding:3px 5px 2px 5px; font-size:11px; min-width:44px; }
QToolBar#HUCViewSToolBar QToolButton:hover { background:#232730; color:#ffffff; }
QToolBar#HUCViewSToolBar QToolButton:pressed { background:#2b303a; }
QToolBar#HUCViewSToolBar QToolButton:checked { background:#173f57; border:1px solid #4cc8f0; color:#ffffff; }
QToolBar#HUCViewSToolBar QToolButton::menu-indicator { image:none; width:0; }
QToolBar#HUCViewSToolBar QLabel#tbBrand { color:#ffffff; font-size:14px; font-weight:bold; padding:0 10px 0 2px; }
QMenu { background:#1e2128; color:#e6e8ec; border:1px solid #343a46; padding:4px; }
QMenu::item { padding:6px 18px 6px 12px; border-radius:5px; }
QMenu::item:selected { background:#1f4d69; }
QMenu::separator { height:1px; background:#2b3039; margin:4px 6px; }
"""

HELP_HTML = ("<div style='font-size:12px; line-height:150%'>"
             "<b style='color:#4cc8f0'>3D 画面</b><br>"
             "左ドラッグ：回転　／　中ドラッグ：移動<br>"
             "右ドラッグ：上のバーで選んだ機能（拡大・ウィンドウ・移動・切る位置）<br>"
             "ホイール：切る位置（1 mm、Shift で 5 mm）。切っていない時は拡大縮小<br>"
             "Ctrl＋ホイール：拡大縮小　／　左右ボタン同時ドラッグ：VR のウィンドウ<br><br>"
             "<b style='color:#4cc8f0'>断面</b><br>"
             "ホイール：スライス送り　／　左ドラッグ：ウィンドウ<br>"
             "Shift＋マウス：3 断面の十字が追従　／　ダブルクリック：1 画面に拡大<br>"
             "線の真ん中をドラッグ：位置　／　線の端の丸をドラッグ：斜めの断面<br><br>"
             "<b style='color:#4cc8f0'>計測</b><br>"
             "計測にマウスを乗せて Delete：1 つ消す　／　「消去」：すべて消す</div>")


def _toolIcons():
    """ツールバーのアイコン（線画の SVG を一時フォルダに書いて使う）"""
    s = "stroke='#d6dae1' stroke-width='1.7' fill='none' stroke-linecap='round' stroke-linejoin='round'"
    F = "#d6dae1"
    body = {
        "zoom": "<circle cx='10.5' cy='10.5' r='6.2'/><path d='M15.2 15.2L20.5 20.5M8 10.5h5M10.5 8v5'/>",
        "window": f"<circle cx='12' cy='12' r='8'/><path d='M12 4a8 8 0 0 0 0 16z' fill='{F}'/>",
        "pan": "<path d='M12 3v18M3 12h18M9.5 5.5L12 3l2.5 2.5M9.5 18.5L12 21l2.5-2.5M5.5 9.5L3 12l2.5 2.5M18.5 9.5L21 12l-2.5 2.5'/>",
        "cut": "<path d='M3 15.5l5-4h13l-5 4z'/><path d='M12 9V3M9.8 5.2L12 3l2.2 2.2M12 17.5V21'/>",
        "line": f"<path d='M5.5 18.5l13-13'/><circle cx='5' cy='19' r='1.9' fill='{F}'/><circle cx='19' cy='5' r='1.9' fill='{F}'/>",
        "curve": f"<path d='M4 18c4.5 0 3.5-12 8-12s3.5 12 8 12'/><circle cx='4' cy='18' r='1.7' fill='{F}'/><circle cx='20' cy='18' r='1.7' fill='{F}'/>",
        "area": f"<path d='M5 9l6-4.5 8 4.5-2 10H7z' fill='{F}' fill-opacity='0.18'/>",
        "angle": "<path d='M4 19h16M4 19L14.5 5.5'/><path d='M10.5 19a6.5 6.5 0 0 0-2.4-5'/>",
        "clear": "<path d='M5 7h14M9.5 7V4.5h5V7M7 7l1 13h8l1-13M10.5 11v5.5M13.5 11v5.5'/>",
        "one": "<rect x='4' y='4' width='16' height='16' rx='2.5'/>",
        "two": "<rect x='4' y='4' width='16' height='16' rx='2.5'/><path d='M12 4v16'/>",
        "four": "<rect x='4' y='4' width='16' height='16' rx='2.5'/><path d='M12 4v16M4 12h16'/>",
        "fit": "<path d='M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5'/><rect x='8.5' y='8.5' width='7' height='7' rx='1.5'/>",
        "wl": "<path d='M4 7h9M17 7h3M4 17h3M11 17h9'/><circle cx='15' cy='7' r='2.2'/><circle cx='9' cy='17' r='2.2'/>",
        "reset": "<path d='M4.5 12a7.5 7.5 0 1 0 2.3-5.4'/><path d='M4.5 4v4.5H9'/>",
        "camera": "<rect x='3' y='7' width='18' height='13' rx='2.5'/><path d='M8.5 7l1.8-3h3.4l1.8 3'/><circle cx='12' cy='13.5' r='3.5'/>",
        "help": f"<circle cx='12' cy='12' r='9'/><path d='M9.6 9.6a2.5 2.5 0 1 1 3.4 2.3c-.7.3-1 .8-1 1.6'/><circle cx='12' cy='16.8' r='.8' fill='{F}'/>",
    }
    out = {}
    try:
        d = os.path.join(qt.QDir.tempPath(), "hucviews_ui"); os.makedirs(d, exist_ok=True)
        for k, b in body.items():
            f = os.path.join(d, f"tb_{k}.svg")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(f"<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24'><g {s}>{b}</g></svg>")
            out[k] = f
    except Exception as e: print("tool icons:", e)
    return out


class _Hud:
    """画面の上の小さな表示（日本語・半透明の帯）。VTK の文字ではなく Qt のラベルで描く"""
    BOX = "QLabel{background:rgba(14,16,20,178); color:#e6e8ec; border-radius:6px; padding:3px 8px; font-size:12px;}"
    EDGE = "QLabel{background:transparent; color:rgba(245,205,95,230); font-size:13px; font-weight:bold; padding:0;}"

    def __init__(self):
        self.items = {}; self.on = True

    def _view(self, key):
        lm = slicer.app.layoutManager()
        if key == "3d": return lm.threeDWidget(0).threeDView()
        w = lm.sliceWidget(key); return w.sliceView() if w is not None else None

    def set(self, key, pos, html):
        lab = self.items.get((key, pos))
        if not html:
            if lab is not None:
                try: lab.setText(""); lab.hide()
                except Exception: self.items.pop((key, pos), None)
            return
        try:
            v = self._view(key)
            if v is None: return
            if lab is not None and lab.parentWidget() is not v:                # 画面割りを変えると断面の部品が作り直されることがある
                try: lab.hide(); lab.setParent(None); lab.deleteLater()
                except Exception: pass
                lab = None
            if lab is None:
                lab = qt.QLabel(v); lab.setAttribute(qt.Qt.WA_TransparentForMouseEvents, True); lab.setTextFormat(qt.Qt.RichText)
                lab.setStyleSheet(self.EDGE if len(pos) == 1 else self.BOX); self.items[(key, pos)] = lab
            if lab.text != html: lab.setText(html); lab.adjustSize()
            if self.on:
                if not lab.visible: lab.show()
                lab.raise_()
            self._place(pos, lab, key)
        except Exception: self.items.pop((key, pos), None)

    def _place(self, pos, lab, key=None):
        p = lab.parentWidget(); W, H = p.width, p.height; w, h = lab.width, lab.height; m = 8
        x, y = {"tl": (m, m), "tr": (W - w - m, m), "bl": (m, H - h - m), "br": (W - w - m, H - h - m),
                "L": (7, (H - h) // 2), "R": (W - w - 7, (H - h) // 2), "T": ((W - w) // 2, 6), "B": ((W - w) // 2, H - h - 30)}[pos]
        if pos == "T":                                                        # 左上の帯と重なる時は、その下へ
            tl = self.items.get((key, "tl"))
            try:
                if tl is not None and tl.visible and tl.x + tl.width + 4 > x: y = tl.y + tl.height + 3
            except Exception: pass
        lab.move(int(x), int(y))

    def placeAll(self):
        for (k, pos), lab in list(self.items.items()):
            try:
                if lab.visible: self._place(pos, lab, k)
            except Exception: self.items.pop((k, pos), None)

    def show(self, on):
        self.on = bool(on)
        for key, lab in list(self.items.items()):
            try: lab.setVisible(self.on and bool(lab.text))
            except Exception: self.items.pop(key, None)


def _hud():
    h = getattr(slicer, "_cvHud", None)
    if h is not None and not isinstance(h, _Hud):                        # モジュールを読み直した時は古い表示を片づけて作り直す
        try: h.show(False)
        except Exception: pass
        h = None
    if h is None: h = slicer._cvHud = _Hud()
    return h


def _cvCur():
    """今の画面（CardiacView のパネル）が使っているロジック。マウス操作は必ずここへ届ける（古い症例のロジックに横取りされない）"""
    try: return slicer.modules.cardiacview.widgetRepresentation().self().logic
    except Exception: return None


# 色合いを選ぶと置き換わる名前（_setPalette）と、一度だけ調べて覚える名前（appVer）。部品へは写さない（写すと古い値のままになる）
LIVE_NAMES = ('BONE_COLOR', 'EPI_COLOR', 'ENDO_COLOR', 'ENDO_R_COLOR', 'MYO_CUT_COLOR', 'MYO_COLOR', 'CALC_COLOR', 'VESSEL_GROUPS', 'VESSEL_OTHER', 'LEGEND', 'LEGEND_WALL', 'CUR_PALETTE', '_APP_VER')
__all__ = [n for n in list(globals()) if not n.startswith("__") and n not in LIVE_NAMES]   # 部品から * で全部（_ で始まる名前も）使えるように
