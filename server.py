#!/usr/bin/env python3
"""
Truth Social Monitor — Deployable Server
"""

import os
import re
import sys
import html
import time
import threading
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import feedparser
import anthropic
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS

FEED_URL = "https://truthsocial.com/@realDonaldTrump.rss"
INTERVAL = 120
PORT     = int(os.environ.get("PORT", 5005))

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

posts_store = []
store_lock  = threading.Lock()
status      = {"last_check": None, "total_scanned": 0, "error": None}
keywords_ref = {"value": "gift, tariff, deal"}


def strip_html(raw):
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def analyze_with_claude(post_text, keywords):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "No ANTHROPIC_API_KEY set on server."
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=400,
            messages=[{"role": "user", "content":
                f"""You are a political economy analyst. Trump just posted on Truth Social matching these keywords: {keywords}.

Post: \"\"\"{post_text}\"\"\"

Respond with exactly 3 bullet points:
- SECTOR/TICKER: which sector or ticker(s) are relevant
- SIGNAL: bullish / bearish / neutral and the core reason  
- CONFIDENCE: low / medium / high + the single most important caveat

Speculative analysis only. Not financial advice."""
            }]
        )
        return msg.content[0].text.strip()
    except Exception as e:
        return f"Claude analysis failed: {e}"


def poll_feed():
    seen = set()
    while True:
        try:
            keywords = [k.strip() for k in keywords_ref["value"].split(",") if k.strip()]
            log(f"Polling feed... keywords: {keywords}")
            feed = feedparser.parse(FEED_URL)
            new_count = 0

            for entry in feed.entries:
                entry_id = entry.get("id") or entry.get("link") or str(time.time())
                if entry_id in seen:
                    continue
                seen.add(entry_id)
                new_count += 1
                status["total_scanned"] += 1

                raw = (
                    entry.get("summary") or
                    (entry.get("content") or [{}])[0].get("value", "") or
                    entry.get("title", "")
                )
                text = strip_html(raw)
                matched = [kw for kw in keywords if kw.lower() in text.lower()]
                analysis = None

                if matched:
                    log(f"  HIT — matched: {matched}")
                    analysis = analyze_with_claude(text, ", ".join(matched))

                post = {
                    "id":        entry_id,
                    "text":      text,
                    "published": entry.get("published", ""),
                    "link":      entry.get("link", ""),
                    "matched":   matched,
                    "analysis":  analysis,
                    "fetched_at": datetime.now().isoformat()
                }

                with store_lock:
                    posts_store.insert(0, post)
                    if len(posts_store) > 200:
                        posts_store.pop()

            status["last_check"] = datetime.now().isoformat()
            status["error"] = None
            log(f"  Done. New: {new_count}, total: {status['total_scanned']}")

        except Exception as e:
            status["error"] = str(e)
            log(f"  Error: {e}")

        time.sleep(INTERVAL)


@app.route("/posts")
def get_posts():
    with store_lock:
        return jsonify({
            "posts":         list(posts_store),
            "last_check":    status["last_check"],
            "total_scanned": status["total_scanned"],
            "error":         status["error"]
        })

@app.route("/status")
def get_status():
    return jsonify(status)

@app.route("/set_keywords/<path:keywords>")
def set_keywords(keywords):
    keywords_ref["value"] = keywords
    log(f"Keywords updated: {keywords}")
    return jsonify({"ok": True, "keywords": keywords})

@app.route("/")
def index():
    import os
    files = os.listdir(".")
    log(f"Current dir: {os.getcwd()}, files: {files}")
    return send_from_directory(".", "monitor.html")


if __name__ == "__main__":
    log(f"Starting server on port {PORT}")
    t = threading.Thread(target=poll_feed, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=PORT, debug=False)
