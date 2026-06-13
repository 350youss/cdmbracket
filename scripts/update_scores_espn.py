"""
Fetch WC 2026 group stage results from ESPN public API (no key needed)
and update the LOCKED block in index.html.

ESPN endpoint: https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard
"""

import re
import sys
import pathlib
import requests
from datetime import datetime, timezone, timedelta

# ── Team name mapping: ESPN names → French names in simulator ──
TEAM_MAP = {
    'Mexico': 'Mexique',
    'South Africa': 'Afrique du Sud',
    'Korea Republic': 'Corée du Sud',
    'South Korea': 'Corée du Sud',
    'Czech Republic': 'Tchéquie',
    'Czechia': 'Tchéquie',
    'Switzerland': 'Suisse',
    'Canada': 'Canada',
    'Bosnia and Herzegovina': 'Bosnie-H.',
    'Bosnia & Herzegovina': 'Bosnie-H.',
    'Qatar': 'Qatar',
    'Brazil': 'Brésil',
    'Morocco': 'Maroc',
    'Scotland': 'Écosse',
    'Haiti': 'Haïti',
    'United States': 'USA',
    'USA': 'USA',
    'Turkey': 'Turquie',
    'Türkiye': 'Turquie',
    'Australia': 'Australie',
    'Paraguay': 'Paraguay',
    'Germany': 'Allemagne',
    'Ecuador': 'Équateur',
    "Côte d'Ivoire": "Côte d'Ivoire",
    'Ivory Coast': "Côte d'Ivoire",
    'Curaçao': 'Curaçao',
    'Curacao': 'Curaçao',
    'Netherlands': 'Pays-Bas',
    'Japan': 'Japon',
    'Sweden': 'Suède',
    'Tunisia': 'Tunisie',
    'Belgium': 'Belgique',
    'Egypt': 'Égypte',
    'Iran': 'Iran',
    'New Zealand': 'Nouvelle-Zélande',
    'Spain': 'Espagne',
    'Uruguay': 'Uruguay',
    'Saudi Arabia': 'Arabie Saoudite',
    'Cape Verde': 'Cap-Vert',
    'France': 'France',
    'Senegal': 'Sénégal',
    'Norway': 'Norvège',
    'Iraq': 'Irak',
    'Argentina': 'Argentine',
    'Algeria': 'Algérie',
    'Austria': 'Autriche',
    'Jordan': 'Jordanie',
    'Portugal': 'Portugal',
    'Colombia': 'Colombie',
    'DR Congo': 'RD Congo',
    'Congo, DR': 'RD Congo',
    'Democratic Republic of Congo': 'RD Congo',
    'Uzbekistan': 'Ouzbékistan',
    'England': 'Angleterre',
    'Croatia': 'Croatie',
    'Ghana': 'Ghana',
    'Panama': 'Panama',
}

# Groups — même ordre que le simulateur
GROUPS = {
    'A': ['Mexique', 'Afrique du Sud', 'Corée du Sud', 'Tchéquie'],
    'B': ['Suisse', 'Canada', 'Bosnie-H.', 'Qatar'],
    'C': ['Brésil', 'Maroc', 'Écosse', 'Haïti'],
    'D': ['USA', 'Turquie', 'Australie', 'Paraguay'],
    'E': ['Allemagne', 'Équateur', "Côte d'Ivoire", 'Curaçao'],
    'F': ['Pays-Bas', 'Japon', 'Suède', 'Tunisie'],
    'G': ['Belgique', 'Égypte', 'Iran', 'Nouvelle-Zélande'],
    'H': ['Espagne', 'Uruguay', 'Arabie Saoudite', 'Cap-Vert'],
    'I': ['France', 'Sénégal', 'Norvège', 'Irak'],
    'J': ['Argentine', 'Algérie', 'Autriche', 'Jordanie'],
    'K': ['Portugal', 'Colombie', 'RD Congo', 'Ouzbékistan'],
    'L': ['Angleterre', 'Croatie', 'Ghana', 'Panama'],
}

# Lookup: French team name → group letter
TEAM_TO_GROUP = {team: g for g, teams in GROUPS.items() for team in teams}


def get_pairs(teams):
    result = []
    for i in range(len(teams) - 1):
        for j in range(i + 1, len(teams)):
            result.append((teams[i], teams[j]))
    return result


def find_pair(teams, team_a, team_b):
    for idx, (a, b) in enumerate(get_pairs(teams)):
        if a == team_a and b == team_b:
            return idx, False
        if a == team_b and b == team_a:
            return idx, True
    return None, None


FINISHED_STATUSES = {'STATUS_FINAL', 'STATUS_FULL_TIME', 'STATUS_FT', 'FINISHED'}

# Slugs ESPN à essayer dans l'ordre
ESPN_SLUGS = ['fifa.world', 'fifa.world-cup', 'FIFA.World']


def fetch_scoreboard(slug, date_str):
    url = f'https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard'
    resp = requests.get(url, params={'dates': date_str}, timeout=10)
    if not resp.ok:
        return None
    data = resp.json()
    events = data.get('events', [])
    if events:
        print(f'  ESPN slug "{slug}" date {date_str} → {len(events)} event(s)')
    return events


