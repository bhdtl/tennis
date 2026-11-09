import httpx
import asyncio
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger("NeuralScout_NeoBetClient")

def log(msg: str):
    logger.info(msg)

def reorder_player_name(name: str) -> str:
    """
    Converts name format from 'Lastname, Firstname' to 'Firstname Lastname'.
    If no comma is present, returns the name unchanged.
    """
    if not name:
        return ""
    if "," in name:
        parts = [p.strip() for p in name.split(",")]
        if len(parts) == 2:
            return f"{parts[1]} {parts[0]}"
    return name.strip()

class NeoBetAPI:
    """
    Client for the public NEO.bet Program Matches API.
    Bypasses key constraints and rate limits via direct affiliate program queries.
    """
    def __init__(self, api_key: Optional[str] = None):
        # API key is not strictly needed for public program requests, but we maintain init signature
        self.api_key = api_key
        self.base_url = "https://neo.bet/.sportsbet/program/matches"
        self._odds_cache: Dict[str, Dict[str, Any]] = {}
        self._raw_matches_cache: List[Dict[str, Any]] = []

    async def _fetch_all_neobet_matches(self, is_settlement: bool = False) -> List[Dict[str, Any]]:
        """
        Helper method to recursively page and fetch the entire active/ended 
        Tennis program from NEO.bet. Prevents 50-match truncation.
        """
        label = "settlement/ended" if is_settlement else "active"
        log(f"📡 [NEO.BET API] Ingesting full {label} Tennis program in paging chunks...")
        all_raw = []
        updated_after = 0
        keep_fetching = True
        pages = 0
        
        while keep_fetching and pages < 25:
            pages += 1
            params = {
                "sport": "Tennis",
                "language": "de",
                "license": "Germany",
                "updatedAfter": updated_after,
                "market": "All"
            }
            
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.get(self.base_url, params=params)
                
                if response.status_code != 200:
                    log(f"⚠️ [NEO.BET API] Chunk fetch failed with HTTP {response.status_code}")
                    break
                    
                data = response.json()
                if not isinstance(data, list) or len(data) == 0:
                    break
                    
                all_raw.extend(data)
                log(f"📦 [NEO.BET API] Page {pages}: Fetched {len(data)} matches (Total: {len(all_raw)}).")
                
                # Find maximum lastUpdated to paginate
                max_updated = updated_after
                for match in data:
                    m_updated = match.get("lastUpdated", 0)
                    if m_updated > max_updated:
                        max_updated = m_updated
                
                # If we fetched fewer than 50, we have reached the end of the stream
                if len(data) < 50 or max_updated == updated_after:
                    keep_fetching = False
                else:
                    updated_after = max_updated
                    # Rate limit throttle: sleep 100ms between page requests to be wholesome
                    await asyncio.sleep(0.1)
                    
            except Exception as e:
                log(f"⚠️ [NEO.BET API] Exception during chunk fetch: {e}")
                break
                
        log(f"✅ [NEO.BET API] Ingestion completed. Total {label} matches in cache: {len(all_raw)}")
        return all_raw

    async def get_fixtures(self, date_str: str, include_ended: bool = False) -> List[Dict[str, Any]]:
        """
        Fetches active/ended Tennis matches from NEO.bet and translates them 
        into standard fixture dictionaries expected by the scraper.
        """
        # If standard scan and cache is empty, fetch the entire program in chunks
        if not include_ended and not self._raw_matches_cache:
            self._raw_matches_cache = await self._fetch_all_neobet_matches(is_settlement=False)

        # If include_ended is true (settlement run), we perform a fresh paginated scan
        raw_source = []
        if include_ended:
            raw_source = await self._fetch_all_neobet_matches(is_settlement=True)
        else:
            raw_source = self._raw_matches_cache

        fixtures = []
        for match in raw_source:
            status_info = match.get("contestStatus", {})
            status_name = status_info.get("name", "Pregame")
            
            # If not include_ended, filter out finished/invalid matches
            if not include_ended and status_name in ["Ended", "EndedRetired", "Canceled", "Aborted"]:
                continue
            
            # Filter out Outright and Live matches unless we are settling ended results
            trading_type = match.get("tradingType", "PreMatch")
            if not include_ended and trading_type != "PreMatch":
                continue
            
            home_raw = match.get("home", "")
            away_raw = match.get("away", "")
            match_id = match.get("id", "")
            
            if not home_raw or not away_raw or not match_id:
                continue
            
            # 🚀 SOTA COMPLIANCE: EXCLUDE ALL DOUBLES MATCHES (Only Singles Matches Allowed!)
            # 1. Slashes in player names (NEO.bet format for doubles, e.g. "Bolelli, S./Vavassori, A.")
            if "/" in home_raw or "/" in away_raw:
                continue
                
            # 2. League/Tournament name matches (e.g. contains "doubles", "doppel", "junior", "qualification", etc.)
            league_name = (match.get("league") or "").lower()
            if any(term in league_name for term in [
                "doubles", "doppel", "doub.", "dop.", 
                "junior", "boys", "girls", "u18", "under 18",
                "qualification", "qual.", "exhibition", "schaukampf", "showdown"
            ]):
                continue
            
            # Normalize player names
            p1_name = reorder_player_name(home_raw)
            p2_name = reorder_player_name(away_raw)
            
            # Parse begin date & time
            begin_str = match.get("begin", "")
            event_date = date_str  # fallback
            event_time = "00:00"
            if begin_str:
                try:
                    dt = datetime.strptime(begin_str.replace("Z", "+00:00"), "%Y-%m-%dT%H:%M:%S%z")
                    event_date = dt.strftime("%Y-%m-%d")
                    event_time = dt.strftime("%H:%M")
                except Exception as date_err:
                    pass
            
            # Only include matches starting on the target date string
            if event_date != date_str:
                continue
            
            # Parse winner and scores for ended/finished matches
            event_winner = None
            final_score = ""
            constructed_scores = []
            
            scores_list = match.get("scores", [])
            if isinstance(scores_list, list):
                # Match score
                match_score_obj = next((s for s in scores_list if isinstance(s, dict) and s.get("name") == "Match"), None)
                if match_score_obj and isinstance(match_score_obj.get("score"), list) and len(match_score_obj["score"]) == 2:
                    try:
                        h_score = int(match_score_obj["score"][0])
                        a_score = int(match_score_obj["score"][1])
                        final_score = f"{h_score}-{a_score}"
                        if h_score > a_score:
                            event_winner = "First Player"
                        elif a_score > h_score:
                            event_winner = "Second Player"
                    except:
                        pass
                
                # Set scores mapping
                for s in scores_list:
                    if not isinstance(s, dict):
                        continue
                    s_name = s.get("name", "")
                    if s_name.startswith("SET") or s_name.startswith("Set"):
                        s_score = s.get("score", [])
                        if isinstance(s_score, list) and len(s_score) == 2:
                            try:
                                set_num = s_name.replace("SET", "").replace("Set", "").strip()
                                constructed_scores.append({
                                    "score_set": set_num,
                                    "score_first": s_score[0],
                                    "score_second": s_score[1]
                                })
                            except:
                                pass

            # Compile the standard fixture format
            fix_dict = {
                "event_first_player": p1_name,
                "event_second_player": p2_name,
                "event_key": match_id,
                "first_player_key": None,
                "second_player_key": None,
                "tournament_name": match.get("league", "Unknown Tournament"),
                "event_date": event_date,
                "event_time": event_time,
                "event_status": status_name,
                "event_winner": event_winner,
                "event_final_result": final_score,
                "scores": constructed_scores,
                "trading_type": trading_type
            }
            
            fixtures.append(fix_dict)
            
            # Parse and cache odds for get_odds calls
            self._cache_match_odds(match_id, match)
            
        log(f"✅ [NEO.BET API] Map matching completed: {len(fixtures)} relevant fixtures for {date_str}.")
        return fixtures

    def _cache_match_odds(self, match_id: str, match_data: Dict[str, Any]):
        """
        Parses NEO.bet markets and caches them in the format expected by get_odds.
        """
        odds_dict = {
            "Home/Away": {},
            "Spread": [],
            "SetSpread": [],
            "Over/Under": [],
            "FirstSetWinner": {},
            "RawMarkets": match_data.get("betmarkets", [])  # Keep raw markets for direct deep linking!
        }
        
        for market in match_data.get("betmarkets", []):
            betting_type = market.get("bettingType", "")
            market_key = market.get("key", "")
            
            # 1. Match Winner Odds
            if betting_type == "MatchWin" or "MATCH_HC2W(0.0)" in market_key:
                home_odd = 0.0
                away_odd = 0.0
                for outcome in market.get("odds", []):
                    o_name = outcome.get("outcome", "")
                    o_odds = outcome.get("odds", 0.0)
                    if o_name == "Home":
                        home_odd = o_odds
                    elif o_name == "Away":
                        away_odd = o_odds
                
                if home_odd > 0 and away_odd > 0:
                    odds_dict["Home/Away"] = {
                        "Home": {
                            "neobet": home_odd,
                            "bet365": home_odd  # Populate bet365 key for backward compatibility
                        },
                        "Away": {
                            "neobet": away_odd,
                            "bet365": away_odd
                        }
                    }
            
            # 2. Handicap Spreads
            elif betting_type == "Spread" or "Game_MATCH_HC2W" in market_key or "Set_MATCH_HC2W" in market_key:
                handicap_val = market.get("handicap")
                if handicap_val is None:
                    # Parse handicap from key e.g. Game_MATCH_HC2W(-5.5) -> -5.5
                    try:
                        inner = market_key.split("(")[1].split(")")[0]
                        handicap_val = float(inner)
                    except:
                        continue
                
                home_odd = 0.0
                away_odd = 0.0
                home_key = "1"
                away_key = "2"
                
                for outcome in market.get("odds", []):
                    o_name = outcome.get("outcome", "")
                    o_odds = outcome.get("odds", 0.0)
                    o_key = outcome.get("key", "1")
                    if o_name == "Home":
                        home_odd = o_odds
                        home_key = o_key
                    elif o_name == "Away":
                        away_odd = o_odds
                        away_key = o_key
                
                if home_odd > 0 and away_odd > 0:
                    spread_item = {
                        "handicap": handicap_val,
                        "market_key": market_key,
                        "odds1": home_odd,
                        "odds2": away_odd,
                        "key1": home_key,
                        "key2": away_key
                    }
                    if "Set_MATCH_HC2W" in market_key and handicap_val != 0.0:
                        odds_dict["SetSpread"].append(spread_item)
                    else:
                        odds_dict["Spread"].append(spread_item)
            
            # 3. Totals Over/Under
            elif betting_type == "OverUnder" or "Game_MATCH_OU" in market_key:
                boundary_val = market.get("boundary")
                if boundary_val is None:
                    try:
                        inner = market_key.split("(")[1].split(")")[0]
                        boundary_val = float(inner)
                    except:
                        continue
                
                under_odd = 0.0
                over_odd = 0.0
                under_key = "-"
                over_key = "+"
                
                for outcome in market.get("odds", []):
                    o_name = outcome.get("outcome", "")
                    o_odds = outcome.get("odds", 0.0)
                    o_key = outcome.get("key", "-")
                    if o_name == "Under":
                        under_odd = o_odds
                        under_key = o_key
                    elif o_name == "Over":
                        over_odd = o_odds
                        over_key = o_key
                
                if under_odd > 0 and over_odd > 0:
                    odds_dict["Over/Under"].append({
                        "boundary": boundary_val,
                        "market_key": market_key,
                        "under": under_odd,
                        "over": over_odd,
                        "key_under": under_key,
                        "key_over": over_key
                    })
            
            # 4. First Set Winner
            elif "Goal_SET1_HC2W" in market_key or "Goal_SET1_MatchWin" in market_key:
                home_odd = 0.0
                away_odd = 0.0
                home_key = "1"
                away_key = "2"
                for outcome in market.get("odds", []):
                    o_name = outcome.get("outcome", "")
                    o_odds = outcome.get("odds", 0.0)
                    o_key = outcome.get("key", "1")
                    if o_name == "Home":
                        home_odd = o_odds
                        home_key = o_key
                    elif o_name == "Away":
                        away_odd = o_odds
                        away_key = o_key
                
                if home_odd > 0 and away_odd > 0:
                    odds_dict["FirstSetWinner"] = {
                        "Home": home_odd,
                        "Away": away_odd,
                        "key1": home_key,
                        "key2": away_key,
                        "market_key": market_key
                    }
                    
        self._odds_cache[match_id] = odds_dict

    async def get_odds(self, match_key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves cached odds for a specific match key.
        Returns mapped dictionary in format compatible with scraper pipeline.
        """
        return self._odds_cache.get(match_key)

    async def get_players(self, player_key: str) -> Optional[Dict[str, Any]]:
        # Third-party players endpoint not needed under NEO partnership
        return None

    async def get_h2h(self, p1_key: str, p2_key: str) -> Optional[Dict[str, Any]]:
        # NEO API does not provide historic H2H stats (we rely on our own historical database)
        return None
