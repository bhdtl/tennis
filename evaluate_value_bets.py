import os
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Konfiguration
MIN_MATCHES_ON_SURFACE = 3
MIN_EDGE_THRESHOLD = 0.075     # 7.5% Mindest-EV
MAX_EDGE_THRESHOLD = 0.60      # Max 60% (Schutz vor Outlier)
DAYS_AHEAD = 10                # Bis zu 10 Tage in die Zukunft blicken

def get_surface_from_supabase(tournament_name: str) -> str:
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
    except Exception:
        pass

    name_lower = tournament_name.lower()
    if any(k in name_lower for k in ["clay", "lima", "buenos aires", "rio", "santiago"]):
        return "Clay"
    elif any(k in name_lower for k in ["grass", "wimbledon", "halle"]):
        return "Grass"
    return "Hard"

def devig_odds(odds_a: float, odds_b: float):
    if odds_a <= 1.0 or odds_b <= 1.0:
        return 0.5, 0.5
    implied_a = 1.0 / odds_a
    implied_b = 1.0 / odds_b
    total = implied_a + implied_b
    return implied_a / total, implied_b / total

def get_player_surface_stats(player_name: str, surface: str):
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
        prior_weight = 5.0
        prior_winrate = 0.50
        raw_wins = len(wins)
        smoothed_win_rate = ((raw_wins + (prior_weight * prior_winrate)) / (total_matches + prior_weight))

        bp_saved = sum([m.get("w_bpsaved") or 0 for m in wins]) + sum([m.get("l_bpsaved") or 0 for m in losses])
        bp_faced = sum([m.get("w_bpfaced") or 0 for m in wins]) + sum([m.get("l_bpfaced") or 0 for m in losses])
        bp_save_rate = (bp_saved / bp_faced) if bp_faced > 0 else 0.50

        return {
            "name": player_name,
            "matches": total_matches,
            "win_rate": smoothed_win_rate,
            "bp_save_rate": bp_save_rate
        }
    except Exception as e:
        return None

def analyze_and_save_value_bets():
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")
    max_future_date = (now_utc + timedelta(days=DAYS_AHEAD)).strftime("%Y-%m-%d")
    
    print(f"⏰ Starte Value-Check ab Heute ({today_str}) bis max. in {DAYS_AHEAD} Tagen ({max_future_date})...")

    # SICHERER WEG: Lade alle Matches ab heute (genau wie beim funktionierenden Code)
    response = supabase.table("market_odds") \
        .select("*") \
        .gte("event_date", today_str) \
        .execute()
    
    raw_fixtures = response.data if response.data else []
    print(f"📊 {len(raw_fixtures)} rohe Ansetzungen ab heute aus Supabase geladen.")

    if len(raw_fixtures) == 0:
        print("⚠️ WARNUNG: Keine fixtures in der Tabelle 'market_odds' gefunden!")
        return

    # Python-seitiger Filter für das 10-Tage-Fenster (schützt vor Formatierungsproblemen in Supabase)
    fixtures = []
    for match in raw_fixtures:
        e_date = str(match.get("event_date", ""))[:10] # Nimmt die ersten 10 Zeichen (YYYY-MM-DD)
        if today_str <= e_date <= max_future_date:
            fixtures.append(match)

    print(f"🎯 {len(fixtures)} Ansetzungen passen in das exakte 10-Tage-Fenster.")

    value_bets_to_insert = []
    skipped_count = 0

    for match in fixtures:
        event_key = match.get("event_key")
        p1 = match.get("event_first_player")
        p2 = match.get("event_second_player")
        tournament = match.get("tournament_name", "Unbekanntes Turnier")
        event_date = str(match.get("event_date", ""))[:10]
        event_time = match.get("event_time", "00:00")
        odds_data = match.get("neobet_match_winner", {})

        if not odds_data or "Home" not in odds_data or "Away" not in odds_data:
            skipped_count += 1
            continue

        try:
            p1_odds = float(odds_data["Home"]["neobet"])
            p2_odds = float(odds_data["Away"]["neobet"])
        except (KeyError, TypeError, ValueError):
            skipped_count += 1
            continue

        surface = get_surface_from_supabase(tournament)
        stats_p1 = get_player_surface_stats(p1, surface)
        stats_p2 = get_player_surface_stats(p2, surface)

        if not stats_p1 or not stats_p2:
            skipped_count += 1
            continue

        if stats_p1["matches"] < MIN_MATCHES_ON_SURFACE or stats_p2["matches"] < MIN_MATCHES_ON_SURFACE:
            skipped_count += 1
            continue

        fair_p1_market, fair_p2_market = devig_odds(p1_odds, p2_odds)

        score_p1 = (stats_p1["win_rate"] * 0.7) + (stats_p1["bp_save_rate"] * 0.3)
        score_p2 = (stats_p2["win_rate"] * 0.7) + (stats_p2["bp_save_rate"] * 0.3)
        total_score = score_p1 + score_p2

        if total_score == 0:
            continue

        model_prob_p1 = score_p1 / total_score
        model_prob_p2 = score_p2 / total_score

        ev_p1 = (model_prob_p1 * p1_odds) - 1
        ev_p2 = (model_prob_p2 * p2_odds) - 1

        chosen_pick = None
        if MIN_EDGE_THRESHOLD <= ev_p1 <= MAX_EDGE_THRESHOLD:
            chosen_pick = (p1, p1_odds, model_prob_p1, fair_p1_market, ev_p1)
        elif MIN_EDGE_THRESHOLD <= ev_p2 <= MAX_EDGE_THRESHOLD:
            chosen_pick = (p2, p2_odds, model_prob_p2, fair_p2_market, ev_p2)

        if chosen_pick:
            pick_name, odds, model_prob, market_prob, ev = chosen_pick
            print(f"🎯 [NEW SIGNAL] @ {tournament} ({surface}) | {event_date} -> {pick_name} @ {odds} (EV: +{ev:.1%})")

            value_bets_to_insert.append({
                "event_key": event_key,
                "tournament_name": tournament,
                "surface": surface,
                "event_date": event_date,
                "event_time": event_time,
                "player_home": p1,
                "player_away": p2,
                "recommended_pick": pick_name,
                "odds": odds,
                "model_prob": round(model_prob, 4),
                "market_prob": round(market_prob, 4),
                "expected_value": round(ev, 4)
            })

    print(f"ℹ️ {skipped_count} Datensätze übersprungen.")

    if value_bets_to_insert:
        print(f"\n💾 Speichere {len(value_bets_to_insert)} Signale in Supabase...")
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
        print("ℹ️ Keine Value Bets im aktuellen Fenster gefunden.")

if __name__ == "__main__":
    analyze_and_save_value_bets()
