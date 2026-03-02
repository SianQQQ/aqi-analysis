"""
第一週實作任務：空氣品質監測與空間分析
Week 1 Mission: AQI Monitoring & Spatial Analysis

功能：
1. 串接環境部 API (aqx_p_432) 獲取全台即時 AQI 數據
2. 使用 folium 繪製互動地圖（分色標記 + 資訊彈窗）
3. 計算每個測站到台北車站的距離
4. 輸出 CSV 報表
"""

import os
import csv
import math
import ssl
import requests
import urllib3
import folium
from dotenv import load_dotenv

# 環境部網站 SSL 憑證缺少 Subject Key Identifier，Python 3.14 會報錯
# 這是政府網站的問題，這裡建立自訂 SSL 設定來處理
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ============================================================
# 設定區 (Configuration)
# ============================================================

# 載入 .env 檔案中的環境變數
load_dotenv()

# 從環境變數讀取 API Key
API_KEY = os.getenv("MOENV_API_KEY")
if not API_KEY or API_KEY == "your_actual_key":
    raise ValueError("請先在 .env 檔案中填入你的 MOENV_API_KEY")

# 環境部 API 端點（aqx_p_432：即時 AQI 資料）
API_URL = "https://data.moenv.gov.tw/api/v2/aqx_p_432"

# 台北車站座標（用於距離計算）
TAIPEI_STATION_LAT = 25.0478
TAIPEI_STATION_LON = 121.5170

# 輸出路徑
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")
MAP_OUTPUT = os.path.join(OUTPUT_DIR, "aqi_map.html")
CSV_OUTPUT = os.path.join(OUTPUT_DIR, "aqi_with_distance.csv")


# ============================================================
# 工具函式 (Utility Functions)
# ============================================================

def get_aqi_color(aqi_value):
    """
    根據 AQI 數值回傳對應的顏色
    - 0~50：綠色（良好）
    - 51~100：黃色（普通）
    - 101 以上：紅色（不良）
    """
    if aqi_value <= 50:
        return "green"
    elif aqi_value <= 100:
        return "orange"  # folium 中 orange 比 yellow 在地圖上更清楚
    else:
        return "red"


def haversine(lat1, lon1, lat2, lon2):
    """
    使用 Haversine 公式計算兩點之間的大圓距離（公里）
    參數：兩組經緯度（十進位度數）
    回傳：距離（公里）
    """
    R = 6371.0  # 地球半徑（公里）

    # 將角度轉為弧度
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    # Haversine 公式
    a = math.sin(dlat / 2) ** 2 + \
        math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


# ============================================================
# 主要功能 (Main Functions)
# ============================================================

def fetch_aqi_data():
    """
    呼叫環境部 API 取得全台即時 AQI 資料
    回傳：測站資料列表（list of dict）
    """
    params = {
        "api_key": API_KEY,
        "limit": 1000,       # 取得所有測站資料
        "sort": "ImportDate desc",
        "format": "JSON",
    }

    print("正在從環境部 API 擷取即時 AQI 資料...")
    # verify=False 是因為環境部 SSL 憑證與 Python 3.14 不完全相容
    response = requests.get(API_URL, params=params, timeout=30, verify=False)
    response.raise_for_status()

    data = response.json()

    # API 可能直接回傳 list，也可能包在 records 裡
    if isinstance(data, list):
        records = data
    else:
        records = data.get("records", [])

    print(f"成功取得 {len(records)} 筆測站資料")
    return records


