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
GEMINI_API_KEY=optional-gemini-api-key
```

Do not commit a real `.env` file. The repository ignores `.env`, local SQLite databases, virtual environments, and local zip archives.

## Notes

- Account creation and login use the local SQLite database created in the Flask `instance/` folder.
- Food recommendations are loaded from `datasets/foods.csv`.
- The chatbot works without a Gemini key by using the built-in fallback recommender.
- Admin add, update, and delete actions are currently disabled in database-free testing mode.

## Tests

```bash
python3 -m unittest -v
```
