"""
Week 2: 空氣品質與避難收容處所之空間交叉分析
Spatial Cross-Analysis of Air Quality and Evacuation Shelters

功能：
  Task 1 — 避難所資料審計：座標品質檢查 + is_indoor 語意推論
  Task 2 — 空間疊圖：AQI 測站 + 避難所 folium 互動地圖
  Task 3 — 最近測站分析：Haversine 最近鄰 + 情境注入 + 風險標記
"""

import os
import csv
import math
import re
import requests
import urllib3
from dotenv import load_dotenv
import folium
from folium import plugins

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================
# 設定區 (Configuration)
# ============================================================

# 載入 .env
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

MOENV_API_KEY = os.getenv("MOENV_API_KEY")
PROJECT_CRS = os.getenv("PROJECT_CRS", "4326")

# 路徑設定
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
RAW_SHELTER_CSV = os.path.join(DATA_DIR, "避難收容處所點位檔案v9.csv")
CLEANED_SHELTER_CSV = os.path.join(DATA_DIR, "shelters_cleaned.csv")
ANALYSIS_CSV = os.path.join(OUTPUT_DIR, "shelter_aqi_analysis.csv")
MAP_OUTPUT = os.path.join(OUTPUT_DIR, "shelter_aqi_map.html")

# 環境部 AQI API
AQI_API_URL = "https://data.moenv.gov.tw/api/v2/aqx_p_432"

# 台灣邊界框（WGS84）— 用於座標驗證
TAIWAN_BOUNDS = {
    "lon_min": 118.0, "lon_max": 123.0,
    "lat_min": 21.5,  "lat_max": 26.5,
}

# ============================================================
# 情境注入設定（Scenario Injection）
# 若當天全台 AQI 偏低，手動將特定測站設為高值以測試邏輯
# ============================================================
SCENARIO_INJECTION = {
    "左營": 150,     # 高雄左營站 AQI 設為 150
    "林口": 120,     # 林口站 AQI 設為 120
}


# ============================================================
# 工具函式
# ============================================================

def haversine(lat1, lon1, lat2, lon2):
    """Haversine 公式：計算兩點間大圓距離（公里）"""
    R = 6371.0
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + \
        math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def infer_is_indoor(name):
    """
    根據設施名稱推論是否為室內設施
    - 室內關鍵字：學校、活動中心、體育館、教室、禮堂、圖書館...
    - 室外關鍵字：公園、廣場、河濱、停車場、操場...
    回傳 True（室內）、False（室外）
    """
    # 室外設施關鍵字（優先判斷，因為「XX公園活動中心」應為室外）
    outdoor_keywords = [
        "公園", "廣場", "河濱", "停車場", "操場", "運動場",
        "球場", "露天", "棒球場", "籃球場", "網球場",
        "空地", "綠地", "農場", "營區",
    ]
    # 室內設施關鍵字
    indoor_keywords = [
        "國小", "國中", "高中", "大學", "學校",
        "活動中心", "社區中心", "市民活動", "集會所",
        "體育館", "體育場館", "室內",
        "教室", "禮堂", "圖書館", "文化館",
        "區公所", "鄉公所", "鎮公所", "市公所", "村辦公",
        "里辦公", "衛生所", "消防",
        "教會", "寺廟", "宮", "殿", "廟",
        "幼兒園", "托兒所", "安養", "養護",
        "國民之家", "榮民之家", "老人會館",
    ]

    for kw in outdoor_keywords:
        if kw in name:
            return False

    for kw in indoor_keywords:
        if kw in name:
            return True

    # 預設為室內（多數避難所為學校或活動中心）
    return True


def get_aqi_color(aqi):
    """AQI 分色：0-50 綠、51-100 黃、101+ 紅"""
    if aqi <= 50:
        return "green"
    elif aqi <= 100:
        return "orange"
    else:
        return "red"


# ============================================================
# Task 1: 資料審計與清理
# ============================================================

