import os
import pandas as pd
import numpy as np
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Wir mappen alle Spalten explizit auf Kleinbuchstaben für Supabase
COLUMNS_MAP = {
    'tourney_id': 'tourney_id', 'tourney_name': 'tourney_name', 'surface': 'surface', 
    'tourney_date': 'tourney_date', 'match_num': 'match_num',
    'winner_id': 'winner_id', 'winner_name': 'winner_name', 'winner_hand': 'winner_hand', 
    'winner_ht': 'winner_ht', 'winner_ioc': 'winner_ioc', 'winner_age': 'winner_age',
    'loser_id': 'loser_id', 'loser_name': 'loser_name', 'loser_hand': 'loser_hand', 
    'loser_ht': 'loser_ht', 'loser_ioc': 'loser_ioc', 'loser_age': 'loser_age',
    'score': 'score', 'best_of': 'best_of', 'round': 'round', 'minutes': 'minutes',
    'w_ace': 'w_ace', 'w_df': 'w_df', 'w_svpt': 'w_svpt', 'w_1stIn': 'w_1stin', 
    'w_1stWon': 'w_1stwon', 'w_2ndWon': 'w_2ndwon', 'w_SvGms': 'w_svgms', 
    'w_bpSaved': 'w_bpsaved', 'w_bpFaced': 'w_bpfaced',
    'l_ace': 'l_ace', 'l_df': 'l_df', 'l_svpt': 'l_svpt', 'l_1stIn': 'l_1stin', 
    'l_1stWon': 'l_1stwon', 'l_2ndWon': 'l_2ndwon', 'l_SvGms': 'l_svgms', 
    'l_bpSaved': 'l_bpsaved', 'l_bpFaced': 'l_bpfaced',
    'winner_rank': 'winner_rank', 'winner_rank_points': 'winner_rank_points', 
    'loser_rank': 'loser_rank', 'loser_rank_points': 'loser_rank_points'
}

def clean_record(val):
    if pd.isna(val) or val is None:
        return None
    if isinstance(val, (np.int64, np.int32)):
        return int(val)
    if isinstance(val, (np.float64, np.float32)):
        return float(val)
    return str(val)

def import_atp_year(year: int):
    url = f"https://raw.githubusercontent.com/Aneeshers/tennis-sackmann-archive/main/atp/atp_matches_{year}.csv"
    print(f"📥 Lade ATP-Daten für Jahr {year}...")
    
    try:
        df = pd.read_csv(url)
    except Exception as e:
        print(f"❌ Fehler beim Laden von Jahr {year}: {e}")
        return

    records = []
    for _, row in df.iterrows():
        item = {}
        for csv_col, db_col in COLUMNS_MAP.items():
            if csv_col in row:
                item[db_col] = clean_record(row.get(csv_col))
        records.append(item)

    # In 300er Batches hochladen
    batch_size = 300
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        try:
            supabase.table("historical_atp_matches").upsert(batch, on_conflict="tourney_id,match_num").execute()
        except Exception as e:
            print(f"  ❌ Fehler bei Batch: {e}")

    print(f"✅ Jahr {year} erfolgreich importiert!\n")

if __name__ == "__main__":
    for year in range(2023, 2027):
        import_atp_year(year)
