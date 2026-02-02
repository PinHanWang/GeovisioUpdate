import pandas as pd

csv_path = r"E:\Peter\GeovisioUpdate\data\10米以上道路\未來分案\景翊20250901.csv"
print ("測試讀取檔案:", csv_path)
# 測試 1: 用 cp950
df1 = pd.read_csv(csv_path, encoding='cp950', encoding_errors='replace')
print("CP950 欄位:", df1.columns.tolist())

# 測試 2: 用 utf-8
try:
    df2 = pd.read_csv(csv_path, encoding='utf-8')
    print("UTF-8 欄位:", df2.columns.tolist())
except:
    print("UTF-8 讀取失敗")

# 測試 3: 用 utf-8-sig
try:
    df3 = pd.read_csv(csv_path, encoding='utf-8-sig')
    print("UTF-8-SIG 欄位:", df3.columns.tolist())
except:
    print("UTF-8-SIG 讀取失敗")