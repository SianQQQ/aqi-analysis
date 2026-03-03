"""
避難收容處所點位檔案 資料品質審計程式
Data Quality Audit for Taiwan Shelter Location Dataset

功能：
1. 讀取原始 CSV 並執行全面品質檢查
2. 標記所有問題紀錄
3. 輸出修正後的 CSV 與問題摘要
"""

import csv
import re
import os
from collections import Counter, defaultdict

# ============================================================
# 設定
# ============================================================

INPUT_CSV = os.path.join(os.path.dirname(__file__), "data", "避難收容處所點位檔案v9.csv")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")
ISSUES_CSV = os.path.join(OUTPUT_DIR, "audit_issues.csv")
SUMMARY_TXT = os.path.join(OUTPUT_DIR, "audit_summary.txt")


# ============================================================
# 審計函式
# ============================================================

def load_data(path):
    """載入 CSV 資料"""
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def audit_missing_values(rows):
    """檢查各欄位的空值"""
    issues = []
    for i, r in enumerate(rows):
        for col in ["村里", "避難收容處所地址", "適用災害類別"]:
            if not r[col].strip():
                issues.append({
                    "行號": i + 2,
                    "名稱": r["避難收容處所名稱"],
                    "縣市": r["縣市及鄉鎮市區"],
                    "問題類別": "空值",
                    "問題描述": f"「{col}」欄位為空",
                    "原始值": "",
                    "建議修正": "需補填",
                })
    return issues


def audit_coordinates(rows):
    """檢查經緯度問題：零值、超出範圍、精度不足、疑似互換"""
    issues = []
    for i, r in enumerate(rows):
        lon_s = r["經度"].strip()
        lat_s = r["緯度"].strip()
        name = r["避難收容處所名稱"]
        county = r["縣市及鄉鎮市區"]
        base = {"行號": i + 2, "名稱": name, "縣市": county}

        # 空值
        if not lon_s or not lat_s:
            issues.append({**base, "問題類別": "座標空值",
                           "問題描述": "經度或緯度為空",
                           "原始值": f"({lon_s}, {lat_s})", "建議修正": "需補填座標"})
            continue

        try:
            lon = float(lon_s)
            lat = float(lat_s)
        except ValueError:
            issues.append({**base, "問題類別": "座標格式錯誤",
                           "問題描述": "無法轉為數字",
                           "原始值": f"({lon_s}, {lat_s})", "建議修正": "需修正格式"})
            continue

        # 經度為零
        if lon == 0:
            issues.append({**base, "問題類別": "座標零值",
                           "問題描述": "經度為 0，資料缺失",
                           "原始值": f"(0, {lat})", "建議修正": "需補填正確經度"})

        # 超出台灣範圍（含離島：118~123, 21~27）
        elif lon < 118 or lon > 123:
            issues.append({**base, "問題類別": "座標超出範圍",
                           "問題描述": f"經度 {lon} 不在台灣範圍 (118~123)",
                           "原始值": f"({lon}, {lat})", "建議修正": "確認是否少打一位數"})

        # 緯度為整數（截斷）
        if "." not in lat_s and lat != 0:
            issues.append({**base, "問題類別": "座標精度不足",
                           "問題描述": f"緯度為整數 {int(lat)}，疑似小數被截斷",
                           "原始值": f"({lon_s}, {lat_s})", "建議修正": "需補回完整小數"})

        # 經緯度都是整數
        elif "." not in lon_s and "." not in lat_s:
            issues.append({**base, "問題類別": "座標精度嚴重不足",
                           "問題描述": f"經緯度皆為整數 ({lon_s}, {lat_s})",
                           "原始值": f"({lon_s}, {lat_s})", "建議修正": "完全無法定位，需重新取得座標"})

        # 小數位數 < 3（精度 ~100 公尺以上）
        elif lon_s != "0" and lat_s != "0":
            lon_dec = len(lon_s.split(".")[-1]) if "." in lon_s else 0
            lat_dec = len(lat_s.split(".")[-1]) if "." in lat_s else 0
            if min(lon_dec, lat_dec) < 2:
                issues.append({**base, "問題類別": "座標精度偏低",
                               "問題描述": f"小數位數僅 {min(lon_dec, lat_dec)} 位",
                               "原始值": f"({lon_s}, {lat_s})", "建議修正": "精度約百公尺級，建議提高"})

    return issues


def audit_duplicate_coords(rows):
    """檢查不同避難所使用完全相同座標"""
    issues = []
    coord_groups = defaultdict(list)
    for i, r in enumerate(rows):
        lon = r["經度"].strip()
        lat = r["緯度"].strip()
        if lon and lat and lon != "0" and lat != "0":
            coord_groups[(lon, lat)].append((i + 2, r["避難收容處所名稱"], r["縣市及鄉鎮市區"]))

    for coord, items in coord_groups.items():
        names = set(n for _, n, _ in items)
        if len(names) > 1:
            for row_num, name, county in items:
                others = [n for _, n, _ in items if n != name]
                issues.append({
                    "行號": row_num, "名稱": name, "縣市": county,
                    "問題類別": "座標重複",
                    "問題描述": f"與「{'、'.join(others[:2])}」共用相同座標",
                    "原始值": f"({coord[0]}, {coord[1]})",
                    "建議修正": "各避難所應有獨立座標",
                })
    return issues


