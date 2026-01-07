from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/extract_h1")
def extract_h1():
    import re
    import traceback

    H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)

    def extract_h1_fast(html: str) -> str:
        m = H1_RE.search(html)
        if not m:
            return ""
        txt = re.sub(r"<[^>]+>", " ", m.group(1))
        txt = re.sub(r"\s+", " ", txt).strip()
        return txt

    try:
        data = request.get_json(silent=True) or {}
        urls = data.get("urls") or []
        if not isinstance(urls, list):
            return jsonify({"error": "urls must be a list"}), 400

        results = []
        session = requests.Session()
        headers = {"User-Agent": "Mozilla/5.0 (compatible; MedReviewsBot/1.0)"}

        import time
        DEADLINE = time.time() + 20  # עד 20 שניות לבקשה אחת

        for url in urls[:100]:
            if time.time() > DEADLINE:
                break

            u = str(url).strip()
            if not u:
                continue

            try:
                r = session.get(
                    u,
                    headers=headers,
                    timeout=(5, 8),
                    allow_redirects=True,
                    stream=True
                )
                r.raise_for_status()

                # קוראות רק את תחילת הדף כדי לחסוך זיכרון
                max_bytes = 400_000
                chunks = []
                read = 0
                for chunk in r.iter_content(chunk_size=16_384, decode_unicode=False):
                    if not chunk:
                        continue
                    chunks.append(chunk)
                    read += len(chunk)
                    if read >= max_bytes:
                        break

                r.close()

                enc = r.encoding or "utf-8"
                head_html = b"".join(chunks).decode(enc, errors="replace")

                h1 = extract_h1_fast(head_html)

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

    except Exception as e:
        print("extract_h1 crashed:", traceback.format_exc())
        return jsonify({"error": "extract_h1 crashed", "detail": str(e)}), 500



