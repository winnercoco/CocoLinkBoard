import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

excel_file = DATA_DIR / "links.xlsx"
json_file = DATA_DIR / "links.json"

df = pd.read_excel(excel_file)

def split_list(val):
    if pd.isna(val):
        return []
    return [x.strip().lower() for x in str(val).split(",") if x.strip()]

df["stars"] = df["stars"].apply(split_list)
df["categories"] = df["categories"].apply(split_list)
df["positions"] = df["positions"].apply(split_list)

df.to_json(json_file, orient="records", indent=2)

print("✅ Excel converted to JSON")