def create_aqi_map(records):
    """
    使用 folium 建立 AQI 互動地圖
    - 以台灣中心為地圖中心
    - 依 AQI 分色標記測站
    - 點擊測站顯示詳細資訊
    """
    # 以台灣中心點建立地圖
    taiwan_map = folium.Map(
        location=[23.5, 120.9],  # 台灣地理中心（約南投）
        zoom_start=8,
        tiles="OpenStreetMap",
    )

    valid_count = 0

    for record in records:
        # 取得經緯度，跳過缺失資料
        lat = record.get("latitude", "")
        lon = record.get("longitude", "")
        if not lat or not lon:
            continue

        try:
            lat = float(lat)
            lon = float(lon)
        except (ValueError, TypeError):
            continue

        # 取得 AQI 數值
        aqi_str = record.get("aqi", "")
        try:
            aqi_value = int(aqi_str)
        except (ValueError, TypeError):
            aqi_value = -1  # 無效值

        # 取得測站資訊
        site_name = record.get("sitename", "未知")
        county = record.get("county", "未知")
        status = record.get("status", "未知")
        publish_time = record.get("publishtime", "未知")

        # 決定標記顏色
        if aqi_value >= 0:
            color = get_aqi_color(aqi_value)
            aqi_display = str(aqi_value)
        else:
            color = "gray"
            aqi_display = "N/A"

        # 建立資訊彈窗的 HTML 內容
        popup_html = f"""
        <div style="font-family: 'Microsoft JhengHei', sans-serif; min-width: 180px;">
            <h4 style="margin: 0 0 8px 0; color: #333;">{site_name}</h4>
            <table style="font-size: 13px;">
                <tr><td><b>縣市：</b></td><td>{county}</td></tr>
                <tr><td><b>AQI：</b></td><td><b style="color: {color}; font-size: 16px;">{aqi_display}</b></td></tr>
                <tr><td><b>狀態：</b></td><td>{status}</td></tr>
                <tr><td><b>更新：</b></td><td>{publish_time}</td></tr>
            </table>
        </div>
        """

        # 在地圖上加入標記
        folium.CircleMarker(
            location=[lat, lon],
            radius=10,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.7,
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=f"{site_name} (AQI: {aqi_display})",
        ).add_to(taiwan_map)

        valid_count += 1

    # 加入圖例
    legend_html = """
    <div style="position: fixed; bottom: 30px; left: 30px; z-index: 1000;
                background: white; padding: 12px 16px; border-radius: 8px;
                box-shadow: 0 2px 6px rgba(0,0,0,0.3);
                font-family: 'Microsoft JhengHei', sans-serif; font-size: 13px;">
        <b>AQI 空氣品質指標</b><br>
        <span style="color: green;">●</span> 0–50 良好<br>
        <span style="color: orange;">●</span> 51–100 普通<br>
        <span style="color: red;">●</span> 101+ 不良<br>
        <span style="color: gray;">●</span> 無資料
    </div>
    """
    taiwan_map.get_root().html.add_child(folium.Element(legend_html))

    # 儲存地圖
    taiwan_map.save(MAP_OUTPUT)
    print(f"地圖已儲存至：{MAP_OUTPUT}（共 {valid_count} 個測站）")

    return taiwan_map


def calculate_distances_and_export(records):
    """
    計算每個測站到台北車站的距離，並輸出 CSV 檔案
    CSV 欄位：測站名稱、縣市、AQI、經度、緯度、到台北車站距離(km)
    """
    results = []

    for record in records:
        lat = record.get("latitude", "")
        lon = record.get("longitude", "")
        if not lat or not lon:
            continue

        try:
            lat = float(lat)
            lon = float(lon)
        except (ValueError, TypeError):
            continue

        # 計算到台北車站的距離
        distance = haversine(lat, lon, TAIPEI_STATION_LAT, TAIPEI_STATION_LON)

        results.append({
            "測站名稱": record.get("sitename", ""),
            "縣市": record.get("county", ""),
            "AQI": record.get("aqi", ""),
            "狀態": record.get("status", ""),
            "緯度": lat,
            "經度": lon,
            "到台北車站距離(km)": round(distance, 2),
            "更新時間": record.get("publishtime", ""),
        })

    # 依距離排序
    results.sort(key=lambda x: x["到台北車站距離(km)"])

    # 寫入 CSV
    if results:
        fieldnames = results[0].keys()
        with open(CSV_OUTPUT, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        print(f"CSV 已儲存至：{CSV_OUTPUT}（共 {len(results)} 筆）")
    else:
        print("警告：沒有有效的測站資料可輸出")

    return results


# ============================================================
# 程式進入點 (Entry Point)
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("  空氣品質監測與空間分析工具")
    print("  AQI Monitoring & Spatial Analysis")
    print("=" * 50)

    # 步驟 1：擷取即時 AQI 資料
    records = fetch_aqi_data()

    # 步驟 2：建立互動地圖（含分色標記與資訊彈窗）
    create_aqi_map(records)

    # 步驟 3：計算距離並輸出 CSV
    results = calculate_distances_and_export(records)

    # 顯示前 5 筆（距台北車站最近的測站）
    print("\n距離台北車站最近的 5 個測站：")
    print(f"{'測站':>8s}  {'縣市':>4s}  {'AQI':>5s}  {'距離(km)':>10s}")
    print("-" * 38)
    for r in results[:5]:
        print(f"{r['測站名稱']:>8s}  {r['縣市']:>4s}  {r['AQI']:>5s}  {r['到台北車站距離(km)']:>10.2f}")

    print(f"\n完成！請開啟 {MAP_OUTPUT} 檢視互動地圖")
