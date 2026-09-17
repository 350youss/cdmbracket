#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Recupere les pointages envoyes via notes-om-admin.html (collection
Firestore "notes-om-pending", ecrite cote client) et les integre dans
data/notes-om.json, avec la liste de joueurs cochee a la main (23min+)
plutot que d'attendre le calcul des stats Sofascore.

La lecture/suppression se fait via l'API REST Firestore brute (pas besoin
du SDK Admin ni de credentials : les regles du projet autorisent la
lecture/ecriture publique, comme pour les autres collections du site).

Usage : python scripts/sync_notes_om_pending.py
"""
import os, sys, json, re, unicodedata
from datetime import datetime
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "notes-om.json")
PLAYERS = os.path.join(ROOT, "data", "players.json")

PROJECT_ID = "predi-l1"
COLLECTION = "notes-om-pending"
BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents/{COLLECTION}"


def norm(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower()


def slugify(s):
    s = norm(s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "match"


NAME_PARTICLES = {"de", "du", "le", "la", "van", "von", "der", "den", "di", "al"}


def short_name(full_name):
    """
    notes-om-admin.html affiche le nom complet (plus lisible pour pointer),
    on le raccourcit ici pour matcher la convention deja utilisee dans les
    autres matchs (indispensable pour que l'agregat saison regroupe bien
    le meme joueur d'un match a l'autre). Meme heuristique que
    scrape_notes_om.py : dernier mot, en gardant la particule qui le
    precede si besoin (ex. "Jeffrey De Lange" -> "De Lange").
    """
    parts = full_name.split()
    if len(parts) <= 1:
        return full_name
    if len(parts) >= 3 and norm(parts[-2]) in NAME_PARTICLES:
        return " ".join(parts[-2:])
    return parts[-1]


def load_roster_positions():
    """nom court normalise -> code de poste precis, tire de data/players.json
    (OM). Calcule le poste ici plutot que de faire confiance a la page de
    pointage : plus fiable (meme source que le reste du site) qu'une
    devinette a partir du code generique G/D/M/F de Sofascore.
    Indexe par nom court (cf. short_name) plutot que nom complet : le nom
    legal Sofascore ("Conrad Jaden Egan-Riley") ne matche pas le nom
    d'usage de notre base ("CJ Egan-Riley"), seul le nom de famille est
    fiable des deux cotes."""
    if not os.path.exists(PLAYERS):
        return {}
    try:
        d = json.load(open(PLAYERS, encoding="utf-8"))
    except Exception:
        return {}
    om = next((c for c in d.get("clubs", []) if c.get("id") == "om"), None)
    if not om:
        return {}
    return {norm(short_name(p["name"])): p["pos"] for p in om.get("players", [])}


def parse_value(v):
    """convertit un champ au format REST Firestore en valeur Python native"""
    if "stringValue" in v:
        return v["stringValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return v["doubleValue"]
    if "booleanValue" in v:
        return v["booleanValue"]
    if "nullValue" in v:
        return None
    if "timestampValue" in v:
        return v["timestampValue"]
    if "arrayValue" in v:
        return [parse_value(x) for x in v["arrayValue"].get("values", [])]
    if "mapValue" in v:
        return {k: parse_value(x) for k, x in v["mapValue"].get("fields", {}).items()}
    return None


def fetch_pending():
    r = requests.get(BASE, timeout=25)
    r.raise_for_status()
    d = r.json()
    docs = []
    for doc in d.get("documents", []):
        name = doc["name"]
        doc_id = name.rsplit("/", 1)[-1]
        fields = {k: parse_value(v) for k, v in doc.get("fields", {}).items()}
        docs.append((doc_id, fields))
    return docs


def delete_pending(doc_id):
    requests.delete(f"{BASE}/{doc_id}", timeout=25).raise_for_status()


def main():
    data = {"updated": datetime.now().isoformat(timespec="seconds"), "matches": []}
    if os.path.exists(OUT):
        try:
            data = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            pass
    existing_dates = {m["date"] for m in data.get("matches", [])}
    roster_pos = load_roster_positions()

    try:
        pending = fetch_pending()
    except Exception as e:
        print(f"! lecture de la file en attente impossible : {e}")
        return

    if not pending:
        print("Aucun pointage en attente.")
        return

    added = 0
    for doc_id, f in pending:
        date = f.get("date")
        opponent = f.get("opponent", "?")
        if not date:
            print(f"  ! document {doc_id} incomplet, ignore")
            continue
        if date in existing_dates:
            print(f"  - {opponent} ({date}) deja present, file nettoyee sans reajouter")
            delete_pending(doc_id)
            continue

        players = f.get("players") or []
        ratings = []
        for p in players:
            full_name = p.get("name")
            if not full_name:
                continue
            player_short = short_name(full_name)
            pos = roster_pos.get(norm(player_short), "MC")
            ratings.append({"player": player_short, "pos": pos, "chat": None, "moi": None, "lequipe": None})
        entry = {
            "id": f"{slugify(opponent)}-{date}",
            "date": date,
            "opponent": opponent,
            "competition": f.get("competition") or "?",
            "journee": None,
            "home": bool(f.get("home")),
            "score": f.get("score") or "?-?",
            "ratings": ratings,
        }
        data["matches"].append(entry)
        existing_dates.add(date)
        print(f"  + {opponent} ({date}) : {len(ratings)} joueur(s) pointe(s)")
        delete_pending(doc_id)
        added += 1

    if added:
        data["updated"] = datetime.now().isoformat(timespec="seconds")
        json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"\n{added} match(s) ajoute(s) depuis la file -> {OUT}")


if __name__ == "__main__":
    main()
