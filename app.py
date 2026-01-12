from flask import Flask, request, jsonify
import requests
import os
import json

from openai import OpenAI

app = Flask(__name__)
client = OpenAI()  # קורא OPENAI_API_KEY מה-ENV

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

@app.post("/translate_batch")
def translate_batch():
    """
    קלט:
      {"items":[{"id":123,"text":"...","lang":"en"}, ...]}

    פלט:
      {"results":[{"id":123,"ok":true,"he":"..."}, ...]}
    """
    import traceback

    try:
        data = request.get_json(silent=True) or {}
        items = data.get("items") or []
        if not isinstance(items, list):
            return jsonify({"error": "items must be a list"}), 400

        cleaned = []
        for it in items[:100]:
            if not isinstance(it, dict):
                continue
            _id = it.get("id")
            txt = (it.get("text") or "").strip()
            lang = (it.get("lang") or "").strip()
            if _id is None or not txt:
                continue
            cleaned.append({"id": _id, "text": txt, "lang": lang})

        if not cleaned:
            return jsonify({"results": []})

        # פרומפט קצר וברור, המודל מחויב ל-JSON דרך text.format
        instructions = (
            "Translate each item.text into Hebrew.\n"
            "Return ONLY JSON with this schema:\n"
            '{ "results": [ { "id": <id>, "he": "<translation>" } ] }\n'
            "Keep names/brands as-is when appropriate. Preserve numbers and punctuation.\n"
            "Return a valid JSON object only."
        )

        resp = client.responses.create(
            model=os.getenv("OPENAI_TRANSLATE_MODEL", "gpt-4o-mini"),
            reasoning={"effort": "low"},
            instructions=instructions,
            input=json.dumps({"items": cleaned}, ensure_ascii=False),
            text={"format": {"type": "json_object"}},
            max_output_tokens=1500
        )

        raw = (resp.output_text or "").strip()

        # לעולם לא להפיל 500 בגלל JSON לא תקין
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {}

        results_list = (parsed.get("results") if isinstance(parsed, dict) else None) or []
        results_map = {}
        for row in results_list:
            if isinstance(row, dict) and "id" in row:
                results_map[row["id"]] = (row.get("he") or "").strip()

        out = []
        for it in cleaned:
            _id = it["id"]
            he = results_map.get(_id, "")
            if he:
                out.append({"id": _id, "ok": True, "he": he})
            else:
                out.append({"id": _id, "ok": False, "error": "missing_or_unparsed_translation"})

        return jsonify({"results": out})

    except Exception as e:
        print("translate_batch crashed:", traceback.format_exc())
        return jsonify({"error": "translate_batch crashed", "detail": str(e)}), 500



