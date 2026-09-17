#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prepare la feuille de match du prochain OM (composition officielle des
qu'elle est annoncee, entre 1h30 et 30min avant le coup d'envoi) et la
publie en JSON statique (data/notes-om-next-lineup.json), lu par
notes-om-admin.html.

Pourquoi ce detour : l'API Sofascore bloque les requetes cross-origin
faites depuis le navigateur sur kooradex.fr (403), meme si un fetch direct
depuis sofascore.com passe. Cote serveur (ce script, via curl_cffi qui
imite un vrai navigateur pour contourner le blocage anti-bot base sur
l'empreinte TLS) ca fonctionne, donc c'est lui qui va chercher la donnee
et la republie en fichier statique du meme domaine, que la page lit sans
souci de CORS.

Usage : python scripts/fetch_next_lineup.py
"""
import os, sys, json, unicodedata

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
OUT = os.path.join(ROOT, "data", "notes-om-next-lineup.json")

OM_TEAM_ID = 1641
HEADERS_IMPERSONATE = "chrome124"
BASE = "https://api.sofascore.com/api/v1"


def norm(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower()


def get(url):
    r = requests.get(url, impersonate=HEADERS_IMPERSONATE, timeout=25)
    r.raise_for_status()
    return r.json()


def main():
    try:
        next_events = get(f"{BASE}/team/{OM_TEAM_ID}/events/next/0").get("events", [])
    except Exception as e:
        print(f"! impossible de recuperer le prochain match : {e}")
        return
    if not next_events:
        json.dump({"eventId": None}, open(OUT, "w", encoding="utf-8"))
        print("Aucun match a venir.")
        return

    ev = next_events[0]
    is_home = ev["homeTeam"]["id"] == OM_TEAM_ID
    opponent = ev["awayTeam"]["name"] if is_home else ev["homeTeam"]["name"]
    out = {
        "eventId": ev["id"],
        "opponent": opponent,
        "competition": ev["tournament"]["name"],
        "home": is_home,
        "startTimestamp": ev["startTimestamp"],
        "starters": [],
        "bench": [],
        "lineupConfirmed": False,
    }

    try:
        lineups = get(f"{BASE}/event/{ev['id']}/lineups")
        side = lineups["home"] if is_home else lineups["away"]
        players = side.get("players", []) if side else []
        if players:
            out["lineupConfirmed"] = bool(lineups.get("confirmed"))
            for p in players:
                name = p["player"]["name"]
                (out["bench"] if p.get("substitute") else out["starters"]).append(name)
    except Exception as e:
        print(f"  (compo pas encore disponible : {e})")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    n = len(out["starters"]) + len(out["bench"])
    print(f"Prochain match : OM {'vs' if is_home else '@'} {opponent} ({out['competition']}) -> {n} joueur(s) dans la compo -> {OUT}")


if __name__ == "__main__":
    main()
