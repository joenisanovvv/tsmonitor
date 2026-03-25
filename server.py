#!/usr/bin/env python3
"""
Truth Social Monitor — Deployable Server with Email Alerts
"""

import os
import re
import sys
import html
import time
import threading
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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
PORT     = int(os.environ.get("PORT", 8080))

# Email config — set these as Railway environment variables
GMAIL_USER     = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS", "")
ALERT_EMAIL    = os.environ.get("ALERT_EMAIL", "")

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

posts_store  = []
store_lock   = threading.Lock()
status       = {"last_check": None, "total_scanned": 0, "error": None}
keywords_ref = {"value": "gift, tariff, deal"}


def strip_html(raw):
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def send_email_alert(post_text, keywords, analysis, link):
    if not GMAIL_USER or not GMAIL_APP_PASS or not ALERT_EMAIL:
        log("Email not configured — skipping alert.")
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"⚑ Truth Social Alert: '{keywords}' detected"
        msg["From"]    = GMAIL_USER
        msg["To"]      = ALERT_EMAIL

        plain = f"""KEYWORD DETECTED: {keywords}

POST:
{post_text}

LINK: {link or 'n/a'}

CLAUDE MARKET ANALYSIS:
{analysis}

---
For research purposes only. Not financial advice.
"""
        html_body = f"""
<html><body style="font-family:sans-serif;max-width:600px;margin:auto;padding:20px;">
  <div style="background:#ff444422;border:1px solid #ff444444;border-radius:8px;padding:16px 20px;margin-bottom:20px;">
    <strong style="color:#ff4444;font-size:16px;">⚑ KEYWORD DETECTED: {keywords}</strong>
  </div>
  <div style="background:#111;border-radius:8px;padding:16px 20px;margin-bottom:20px;">
    <p style="color:#ccc;line-height:1.7;margin:0;">{post_text}</p>
    {('<p style="margin-top:10px;"><a href="' + link + '" style="color:#00d4aa;">View on Truth Social →</a></p>') if link else ''}
  </div>
  <div style="background:#161616;border:1px solid #2a2a2a;border-radius:8px;padding:16px 20px;margin-bottom:20px;">
    <p style="color:#c8f135;font-size:11px;letter-spacing:2px;margin:0 0 10px;">CLAUDE MARKET ANALYSIS</p>
    <p style="color:#bbb;line-height:1.8;margin:0;white-space:pre-line;">{analysis}</p>
  </div>
  <p style="color:#555;font-size:12px;">For research purposes only. Not financial advice.</p>
</body></html>
"""
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASS)
            server.sendmail(GMAIL_USER, ALERT_EMAIL, msg.as_string())

        log(f"  Email alert sent to {ALERT_EMAIL}")
    except Exception as e:
        log(f"  Email failed: {e}")


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
                text     = strip_html(raw)
                matched  = [kw for kw in keywords if kw.lower() in text.lower()]
                analysis = None
                link     = entry.get("link", "")

                if matched:
                    log(f"  HIT — matched: {matched}")
                    analysis = analyze_with_claude(text, ", ".join(matched))
                    send_email_alert(text, ", ".join(matched), analysis, link)

                post = {
                    "id":        entry_id,
                    "text":      text,
                    "published": entry.get("published", ""),
                    "link":      link,
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

@app.route("/analyze", methods=["POST"])
def analyze_route():
    data     = request.get_json()
    post_text = data.get("text", "")
    keywords  = data.get("keywords", "")
    result    = analyze_with_claude(post_text, keywords)
    return jsonify({"analysis": result})

@app.route("/set_keywords/<path:keywords>")
def set_keywords(keywords):
    keywords_ref["value"] = keywords
    log(f"Keywords updated: {keywords}")
    return jsonify({"ok": True, "keywords": keywords})

@app.route("/")
def index():
    return send_from_directory(".", "monitor.html")


# Start polling thread when gunicorn imports this module
t = threading.Thread(target=poll_feed, daemon=True)
t.start()

if __name__ == "__main__":
    log(f"Starting server on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