def parse_events(events, date_str, finished):
    for event in events:
        comps = event.get('competitions', [])
        for comp in comps:
            status_name = comp.get('status', {}).get('type', {}).get('name', '')
            status_desc = comp.get('status', {}).get('type', {}).get('description', '')
            competitors = comp.get('competitors', [])
            if len(competitors) != 2:
                continue
            home = next((c for c in competitors if c.get('homeAway') == 'home'), None)
            away = next((c for c in competitors if c.get('homeAway') == 'away'), None)
            if not home or not away:
                continue
            home_name = home.get('team', {}).get('displayName', '')
            away_name = away.get('team', {}).get('displayName', '')
            home_score = home.get('score')
            away_score = away.get('score')
            if home_score is None or away_score is None:
                continue
            is_finished = (status_name in FINISHED_STATUSES
                           or status_desc.upper() in FINISHED_STATUSES
                           or 'FINAL' in status_name.upper()
                           or 'FULL' in status_name.upper())
            if not is_finished:
                print(f'    (en cours / pas terminé : {status_name} | {home_name} vs {away_name})')
                continue
            # Dédoublonnage
            key = (home_name, away_name)
            if any(m['home'] == home_name and m['away'] == away_name for m in finished):
                continue
            finished.append({
                'home': home_name,
                'away': away_name,
                'home_score': int(home_score),
                'away_score': int(away_score),
                'date': date_str,
            })


def fetch_espn_matches():
    """Itère sur les dates de la phase de groupes et récupère les matchs terminés."""
    finished = []

    # WC 2026 group stage: June 11 – July 2, 2026
    start    = datetime(2026, 6, 11, tzinfo=timezone.utc)
    end      = datetime(2026, 7, 3, tzinfo=timezone.utc)
    scan_end = min(end, datetime.now(timezone.utc) + timedelta(days=1))

    current = start
    while current <= scan_end:
        date_str = current.strftime('%Y%m%d')
        for slug in ESPN_SLUGS:
            try:
                events = fetch_scoreboard(slug, date_str)
                if events:
                    parse_events(events, date_str, finished)
                    break  # slug trouvé pour cette date
            except Exception as e:
                print(f'  ⚠ {slug} {date_str}: {e}')
        current += timedelta(days=1)

    return finished


def build_locked(matches):
    locked = {}
    for m in matches:
        home = TEAM_MAP.get(m['home'], m['home'])
        away = TEAM_MAP.get(m['away'], m['away'])
        gid = TEAM_TO_GROUP.get(home) or TEAM_TO_GROUP.get(away)
        if not gid:
            print(f'  ⚠ Groupe introuvable : {home} vs {away}')
            continue
        idx, flipped = find_pair(GROUPS[gid], home, away)
        if idx is None:
            print(f'  ⚠ Paire introuvable : {home} vs {away} dans Groupe {gid}')
            continue
        a = m['away_score'] if flipped else m['home_score']
        b = m['home_score'] if flipped else m['away_score']
        locked.setdefault(gid, {})[idx] = (a, b)
        print(f'  ✓ Groupe {gid} idx={idx} : {GROUPS[gid][0 if not flipped else 1]} {a}-{b} ...')
    return locked


def generate_scores_block(locked):
    lines = ['// ── SCORES_START ──']
    if not locked:
        lines.append('var LOCKED = {};')
    else:
        locked_parts = []
        for gid in sorted(locked):
            idxs = sorted(locked[gid].keys())
            locked_parts.append(f"'{gid}': [{', '.join(str(i) for i in idxs)}]")
        lines.append('var LOCKED = { ' + ', '.join(locked_parts) + ' };')
        for gid in sorted(locked):
            pairs = get_pairs(GROUPS[gid])
            for idx in sorted(locked[gid]):
                a, b = locked[gid][idx]
                ta, tb = pairs[idx]
                lines.append(f"RES['{gid}'][{idx}] = {{a:{a}, b:{b}}}; // {ta} {a}-{b} {tb}")
    lines.append('// ── SCORES_END ──')
    return '\n'.join(lines)


def update_html(html_path, locked):
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()
    new_block = generate_scores_block(locked)
    pattern = r'// ── SCORES_START ──.*?// ── SCORES_END ──'
    new_content = re.sub(pattern, new_block, content, flags=re.DOTALL)
    if new_content == content:
        print('Aucun changement.')
        return False
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    total = sum(len(v) for v in locked.values())
    print(f'index.html mis à jour — {total} match(s) verrouillé(s).')
    return True


if __name__ == '__main__':
    html_path = pathlib.Path(__file__).parent.parent / 'index.html'
    print('Récupération des matchs terminés (ESPN)...')
    matches = fetch_espn_matches()
    print(f'{len(matches)} match(s) terminé(s) trouvé(s).')
    for m in matches:
        print(f"  {m['date']} {m['home']} {m['home_score']}-{m['away_score']} {m['away']}")

    if not matches:
        print('⚠ Aucun match trouvé — index.html NON modifié (protection contre écrasement).')
        sys.exit(0)

    locked = build_locked(matches)
    print(f'Groupes avec résultats : {sorted(locked.keys()) or "aucun"}')

    if not locked:
        print('⚠ Aucun match mappé — index.html NON modifié.')
        sys.exit(0)

    update_html(str(html_path), locked)
