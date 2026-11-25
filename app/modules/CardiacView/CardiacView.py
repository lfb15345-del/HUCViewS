# -*- coding: utf-8 -*-
r"""
CardiacView — 3D Slicer scripted module（かんたんモード版）
HU 帯域ごとの等値面レイヤー ＋ スライダーで動かす切断面 ＋ 視点ボタン。
"""

import os, sys
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path: sys.path.insert(0, _HERE)
for _k in [k for k in list(sys.modules) if k == "CardiacViewLib" or k.startswith("CardiacViewLib.")]:
    del sys.modules[_k]                               # 読み直し（Reload）の時も部品を新しく読む
from CardiacViewLib.common import *
from CardiacViewLib import common, ui_build, ui_base, ui_view, ui_case, ui_patch, logic_core, logic_metal, logic_auto, logic_volume, logic_surface, logic_wall, logic_patch, logic_autopatch, logic_cut, logic_vr, logic_perf, logic_layout, logic_mouse, logic_4d, logic_look
from CardiacViewLib.logic_cut import _Inset
from CardiacViewLib.logic_layout import _MprMark

# 部品の地図（どこに何があるか）
#   CardiacViewLib/ui_build.py — 画面を組み立てる（setup）
#   CardiacViewLib/ui_base.py — 画面の部品・共通（画像の上のツールバー・凡例・色合い・陰影・カード・ボタン・タブ・お知らせ・入る／出る）
#   CardiacViewLib/ui_view.py — 表示の操作（4D の再生・層・切断・VR・補う・ふた・場面の切り替え）
#   CardiacViewLib/ui_case.py — 読み込み・3D を作る・保存・大動脈サイジングへ
#   CardiacViewLib/ui_patch.py — パッチ（塗って色分け・自動で探す・外す）・VSD
#   CardiacViewLib/logic_core.py — 土台（初期化・シーンの小道具）と、層（面）の作成・表示・色合い・つや
#   CardiacViewLib/logic_metal.py — 人工物（金属・胸骨ワイヤー）・骨・石灰化
#   CardiacViewLib/logic_auto.py — 全自動（CT の読み込み・格子・AI・較正・品質・手順・シーンの引き継ぎ）
#   CardiacViewLib/logic_volume.py — 元の CT と作業用の画像・AI のラベル（マスク）の取り出し
#   CardiacViewLib/logic_surface.py — 面づくり（マスク → なめらかな面）・向き・表示の設定
#   CardiacViewLib/logic_wall.py — 心筋・壁（外膜・内膜）・心筋の断面のふた・四腔
#   CardiacViewLib/logic_patch.py — パッチ（3D の面の上で塗って色分け）・シートにする
#   CardiacViewLib/logic_autopatch.py — パッチを自動で探す（VSD）・外す・やり直し・面の向き
#   CardiacViewLib/logic_cut.py — 切断（クリップ: 再計算なし・即時）・全体図（_Inset）・自由平面
#   CardiacViewLib/logic_vr.py — VR（ボリュームレンダリング）: 心内構造・造影・色分け・窓・切断との同期・動かす間だけ粗く
#   CardiacViewLib/logic_perf.py — 性能の自動調整（GPU なしの PC でも、なめらかさ優先）・性能の記録（この PC と NAS）
#   CardiacViewLib/logic_layout.py — 一般的なビューアの機能: スケール・右ドラッグの切り替え・画面の並び（1・2・4 画面）・MPR・計測
#   CardiacViewLib/logic_mouse.py — マウス・キー（3D と断面: 回転・拡大・ウィンドウ・移動・切る位置・削除）
#   CardiacViewLib/logic_4d.py — 4D（動く心臓）: 読み込み・窓・色・再生・位相
#   CardiacViewLib/logic_look.py — 見た目（陰影・光・深さの剥離を切る・背景）とカメラ（視点・視野・大動脈に沿って飛ぶ）
#   CardiacViewLib/common.py — 定数・色合い・画面の見た目（スタイル）・小さな関数・画面の上の表示（_Hud）


class CardiacView(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        parent.title = "Cardiac View"
        parent.categories = ["HUCVS"]
        parent.dependencies = []
        parent.contributors = ["HUCVS (with Claude)"]
        parent.helpText = "HU 帯域の等値面レイヤー、切断面、視点プリセット。研究・教育用。"
        parent.acknowledgementText = "Built on 3D Slicer, VMTK, TotalSegmentator."


# =============================================================================== Widget
class CardiacViewWidget(ui_build.WidgetBuildMixin, ui_base.WidgetBaseMixin, ui_view.ViewUIMixin, ui_case.CaseUIMixin, ui_patch.PatchUIMixin, ScriptedLoadableModuleWidget):
    """画面。中身は CardiacViewLib/ui_*.py"""


# =============================================================================== Logic
class CardiacViewLogic(logic_core.CoreMixin, logic_metal.MetalMixin, logic_auto.AutoMixin, logic_volume.VolumeMixin, logic_surface.SurfaceMixin, logic_wall.WallMixin, logic_patch.PatchMixin, logic_autopatch.AutoPatchMixin, logic_cut.CutMixin, logic_vr.VRMixin, logic_perf.PerfMixin, logic_layout.LayoutMixin, logic_mouse.MouseMixin, logic_4d.FourDMixin, logic_look.LookMixin, ScriptedLoadableModuleLogic):
    """計算と表示。中身は CardiacViewLib/logic_*.py"""


for _m in (ui_build, ui_base, ui_view, ui_case, ui_patch, logic_core, logic_metal, logic_auto, logic_volume, logic_surface, logic_wall, logic_patch, logic_autopatch, logic_cut, logic_vr, logic_perf, logic_layout, logic_mouse, logic_4d, logic_look):
    _m.CardiacViewLogic = CardiacViewLogic; _m.CardiacViewWidget = CardiacViewWidget; _m.CardiacView = CardiacView


def __getattr__(name):
    """色合いで置き換わる名前（凡例・面の色など）は、CardiacView.名前 でも今の値を返す（common から）"""
    if name in common.LIVE_NAMES: return getattr(common, name)
    raise AttributeError(f"module 'CardiacView' has no attribute '{name}'")
