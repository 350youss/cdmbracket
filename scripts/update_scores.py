"""
Fetch completed WC 2026 group stage matches from football-data.org
and update the LOCKED block in index.html automatically.

Requires: FOOTBALL_API_KEY env var (free key from football-data.org)
"""

import os
import re
import sys
import requests

# ── Team name mapping: API names → French names in simulator ──
TEAM_MAP = {
    'Mexico': 'Mexique',
    'South Africa': 'Afrique du Sud',
    'Korea Republic': 'Corée du Sud',
    'South Korea': 'Corée du Sud',
    'Republic of Korea': 'Corée du Sud',
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
    'Democratic Republic of Congo': 'RD Congo',
    'Congo DR': 'RD Congo',
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


def get_pairs(teams):
    """Réplique la fonction pairs() du simulateur."""
    result = []
    for i in range(len(teams) - 1):
        for j in range(i + 1, len(teams)):
            result.append((teams[i], teams[j]))
    return result


def find_pair(teams, team_a, team_b):
    """Retourne (index, flipped) — flipped=True si l'ordre API est inversé."""
    for idx, (a, b) in enumerate(get_pairs(teams)):
        if a == team_a and b == team_b:
            return idx, False
        if a == team_b and b == team_a:
            return idx, True
    return None, None


def parse_group_id(match):
    """Extrait la lettre du groupe depuis le champ 'group' de l'API."""
    raw = match.get('group') or ''
    # Formats possibles: "GROUP_A", "Group A", "A"
    cleaned = raw.upper().replace('GROUP_', '').replace('GROUP ', '').strip()
    if cleaned and cleaned[-1].isalpha():
        return cleaned[-1]
    return None


def fetch_finished_matches(api_key):
    url = 'https://api.football-data.org/v4/competitions/WC/matches'
    headers = {'X-Auth-Token': api_key}
    resp = requests.get(url, headers=headers, params={'status': 'FINISHED'}, timeout=15)
    resp.raise_for_status()
    return resp.json().get('matches', [])


def build_locked(matches):
    """Construit le dict {group_id: {pair_idx: (a, b)}} depuis les matchs terminés."""
    locked = {}
    for match in matches:
        # Ne traiter que la phase de groupes
        stage = match.get('stage', '')
        if 'GROUP' not in stage.upper():
            continue

        home_raw = match['homeTeam']['name']
        away_raw = match['awayTeam']['name']
        home = TEAM_MAP.get(home_raw, home_raw)
        away = TEAM_MAP.get(away_raw, away_raw)

        score = match.get('score', {}).get('fullTime', {})
        home_score = score.get('home')
        away_score = score.get('away')
        if home_score is None or away_score is None:
            continue

        gid = parse_group_id(match)
        if not gid or gid not in GROUPS:
            print(f'  ⚠ Groupe inconnu pour {home} vs {away} (raw group: {match.get("group")})')
            continue

        idx, flipped = find_pair(GROUPS[gid], home, away)
        if idx is None:
            print(f'  ⚠ Paire introuvable : {home} vs {away} dans Groupe {gid}')
            continue

        a, b = (away_score, home_score) if flipped else (home_score, away_score)
        locked.setdefault(gid, {})[idx] = (a, b)
        print(f'  ✓ Groupe {gid} idx={idx} : {home} {a}-{b} {away}')

    return locked


def generate_scores_block(locked):
    """Génère le bloc JS à injecter entre les marqueurs SCORES_START/END."""
    lines = ['// ── SCORES_START ──']

    if not locked:
        lines.append('var LOCKED = {};')
    else:
        # var LOCKED = { 'A': [0, 5], ... };
        locked_parts = []
        for gid in sorted(locked):
            idxs = sorted(locked[gid].keys())
            locked_parts.append(f"'{gid}': [{', '.join(str(i) for i in idxs)}]")
        lines.append('var LOCKED = { ' + ', '.join(locked_parts) + ' };')

        # RES lines
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

    total = sum(len(m) for m in locked.values())
    print(f'index.html mis à jour — {total} match(s) verrouillé(s).')
    return True


if __name__ == '__main__':
    import pathlib

    api_key = os.environ.get('FOOTBALL_API_KEY', '')
    if not api_key:
        print('ERREUR : variable FOOTBALL_API_KEY manquante.', file=sys.stderr)
        sys.exit(1)

    html_path = pathlib.Path(__file__).parent.parent / 'index.html'

    print('Récupération des matchs terminés...')
    matches = fetch_finished_matches(api_key)
    print(f'{len(matches)} match(s) terminé(s) trouvé(s).')

    locked = build_locked(matches)
    print(f'Groupes avec résultats : {sorted(locked.keys()) or "aucun"}')

    update_html(str(html_path), locked)
