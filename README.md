# HUCViewS — 心臓・大動脈 3D ビューア

造影 CT（CD-R や DICOM フォルダ）から、心臓の 3D（心内膜・心外膜・心筋の断面）、VR（ボリュームレンダリング）、大動脈の 3D とサイジング（中心線・径・長さ）を作って見るためのソフトです。
中身は [3D Slicer](https://www.slicer.org/)（無料のオープンソース）＋ AI（[TotalSegmentator](https://github.com/wasserth/TotalSegmentator)）＋ 北海道大学 心臓血管外科で作った画面です。

> **注意（必ずお読みください）**
> - 本ソフトは **医療機器ではありません**。研究・教育・術前のイメージ作りのためのものです。
> - **診断・治療方針の決定には使わないでください。** 必ず元の画像と正式なビューアで確認してください。
> - AI の自動認識や「薄い壁の補完」で、本物の欠損（VSD・穿孔など）が埋まって見えることがあります。
> - 患者データはお使いの PC の中だけで扱います。本ソフトがインターネットへ送ることはありません（更新の確認だけ GitHub に問い合わせます）。

## インストール

**かんたんダウンロードページ：https://lfb15345-del.github.io/HUCViewS/** （ボタンを押してダウンロード → 開くだけ）

### Windows 10 / 11（管理者権限は不要）
1. [最新リリース](https://github.com/lfb15345-del/HUCViewS/releases/latest) から **`HUCViewS_Windows.exe`** をダウンロードして実行
   - 「Windows によって PC が保護されました」と出たら「詳細情報」→「実行」（署名のない配布物のため）
2. 黒い画面の案内に沿って待つ（10〜30 分。3D Slicer と AI の部品を自動で入れます）
3. デスクトップの **HUCViewS** から起動

exe が使えない場合は、PowerShell に次を貼っても同じです：
```powershell
irm https://github.com/lfb15345-del/HUCViewS/releases/latest/download/install.ps1 | iex
```

### macOS（Apple Silicon / Intel）
「ターミナル」に次を貼って Enter：
```bash
curl -fsSL https://github.com/lfb15345-del/HUCViewS/releases/latest/download/install_mac.sh | bash
```
終わると、ホームの「アプリケーション」に **HUCViewS** ができます。

**Mac の制約**：3D Slicer の Mac 版は Intel 用のみで、Apple Silicon（M1〜）では Rosetta 2 で動きます（インストーラーが自動で入れます）。
表示・切断・計測・大動脈サイジングは使えますが、**AI による自動認識は Mac では遅い、または動かない場合があります**。
その場合は Windows で「3D を作る」まで行って症例を保存し、Mac では「保存した症例を開く」で見てください。

## AI ライセンス（心腔の色分けに必要・無料）
左右の心腔の色分けと心筋の断面には、TotalSegmentator の心腔モデル（heartchambers_highres）を使います。
このモデルは学術用の無料ライセンスが必要です。[こちら](https://backend.totalsegmentator.com/license-academic/)で各自申請し、
起動後の画面の「AI ライセンスを登録する」に番号を入れてください（番号はその PC にだけ保存されます）。
ライセンスがなくても、簡易表示（色分けなし）で使えます。

## 自動更新
起動するたびに、このリポジトリの最新リリースを確認し、新しい版があれば数秒で入れ替えます（ネットにつながらないときは今の版で起動）。

## 必要な PC
- Windows 10/11（64bit）または macOS 12 以降
- メモリ 16 GB 以上（32 GB 推奨）、空き容量 15 GB 以上
- GPU は必須ではありません（あると VR と AI が速くなります）

## ライセンス
- 本ソフト（このリポジトリのコード）：[PolyForm Noncommercial License 1.0.0](LICENSE.md)（**非営利・研究・教育目的に限り**利用・改変・再配布できます。商用利用は不可）
  - Required Notice: Copyright (c) 2026 HUCVS — Department of Cardiovascular Surgery, Hokkaido University
- 3D Slicer：[3D Slicer License](https://github.com/Slicer/Slicer/blob/main/License.txt)（BSD 系）
- TotalSegmentator：コードは Apache-2.0。一部の学習済みモデル（heartchambers_highres など）は個別の学術ライセンスが必要です。

## 連絡先
北海道大学 心臓血管外科（HUCVS）— 不具合や要望は [Issues](https://github.com/lfb15345-del/HUCViewS/issues) へ（**患者情報・画像は絶対に貼らないでください**）。

---

**English summary** — HUCViewS is a cardiac / aortic 3D viewer built on 3D Slicer and TotalSegmentator. **Not a medical device; for research and education only — do not use for diagnosis.** Install on Windows with `HUCViewS_Windows.exe` from the latest release (or the PowerShell one-liner), and on macOS with the Terminal one-liner above. The app updates itself from GitHub releases at start-up. Patient data never leaves your computer. License: PolyForm Noncommercial 1.0.0.
