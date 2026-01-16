# Analemma Solar Capture System

Raspberry PiとZWO ASI224MCカメラを使用して、毎日正午の太陽を自動撮影し、1年間のアナレンマ（8の字パターン）を記録するシステムです。

## 特徴

- 毎日指定時刻に自動撮影
- ZWO ASI224MCカメラ対応
- FITS/PNG形式での画像保存
- メタデータの自動記録
- systemdサービスとしての運用
- CLIによる手動操作・状態確認

## 必要なハードウェア

- Raspberry Pi 4/5
- ZWO ASI224MC カメラ
- 2.1mm魚眼レンズ
- 溶接シェード #11（太陽撮影用フィルター）

## インストール

### 1. udevルールの設定

```bash
sudo cp systemd/99-zwo.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

### 2. アプリケーションのインストール

```bash
cd /home/pi
git clone <repository>
cd analemma-capture
python -m venv venv
source venv/bin/activate
pip install -e .
```

### 3. 設定ファイルの作成

```bash
cp config/config.example.yaml config/config.yaml
# config.yamlを編集して設定をカスタマイズ
```

### 4. systemdサービスの有効化

```bash
sudo cp systemd/analemma-capture.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable analemma-capture
sudo systemctl start analemma-capture
```

## 使い方

### 手動撮影

```bash
analemma capture
```

### カメラ情報の確認

```bash
analemma camera-info
```

### システム状態の確認

```bash
analemma status
```

### デーモンモードで起動

```bash
analemma daemon
```

### 設定の確認

```bash
analemma config --show
```

## 設定ファイル

`config/config.yaml` で以下の項目を設定できます：

```yaml
camera:
  exposure_us: 1000      # 露出時間（マイクロ秒）
  gain: 0                # ゲイン（0-300）
  image_type: "fits"     # 画像形式（fits/png）
  wb_r: 52               # ホワイトバランスR
  wb_b: 95               # ホワイトバランスB

schedule:
  capture_time: "12:00"  # 撮影時刻（HH:MM）
  timezone: "Asia/Tokyo" # タイムゾーン

storage:
  base_path: "/home/pi/analemma/images"
  monthly_subfolders: true
  min_free_space_mb: 1024

logging:
  level: "INFO"
  file: "/var/log/analemma/capture.log"
  max_size_mb: 10
  backup_count: 5
```

## ライセンス

MIT License
