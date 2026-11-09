import asyncio
import httpx

async def debug_raw():
    print("🔍 Starte direkten Rohdaten-Abruf von Neo.bet...")
    url = "https://neo.bet/.sportsbet/program/matches"
    params = {
        "sport": "Tennis",
        "language": "de",
        "license": "Germany",
        "market": "All"
    }
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, params=params)
        print(f"📡 HTTP Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"📦 Anzahl roher Einträge im JSON: {len(data) if isinstance(data, list) else 'Keine Liste'}")
            
            if isinstance(data, list) and len(data) > 0:
                print("\n--- Beispiel für den ERSTEN rohen API-Eintrag ---")
                first = data[0]
                print(f"ID: {first.get('id')}")
                print(f"Sport: {first.get('sport')}")
                print(f"League/Turnier: {first.get('league')}")
                print(f"Home: {first.get('home')} | Away: {first.get('away')}")
                print(f"TradingType: {first.get('tradingType')}")
                print(f"ContestStatus: {first.get('contestStatus')}")
                print(f"Begin: {first.get('begin')}")
                print("--------------------------------------------------")
        else:
            print(f"❌ API blockiert den Zugriff! Response: {response.text[:200]}shaped")

if __name__ == "__main__":
    asyncio.run(debug_raw())
