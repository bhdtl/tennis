import asyncio
import os
from datetime import datetime
from supabase import create_client, Client
from neobet_client import NeoBetAPI

# Supabase Verbindung herstellen
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

async def main():
    print("🚀 Starte Neo.bet Sync zu Supabase...")
    api = NeoBetAPI()
    
    # 1. Hole alle aktuellen Matches über den Client
    fixtures = await api.get_fixtures()
    print(f"✅ {len(fixtures)} Matches von Neo.bet geladen.")
    
    # 2. Speichere jedes Match in Supabase
    for fix in fixtures:
        match_id = fix["event_key"]
        
        # Hole die zugehörigen Quoten aus dem Cache des Clients
        odds = await api.get_odds(match_id) or {}
        
        payload = {
            "event_key": match_id,
            "event_first_player": fix["event_first_player"],
            "event_second_player": fix["event_second_player"],
            "tournament_name": fix["tournament_name"],
            "event_date": fix["event_date"],
            "event_time": fix["event_time"],
            "event_status": fix["event_status"],
            "trading_type": fix["trading_type"],
            "neobet_match_winner": odds.get("Home/Away", {}),
            "neobet_spreads": odds.get("Spread", []),
            "neobet_over_unders": odds.get("Over/Under", []),
        }
        
        try:
            # Upsert in Supabase (aktualisiert, falls event_key schon existiert)
            supabase.table("market_odds").upsert(payload, on_conflict="event_key").execute()
        except Exception as e:
            print(f"❌ Fehler beim Speichern von {match_id}: {e}")

    print("🎉 Alle Matches erfolgreich in Supabase synchronisiert!")

if __name__ == "__main__":
    asyncio.run(main())
