# Kalshi Sports +EV Scanner

Streamlit app (`streamlit_app.py` + `matching.py`) that compares Kalshi game-winner prices to the devigged sportsbook
consensus (The Odds API) and flags +EV contracts net of Kalshi fees, with fractional-Kelly sizing.

## Run locally
```
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # add your key
streamlit run streamlit_app.py
```

## Deploy
1. Push this repo to GitHub (`secrets.toml` is git-ignored; never commit your key).
2. Go to share.streamlit.io, click **Create app**, pick the repo, branch `main`, main file `streamlit_app.py`.
3. **Advanced settings → Secrets**, paste: `ODDS_API_KEY = "your_key"`
4. Deploy.

Free Odds API tier is 500 credits/month; the app caches sportsbook data for 5 minutes.
Read-only: places no orders. Not financial advice.
