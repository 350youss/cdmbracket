#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agrège les dernières rumeurs mercato OM depuis des flux RSS publics
(foot-sur7.fr, mercatolive.fr, déjà filtrés OM par leurs propres
catégories/tags) -> data/rumeurs.json

Pas de scraping Twitter/X ici : l'API n'est plus accessible sans
abonnement payant et le scraping du site est contraire à ses CGU.
Les flux RSS de médias spécialisés OM sont la source la plus fiable
et la plus légale pour ce type d'agrégation automatique.

Best-effort : si un flux échoue ce passage, il est simplement ignoré
et l'ancien data/rumeurs.json est conservé si aucun flux ne répond.

Usage : python scripts/scrape_rumeurs.py
"""
import os, re, sys, json, hashlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "rumeurs.json")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

FEEDS = [
    {"url": "https://www.foot-sur7.fr/foot-marseille/feed", "source": "Foot Sur 7"},
    {"url": "https://mercatolive.fr/tag/om/feed", "source": "MercatoLive"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

MAX_ITEMS = 14


def strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def fetch_feed(feed):
    items = []
    try:
        r = requests.get(feed["url"], headers=HEADERS, timeout=15)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        for it in root.findall(".//item"):
            title_el = it.find("title")
            link_el = it.find("link")
            date_el = it.find("pubDate")
            if title_el is None or not (title_el.text or "").strip():
                continue
            title = strip_html(title_el.text)
            link = (link_el.text or "").strip() if link_el is not None else ""
            date_iso = None
            if date_el is not None and date_el.text:
                try:
                    date_iso = parsedate_to_datetime(date_el.text).astimezone(timezone.utc).isoformat()
                except Exception:
                    date_iso = None
            items.append({
                "title": title,
                "link": link,
                "source": feed["source"],
                "date": date_iso,
            })
    except Exception as e:
        print(f"  -> {feed['source']} indisponible ce passage ({e})")
    return items


def dedupe_key(title):
    norm = re.sub(r"[^a-z0-9]+", "", title.lower())
    return hashlib.md5(norm.encode("utf-8")).hexdigest()


def main():
    all_items = []
    for feed in FEEDS:
        got = fetch_feed(feed)
        print(f"{feed['source']}: {len(got)} article(s)")
        all_items.extend(got)

    if not all_items:
        print("Aucun flux disponible ce passage, data/rumeurs.json conservé tel quel.")
        return

    seen = set()
    deduped = []
    for it in all_items:
        key = dedupe_key(it["title"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)

    deduped.sort(key=lambda it: it["date"] or "", reverse=True)
    deduped = deduped[:MAX_ITEMS]

    out = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "items": deduped,
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n{len(deduped)} rumeur(s) écrite(s) -> {OUT}")


if __name__ == "__main__":
    main()