def audit_duplicates(rows):
    """檢查完全重複的紀錄（名稱+地址相同）"""
    issues = []
    seen = {}
    for i, r in enumerate(rows):
        key = (r["避難收容處所名稱"], r["避難收容處所地址"])
        if key in seen:
            issues.append({
                "行號": i + 2, "名稱": r["避難收容處所名稱"], "縣市": r["縣市及鄉鎮市區"],
                "問題類別": "重複紀錄",
                "問題描述": f"與行 {seen[key]} 完全重複（名稱+地址相同）",
                "原始值": r["避難收容處所地址"],
                "建議修正": "移除重複項",
            })
        else:
            seen[key] = i + 2
    return issues


def audit_phone(rows):
    """檢查電話欄位問題：科學記號、中文、格式異常"""
    issues = []
    for i, r in enumerate(rows):
        phone = r["管理人電話"].strip()
        name = r["避難收容處所名稱"]
        county = r["縣市及鄉鎮市區"]
        base = {"行號": i + 2, "名稱": name, "縣市": county}

        if not phone:
            continue

        # 科學記號（Excel 污染）
        if re.match(r"[\d.]+E\+\d+", phone, re.IGNORECASE):
            issues.append({**base, "問題類別": "電話科學記號",
                           "問題描述": "電話被 Excel 轉成科學記號，原始號碼已遺失",
                           "原始值": phone, "建議修正": "需重新查詢正確電話"})

        # 純中文（欄位填錯）
        elif re.match(r"^[\u4e00-\u9fff]+$", phone):
            issues.append({**base, "問題類別": "電話欄位填錯",
                           "問題描述": f"電話欄填入中文「{phone}」，疑似填入姓名",
                           "原始值": phone, "建議修正": "需修正為正確電話號碼"})

    return issues


def audit_capacity(rows):
    """檢查預計收容人數異常值"""
    issues = []
    for i, r in enumerate(rows):
        cap_str = r["預計收容人數"].strip()
        if not cap_str:
            continue
        try:
            cap = int(cap_str)
        except ValueError:
            issues.append({
                "行號": i + 2, "名稱": r["避難收容處所名稱"],
                "縣市": r["縣市及鄉鎮市區"],
                "問題類別": "收容人數格式錯誤",
                "問題描述": f"無法轉為整數：{cap_str}",
                "原始值": cap_str, "建議修正": "需修正格式",
            })
            continue

        if cap > 10000:
            issues.append({
                "行號": i + 2, "名稱": r["避難收容處所名稱"],
                "縣市": r["縣市及鄉鎮市區"],
                "問題類別": "收容人數異常大",
                "問題描述": f"預計收容 {cap:,} 人，請確認是否合理",
                "原始值": str(cap), "建議修正": "需人工確認",
            })
    return issues


# ============================================================
# 主程式
# ============================================================

if __name__ == "__main__":
    print("=" * 55)
    print("  避難收容處所點位檔案 — 資料品質審計")
    print("  Shelter Location Dataset — Data Quality Audit")
    print("=" * 55)

    # 載入資料
    rows = load_data(INPUT_CSV)
    print(f"\n載入 {len(rows)} 筆資料")

    # 執行各項審計
    all_issues = []

    checks = [
        ("空值檢查", audit_missing_values),
        ("座標檢查", audit_coordinates),
        ("座標重複", audit_duplicate_coords),
        ("重複紀錄", audit_duplicates),
        ("電話檢查", audit_phone),
        ("收容人數", audit_capacity),
    ]

    for check_name, check_func in checks:
        issues = check_func(rows)
        all_issues.extend(issues)
        print(f"  {check_name}: 發現 {len(issues)} 筆問題")

    print(f"\n共計 {len(all_issues)} 筆問題")

    # 問題分類統計
    category_counts = Counter(issue["問題類別"] for issue in all_issues)
    print("\n問題分類統計：")
    for cat, count in category_counts.most_common():
        print(f"  {cat}: {count} 筆")

    # 輸出問題清單 CSV
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if all_issues:
        fieldnames = ["行號", "名稱", "縣市", "問題類別", "問題描述", "原始值", "建議修正"]
        with open(ISSUES_CSV, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_issues)
        print(f"\n問題清單已輸出至：{ISSUES_CSV}")

    # 輸出摘要
    with open(SUMMARY_TXT, "w", encoding="utf-8") as f:
        f.write("避難收容處所點位檔案 — 審計摘要\n")
        f.write("=" * 40 + "\n\n")
        f.write(f"資料總筆數: {len(rows)}\n")
        f.write(f"問題總筆數: {len(all_issues)}\n\n")
        f.write("問題分類統計:\n")
        for cat, count in category_counts.most_common():
            f.write(f"  {cat}: {count}\n")
    print(f"審計摘要已輸出至：{SUMMARY_TXT}")

    print("\n審計完成！")