def audit_and_clean_shelters():
    """
    讀取原始避難所 CSV，執行空間審計：
    1. 判斷座標系統（WGS84 vs TWD97）
    2. 移除無效座標（0,0、超出範圍）
    3. 新增 is_indoor 欄位
    4. 輸出 shelters_cleaned.csv
    回傳：(清理後的紀錄列表, 審計問題列表)
    """
    print("\n[Task 1] 載入避難所原始資料...")
    with open(RAW_SHELTER_CSV, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        raw_rows = list(reader)
    print(f"  原始筆數: {len(raw_rows)}")

    issues = []       # 審計問題紀錄
    cleaned = []       # 清理後的資料
    crs_check = {"wgs84": 0, "twd97": 0, "unknown": 0}

    for i, r in enumerate(raw_rows):
        row_num = i + 2
        lon_s = r["經度"].strip()
        lat_s = r["緯度"].strip()
        name = r["避難收容處所名稱"]
        county = r["縣市及鄉鎮市區"]

        # --- 座標解析 ---
        if not lon_s or not lat_s:
            issues.append(f"行{row_num}: {name} — 座標為空")
            continue
        try:
            lon = float(lon_s)
            lat = float(lat_s)
        except ValueError:
            issues.append(f"行{row_num}: {name} — 座標格式錯誤 ({lon_s}, {lat_s})")
            continue

        # --- CRS 判斷 ---
        # WGS84: 經度 ~118-123, 緯度 ~21-27
        # TWD97 (TM2): Easting ~150000-350000, Northing ~2400000-2850000
        if 118 <= lon <= 123 and 21 <= lat <= 27:
            crs_check["wgs84"] += 1
        elif 150000 <= lon <= 350000 and 2400000 <= lat <= 2850000:
            crs_check["twd97"] += 1
            issues.append(f"行{row_num}: {name} — 座標疑似 TWD97 ({lon}, {lat})")
            continue  # 無法直接使用，需轉換
        else:
            crs_check["unknown"] += 1

        # --- 零值檢查 ---
        if lon == 0 or lat == 0:
            issues.append(f"行{row_num}: {name} ({county}) — 座標含零值 ({lon}, {lat})")
            continue

        # --- 邊界檢查 ---
        if not (TAIWAN_BOUNDS["lon_min"] <= lon <= TAIWAN_BOUNDS["lon_max"] and
                TAIWAN_BOUNDS["lat_min"] <= lat <= TAIWAN_BOUNDS["lat_max"]):
            issues.append(f"行{row_num}: {name} ({county}) — 超出台灣範圍 ({lon}, {lat})")
            continue

        # --- 精度檢查 ---
        lon_dec = len(lon_s.split(".")[-1]) if "." in lon_s else 0
        lat_dec = len(lat_s.split(".")[-1]) if "." in lat_s else 0
        if lon_dec == 0 and lat_dec == 0:
            issues.append(f"行{row_num}: {name} — 座標為整數，精度嚴重不足 ({lon_s}, {lat_s})")
            continue

        # --- is_indoor 推論 ---
        is_indoor = infer_is_indoor(name)

        # --- 通過審計，加入清理資料 ---
        cleaned.append({
            "序號": r["序號"],
            "縣市": county,
            "村里": r["村里"],
            "地址": r["避難收容處所地址"],
            "經度": lon,
            "緯度": lat,
            "名稱": name,
            "預計收容人數": r["預計收容人數"],
            "適用災害類別": r["適用災害類別"],
            "室內": r["室內"],
            "室外": r["室外"],
            "is_indoor": is_indoor,
            "適合避難弱者安置": r["適合避難弱者安置"],
        })

    # 輸出結果
    removed = len(raw_rows) - len(cleaned)
    print(f"  CRS 判斷: WGS84={crs_check['wgs84']}, TWD97={crs_check['twd97']}, 未知={crs_check['unknown']}")
    print(f"  審計問題: {len(issues)} 筆")
    print(f"  移除無效: {removed} 筆")
    print(f"  清理後: {len(cleaned)} 筆")

    # 統計 is_indoor
    indoor_count = sum(1 for r in cleaned if r["is_indoor"])
    outdoor_count = len(cleaned) - indoor_count
    print(f"  is_indoor 推論: 室內={indoor_count}, 室外={outdoor_count}")

    # 存檔
    os.makedirs(DATA_DIR, exist_ok=True)
    fieldnames = cleaned[0].keys()
    with open(CLEANED_SHELTER_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cleaned)
    print(f"  已儲存: {CLEANED_SHELTER_CSV}")

    return cleaned, issues, crs_check


# ============================================================
# Task 2 & 3: AQI 擷取 + 疊圖 + 最近測站 + 風險標記
# ============================================================

def fetch_aqi_data():
    """擷取即時 AQI 資料並套用情境注入"""
    print("\n[Task 2] 擷取即時 AQI 資料...")
    params = {
        "api_key": MOENV_API_KEY,
        "limit": 1000,
        "sort": "ImportDate desc",
        "format": "JSON",
    }
    response = requests.get(AQI_API_URL, params=params, timeout=30, verify=False)
    response.raise_for_status()
    data = response.json()
    records = data if isinstance(data, list) else data.get("records", [])

    # 解析有效測站
    stations = []
    for r in records:
        try:
            lon = float(r.get("longitude", ""))
            lat = float(r.get("latitude", ""))
            aqi = int(r.get("aqi", "-1"))
        except (ValueError, TypeError):
            continue
        if lon == 0 or lat == 0 or aqi < 0:
            continue

        site_name = r.get("sitename", "")

        # 情境注入：覆寫特定測站的 AQI
        if site_name in SCENARIO_INJECTION:
            original_aqi = aqi
            aqi = SCENARIO_INJECTION[site_name]
            print(f"  ⚠ 情境注入: {site_name} AQI {original_aqi} → {aqi}")

        stations.append({
            "sitename": site_name,
            "county": r.get("county", ""),
            "aqi": aqi,
            "status": r.get("status", ""),
            "lon": lon,
            "lat": lat,
        })

    print(f"  有效測站: {len(stations)} 個")

    # 檢查是否需要情境注入提醒
    max_aqi = max(s["aqi"] for s in stations) if stations else 0
    if max_aqi < 50:
        print("  ℹ 今日全台 AQI 偏低，已套用情境注入以測試風險標記邏輯")

    return stations


def find_nearest_station(shelter_lat, shelter_lon, stations):
    """找出離避難所最近的 AQI 測站，回傳 (站名, AQI, 距離km)"""
    best = None
    for st in stations:
        dist = haversine(shelter_lat, shelter_lon, st["lat"], st["lon"])
        if best is None or dist < best[2]:
            best = (st["sitename"], st["aqi"], dist)
    return best


def classify_risk(aqi, is_indoor):
    """
    風險分級：
    - High Risk: 最近測站 AQI > 100
    - Warning: 最近測站 AQI > 50 且為室外設施
    - Normal: 其他
    """
    if aqi > 100:
        return "High Risk"
    elif aqi > 50 and not is_indoor:
        return "Warning"
    else:
        return "Normal"


def create_overlay_map(shelters, stations):
    """
    Task 2: 建立 AQI + 避難所疊圖
    Task 3: 最近測站分析 + 風險標記
    """
    print("\n[Task 2] 建立空間疊圖...")
    print("[Task 3] 計算最近測站與風險標記...")

    m = folium.Map(location=[23.5, 120.9], zoom_start=8)

    # --- 圖層 A: AQI 測站 ---
    aqi_layer = folium.FeatureGroup(name="AQI 測站")
    for st in stations:
        color = get_aqi_color(st["aqi"])
        injected = " ⚠情境注入" if st["sitename"] in SCENARIO_INJECTION else ""
        popup_html = f"""
        <div style="font-family: sans-serif;">
            <b>{st['sitename']}</b>{injected}<br>
            縣市: {st['county']}<br>
            AQI: <b style="color:{color}; font-size:16px;">{st['aqi']}</b><br>
            狀態: {st['status']}
        </div>"""
        folium.CircleMarker(
            location=[st["lat"], st["lon"]],
            radius=12, color=color, fill=True,
            fill_color=color, fill_opacity=0.8,
            popup=folium.Popup(popup_html, max_width=200),
            tooltip=f"{st['sitename']} AQI:{st['aqi']}",
        ).add_to(aqi_layer)
    aqi_layer.add_to(m)

    # --- 圖層 B: 避難收容處所 + 風險分析 ---
    shelter_layer = folium.FeatureGroup(name="避難收容處所")
    analysis_results = []

    for sh in shelters:
        nearest = find_nearest_station(sh["緯度"], sh["經度"], stations)
        if not nearest:
            continue

        nearest_name, nearest_aqi, nearest_dist = nearest
        risk = classify_risk(nearest_aqi, sh["is_indoor"])

        # 圖標：室內用藍色房屋、室外用綠色樹木
        if sh["is_indoor"]:
            icon_color = "blue"
            icon_name = "home"
            facility_type = "室內"
        else:
            icon_color = "green"
            icon_name = "tree-deciduous"
            facility_type = "室外"

        # 風險高的用紅色覆蓋
        if risk == "High Risk":
            icon_color = "red"
        elif risk == "Warning":
            icon_color = "orange"

        popup_html = f"""
        <div style="font-family: sans-serif; min-width: 200px;">
            <h4 style="margin:0 0 5px 0;">{sh['名稱']}</h4>
            <b>縣市:</b> {sh['縣市']}<br>
            <b>類型:</b> {facility_type}<br>
            <b>最近測站:</b> {nearest_name} ({nearest_dist:.1f} km)<br>
            <b>該站 AQI:</b> {nearest_aqi}<br>
            <b style="color:{'red' if risk=='High Risk' else 'orange' if risk=='Warning' else 'green'};">
            風險等級: {risk}</b>
        </div>"""

        folium.Marker(
            location=[sh["緯度"], sh["經度"]],
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=f"{sh['名稱']} [{risk}]",
            icon=folium.Icon(color=icon_color, icon=icon_name, prefix="glyphicon"),
        ).add_to(shelter_layer)

        # 收集分析結果
        analysis_results.append({
            "名稱": sh["名稱"],
            "縣市": sh["縣市"],
            "緯度": sh["緯度"],
            "經度": sh["經度"],
            "is_indoor": sh["is_indoor"],
            "設施類型": facility_type,
            "最近測站": nearest_name,
            "測站AQI": nearest_aqi,
            "距離(km)": round(nearest_dist, 2),
            "風險等級": risk,
        })

    shelter_layer.add_to(m)

    # 圖層控制器
    folium.LayerControl().add_to(m)

    # 圖例
    legend_html = """
    <div style="position: fixed; bottom: 30px; left: 30px; z-index: 1000;
                background: white; padding: 12px; border-radius: 8px;
                box-shadow: 0 2px 6px rgba(0,0,0,0.3); font-size: 12px;">
        <b>圖例</b><br>
        <b>AQI 測站:</b><br>
        <span style="color:green;">●</span> 0-50 良好
        <span style="color:orange;">●</span> 51-100 普通
        <span style="color:red;">●</span> 101+ 不良<br><br>
        <b>避難所:</b><br>
        🏠 藍色=室內 🌳 綠色=室外<br>
        🔴 紅色=High Risk 🟠 橙色=Warning
    </div>"""
    m.get_root().html.add_child(folium.Element(legend_html))

    # 儲存地圖
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    m.save(MAP_OUTPUT)
    print(f"  地圖已儲存: {MAP_OUTPUT}")

    # 風險統計
    risk_counts = {}
    for r in analysis_results:
        risk_counts[r["風險等級"]] = risk_counts.get(r["風險等級"], 0) + 1
    print(f"\n  風險統計:")
    for risk, count in sorted(risk_counts.items()):
        print(f"    {risk}: {count} 個避難所")

    return analysis_results


def export_analysis_csv(results):
    """輸出分析結果 CSV"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    fieldnames = results[0].keys()
    with open(ANALYSIS_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"\n  分析結果已儲存: {ANALYSIS_CSV}")

    # 顯示 High Risk 範例
    high_risk = [r for r in results if r["風險等級"] == "High Risk"]
    if high_risk:
        print(f"\n  High Risk 避難所範例（前 10 筆）:")
        print(f"  {'名稱':>12s}  {'縣市':>6s}  {'類型':>4s}  {'最近測站':>6s}  {'AQI':>4s}  {'距離km':>8s}")
        print(f"  {'-'*52}")
        for r in high_risk[:10]:
            print(f"  {r['名稱']:>12s}  {r['縣市']:>6s}  {r['設施類型']:>4s}  {r['最近測站']:>6s}  {r['測站AQI']:>4d}  {r['距離(km)']:>8.2f}")


# ============================================================
# 主程式
# ============================================================

if __name__ == "__main__":
    print("=" * 58)
    print("  Week 2: 空氣品質與避難收容處所之空間交叉分析")
    print(f"  Project CRS: EPSG:{PROJECT_CRS}")
    print("=" * 58)

    # Task 1: 資料審計與清理
    shelters, audit_issues, crs_info = audit_and_clean_shelters()

    # Task 2 & 3: AQI 擷取 + 疊圖 + 最近測站 + 風險標記
    stations = fetch_aqi_data()
    results = create_overlay_map(shelters, stations)

    # 輸出分析 CSV
    export_analysis_csv(results)

    # 儲存審計問題供 audit_report.md 使用
    issues_path = os.path.join(OUTPUT_DIR, "_audit_issues.txt")
    with open(issues_path, "w", encoding="utf-8") as f:
        f.write("\n".join(audit_issues))

    print(f"\n{'='*58}")
    print("  完成！")
    print(f"  地圖: {MAP_OUTPUT}")
    print(f"  分析: {ANALYSIS_CSV}")
    print(f"  清理資料: {CLEANED_SHELTER_CSV}")
    print(f"{'='*58}")
