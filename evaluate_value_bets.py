import os
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Konfiguration
MIN_MATCHES_ON_SURFACE = 3     # Mindestanzahl Matches auf dem Belag für eine Wertung
MIN_EDGE_THRESHOLD = 0.075     # Mindestens 7.5% Erwartungswert (+EV)
MAX_EDGE_THRESHOLD = 0.60      # Obergrenze bei 60% (schützt vor Daten-Outlier)

def get_surface_from_supabase(tournament_name: str) -> str:
    """Sucht in Supabase dynamisch nach dem historischen Belag des Turniers."""
    clean_name = tournament_name.replace("Challenger ", "").replace(" Men", "").replace(" Women", "").strip()
    
    try:
        res = supabase.table("historical_atp_matches") \
            .select("surface") \
            .ilike("tourney_name", f"%{clean_name}%") \
            .limit(20) \
            .execute()
        
        if res.data and len(res.data) > 0:
            surfaces = [r["surface"] for r in res.data if r.get("surface")]
            if surfaces:
                return max(set(surfaces), key=surfaces.count)
    except Exception as e:
        print(f"⚠️ DB-Abfrage für Turnier-Belag fehlgeschlagen ({tournament_name}): {e}")

    # Fallback-Regeln für komplett neue Turniere
    name_lower = tournament_name.lower()
    if any(k in name_lower for k in ["clay", "lima", "buenos aires", "rio", "santiago"]):
        return "Clay"
    elif any(k in name_lower for k in ["grass", "wimbledon", "halle"]):
        return "Grass"
    
    return "Hard"  # Standard-Fallback

def devig_odds(odds_a: float, odds_b: float):
    """Entfernt die Buchmacher-Marge (Vig) für die wahre Markt-Wahrscheinlichkeit."""
    if odds_a <= 1.0 or odds_b <= 1.0:
        return 0.5, 0.5
    implied_a = 1.0 / odds_a
    implied_b = 1.0 / odds_b
    total = implied_a + implied_b
    return implied_a / total, implied_b / total

def get_player_surface_stats(player_name: str, surface: str):
    """Holt Performance-Daten eines Spielers strikt gefiltert nach Belag mit Bayesian Smoothing."""
    try:
        res_w = supabase.table("historical_atp_matches").select("*") \
            .ilike("winner_name", f"%{player_name}%") \
            .eq("surface", surface) \
            .execute()
        wins = res_w.data if res_w.data else []

        res_l = supabase.table("historical_atp_matches").select("*") \
            .ilike("loser_name", f"%{player_name}%") \
            .eq("surface", surface) \
            .execute()
        losses = res_l.data if res_l.data else []

        total_matches = len(wins) + len(losses)
        
        # Bayesian Smoothing: 5 Pseudo-Matches mit 50% Winrate als Prior
        prior_weight = 5.0
        prior_winrate = 0.50
        raw_wins = len(wins)
        smoothed_win_rate = ((raw_wins + (prior_weight * prior_winrate)) / (total_matches + prior_weight))

        bp_saved = sum([m.get("w_bpsaved") or 0 for m in wins]) + sum([m.get("l_bpsaved") or 0 for m in losses])
        bp_faced = sum([m.get("w_bpfaced") or 0 for m in wins]) + sum([m.get("l_bpfaced") or 0 for m in losses])
        bp_save_rate = (bp_saved / bp_faced) if bp_faced > 0 else 0.50

        return {
            "name": player_name,
            "surface": surface,
            "matches": total_matches,
            "win_rate": smoothed_win_rate,
            "bp_save_rate": bp_save_rate
        }
    except Exception as e:
        print(f"⚠️ Fehler bei Stats-Abfrage für {player_name} ({surface}): {e}")
        return None

