import asyncio
from datetime import datetime
from neobet_client import NeoBetAPI

async def main():
    print("🚀 Starte Neo.bet API Test in GitHub Actions...")
    api = NeoBetAPI()
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"📅 Suche Matches für: {today}")
    
    try:
        fixtures = await api.get_fixtures(today)
        print(f"✅ ERFOLG! Es wurden {len(fixtures)} Matches gefunden.")
        if fixtures:
            print("Beispiel-Match:", fixtures[0].get("event_first_player"), "vs", fixtures[0].get("event_second_player"))
    except Exception as e:
        print(f"❌ FEHLER: {e}")

if __name__ == "__main__":
    asyncio.run(main())
