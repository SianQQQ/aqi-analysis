# AQI 空氣品質監測與空間分析工具

**課程：** 遙測與空間資訊分析及應用（114）
**學生：** 張育憲 R14623019
**作業：** 第一週 — AQI 空間分析與地圖產製
**主要協作 AI：** Claude Code (Sonnet 4.6)

---

## 程式功能說明

本程式共完成三項任務：

| 任務 | 功能 |
|------|------|
| 任務 1 | 串接環境部 API 取得全台即時 AQI 資料並繪製互動地圖 |
| 任務 2 | 依 AQI 數值分色標記（綠/橙/紅），點擊測站顯示詳細資訊 |
| 任務 3 | 計算每個測站到台北車站的距離，輸出 CSV 報表 |

---

## 專案結構

```
aqi-analysis/
├── main.py              # 主程式
├── requirements.txt     # 套件需求
├── .env                 # API Key（不上傳 GitHub）
├── .gitignore
└── outputs/
    ├── aqi_map.html     # 互動地圖（用瀏覽器開啟）
    └── aqi_with_distance.csv  # 測站距離報表
```

---

## 安裝與執行

### 1. 安裝套件

```bash
pip install -r requirements.txt
```

### 2. 設定 API Key

建立 `.env` 檔案，填入環境部授權碼：

```
MOENV_API_KEY=你的授權碼
```

API Key 申請：[環境部開放資料平台](https://data.moenv.gov.tw/)

### 3. 執行程式

```bash
python main.py
```

### 4. 查看結果

- 互動地圖：用瀏覽器開啟 `outputs/aqi_map.html`
- 距離報表：開啟 `outputs/aqi_with_distance.csv`

---

## 技術說明

### 資料來源
- **API：** 環境部 `aqx_p_432`（全台即時 AQI）
- **格式：** JSON，每次取得最多 1000 筆測站資料

### AQI 分色標準

| 顏色 | AQI 範圍 | 意義 |
|------|----------|------|
| 綠色 | 0 – 50 | 良好 |
| 橙色 | 51 – 100 | 普通 |
| 紅色 | 101 以上 | 不良 |
| 灰色 | — | 無資料 |

### 距離計算方法
使用 **Haversine 公式** 計算球面大圓距離（公里），以台北車站（25.0478°N, 121.5170°E）為基準點。

### 已知問題
環境部網站 SSL 憑證缺少 Subject Key Identifier，與 Python 3.14 的嚴格驗證不相容，程式中使用 `verify=False` 繞過此問題（這是政府網站的憑證問題，非程式錯誤）。

---

## AI 協作開發流程

1. 提供基本環境資訊（Mac + Cursor IDE）
2. 將作業中的 Prompt 逐一提供給 AI
3. 要求 AI 詳列執行步驟，逐步審核後再執行
4. 執行完成後輸入繳交確認 Prompt，請 AI 進行最終檢查
