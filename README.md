# Urban Diner Food Recommendation System

A Flask college project that recommends dishes from a local food dataset based on cuisine, diet, spice level, health goal, mood, budget, and search text.

## Setup

1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the app:

```bash
python3 app.py
```

4. Open the site:

```text
http://127.0.0.1:8080
```

If port `8080` is busy, run with another port:

```bash
PORT=5099 python3 app.py
```

## Optional Environment Variables

The app works without these for local demos.

```text
SECRET_KEY=replace-with-a-local-secret
DATABASE_URL=sqlite:///food_recommendation.db
ADMIN_USERNAME=local-admin-name
ADMIN_PASSWORD=local-admin-password
OPENROUTER_API_KEY=optional-openrouter-api-key
OPENROUTER_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
OPENROUTER_SITE_URL=http://127.0.0.1:8080
OPENROUTER_TIMEOUT_SECONDS=55
ENABLE_DEV_OTP_RESET=1
```

Do not commit a real `.env` file. The repository ignores `.env`, local SQLite databases, virtual environments, and local zip archives.

## Notes

- Account creation and login use the local SQLite database created in the Flask `instance/` folder. New users are signed in immediately after registration.
- Password reset is disabled by default for production safety. Set `ENABLE_DEV_OTP_RESET=1` locally to enable the development reset-code helper; it is ignored on Vercel/production.
- Food inventory is stored in the configured database. Missing dishes from `datasets/foods.csv` are added on startup without overwriting existing admin edits.
- The chatbot uses OpenRouter when `OPENROUTER_API_KEY` is set, otherwise it uses the built-in fallback recommender. Free models can be slow or rate-limited, so `OPENROUTER_TIMEOUT_SECONDS` controls how long the app waits before falling back.
- Admin inventory add, update, and delete actions require `ADMIN_USERNAME` and `ADMIN_PASSWORD`.

## Tests

```bash
python3 -m unittest -v
```
