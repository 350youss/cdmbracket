#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scrape des transferts Ligue 1 (Transfermarkt) -> régénère mercato-l1-2026.html

- Arrivées à gauche, départs à droite, montants inclus.
- Retire les RETOURS DE PRÊT ("Fin du prêt ...").
- Retire les joueurs venant/allant d'une ÉQUIPE B / réserve / catégorie jeunes
  SANS montant (ex : Limon, Belazzoug depuis "Rennes B"). Les achats payants
  d'un jeune (ex : São Paulo U20 pour 5 M€) sont conservés.
- Détecte les nouvelles arrivées à chaque passage (diff de snapshot) pour
  alimenter les cases "Dernières arrivées" en haut de page.

Usage :
    python scripts/scrape_l1_transfers.py            # scrape en ligne + régénère
    python scripts/scrape_l1_transfers.py --offline  # réutilise le cache HTML
"""
import os, re, sys, json, time, html as _html
from datetime import date, datetime
import requests
from bs4 import BeautifulSoup

# console Windows -> UTF-8 (évite les plantages de print sur cp1252)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE  = os.path.join(ROOT, "scripts", ".cache")
DATA   = os.path.join(ROOT, "data")
TPL    = os.path.join(ROOT, "scripts", "mercato_template.html")
OUT    = os.path.join(ROOT, "mercato-l1-2026.html")
STATE  = os.path.join(DATA, "transfers_l1.json")   # snapshot + historique des dates
SEASON = 2026
LATEST_DAYS = 7      # fenêtre "dernières arrivées"
LATEST_MAX  = 10     # nb de cases max
os.makedirs(CACHE, exist_ok=True)
os.makedirs(DATA,  exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# code, nom, slug transfermarkt, id, couleur fond, couleur texte  (ordre d'affichage)
CLUBS = [
    ("PSG",   "Paris Saint-Germain", "fc-paris-saint-germain", 583,   "#0b1e4d", "#fff"),
    ("RCL",   "RC Lens",             "rc-lens",                826,   "#fff200", "#b10012"),
    ("LOSC",  "LOSC Lille",          "losc-lille",             1082,  "#e01e13", "#fff"),
    ("OL",    "Olympique Lyonnais",  "olympique-lyon",         1041,  "#14387f", "#fff"),
    ("OM",    "Olympique de Marseille","olympique-marseille",  244,   "#2faee0", "#fff"),
    ("SRFC",  "Stade Rennais FC",    "fc-stade-rennes",        273,   "#e51b22", "#fff"),
    ("ASM",   "AS Monaco",           "as-monaco",              162,   "#e63329", "#fff"),
    ("RCSA",  "RC Strasbourg",       "rc-strassburg-alsace",   667,   "#009fe3", "#fff"),
    ("FCL",   "FC Lorient",          "fc-lorient",             1158,  "#ee7f00", "#fff"),
    ("TFC",   "Toulouse FC",         "fc-toulouse",            415,   "#5f259f", "#fff"),
    ("PFC",   "Paris FC",            "paris-fc",               10004, "#00518f", "#fff"),
    ("SB29",  "Stade Brestois 29",   "stade-brest-29",         3911,  "#e2001a", "#fff"),
    ("SCO",   "Angers SCO",          "sco-angers",             1420,  "#2b2b2b", "#fff"),
    ("HAC",   "Le Havre AC",         "ac-le-havre",            738,   "#003e7e", "#fff"),
    ("AJA",   "AJ Auxerre",          "aj-auxerre",             290,   "#0072bc", "#fff"),
    ("OGCN",  "OGC Nice",            "ogc-nizza",              417,   "#e30613", "#fff"),
    ("ESTAC", "ESTAC Troyes",        "es-troyes-ac",           1095,  "#1462b0", "#fff"),
    ("LM",    "Le Mans FC",          "le-mans-fc",             1164,  "#e2001a", "#fff"),
]

POS = {
    "Gardien de but": "GdB", "Arrière droit": "ArD", "Arrière gauche": "ArG",
    "Défenseur central": "DC", "Milieu défensif": "MDC", "Milieu central": "MC",
    "Milieu offensif": "MO", "Milieu droit": "MD", "Milieu gauche": "MG",
    "Ailier droit": "AiD", "Ailier gauche": "AiG", "Avant-centre": "AC",
    "Second attaquant": "SA", "Attaquant": "AC", "Défenseur": "DC", "Milieu": "MC",
}
def pos_short(full):
    full = full.strip()
    if full in POS: return POS[full]
    # fallback : initiales des mots
    return "".join(w[0] for w in full.split()[:3]).upper()[:4] or "?"

# --- détection équipe B / réserve / jeunes ---
RESERVE_RE = re.compile(
    r"(\bB\b|\bII\b|\bU-?1\d\b|\bU-?2\d\b|Futuro|R[ée]serve|Youth|Juniores|Primavera|Akademi)",
    re.I)
def is_reserve(club):
    return bool(RESERVE_RE.search(club or ""))

# --- parsing du montant ---
def parse_fee(raw):
    """retourne (type, val_millions, is_loan_return)
       type ∈ {paid, loan, free, none}"""
    t = (raw or "").strip()
    low = t.lower()
    if "fin du prêt" in low or "fin de prêt" in low or "fin du pret" in low:
        return ("none", 0.0, True)          # retour de prêt -> à retirer
    # nombre + unité
    val = 0.0
    m = re.search(r"([\d.,]+)\s*(mio|th|k)\b", low)
    if m:
        num = float(m.group(1).replace(".", "").replace(",", ".")) \
              if m.group(1).count(",") else float(m.group(1).replace(",", "."))
        unit = m.group(2)
        val = num if unit == "mio" else num / 1000.0
    if "prêt" in low or "pret" in low or "loan" in low:
        return ("loan", val, False)
    if m:
        return ("paid", val, False)
    if "libre" in low or "free" in low:
        return ("free", 0.0, False)
    return ("none", 0.0, False)

def fetch(slug, cid, offline=False):
    fn = os.path.join(CACHE, f"{cid}.html")
    if offline and os.path.exists(fn):
        return open(fn, "rb").read()
    url = f"https://www.transfermarkt.fr/{slug}/transfers/verein/{cid}/saison_id/{SEASON}"
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            if r.status_code == 200 and len(r.content) > 5000:
                open(fn, "wb").write(r.content)
                return r.content
            print(f"  ! HTTP {r.status_code} pour {slug} (essai {attempt+1})")
        except Exception as e:
            print(f"  ! {slug} : {e} (essai {attempt+1})")
        time.sleep(2 + attempt * 2)
    if os.path.exists(fn):
        print(f"  -> cache utilisé pour {slug}")
        return open(fn, "rb").read()
    return None

def club_name_from_cell(td):
    for a in td.find_all("a"):
        txt = a.get_text(strip=True)
        if txt:
            return txt
    txt = td.get_text(" ", strip=True)
    # retire un éventuel nom de compétition en fin (span détaché)
    return txt or "Sans club"

def parse_side(rt):
    """parse une responsive-table -> liste de dict transferts bruts"""
    out = []
    tbody = rt.find("table").find("tbody")
    if not tbody:
        return out
    for tr in tbody.find_all("tr", recursive=False):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 6:
            continue
        namea = tds[1].select_one(".hauptlink a") or tds[1].find("a")
        if not namea:
            continue
        name = (namea.get("title") or namea.get_text(strip=True)).strip()
        # poste = dernière ligne de l'inline-table du joueur
        pos_full = ""
        inner_rows = tds[1].find_all("tr")
        if inner_rows:
            pos_full = inner_rows[-1].get_text(" ", strip=True)
        age  = re.sub(r"\D", "", tds[2].get_text(strip=True))[:2]
        club = club_name_from_cell(tds[4])
        # nettoie le nom de club (retire compétition collée si présente)
        fee_raw = tds[5].get_text(" ", strip=True)
        out.append({
            "p": name, "age": int(age) if age else 0,
            "pos": pos_short(pos_full), "club": club, "feeRaw": fee_raw,
        })
    return out

def clean(rows):
    """applique règles : retire retours de prêt + jeunes/réserve sans montant"""
    res = []
    for t in rows:
        typ, val, loan_ret = parse_fee(t["feeRaw"])
        if loan_ret:
            continue                                   # retour de prêt
        if is_reserve(t["club"]) and typ in ("free", "none", "loan"):
            continue                                   # promu équipe B / jeune sans transfert
        res.append({
            "p": t["p"], "age": t["age"], "pos": t["pos"], "club": t["club"],
            "type": typ, "val": round(val, 3),
        })
    return res

def scrape(offline=False):
    clubs_data = []
    for code, name, slug, cid, bg, fg in CLUBS:
        print(f"· {name} …")
        raw = fetch(slug, cid, offline)
        if not raw:
            print(f"  !! échec total {name}, club ignoré ce passage")
            clubs_data.append({"code": code, "name": name, "bg": bg, "fg": fg,
                               "arr": [], "dep": [], "failed": True})
            continue
        soup = BeautifulSoup(raw, "lxml", from_encoding="utf-8")
        rts = soup.select("div.responsive-table")
        arr = clean(parse_side(rts[0])) if len(rts) > 0 else []
        dep = clean(parse_side(rts[1])) if len(rts) > 1 else []
        clubs_data.append({"code": code, "name": name, "bg": bg, "fg": fg,
                           "arr": arr, "dep": dep})
        if not offline:
            time.sleep(1.2)
    return clubs_data

# ---------- diff / dates ----------
def key(club_code, direction, t):
    return f"{club_code}|{direction}|{t['p']}|{t['club']}"

def load_state():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE, encoding="utf-8"))
        except Exception:
            pass
    return {}

def signature(clubs_data):
    """empreinte des DONNÉES (hors horodatage) pour détecter un vrai changement"""
    import hashlib
    def norm(lst):
        return sorted([[t["p"], t["club"], t["type"], t["val"]] for t in lst])
    canon = [[c["code"], "FAILED" if c.get("failed") else norm(c["arr"]),
              [] if c.get("failed") else norm(c["dep"])] for c in clubs_data]
    return hashlib.md5(json.dumps(canon, ensure_ascii=False, sort_keys=True)
                       .encode("utf-8")).hexdigest()

def restore_failed(clubs_data, old):
    """réutilise la dernière version connue d'un club qui a échoué au scrape"""
    old_by = {c["code"]: c for c in old.get("clubs", [])}
    for i, c in enumerate(clubs_data):
        if c.get("failed") and c["code"] in old_by:
            oc = old_by[c["code"]]
            clubs_data[i] = {**c, "arr": oc.get("arr", []), "dep": oc.get("dep", []),
                             "failed": False, "restored": True}
            print(f"  ↻ {c['name']} : réutilisation de la dernière version connue")

