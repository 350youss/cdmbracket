#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scrape des effectifs de grands clubs européens (hors Ligue 1) -> régénère
la landing page du hub + la page compo/terrain interactif (equipe.html).

Pas de mercato (arrivées/départs) pour ces clubs : juste l'effectif à jour,
comme demandé. Réutilise les fonctions de scraping génériques du pipeline
Ligue 1 (scrape_squad, pos_short, pos_group, parse_fee).

Usage :
    python scripts/scrape_big_clubs.py            # scrape en ligne + régénère
    python scripts/scrape_big_clubs.py --offline  # réutilise le cache HTML
"""
import os, sys, json, time, base64
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from scrape_l1_transfers import scrape_squad  # réutilise le scraping d'effectif générique

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---- config ----
OUT_ROOT = os.path.dirname(SCRIPT_DIR)                         # repo kooradex (unifié)
TPL_TEAM  = os.path.join(SCRIPT_DIR, "equipe_hub_template.html")
TPL_INDEX = os.path.join(SCRIPT_DIR, "hub_index_template.html")
OUT_TEAM  = os.path.join(OUT_ROOT, "equipe-europe.html")
OUT_INDEX = os.path.join(OUT_ROOT, "grands-clubs.html")
LOGOS_DIR = os.path.join(OUT_ROOT, "logos")
DATA_DIR  = os.path.join(OUT_ROOT, "data")
STATE     = os.path.join(DATA_DIR, "squads.json")
L1_URL    = "mercato-l1.html"
L2_URL    = "mercato-l2.html"
os.makedirs(LOGOS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# code, nom, ligue, slug transfermarkt, id, couleur fond, couleur texte
CLUBS = [
    ("FCB", "FC Barcelone",       "Liga",           "fc-barcelone",       131, "#a50044", "#ffed02"),
    ("RMA", "Real Madrid",        "Liga",           "real-madrid",        418, "#fefefe", "#febe10"),
    ("ATM", "Atlético de Madrid", "Liga",           "atletico-madrid",    13,  "#ce3524", "#fff"),
    ("MCI", "Manchester City",    "Premier League", "manchester-city",    281, "#6cabdd", "#1c2c5b"),
    ("ARS", "Arsenal FC",         "Premier League", "arsenal-fc",         11,  "#ef0107", "#fff"),
    ("LIV", "FC Liverpool",       "Premier League", "fc-liverpool",       31,  "#c8102e", "#fff"),
    ("CHE", "Chelsea FC",         "Premier League", "fc-chelsea",         631, "#034694", "#fff"),
    ("MUN", "Manchester United",  "Premier League", "manchester-united",  985, "#da291c", "#fff"),
    ("TOT", "Tottenham Hotspur",  "Premier League", "tottenham-hotspur",  148, "#132257", "#fff"),
    ("AVL", "Aston Villa",        "Premier League", "aston-villa",        405, "#670e36", "#95bfe5"),
    ("BAY", "Bayern Munich",      "Bundesliga",      "bayern-munich",     27,  "#dc052d", "#fff"),
    ("BVB", "Borussia Dortmund",  "Bundesliga",      "borussia-dortmund", 16,  "#fde100", "#000"),
    ("JUV", "Juventus Turin",     "Serie A",         "juventus-turin",    506, "#000",    "#fff"),
    ("INT", "Inter Milan",        "Serie A",         "inter-milan",       46,  "#010e80", "#f7b900"),
    ("MIL", "AC Milan",           "Serie A",         "ac-milan",          5,   "#fb090b", "#000"),
    ("NAP", "SSC Napoli",         "Serie A",         "ssc-napoli",        6195,"#12a2d4", "#fff"),
]

def load_logo(code):
    for ext in ("png", "svg", "webp", "jpg", "jpeg"):
        p = os.path.join(LOGOS_DIR, f"{code}.{ext}")
        if os.path.exists(p):
            mime = "image/svg+xml" if ext == "svg" else \
                   ("image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}")
            b64 = base64.b64encode(open(p, "rb").read()).decode()
            return f"data:{mime};base64,{b64}"
    return ""

def logo_assets(logos):
    css, codes = [], []
    for code, uri in logos.items():
        if uri:
            codes.append(code)
            css.append(f".crest.l-{code}{{background-image:url(\"{uri}\");}}")
    return "\n".join(css), sorted(codes)

def load_state():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE, encoding="utf-8"))
        except Exception:
            pass
    return {}

def scrape_all(offline=False, old=None):
    squads = {}
    old_sq = (old or {}).get("squads", {})
    for code, name, league, slug, cid, bg, fg in CLUBS:
        print(f"· effectif {name} …")
        pl = scrape_squad(slug, cid, offline)
        if not pl and code in old_sq:
            print(f"  ↻ {name} : effectif précédent réutilisé (échec du scrape)")
            pl = old_sq[code]
        squads[code] = pl
        if not offline:
            time.sleep(1.0)
    return squads

def generate(squads):
    logos = {code: load_logo(code) for code, *_ in CLUBS}
    logos["L1"] = load_logo("L1")   # logo de la compétition Ligue 1 (badge sur la landing page)
    logos["L2"] = load_logo("L2")   # logo de la compétition Ligue 2 (badge sur la landing page)
    logocss, logocodes = logo_assets(logos)
    meta = {code: {"name": name, "bg": bg, "fg": fg} for code, name, league, slug, cid, bg, fg in CLUBS}
    order = [code for code, *_ in CLUBS]
    updated = datetime.now().strftime("%d/%m/%Y à %Hh%M")

    # ---- page compo (terrain) ----
    tpl = open(TPL_TEAM, encoding="utf-8").read()
    out = (tpl
           .replace("/*__SQUADS__*/{}", json.dumps(squads, ensure_ascii=False))
           .replace("/*__CLUBMETA__*/{}", json.dumps(meta, ensure_ascii=False))
           .replace("/*__ORDER__*/[]", json.dumps(order))
           .replace("/*__LOGOCODES__*/[]", json.dumps(logocodes))
           .replace("/*__LOGOCSS__*/", logocss))
    open(OUT_TEAM, "w", encoding="utf-8").write(out)
    n = sum(len(v) for v in squads.values())
    print(f"✓ {OUT_TEAM} régénéré — {n} joueurs sur {len(squads)} clubs")

    # ---- landing page du hub ----
    clubs_js = [{"code": code, "name": name, "league": league, "bg": bg, "fg": fg}
                for code, name, league, slug, cid, bg, fg in CLUBS]
    tpl2 = open(TPL_INDEX, encoding="utf-8").read()
    out2 = (tpl2
            .replace("/*__CLUBS__*/[]", json.dumps(clubs_js, ensure_ascii=False))
            .replace("/*__LOGOCODES__*/[]", json.dumps(logocodes))
            .replace("/*__LOGOCSS__*/", logocss)
            .replace("__L1_URL__", L1_URL)
            .replace("__L2_URL__", L2_URL)
            .replace("__UPDATED__", updated))
    open(OUT_INDEX, "w", encoding="utf-8").write(out2)
    print(f"✓ {OUT_INDEX} régénéré")

def signature(squads):
    """empreinte des DONNÉES (hors horodatage) pour détecter un vrai changement"""
    import hashlib
    canon = {code: sorted([[p.get("n",""), p["p"], p["pos"], p["val"]] for p in pl])
             for code, pl in squads.items()}
    return hashlib.md5(json.dumps(canon, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

def main():
    offline = "--offline" in sys.argv
    print(f"Scrape grands clubs {'(cache)' if offline else '(en ligne)'}\n")
    old = load_state()
    old_sig = old.get("sig")
    squads = scrape_all(offline, old)
    sig = signature(squads)
    json.dump({"updated": datetime.now().isoformat(timespec="seconds"), "sig": sig, "squads": squads},
              open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    generate(squads)

    changed = (sig != old_sig)
    open(os.path.join(DATA_DIR, ".push_europe"), "w", encoding="utf-8").write("1" if changed else "0")
    print("→ Données " + ("MODIFIÉES : publication." if changed else "inchangées : pas de publication."))

if __name__ == "__main__":
    main()
