#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Detecte automatiquement les nouveaux matchs de l'OM en Ligue 1 termines et
ajoute une entree dans data/notes-om.json avec la liste des joueurs ayant
joue au moins 23 minutes (reference : Sofascore), prete a recevoir les
notes (chat / 350 / L'Equipe / site) qui restent saisies a la main.

Ne touche jamais aux matchs deja presents dans le fichier (identifies par
leur date) : ne fait qu'ajouter les matchs manquants, pour ne jamais
ecraser des notes deja rentrees.

L'API Sofascore bloque les clients HTTP "nus" (User-Agent seul ne suffit
pas, blocage au niveau de l'empreinte TLS) : on passe par curl_cffi avec
un impersonate Chrome pour la contourner, sans avoir besoin d'un vrai
navigateur headless.

Usage : python scripts/scrape_notes_om.py
"""
import os, re, sys, json, unicodedata
from datetime import datetime, timezone

try:
    from curl_cffi import requests
except ImportError:
    print("!! curl_cffi manquant : pip install curl_cffi")
    sys.exit(1)

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "notes-om.json")
PLAYERS = os.path.join(ROOT, "data", "players.json")

OM_TEAM_ID = 1641
L1_TOURNAMENT_ID = 34
L1_SEASON_ID = 96127          # Ligue 1 26/27, a mettre a jour l'an prochain
MIN_MINUTES = 23

HEADERS_IMPERSONATE = "chrome124"
BASE = "https://api.sofascore.com/api/v1"

# poste Sofascore (une seule lettre) -> poste par defaut si le joueur n'est
# pas trouve dans notre base (players.json a une position plus precise)
POS_FALLBACK = {"G": "GdB", "D": "DC", "M": "MC", "F": "AC"}


def norm(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower()


def slugify(s):
    s = norm(s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "match"


NAME_PARTICLES = {"de", "du", "le", "la", "van", "von", "der", "den", "di", "al"}


def short_name(full_name):
    """
    Sofascore fournit un champ lastName souvent vide/incomplet pour les
    noms composes : on derive plutot un nom court a partir du nom complet
    (dernier mot, en gardant la particule qui le precede si besoin, ex.
    "Jeffrey De Lange" -> "De Lange"), pour matcher la convention deja
    utilisee dans les matchs saisis a la main (indispensable pour que
    l'agregat saison regroupe bien le meme joueur d'un match a l'autre).
    """
    parts = full_name.split()
    if len(parts) <= 1:
        return full_name
    if len(parts) >= 3 and norm(parts[-2]) in NAME_PARTICLES:
        return " ".join(parts[-2:])
    return parts[-1]


def get(url, **params):
    r = requests.get(url, params=params, impersonate=HEADERS_IMPERSONATE, timeout=25)
    r.raise_for_status()
    return r.json()


def load_roster_positions():
    """nom normalise -> code de poste precis, tire de data/players.json (OM)"""
    if not os.path.exists(PLAYERS):
        return {}
    try:
        d = json.load(open(PLAYERS, encoding="utf-8"))
    except Exception:
        return {}
    om = next((c for c in d.get("clubs", []) if c.get("id") == "om"), None)
    if not om:
        return {}
    return {norm(p["name"]): p["pos"] for p in om.get("players", [])}


def find_om_rounds():
    """parcourt les journees de L1 et renvoie les matchs OM termines"""
    matches = []
    round_num = 1
    misses = 0
    while round_num <= 40 and misses < 3:
        try:
            d = get(f"{BASE}/unique-tournament/{L1_TOURNAMENT_ID}/season/{L1_SEASON_ID}/events/round/{round_num}")
        except Exception as e:
            print(f"  ! journee {round_num} : {e}")
            misses += 1
            round_num += 1
            continue
        events = d.get("events", [])
        if not events:
            misses += 1
            round_num += 1
            continue
        misses = 0
        for e in events:
            home, away = e["homeTeam"], e["awayTeam"]
            if OM_TEAM_ID not in (home["id"], away["id"]):
                continue
            if e.get("status", {}).get("type") != "finished":
                continue
            matches.append({"event": e, "round": round_num})
        round_num += 1
    return matches


def build_match_entry(ev, round_num, roster_pos):
    home, away = ev["homeTeam"], ev["awayTeam"]
    is_home = home["id"] == OM_TEAM_ID
    opponent = away["name"] if is_home else home["name"]
    date = datetime.fromtimestamp(ev["startTimestamp"], tz=timezone.utc).strftime("%Y-%m-%d")
    score = f"{ev['homeScore'].get('display','?')}-{ev['awayScore'].get('display','?')}"

    lineups = get(f"{BASE}/event/{ev['id']}/lineups")
    side = lineups["home"] if is_home else lineups["away"]
    ratings = []
    for p in side.get("players", []):
        stats = p.get("statistics") or {}
        minutes = stats.get("minutesPlayed", 0)
        if minutes < MIN_MINUTES:
            continue
        full_name = p["player"]["name"]
        name = short_name(full_name)
        pos = roster_pos.get(norm(full_name)) or POS_FALLBACK.get(p.get("position"), "MC")
        ratings.append({"player": name, "pos": pos, "chat": None, "moi": None, "lequipe": None})

    return {
        "id": f"{slugify(opponent)}-{date}",
        "date": date,
        "opponent": opponent,
        "competition": "Ligue 1",
        "journee": round_num,
        "home": is_home,
        "score": score,
        "ratings": ratings,
    }


def main():
    data = {"updated": datetime.now().isoformat(timespec="seconds"), "matches": []}
    if os.path.exists(OUT):
        try:
            data = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            pass
    existing_dates = {m["date"] for m in data.get("matches", [])}

    print("Recherche des journees de Ligue 1 jouees par l'OM...")
    found = find_om_rounds()
    print(f"{len(found)} match(s) OM termine(s) trouve(s) sur Sofascore.")

    roster_pos = load_roster_positions()

    added = 0
    for item in found:
        ev, round_num = item["event"], item["round"]
        date = datetime.fromtimestamp(ev["startTimestamp"], tz=timezone.utc).strftime("%Y-%m-%d")
        if date in existing_dates:
            continue
        print(f"  + nouveau match : {ev['homeTeam']['name']} - {ev['awayTeam']['name']} ({date})")
        try:
            entry = build_match_entry(ev, round_num, roster_pos)
        except Exception as e:
            print(f"    ! echec recuperation composition : {e}")
            continue
        data["matches"].append(entry)
        existing_dates.add(date)
        added += 1

    if added:
        data["updated"] = datetime.now().isoformat(timespec="seconds")
        json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"\n{added} nouveau(x) match(s) ajoute(s) -> {OUT}")
    else:
        print("\nAucun nouveau match a ajouter.")


if __name__ == "__main__":
    main()
