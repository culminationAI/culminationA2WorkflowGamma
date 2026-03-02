#!/usr/bin/env python3
"""Free web search via DuckDuckGo HTML. No API key needed.

Usage:
    python3 web_search.py "query" [--limit 5]
"""
import argparse
import json
import re
from urllib.request import urlopen, Request
from urllib.parse import quote, unquote

def search(query: str, limit: int = 5) -> list[dict]:
    url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    resp = urlopen(req, timeout=15)
    html = resp.read().decode()
    
    results = []
    # Extract links
    links = re.findall(r'<a rel="nofollow" class="result__a" href="([^"]+)">(.+?)</a>', html)
    snippets = re.findall(r'<a class="result__snippet"[^>]*>(.+?)</a>', html)
    
    for i, (href, title) in enumerate(links[:limit]):
        title = re.sub(r'<[^>]+>', '', title).strip()
        # Extract actual URL from DDG redirect
        actual = re.search(r'uddg=([^&]+)', href)
        url = unquote(actual.group(1)) if actual else href
        snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip() if i < len(snippets) else ""
        results.append({"title": title, "url": url, "snippet": snippet})
    
    return results

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--limit", "-l", type=int, default=5)
    args = parser.parse_args()
    
    results = search(args.query, args.limit)
    print(json.dumps(results, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
