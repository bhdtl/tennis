import asyncio
import os
from datetime import datetime
from supabase import create_client, Client
from neobet_client import NeoBetAPI

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")

async def sync_neobet_to_supabase() -> int:
    """
    Scrapt alle aktuellen und zukünftigen Tennis-Matches aus dem Neo.bet Programm
    und synchronisiert Quoten & Ansetzungen in die Supabase Tabelle 'market_odds'.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️ SUPABASE_URL oder SUPABASE_KEY nicht gesetzt. Überspringe Sync.")
        return 0

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("🚀 Starte Neo.bet Multi-Day Sync zu Supabase...")
    api = NeoBetAPI()
    
    # Hole alle Matches (heute + zukünftige Spieltage)
    fixtures = await api.get_fixtures()
    print(f"✅ {len(fixtures)} Matches von Neo.bet geladen.")
    
    synced_count = 0
    for fix in fixtures:
        match_id = fix["event_key"]
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
            supabase.table("market_odds").upsert(payload, on_conflict="event_key").execute()
            synced_count += 1
        except Exception as e:
            print(f"❌ Fehler beim Speichern von {match_id}: {e}")

    print(f"🎉 {synced_count} Matches erfolgreich in Supabase synchronisiert!")
    return synced_count

async def main():
    await sync_neobet_to_supabase()

if __name__ == "__main__":
    asyncio.run(main())
