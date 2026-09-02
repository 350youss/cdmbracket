#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Recalcule le squad cost ratio (règle UEFA des 70 %) de l'OM à partir de
l'EFFECTIF ACTUEL (pas d'une base figée 2024-25) -> régénère squad-cost.html

Numérateur = Σ(masse salariale effectif actuel, Capology brut × 1,5)
           + Σ(amortissement annuel effectif actuel, prix de transfert / durée
             de contrat, scrapés sur Transfermarkt)
           + honoraires agents (fixe, éditable dans data/squad_cost.json)
Dénominateur = estimation de produits saisie dans data/squad_cost.json
  ("denominator_estimate") — à affiner à la main, pas de scraping dessus.

Le prix de transfert de chaque joueur de l'effectif est retrouvé en parcourant
les pages de transferts du club sur les saisons passées (même mécanisme que
scrape_l1_transfers.py, mais uniquement pour l'OM et sur plusieurs saisons) :
la fiche joueur elle-même ne sert QUE pour la durée de contrat, car son
"historique des transferts" est rendu en JS côté Transfermarkt (illisible par
un scraper HTML simple).

Best-effort partout : si une donnée est introuvable (site indisponible,
joueur non trouvé, etc.) le champ reste null et le calcul l'ignore plutôt que
de planter ou d'inventer un chiffre — à compléter à la main si besoin dans
data/squad_cost.json. Les données déjà connues (fee/contrat) ne sont pas
re-scrapées à chaque run ; seul le salaire (1 seule page Capology pour tout
l'effectif) est rafraîchi à chaque passage.

Usage :
    python scripts/scrape_squad_cost.py            # scrape en ligne + régénère
    python scripts/scrape_squad_cost.py --offline  # réutilise le cache HTML
"""
import os, re, sys, json, time, unicodedata
from datetime import date, datetime
import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrape_l1_transfers import fetch_url, HEADERS, CACHE, ROOT, parse_side, clean  # réutilise le socle existant

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA        = os.path.join(ROOT, "data")
STATE_L1    = os.path.join(DATA, "transfers_l1.json")
STATE_COST  = os.path.join(DATA, "squad_cost.json")
TPL         = os.path.join(ROOT, "scripts", "squad_cost_template.html")
OUT         = os.path.join(ROOT, "squad-cost.html")
OM_CODE     = "OM"
OM_SLUG     = "olympique-marseille"
OM_CID      = 244
WAGE_COEF   = 1.5   # brut Capology -> coût chargé estimé (x1,5, cotisations patronales non incluses dans le brut affiché)
HISTORY_SEASONS = range(2018, 2027)   # fenêtre de recherche du prix de transfert d'arrivée à l'OM


_TM_STATUS = {"checked": False, "available": True}

def tm_available(offline=False):
    """sonde rapide (1 requête, pas de retry) avant de lancer des dizaines de
       fetch avec backoff -> évite de perdre plusieurs minutes si Transfermarkt
       bloque/rate-limite (ex : après un gros scrape plus tôt dans la journée)."""
    if offline:
        return True   # en offline on ne fait que lire le cache, jamais de requête réseau bloquante
    if _TM_STATUS["checked"]:
        return _TM_STATUS["available"]
    try:
        r = requests.get(f"https://www.transfermarkt.fr/{OM_SLUG}/startseite/verein/{OM_CID}",
                          headers=HEADERS, timeout=10)
        ok = r.status_code == 200 and len(r.content) > 5000
    except Exception:
        ok = False
    _TM_STATUS["checked"], _TM_STATUS["available"] = True, ok
    if not ok:
        print("  ! Transfermarkt semble indisponible/bloqué pour l'instant — durée de contrat et "
              "prix de transfert non rafraîchis ce passage (valeurs déjà connues conservées).")
    return ok


def load_json(path, default):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            pass
    return default


def player_key(direction, t):
    return f"{direction}|{t['p']}|{t['club']}"


# ---------- best-effort : durée de contrat (fiche joueur Transfermarkt) ----------
def find_player_profile(name, offline=False):
    if not tm_available(offline):
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    fn = os.path.join(CACHE, f"search_{slug}.html")
    url = f"https://www.transfermarkt.fr/schnellsuche/ergebnis/schnellsuche?query={requests.utils.quote(name)}"
    raw = fetch_url(fn, url, offline, f"recherche {name}")
    if not raw:
        return None
    soup = BeautifulSoup(raw, "lxml", from_encoding="utf-8")
    a = soup.select_one("table.items td.hauptlink a[href*='/profil/spieler/']")
    if not a:
        return None
    href = a["href"]
    return "https://www.transfermarkt.fr" + href if href.startswith("/") else href


def fetch_contract_info(name, offline=False):
    """renvoie (année de fin de contrat, année de dernière prolongation ou None)
       depuis la fiche Transfermarkt. La prolongation prime sur l'arrivée d'origine :
       quand un contrat est renouvelé, l'amortissement repart de cette date-là
       (valeur nette restante réétalée sur la nouvelle durée), pas de la signature
       initiale -> voir compute_contract_years()."""
    try:
        profile_url = find_player_profile(name, offline)
        if not profile_url:
            return None, None
        m = re.search(r"spieler/(\d+)", profile_url)
        pid = m.group(1) if m else re.sub(r"\W+", "_", name)
        fn = os.path.join(CACHE, f"profile_{pid}.html")
        raw = fetch_url(fn, profile_url, offline, f"fiche {name}")
        if not raw:
            return None, None
        soup = BeautifulSoup(raw, "lxml", from_encoding="utf-8")
        label = soup.find(string=re.compile(r"Contrat jusqu.à", re.I))
        end_year = None
        if label:
            span = label.find_next("span", class_="data-header__content")
            if span:
                m = re.search(r"(\d{4})", span.get_text(" ", strip=True))
                end_year = int(m.group(1)) if m else None
        renew_label = soup.find(string=re.compile(r"derni.re prolongation", re.I))
        renewal_year = None
        if renew_label:
            renew_val = renew_label.find_next(
                "span", class_="info-table__content--bold")
            if renew_val:
                m = re.search(r"(\d{4})", renew_val.get_text(" ", strip=True))
                renewal_year = int(m.group(1)) if m else None
        return end_year, renewal_year
    except Exception as e:
        print(f"  ! durée contrat introuvable pour {name} : {e}")
        return None, None


def compute_amortization(fee, arrival_year, end_year, renewal_year, override=None):
    """Calcule (durée affichée, base, amortissement annuel) pour un joueur.

    Priorité :
    1. override["contract_years"] : durée totale imposée à la main (ex: la fiche
       Transfermarkt d'un joueur prêté montre la date de retour de prêt, pas la
       fin réelle du contrat OM -> on écrase avec la vraie valeur connue).
    2. Prolongation connue + override["original_contract_years"] : méthode
       comptable correcte. On calcule l'amortissement annuel D'ORIGINE
       (fee / durée initiale), on déduit ce qui a déjà été amorti entre la
       signature et la prolongation, et on répartit la VALEUR NETTE RESTANTE
       sur la durée restant à courir après la prolongation.
    3. Prolongation connue sans durée initiale : approximation (fee total étalé
       sur la durée post-prolongation) — surestime légèrement l'amortissement
       puisqu'une partie du fee était déjà amortie avant le renouvellement.
    4. Durée signée à l'arrivée (fin - année de signature).
    5. Années restantes depuis aujourd'hui (dernier recours, transfert hors
       fenêtre d'historique 2018-2026)."""
    override = override or {}
    if fee is None:
        return None, "inconnue", 0.0

    if override.get("contract_years"):
        years = override["contract_years"]
        return years, "manuel", round(fee / years, 3)

    if renewal_year and end_year:
        years_after = max(1, end_year - renewal_year)
        orig_years = override.get("original_contract_years")
        if orig_years and arrival_year:
            orig_annual = fee / orig_years
            elapsed = max(0, renewal_year - arrival_year)
            amortized_before = min(fee, elapsed * orig_annual)
            remaining_value = fee - amortized_before
            basis = f"prolongation {renewal_year} (valeur restante, initial {orig_years} ans)"
            return years_after, basis, round(remaining_value / years_after, 3)
        basis = f"prolongation {renewal_year} (approx, fee total)"
        return years_after, basis, round(fee / years_after, 3)

    if end_year is None:
        return None, "inconnue", 0.0
    if arrival_year is not None:
        years = max(1, end_year - arrival_year)
        return years, "signée", round(fee / years, 3)
    years = max(1, end_year - date.today().year)
    return years, "restante (approx)", round(fee / years, 3)


# ---------- best-effort : prix de transfert d'arrivée (historique des pages club) ----------
def fetch_om_transfer_history(offline=False):
    """parcourt les pages de transferts de l'OM saison par saison (mécanisme déjà
       utilisé par scrape_l1_transfers.py, ici uniquement pour l'OM) et renvoie
       {nom_joueur: {"fee":…, "type":…, "season":…}} — dernière arrivée connue."""
    if not tm_available(offline):
        return {}
    out = {}
    for season in HISTORY_SEASONS:
        fn = os.path.join(CACHE, f"om_hist_{season}.html")
        url = f"https://www.transfermarkt.fr/{OM_SLUG}/transfers/verein/{OM_CID}/saison_id/{season}"
        raw = fetch_url(fn, url, offline, f"OM historique {season}")
        if not raw:
            continue
        soup = BeautifulSoup(raw, "lxml", from_encoding="utf-8")
        rts = soup.select("div.responsive-table")
        if not rts:
            continue
        arr = clean(parse_side(rts[0]))
        for t in arr:
            out[t["p"]] = {"fee": t["val"], "type": t["type"], "season": season}
        if not offline:
            time.sleep(1.0)
    return out


# ---------- best-effort : salaire brut (Capology, 1 page = tout l'effectif) ----------
_CAPOLOGY_CACHE = {}   # évite de re-télécharger la même page pour chaque joueur du run

_ACCENT_CLASS = {   # classe de caractères tolérante, pour matcher quel que soit l'accent utilisé par Capology
    "a": "[aàáâãäA]", "e": "[eèéêëE]", "i": "[iìíîïI]", "o": "[oòóôõöO]",
    "u": "[uùúûüU]", "c": "[cçC]", "n": "[nñN]", "y": "[yýÿY]",
}

def _accent_insensitive_pattern(s):
    """motif regex qui matche le nom COMPLET quel que soit l'accent (ï/î, é/è...) sur
    chaque lettre — remplace un ancien tronquage à la ASCII-prefix (ex: 'Meïté' -> 'Me')
    qui était assez court pour matcher un tout autre joueur ('Medina') en premier sur
    la page Capology et lui piquer son salaire."""
    out = []
    for ch in s:
        base = (unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode("ascii") or ch).lower()
        out.append(_ACCENT_CLASS.get(base, re.escape(ch)))
    return "".join(out)

def fetch_capology_wage(name, offline=False):
    if "raw" not in _CAPOLOGY_CACHE:
        fn = os.path.join(CACHE, "capology_om.html")
        url = "https://www.capology.com/club/marseille/salaries/"
        _CAPOLOGY_CACHE["raw"] = fetch_url(fn, url, offline, "Capology OM")
    raw = _CAPOLOGY_CACHE["raw"]
    if not raw:
        return None
    try:
        text = raw.decode("utf-8", errors="replace")
        raw_last = name.split()[-1]
        last = _accent_insensitive_pattern(raw_last)
        m_name = re.search(rf"'name':\s*\"[^\"]*{last}[^<\"]*</a>\"", text, re.I)
        if not m_name:
            return None
        window = text[m_name.end():m_name.end() + 800]
        m_wage = re.search(r"weekly_gross_eur':accounting\.formatMoney\(\"(\d+)\"", window)
        if not m_wage:
            return None
        annual = int(m_wage.group(1))  # champ nommé "weekly_..." mais la valeur brute est l'ANNUEL
        return round(annual / 1_000_000, 3)
    except Exception as e:
        print(f"  ! salaire Capology introuvable pour {name} : {e}")
        return None


# ---------- mouvements mercato (pilier Ventes + timeline) ----------
def process_transfers(cost_state, l1_state, offline=False):
    om = next((c for c in l1_state.get("clubs", []) if c["code"] == OM_CODE), None)
    if not om:
        print("! Club OM introuvable dans data/transfers_l1.json — rien à traiter.")
        return cost_state

    players = cost_state.setdefault("players", {})
    manual_names = {(p["name"], p["direction"]) for p in players.values() if p.get("manual")}
    for direction, lst in (("in", om.get("arr", [])), ("out", om.get("dep", []))):
        for t in lst:
            k = player_key(direction, t)
            if k in players or (t["p"], direction) in manual_names:
                continue
            print(f"· nouveau mouvement OM : {t['p']} ({direction}) …")
            fee = t.get("val", 0.0) or 0.0
            # le salaire n'a de sens à afficher que pour une ARRIVÉE (coût qui démarre) :
            # pour un départ (vente ou prêt), l'OM ne paie plus ce salaire, l'afficher induirait en erreur
            wage_gross = fetch_capology_wage(t["p"], offline) if direction == "in" else None
            wage_loaded = round(wage_gross * WAGE_COEF, 3) if wage_gross else None
            players[k] = {
                "name": t["p"], "direction": direction, "date": t.get("fs", date.today().isoformat()),
                "counterpart_club": t.get("club"), "type": t.get("type"),
                "fee": fee, "wage_capology_gross": wage_gross, "wage_estimated_loaded": wage_loaded,
            }
    return cost_state


def resync_wage_coefficient(cost_state):
    for p in cost_state.get("players", {}).values():
        if p["direction"] == "out":
            # un départ (vente ou prêt) n'est plus un coût salarial OM -> jamais affiché
            p["wage_capology_gross"] = None
            p["wage_estimated_loaded"] = None
            continue
        gross = p.get("wage_capology_gross")
        if gross is not None:
            p["wage_estimated_loaded"] = round(gross * WAGE_COEF, 3)
    for p in cost_state.get("squad_finances", {}).values():
        gross = p.get("wage_capology_gross")
        if gross is not None:
            p["wage_estimated_loaded"] = round(gross * WAGE_COEF, 3)
    return cost_state


def compute_sales(cost_state):
    """pilier Ventes : indemnités de transfert ENCAISSÉES PAR L'OM sur les départs
       payants de la saison (hors prêts/libres, hors bonus conditionnels, part
       du club uniquement quand une clause de reversement s'applique)."""
    players = cost_state.get("players", {})
    sales = [p for p in players.values() if p["direction"] == "out" and (p.get("fee") or 0) > 0
             and p.get("type") in ("paid", None)]
    total = round(sum(p["fee"] for p in sales), 3)
    total_with_bonus = round(total + sum(p.get("bonus_fee") or 0 for p in sales), 3)
    return {"total": total, "total_with_bonus": total_with_bonus, "count": len(sales)}


# ---------- plus-values comptables sur les départs payants de la saison ----------
def compute_trading_result(cost_state, offline=False):
    """résultat net des opérations de mutation (partie du dénominateur UEFA) :
       Σ(prix de vente - valeur nette comptable) sur les départs payants.
       VNC à la date de départ = prix d'arrivée à l'OM - amortissement déjà pris
       (années écoulées entre l'arrivée et le départ × amortissement annuel
       d'origine). Sans la durée de contrat ORIGINALE (non scrapable une fois le
       joueur parti, son profil TM affiche déjà le contrat de son nouveau club),
       on ne peut pas la déduire -> nécessite un override manuel par joueur
       (cost_state["contract_overrides"][nom]["contract_years"])."""
    players = cost_state.get("players", {})
    overrides = cost_state.get("contract_overrides", {})
    sales = [p for p in players.values() if p["direction"] == "out"
             and p.get("type") == "paid" and (p.get("fee") or 0) > 0]
    if not sales:
        return {"total": 0.0, "details": {}}

    history = fetch_om_transfer_history(offline)
    details = {}
    for p in sales:
        name = p["name"]
        h = history.get(name)
        arrival_fee = h["fee"] if (h and h["type"] == "paid") else None
        arrival_year = h["season"] if h else None
        try:
            departure_year = int(p["date"][:4])
        except (TypeError, ValueError, KeyError):
            departure_year = date.today().year

        if not arrival_fee:
            # arrivé libre (ou fee inconnu) -> VNC nulle, la vente est un gain sec
            book_value = 0.0
            note = "arrivé libre -> VNC nulle"
        elif arrival_year == departure_year:
            # acheté et revendu la même année -> aucun amortissement encore pris
            book_value = arrival_fee
            note = f"acheté {arrival_fee} M€ en {arrival_year}, revendu la même année -> VNC = fee entier"
        else:
            contract_years = overrides.get(name, {}).get("contract_years")
            if not contract_years:
                book_value = arrival_fee   # durée inconnue -> prudence, VNC = fee entier (sous-estime la PV)
                note = f"acheté {arrival_fee} M€ en {arrival_year}, durée de contrat initiale inconnue -> VNC prudente = fee entier"
            else:
                annual = arrival_fee / contract_years
                elapsed = max(0, departure_year - arrival_year)
                amortized = min(arrival_fee, elapsed * annual)
                book_value = round(arrival_fee - amortized, 3)
                note = (f"acheté {arrival_fee} M€ en {arrival_year} ({contract_years} ans signés), "
                        f"{elapsed} an(s) amorti(s) = {round(amortized,3)} M€ -> VNC = {book_value} M€")

        gain = round(p["fee"] - book_value, 3)
        details[name] = {"sale_fee": p["fee"], "arrival_fee": arrival_fee,
                          "book_value": book_value, "capital_gain": gain, "note": note}

    total = round(sum(d["capital_gain"] for d in details.values()), 3)
    return {"total": total, "details": details}


# ---------- effectif actuel : masse salariale + amortissement ----------
def sync_squad_finances(cost_state, l1_state, offline=False):
    squad = l1_state.get("squads", {}).get(OM_CODE, [])
    if not squad:
        print("! Effectif OM introuvable dans data/transfers_l1.json.")
        return cost_state

    players = cost_state.get("players", {})
    # départ DÉFINITIF (vente/libre) -> sort du calcul. Un PRÊT reste la propriété
    # de l'OM (toujours amorti) : traité à part par apply_loans(), jamais ici.
    departed_permanent = {p["name"] for p in players.values()
                           if p["direction"] == "out" and p.get("type") != "loan"}
    loaned_out = {p["name"] for p in players.values()
                  if p["direction"] == "out" and p.get("type") == "loan"}

    sf = cost_state.setdefault("squad_finances", {})
    # purge les entrées obsolètes : plus dans le kader ET pas un prêt en cours
    # (ex : joueur vendu il y a plusieurs runs, Transfermarkt a mis à jour le kader)
    current_names = {p["p"] for p in squad}
    for stale in [n for n in sf if n not in current_names and n not in loaned_out]:
        del sf[stale]

    history = None
    missing_fee = []

    for p in squad:
        name = p["p"]
        if name in departed_permanent:
            sf.pop(name, None)   # transfert de départ déjà enregistré -> sort de l'effectif suivi
            continue

        wage_gross = fetch_capology_wage(name, offline)
        wage_loaded = round(wage_gross * WAGE_COEF, 3) if wage_gross else None

        if name in sf and sf[name].get("fee_lookup_done"):
            sf[name]["wage_capology_gross"] = wage_gross
            sf[name]["wage_estimated_loaded"] = wage_loaded
            if sf[name].get("fee") is None:
                missing_fee.append(name)
            continue

        if history is None:
            print("· Historique des transferts OM (recherche du prix d'arrivée par joueur)…")
            history = fetch_om_transfer_history(offline)

        h = history.get(name)
        # arrivé libre (h["type"]=="free") -> fee CONNU = 0, amortissement 0 à juste
        # titre (rien à amortir). Seul h absent = prix vraiment introuvable.
        if h and h["type"] == "paid":
            fee = h["fee"]
        elif h and h["type"] == "free":
            fee = 0.0
        else:
            fee = None
        end_year, renewal_year = fetch_contract_info(name, offline)
        override = cost_state.get("contract_overrides", {}).get(name)
        contract_years, basis, amort = compute_amortization(
            fee, h["season"] if h else None, end_year, renewal_year, override)
        if fee is None:
            missing_fee.append(name)
        elif fee == 0.0:
            basis = "arrivé libre"

        sf[name] = {
            "fee": fee, "contract_years": contract_years, "contract_years_basis": basis,
            "contract_end_year": end_year, "amortization_annual": amort,
            "wage_capology_gross": wage_gross, "wage_estimated_loaded": wage_loaded,
            "arrival_season": h["season"] if h else None,
            "market_value_fallback": p.get("val"),
            # ne fige "trouvé" que si TM répondait vraiment lors de cette tentative,
            # sinon on retente au run suivant plutôt que d'abandonner définitivement
            "fee_lookup_done": tm_available(offline),
        }
        if not offline:
            time.sleep(1.0)

    if missing_fee:
        print(f"  ! prix de transfert non trouvé pour : {', '.join(missing_fee)} "
              f"(Transfermarkt indisponible ou joueur non identifié — amortissement compté 0 pour eux)")
    return cost_state


def apply_loans(cost_state, offline=False):
    """Un joueur PRÊTÉ reste la propriété de l'OM : son amortissement continue de
       courir même s'il a disparu du kader Transfermarkt (donc absent de
       sync_squad_finances). On le réintègre ici avec un amortissement NET =
       amortissement brut (prix d'achat / durée contrat) − indemnité de prêt
       reçue (elle compense une partie du coût, mais ne doit jamais être comptée
       dans le pilier Ventes, qui ne concerne que les cessions définitives)."""
    players = cost_state.get("players", {})
    sf = cost_state.setdefault("squad_finances", {})
    loans_out = [p for p in players.values() if p["direction"] == "out" and p.get("type") == "loan"]

    for loan in loans_out:
        name = loan["name"]
        loan_income = loan.get("fee") or 0.0
        prev = sf.get(name)
        prev_basis = prev.get("contract_years_basis") if prev else None
        override = cost_state.get("contract_overrides", {}).get(name)
        prev_reliable = prev_basis == "manuel" or prev_basis == "signée" \
                         or (prev_basis or "").startswith("prolongation")
        if prev and prev_reliable:
            # déjà suivi avec une durée fiable (signature ou prolongation), avant OU
            # pendant son prêt : on garde ce chiffre plutôt que de le recalculer depuis
            # Transfermarkt, qui affiche la date de retour de prêt comme fin de contrat
            fee, contract_years, basis = prev.get("fee"), prev.get("contract_years"), prev_basis
            # si deja en pret avant ce passage, "amortization_annual" est deja NET
            # (gross - loan_income precedent) : reprendre "amortization_gross" pour
            # eviter de soustraire l'indemnite de pret deux fois
            gross_amort = prev.get("amortization_gross", prev.get("amortization_annual", 0.0))
        else:
            # sinon, cherche le prix d'achat dans l'arrivée mercato du même nom
            # (cas courant : joueur acheté puis prêté dans la foulée, ex. Traoré)
            # et recalcule la durée SIGNÉE (fin de contrat - année d'arrivée) —
            # attention : côté profil Transfermarkt, un joueur EN PRÊT affiche la
            # date de retour de prêt comme "Contrat jusqu'à", pas la vraie fin de
            # contrat OM -> se fier à override["contract_years"] quand connu.
            arrival = next((p for p in players.values()
                             if p["direction"] == "in" and p["name"] == name), None)
            fee = arrival.get("fee") if arrival else (prev.get("fee") if prev else None)
            end_year, renewal_year = fetch_contract_info(name, offline)
            arrival_year = None
            if arrival and arrival.get("date"):
                try:
                    arrival_year = int(arrival["date"][:4])
                except (TypeError, ValueError):
                    pass
            contract_years, basis, gross_amort = compute_amortization(
                fee, arrival_year, end_year, renewal_year, override)
            if contract_years is None:
                contract_years = (prev.get("contract_years") if prev else None) \
                                  or (arrival.get("contract_years") if arrival else None)
                basis = "reprise valeur précédente"
                gross_amort = round(fee / contract_years, 3) if (fee and contract_years) else 0.0

        sf[name] = {
            "fee": fee, "contract_years": contract_years, "contract_years_basis": basis,
            "amortization_gross": gross_amort, "loan_income": loan_income,
            "amortization_annual": round(gross_amort - loan_income, 3),
            "wage_capology_gross": None, "wage_estimated_loaded": None,
            "on_loan": True, "fee_lookup_done": fee is not None,
        }
    return cost_state


def compute_ratio(cost_state):
    sf = cost_state.get("squad_finances", {})
    wage_total = round(sum(p.get("wage_estimated_loaded") or 0.0 for p in sf.values()), 3)
    amort_total = round(sum(p.get("amortization_annual") or 0.0 for p in sf.values()), 3)
    agent_fees = cost_state.get("base", {}).get("agent_fees_base", 10.0)

    numerator = round(wage_total + amort_total + agent_fees, 3)

    den_fields = cost_state.get("denominator_estimate", {})
    filled = [v for k, v in den_fields.items() if k != "note" and v is not None]
    denominator = round(sum(filled), 3) if filled else None

    ratio = round(numerator / denominator, 4) if denominator else None
    return numerator, denominator, ratio, wage_total, amort_total


def player_book_value_today(p):
    """valeur nette comptable ESTIMÉE aujourd'hui (même logique que
       compute_trading_result, mais projetée à la date du jour plutôt qu'à une
       date de vente réelle) : sert à estimer la plus-value d'un départ
       hypothétique à la valeur marchande Transfermarkt."""
    fee = p.get("fee")
    if not fee:
        return 0.0
    amort = p.get("amortization_annual") or 0.0
    basis = p.get("contract_years_basis") or ""
    current_year = date.today().year

    m = re.match(r"prolongation (\d{4})", basis)
    if m and p.get("contract_years"):
        renewal_year = int(m.group(1))
        remaining_at_renewal = amort * p["contract_years"]
        elapsed = max(0, current_year - renewal_year)
        amortized_since = min(remaining_at_renewal, elapsed * amort)
        return round(remaining_at_renewal - amortized_since, 3)

    arrival_year = p.get("arrival_season")
    if arrival_year and p.get("contract_years"):
        annual = fee / p["contract_years"]
        elapsed = max(0, current_year - arrival_year)
        return round(fee - min(fee, elapsed * annual), 3)

    return fee   # durée inconnue -> prudence, VNC = fee entier


def compute_departure_impact(cost_state):
    """classe les joueurs de l'effectif par impact sur le ratio en cas de départ
       hypothétique À LA VALEUR MARCHANDE TRANSFERMARKT : le numérateur perd son
       salaire + son amortissement, le dénominateur gagne la plus-value
       (valeur marchande - valeur nette comptable actuelle)."""
    sf = cost_state.get("squad_finances", {})
    numerator, denominator, ratio, _, _ = compute_ratio(cost_state)
    if not denominator:
        return []
    rows = []
    for name, p in sf.items():
        if p.get("on_loan"):
            continue   # déjà prêté, pas un départ hypothétique pertinent ici
        market_value = p.get("market_value_fallback")
        if market_value is None:
            continue
        wage = p.get("wage_estimated_loaded") or 0.0
        amort = p.get("amortization_annual") or 0.0
        book_value = player_book_value_today(p)
        capital_gain = round(market_value - book_value, 3)

        new_numerator = round(numerator - wage - amort, 3)
        new_denominator = round(denominator + capital_gain, 3)
        new_ratio = round(new_numerator / new_denominator, 4) if new_denominator else None
        # négatif = le ratio BAISSE (départ qui allège la contrainte des 70%),
        # positif = le ratio MONTE (rare : vente à perte comptable qui l'emporte
        # sur le gain de salaire/amortissement)
        delta_points = round((new_ratio - ratio) * 100, 2) if new_ratio is not None else None

        rows.append({
            "name": name, "market_value": market_value, "wage": round(wage, 3),
            "amortization": round(amort, 3), "book_value": book_value,
            "capital_gain": capital_gain, "new_ratio": new_ratio, "delta_points": delta_points,
        })
    rows.sort(key=lambda r: r["delta_points"] if r["delta_points"] is not None else 999)
    return rows


def generate(cost_state):
    tpl = open(TPL, encoding="utf-8").read()
    updated = datetime.now().strftime("%d/%m/%Y à %Hh%M")
    out = (tpl
           .replace("/*__SQUADCOST__*/{}", json.dumps(cost_state, ensure_ascii=False))
           .replace("__UPDATED__", updated))
    open(OUT, "w", encoding="utf-8").write(out)
    print(f"✓ {OUT} régénéré — MAJ {updated}")


def main():
    offline = "--offline" in sys.argv
    print(f"Squad cost ratio OM {'(cache)' if offline else '(en ligne)'}\n")

    l1_state = load_json(STATE_L1, {})
    cost_state = load_json(STATE_COST, {
        "season": "2026-27", "updated": None,
        "base": {"agent_fees_base": 10.0}, "denominator_estimate": {},
        "players": {}, "squad_finances": {}, "history": [],
    })

    cost_state = process_transfers(cost_state, l1_state, offline)
    cost_state = sync_squad_finances(cost_state, l1_state, offline)
    cost_state = apply_loans(cost_state, offline)
    cost_state = resync_wage_coefficient(cost_state)

    trading = compute_trading_result(cost_state, offline)
    cost_state.setdefault("denominator_estimate", {})["resultat_trading_ete"] = trading["total"]
    cost_state["trading_result_detail"] = trading["details"]

    numerator, denominator, ratio, wage_total, amort_total = compute_ratio(cost_state)
    sales = compute_sales(cost_state)
    cost_state["departure_impact"] = compute_departure_impact(cost_state)

    last = cost_state["history"][-1] if cost_state.get("history") else None
    changed_vals = (numerator, denominator)
    last_vals = (last["numerator"], last["denominator"]) if last else None
    if last_vals != changed_vals:
        new_players = [p["name"] for p in cost_state["players"].values()
                       if p["date"] == date.today().isoformat()]
        trigger = f"MAJ mercato : {', '.join(new_players)}" if new_players else "Recalcul"
        cost_state.setdefault("history", []).append({
            "date": date.today().isoformat(), "numerator": numerator,
            "denominator": denominator, "ratio": ratio,
            "sales_total": sales["total"], "trigger": trigger,
        })

    cost_state["updated"] = datetime.now().isoformat(timespec="seconds")
    json.dump(cost_state, open(STATE_COST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"\nMasse salariale effectif = {wage_total} M€ · Amortissements effectif = {amort_total} M€")
    print(f"Résultat net trading (plus-values) = {trading['total']} M€")
    print(f"Numérateur = {numerator} M€ · Dénominateur = {denominator} M€ · Ratio = {ratio}")
    print(f"Ventes de la saison = {sales['total']} M€ ({sales['count']} vente(s), "
          f"{sales['total_with_bonus']} M€ bonus inclus)")
    generate(cost_state)

    changed = "1" if last_vals != changed_vals else "0"
    open(os.path.join(DATA, ".push_squadcost"), "w", encoding="utf-8").write(changed)
    print("→ Ratio " + ("MODIFIÉ : publication." if changed == "1" else "inchangé : pas de publication."))


if __name__ == "__main__":
    main()
