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
      {
        "items": [
          {"id": 123, "text": "Hello world", "lang": "en"},
          ...
        ]
      }

    פלט:
      {
        "results": [
          {"id": 123, "ok": true, "he": "שלום עולם"},
          {"id": 124, "ok": false, "error": "..."}
        ]
      }
    """
    import traceback

    try:
        data = request.get_json(silent=True) or {}
        items = data.get("items") or []
        if not isinstance(items, list):
            return jsonify({"error": "items must be a list"}), 400

        # ניקוי בסיסי והגבלת גודל באצ'
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

        # מבקשות מהמודל להחזיר JSON בלבד
        instructions = (
            "You are a professional medical-content translator.\n"
            "Task: translate each input text to Hebrew (he).\n"
            "Rules:\n"
            "1) Return ONLY valid JSON, no prose.\n"
            "2) Keep brand/proper names as-is when appropriate.\n"
            "3) Preserve numbers and punctuation.\n"
            "4) Keep it concise, natural Hebrew.\n"
            "Output schema:\n"
            "{\n"
            '  "results": [\n'
            '    {"id": <id>, "he": "<hebrew translation>"}\n'
            "  ]\n"
            "}\n"
        )

        payload = {
            "items": cleaned
        }

        # מודל חסכוני לתרגום; אפשר לשנות ל-gpt-5 אם תרצי איכות מקסימלית
        resp = client.responses.create(
            model=os.getenv("OPENAI_TRANSLATE_MODEL", "gpt-5-mini"),
            reasoning={"effort": "low"},
            instructions=instructions,
            input=json.dumps(payload, ensure_ascii=False),
            max_output_tokens=1200
        )

        raw = resp.output_text or ""
        raw = raw.strip()

        # ניסיון פענוח JSON
        parsed = None
        try:
            parsed = json.loads(raw)
        except Exception:
            # ניסיון חילוץ JSON אם המודל עטף בטקסט (נדיר, אבל קורה)
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                parsed = json.loads(raw[start:end + 1])

        results_map = {}
        for row in (parsed or {}).get("results", []):
            try:
                results_map[row["id"]] = row.get("he", "")
            except Exception:
                continue

        out = []
        for it in cleaned:
            _id = it["id"]
            he = (results_map.get(_id) or "").strip()
            if he:
                out.append({"id": _id, "ok": True, "he": he})
            else:
                out.append({"id": _id, "ok": False, "error": "missing_translation_in_model_output"})

        return jsonify({"results": out})

    except Exception as e:
        print("translate_batch crashed:", traceback.format_exc())
        return jsonify({"error": "translate_batch crashed", "detail": str(e)}), 500