def analyze_and_save_value_bets():
    print("🔍 Lade aktuelle Neo.bet Quoten aus Supabase (ungefiltert)...")
    response = supabase.table("market_odds").select("*").execute()
    fixtures = response.data if response.data else []

    print(f"📊 {len(fixtures)} Ansetzungen gefunden. Starte dynamischen Oberflächen- & Value-Abgleich...\n")

    value_bets_to_insert = []
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for match in fixtures:
        event_key = match.get("event_key") or f"{match.get('event_first_player')}-{match.get('event_second_player')}"
        p1 = match.get("event_first_player")
        p2 = match.get("event_second_player")
        tournament = match.get("tournament_name", "Unbekanntes Turnier")
        event_date = match.get("event_date", today_str)
        event_time = match.get("event_time", "")
        odds_data = match.get("neobet_match_winner", {})

        if not odds_data or "Home" not in odds_data or "Away" not in odds_data:
            continue

        try:
            p1_odds = float(odds_data["Home"]["neobet"])
            p2_odds = float(odds_data["Away"]["neobet"])
        except (KeyError, TypeError, ValueError):
            continue

        # 1. Belag dynamisch aus Supabase auslesen
        surface = get_surface_from_supabase(tournament)

        # 2. Stats gefiltert nach Belag abrufen
        stats_p1 = get_player_surface_stats(p1, surface)
        stats_p2 = get_player_surface_stats(p2, surface)

        if not stats_p1 or not stats_p2:
            continue

        if stats_p1["matches"] < MIN_MATCHES_ON_SURFACE or stats_p2["matches"] < MIN_MATCHES_ON_SURFACE:
            continue

        # 3. Markt-Probabilities berechnen (ohne Buchmacher-Marge)
        fair_p1_market, fair_p2_market = devig_odds(p1_odds, p2_odds)

        # 4. Modell-Score auf Oberflächen-Basis
        score_p1 = (stats_p1["win_rate"] * 0.7) + (stats_p1["bp_save_rate"] * 0.3)
        score_p2 = (stats_p2["win_rate"] * 0.7) + (stats_p2["bp_save_rate"] * 0.3)
        total_score = score_p1 + score_p2

        if total_score == 0:
            continue

        model_prob_p1 = score_p1 / total_score
        model_prob_p2 = score_p2 / total_score

        # 5. Erwartungswert (+EV)
        ev_p1 = (model_prob_p1 * p1_odds) - 1
        ev_p2 = (model_prob_p2 * p2_odds) - 1

        chosen_pick = None
        if MIN_EDGE_THRESHOLD <= ev_p1 <= MAX_EDGE_THRESHOLD:
            chosen_pick = (p1, p1_odds, model_prob_p1, fair_p1_market, ev_p1)
        elif MIN_EDGE_THRESHOLD <= ev_p2 <= MAX_EDGE_THRESHOLD:
            chosen_pick = (p2, p2_odds, model_prob_p2, fair_p2_market, ev_p2)

        if chosen_pick:
            pick_name, odds, model_prob, market_prob, ev = chosen_pick
            print(f"🎯 [VALUE FOUND] @ {tournament} (Belag: {surface})")
            print(f"   Match: {p1} vs {p2}")
            print(f"   👉 EMPFEHLUNG: {pick_name} (Quote: {odds})")
            print(f"   Modell ({surface}): {model_prob:.1%} | Markt: {market_prob:.1%}")
            print(f"   Erwartungswert (EV): +{ev:.1%}\n")

            value_bets_to_insert.append({
                "event_key": str(event_key),
                "tournament_name": tournament,
                "surface": surface,
                "event_date": str(event_date)[:10] if event_date else today_str,
                "event_time": str(event_time),
                "player_home": p1,
                "player_away": p2,
                "recommended_pick": pick_name,
                "odds": odds,
                "model_prob": round(model_prob, 4),
                "market_prob": round(market_prob, 4),
                "expected_value": round(ev, 4)
            })

    # In Supabase speichern für das Vercel-Dashboard
    if value_bets_to_insert:
        print(f"💾 Speichere {len(value_bets_to_insert)} Signale in Supabase...")
        for signal in value_bets_to_insert:
            existing = supabase.table("value_signals") \
                .select("id") \
                .eq("event_key", signal["event_key"]) \
                .eq("recommended_pick", signal["recommended_pick"]) \
                .execute()
            
            if not existing.data:
                supabase.table("value_signals").insert(signal).execute()
        print("✅ Speichern abgeschlossen!")
    else:
        print("ℹ️ Keine neuen Value Bets gefunden.")

if __name__ == "__main__":
    analyze_value_bets()
