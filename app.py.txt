from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/extract_h1")
def extract_h1():
    data = request.get_json(silent=True) or {}
    urls = data.get("urls") or []
    if not isinstance(urls, list):
        return jsonify({"error": "urls must be a list"}), 400

    results = []
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MedReviewsBot/1.0)"
    }

    for url in urls[:100]:  # הגנה בסיסית
        u = str(url).strip()
        if not u:
            continue

        try:
            r = session.get(u, headers=headers, timeout=20, allow_redirects=True)
            r.raise_for_status()

            soup = BeautifulSoup(r.text, "html.parser")
            h1_tag = soup.find("h1")
            h1 = h1_tag.get_text(" ", strip=True) if h1_tag else ""

            results.append({
                "url": u,
                "ok": True,
                "status_code": r.status_code,
                "h1_raw": h1
            })
        except Exception as e:
            results.append({
                "url": u,
                "ok": False,
                "error": str(e)
            })

    return jsonify({"results": results})
