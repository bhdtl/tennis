import os
import pandas as pd
import numpy as np
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Spalten-Mapping für Supabase
COLUMNS = [
    'tourney_id', 'tourney_name', 'surface', 'tourney_date', 'match_num',
    'winner_id', 'winner_name', 'winner_hand', 'winner_ht', 'winner_ioc', 'winner_age',
    'loser_id', 'loser_name', 'loser_hand', 'loser_ht', 'loser_ioc', 'loser_age',
    'score', 'best_of', 'round', 'minutes',
    'w_ace', 'w_df', 'w_svpt', 'w_1stIn', 'w_1stWon', 'w_2ndWon', 'w_SvGms', 'w_bpSaved', 'w_bpFaced',
    'l_ace', 'l_df', 'l_svpt', 'l_1stIn', 'l_1stWon', 'l_2ndWon', 'l_SvGms', 'l_bpSaved', 'l_bpFaced',
    'winner_rank', 'winner_rank_points', 'loser_rank', 'loser_rank_points'
]

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
        for col in COLUMNS:
            item[col] = clean_record(row.get(col))
        records.append(item)

    # In 300er Batches hochladen
    batch_size = 300
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        try:
            supabase.table("historical_atp_matches").upsert(batch, on_conflict="tourney_id,match_num").execute()
            print(f"  📦 Batch {i // batch_size + 1}/{len(records)//batch_size + 1} hochgeladen")
        except Exception as e:
            print(f"  ❌ Fehler bei Batch: {e}")

    print(f"✅ Jahr {year} komplett importiert!\n")

if __name__ == "__main__":
    # Importiere z.B. die letzten Jahre
    for year in range(2023, 2027):
        import_atp_year(year)
