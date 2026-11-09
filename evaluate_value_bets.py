import os
import pandas as pd
import numpy as np
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Konfiguration für Value-Erkennung
MIN_MATCHES_REQUIRED = 5     # Spieler muss mind. 5 Matches in der DB haben
MIN_EDGE_THRESHOLD = 0.075   # Mindestens 7.5% Erwartungswert (+EV) für einen echten Pick

def devig_odds(odds_a: float, odds_b: float):
    """Entfernt die Buchmacher-Marge (Vig), um die faire implizite Markt-Wahrscheinlichkeit zu berechnen."""
    if odds_a <= 1.0 or odds_b <= 1.0:
        return 0.5, 0.5
    implied_a = 1.0 / odds_a
    implied_b = 1.0 / odds_b
    total = implied_a + implied_b
    return implied_a / total, implied_b / total

def get_player_stats(player_name: str):
    """Holt historische Performance-Daten eines Spielers aus der Supabase-Datenbank."""
    try:
        # Als Sieger
        res_w = supabase.table("historical_atp_matches").select("*").ilike("winner_name", f"%{player_name}%").execute()
        wins = res_w.data if res_w.data else []

        # Als Verlierer
        res_l = supabase.table("historical_atp_matches").select("*").ilike("loser_name", f"%{player_name}%").execute()
        losses = res_l.data if res_l.data else []

        total_matches = len(wins) + len(losses)
        if total_matches < MIN_MATCHES_REQUIRED:
            return None

        win_rate = len(wins) / total_matches

        # Breakpoint-Performance (Druckresistenz)
        bp_saved = sum([m.get("w_bpsaved") or 0 for m in wins]) + sum([m.get("l_bpsaved") or 0 for m in losses])
        bp_faced = sum([m.get("w_bpfaced") or 0 for m in wins]) + sum([m.get("l_bpfaced") or 0 for m in losses])
        bp_save_rate = (bp_saved / bp_faced) if bp_faced > 0 else 0.50

        return {
            "name": player_name,
            "matches": total_matches,
            "win_rate": win_rate,
            "bp_save_rate": bp_save_rate
        }
    except Exception as e:
        print(f"⚠️ Fehler beim Abrufen der Stats für {player_name}: {e}")
        return None

def analyze_value_bets():
    print("🔍 Lade aktuelle Neo.bet Quoten aus Supabase...")
    response = supabase.table("market_odds").select("*").execute()
    fixtures = response.data if response.data else 0

    print(f"📊 {len(fixtures)} Ansetzungen gefunden. Starte Daten-Filter & Modell-Abgleich...\n")

    value_bets_found = 0

    for match in fixtures:
        p1 = match.get("event_first_player")
        p2 = match.get("event_second_player")
        tournament = match.get("tournament_name", "Unbekanntes Turnier")
        odds_data = match.get("neobet_match_winner", {})

        if not odds_data or "Home" not in odds_data or "Away" not in odds_data:
            continue

        try:
            p1_odds = float(odds_data["Home"]["neobet"])
            p2_odds = float(odds_data["Away"]["neobet"])
        except (KeyError, TypeError, ValueError):
            continue

        # Historische Stats prüfen
        stats_p1 = get_player_stats(p1)
        stats_p2 = get_player_stats(p2)

        # Wenn für einen Spieler zu wenig historische Daten vorliegen -> Überspringen!
        if not stats_p1 or not stats_p2:
            continue

        # Markt-Wahrscheinlichkeiten (ohne Marge)
        fair_p1_market, fair_p2_market = devig_odds(p1_odds, p2_odds)

        # Modell-Berechnung (Kombination aus Win-Rate und Save-Rate)
        score_p1 = (stats_p1["win_rate"] * 0.7) + (stats_p1["bp_save_rate"] * 0.3)
        score_p2 = (stats_p2["win_rate"] * 0.7) + (stats_p2["bp_save_rate"] * 0.3)
        total_score = score_p1 + score_p2

        if total_score == 0:
            continue

        model_prob_p1 = score_p1 / total_score
        model_prob_p2 = score_p2 / total_score

        # Erwartungswert (+EV) berechnen
        ev_p1 = (model_prob_p1 * p1_odds) - 1
        ev_p2 = (model_prob_p2 * p2_odds) - 1

        # Nur ausgeben, wenn der Edge den Schwellenwert (z.B. 7.5%) überschreitet
        if ev_p1 >= MIN_EDGE_THRESHOLD:
            value_bets_found += 1
            print(f"🎯 [VALUE FOUND] @ {tournament}")
            print(f"   Match: {p1} vs {p2}")
            print(f"   👉 EMPFEHLUNG: {p1} (Quote: {p1_odds})")
            print(f"   Modell-Wahrscheinlichkeit: {model_prob_p1:.1%} | Markt-Implied: {fair_p1_market:.1%}")
            print(f"   Erwartungswert (EV): +{ev_p1:.1%}\n")

        elif ev_p2 >= MIN_EDGE_THRESHOLD:
            value_bets_found += 1
            print(f"🎯 [VALUE FOUND] @ {tournament}")
            print(f"   Match: {p1} vs {p2}")
            print(f"   👉 EMPFEHLUNG: {p2} (Quote: {p2_odds})")
            print(f"   Modell-Wahrscheinlichkeit: {model_prob_p2:.1%} | Markt-Implied: {fair_p2_market:.1%}")
            print(f"   Erwartungswert (EV): +{ev_p2:.1%}\n")

    print(f"🏁 Analyse beendet. {value_bets_found} echte Value Bets über dem Schwellenwert von {MIN_EDGE_THRESHOLD*100}% gefunden.")

if __name__ == "__main__":
    analyze_value_bets()
