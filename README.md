# Truth Social Monitor

A web app that monitors Trump's Truth Social feed for keywords and uses Claude AI to analyze potential market signals.

## Deploy to Railway (free)

1. Go to [railway.app](https://railway.app) and sign up with GitHub
2. Click **New Project → Deploy from GitHub repo**
3. Upload this folder or push to a GitHub repo
4. Add environment variable: `ANTHROPIC_API_KEY=sk-ant-...`
5. Deploy — you'll get a public URL in ~2 minutes

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key from console.anthropic.com |

## Local Development

```bash
pip install -r requirements.txt
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
python server.py
```

Open http://localhost:5005

## Disclaimer

For research purposes only. Not financial advice.