def apply_history(clubs_data, old):
    """affecte first_seen à chaque transfert et renvoie la liste 'latest'"""
    today = date.today().isoformat()
    prev = old.get("seen", {})
    first_run = not old
    seen = {}
    latest = []
    for c in clubs_data:
        if c.get("failed"):
            continue
        for direction, lst in (("in", c["arr"]), ("out", c["dep"])):
            for t in lst:
                k = key(c["code"], direction, t)
                fs = prev.get(k, today)
                seen[k] = fs
                t["fs"] = fs
                if direction == "in":
                    latest.append({**t, "club_code": c["code"], "club_name": c["name"],
                                   "bg": c["bg"], "fg": c["fg"], "fs": fs})
    sig = signature(clubs_data)
    json.dump({"updated": datetime.now().isoformat(timespec="seconds"),
               "sig": sig, "seen": seen, "clubs": clubs_data},
              open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # sélection "dernières arrivées"
    def days_ago(fs):
        try:
            return (date.today() - date.fromisoformat(fs)).days
        except Exception:
            return 999
    if first_run:
        # pas d'historique : on met en avant les plus gros coups du moment
        pool = sorted(latest, key=lambda x: (-x["val"], x["p"]))
    else:
        recent = [x for x in latest if days_ago(x["fs"]) <= LATEST_DAYS]
        if not recent:                      # rien de neuf : on montre les plus récentes
            recent = sorted(latest, key=lambda x: x["fs"], reverse=True)[:LATEST_MAX]
        pool = sorted(recent, key=lambda x: (x["fs"], x["val"]), reverse=True)
    return pool[:LATEST_MAX], first_run, sig

# ---------- génération HTML ----------
def generate(clubs_data, latest, first_run):
    tpl = open(TPL, encoding="utf-8").read()
    updated = datetime.now().strftime("%d/%m/%Y à %Hh%M")
    tag = "Plus gros coups du mercato" if first_run else f"Nouvelles arrivées ({LATEST_DAYS} derniers jours)"
    out = (tpl
           .replace("/*__CLUBS__*/[]", json.dumps(clubs_data, ensure_ascii=False))
           .replace("/*__LATEST__*/[]", json.dumps(latest, ensure_ascii=False))
           .replace("__LATEST_LABEL__", tag)
           .replace("__UPDATED__", updated))
    open(OUT, "w", encoding="utf-8").write(out)
    print(f"\n✓ {OUT} régénéré — MAJ {updated}")

def main():
    offline = "--offline" in sys.argv
    print(f"Scrape Ligue 1 {SEASON}/{SEASON+1} {'(cache)' if offline else '(en ligne)'}\n")
    old = load_state()
    old_sig = old.get("sig")
    clubs_data = scrape(offline)
    restore_failed(clubs_data, old)
    latest, first_run, sig = apply_history(clubs_data, old)
    na = sum(len(c["arr"]) for c in clubs_data)
    nd = sum(len(c["dep"]) for c in clubs_data)
    print(f"\nTotal : {na} arrivées, {nd} départs, {len(latest)} cases 'dernières arrivées'.")
    generate(clubs_data, latest, first_run)

    changed = (sig != old_sig)
    open(os.path.join(DATA, ".push"), "w", encoding="utf-8").write("1" if changed else "0")
    print("→ Données " + ("MODIFIÉES : publication." if changed else "inchangées : pas de publication."))

if __name__ == "__main__":
    main()
