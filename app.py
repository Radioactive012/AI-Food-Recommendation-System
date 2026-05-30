import os
import csv
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from ml.similarity_model import RecommendationEngine
from models.models import db, User
import requests
import json

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

with app.app_context():
    db.create_all()

# Initialize Recommendation Engine
engine = RecommendationEngine()

# Lightweight representation of Food items matching the attributes of the database models
class FoodItem:
    def __init__(self, food_id, food_name, cuisine, category, calories, protein, carbs, fats, spice_level, veg_nonveg, price, meal_type, image_url, description):
        self.food_id = food_id
        self.food_name = food_name
        self.cuisine = cuisine
        self.category = category
        self.calories = int(calories)
        self.protein = float(protein)
        self.carbs = float(carbs)
        self.fats = float(fats)
        self.spice_level = spice_level
        self.veg_nonveg = veg_nonveg
        self.price = float(price)
        self.meal_type = meal_type
        self.image_url = image_url
        self.description = description

    def to_dict(self):
        return {
            'food_id': self.food_id,
            'food_name': self.food_name,
            'cuisine': self.cuisine,
            'category': self.category,
            'calories': self.calories,
            'protein': self.protein,
            'carbs': self.carbs,
            'fats': self.fats,
            'spice_level': self.spice_level,
            'veg_nonveg': self.veg_nonveg,
            'price': self.price,
            'meal_type': self.meal_type,
            'image_url': self.image_url,
            'description': self.description
        }

# Load foods from datasets/foods.csv
def load_foods():
    foods = []
    csv_path = os.path.join(app.root_path, 'datasets', 'foods.csv')
    if os.path.exists(csv_path):
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                foods.append(FoodItem(
                    food_id=row['food_id'],
                    food_name=row['food_name'],
                    cuisine=row['cuisine'],
                    category=row['category'],
                    calories=row['calories'],
                    protein=row['protein'],
                    carbs=row['carbs'],
                    fats=row['fats'],
                    spice_level=row['spice_level'],
                    veg_nonveg=row['veg_nonveg'],
                    price=row['price'],
                    meal_type=row.get('meal_type', 'Heavy'),
                    image_url=row.get('image_url', ''),
                    description=row.get('description', '')
                ))
    return foods

foods_list = load_foods()

# Context processor to expose common variables to templates (always evaluated to dummy/neutral values to avoid template crashes)
@app.context_processor
def inject_user():
    current_user = None
    user_id = session.get('user_id')
    if user_id:
        current_user = db.session.get(User, user_id)
    return dict(
        current_user=current_user,
        is_logged_in=current_user is not None
    )

# --- ROUTES ---

@app.route('/')
def index():
    # If the user has preferences saved in session, pass them.
    user_profile = session.get('preferences', {})
    return render_template(
        'index.html',
        user_profile=user_profile,
        featured_foods=foods_list[:3],
        active_page='home'
    )

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password, password):
            flash('Invalid email or password.', 'error')
            return render_template('login.html', active_page='login'), 401

        session['user_id'] = user.user_id
        session['preferences'] = {
            'diet_type': user.diet_type or 'Veg',
            'spice_preference': user.spice_preference or 'Medium',
            'health_goal': user.health_goal or 'Healthy Eating',
            'mood_preference': user.mood_preference or 'Neutral',
            'cuisine_preference': '',
            'budget': 500,
            'search_query': ''
        }
        flash(f'Welcome back, {user.name}.', 'success')
        return redirect(url_for('index'))

    return render_template('login.html', active_page='login')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not name or not email or len(password) < 6:
            flash('Please enter your name, email, and a password of at least 6 characters.', 'error')
            return render_template('register.html', active_page='login'), 400

        if User.query.filter_by(email=email).first():
            flash('An account with that email already exists. Please sign in.', 'error')
            return redirect(url_for('login'))

        def optional_int(value):
            try:
                return int(value) if value else None
            except ValueError:
                return None

        user = User(
            name=name,
            email=email,
            password=generate_password_hash(password, method='pbkdf2:sha256'),
            age=optional_int(request.form.get('age')),
            gender=request.form.get('gender') or None,
            diet_type=request.form.get('diet_type') or 'Veg',
            spice_preference=request.form.get('spice_preference') or 'Medium',
            health_goal=request.form.get('health_goal') or 'Healthy Eating',
            mood_preference=request.form.get('mood_preference') or 'Neutral'
        )
        db.session.add(user)
        db.session.commit()

        session['user_id'] = user.user_id
        session['preferences'] = {
            'diet_type': user.diet_type,
            'spice_preference': user.spice_preference,
            'health_goal': user.health_goal,
            'mood_preference': user.mood_preference,
            'cuisine_preference': '',
            'budget': 500,
            'search_query': ''
        }
        flash('Account created. Your taste profile is ready.', 'success')
        return redirect(url_for('index'))

    return render_template('register.html', active_page='login')

@app.route('/logout')
def logout():
    # Used as a "Reset Preferences & History" action
    session.clear()
    flash('Preferences and history reset successfully.', 'success')
    return redirect(url_for('index'))

@app.route('/recommendations', methods=['POST'])
def get_recommendation_results():
    # Extract preferences from request form
    cuisine = request.form.get('cuisine', '').strip()
    diet = request.form.get('diet', 'Veg')
    spice = request.form.get('spice', 'Medium')
    health_goal = request.form.get('health_goal', 'Healthy Eating')
    mood = request.form.get('mood', 'Neutral')

    try:
        budget = float(request.form.get('budget', 500))
    except Exception:
        budget = 500.0

    search_query = request.form.get('search_query', '').strip()

    # Save these as current preferences in session
    session['preferences'] = {
        'diet_type': diet,
        'spice_preference': spice,
        'health_goal': health_goal,
        'mood_preference': mood,
        'cuisine_preference': cuisine,
        'budget': budget,
        'search_query': search_query
    }

    # Fetch all foods
    all_foods = foods_list

    # Fetch rating history from session
    class SessionRating:
        def __init__(self, food_id, rating):
            self.food_id = food_id
            self.rating = rating

    user_ratings = [SessionRating(r['food_id'], r['rating']) for r in session.get('ratings', [])]

    # Construct user profile dictionary for the engine
    user_profile = {
        'diet_type': diet,
        'cuisine_preference': cuisine,
        'spice_preference': spice,
        'health_goal': health_goal,
        'mood_preference': mood,
        'budget': budget,
        'age': 25
    }

    # Filter foods by search query keywords first if present
    if search_query:
        query_words = search_query.lower().split()
        matched_foods = []
        for food in all_foods:
            text = f"{food.food_name} {food.cuisine} {food.description or ''}".lower()
            if any(word in text for word in query_words):
                matched_foods.append(food)
        if matched_foods:
            all_foods = matched_foods

    # Calculate Recommendations
    suggestions = engine.get_recommendations(
        user_profile=user_profile,
        all_foods=all_foods,
        rating_history=user_ratings,
        limit=6
    )

    # Log recommended foods to history in session
    if suggestions:
        history = session.get('history', [])
        for item in suggestions:
            # Avoid duplicates within history
            if not any(h['food_id'] == item['food'].food_id for h in history):
                history.append({
                    'food_id': item['food'].food_id,
                    'timestamp': datetime.now().isoformat()
                })
        session['history'] = history[-20:] # Keep last 20 entries
        session.modified = True

    return render_template(
        'recommendations.html',
        suggestions=suggestions,
        user_profile=session.get('preferences', {}),
        active_page='hitlist'
    )

@app.route('/history')
def history():
    history_items = []
    foods_dict = {f.food_id: f for f in foods_list}
    for item in session.get('history', []):
        food = foods_dict.get(item['food_id'])
        if food:
            try:
                dt = datetime.fromisoformat(item['timestamp'])
            except Exception:
                dt = datetime.now()

            class HistoryViewItem:
                def __init__(self, food, timestamp):
                    self.food = food
                    self.timestamp = timestamp
            history_items.append(HistoryViewItem(food, dt))

    history_items.sort(key=lambda x: x.timestamp, reverse=True)
    return render_template('history.html', history_items=history_items, active_page='history')

@app.route('/submit-rating', methods=['POST'])
def submit_rating():
    # Support both form data and JSON (for AJAX)
    if request.is_json:
        data = request.json
        food_id = data.get('food_id')
        rating_val = data.get('rating')
        review = data.get('review', '').strip()
    else:
        food_id = request.form.get('food_id')
        rating_val = request.form.get('rating')
        review = request.form.get('review', '').strip()

    if not food_id or not rating_val:
        if request.is_json:
            return jsonify({'status': 'error', 'message': 'Missing rating details.'}), 400
        flash('Missing rating details.', 'error')
        return redirect(url_for('index'))

    ratings = session.get('ratings', [])
    ratings.append({
        'food_id': food_id,
        'rating': int(rating_val),
        'review': review
    })
    session['ratings'] = ratings
    session.modified = True

    if request.is_json:
        return jsonify({'status': 'success', 'message': 'Thank you for rating!'})

    flash('Thank you for rating this recommendation!', 'success')
    return redirect(url_for('index'))

@app.route('/recommendation-direct')
def direct_food_info():
    food_id = request.args.get('food_id')
    food = next((f for f in foods_list if f.food_id == food_id), None)
    if not food:
        flash("Dish not found.", "error")
        return redirect(url_for('index'))

    # Log to history
    history = session.get('history', [])
    if not any(h['food_id'] == food.food_id for h in history):
        history.append({
            'food_id': food.food_id,
            'timestamp': datetime.now().isoformat()
        })
        session['history'] = history[-20:]
        session.modified = True

    dummy_item = {
        'food': food,
        'score': 15,
        'explanation': "Served directly from your assistant selection."
    }
    return render_template(
        'recommendations.html',
        suggestions=[dummy_item],
        user_profile=session.get('preferences', {}),
        active_page='hitlist'
    )

# --- ADMIN PANEL ---

@app.route('/admin')
def admin_dashboard():
    return render_template(
        'admin.html',
        foods=[food.to_dict() for food in foods_list],
        active_page='admin'
    )

@app.route('/admin/save', methods=['POST'])
def admin_save_food():
    flash('Admin additions/updates are disabled in database-free testing mode.', 'info')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete/<food_id>', methods=['POST'])
def admin_delete_food(food_id):
    flash('Admin deletions are disabled in database-free testing mode.', 'info')
    return redirect(url_for('admin_dashboard'))

# --- CHATBOT API ---

@app.route('/api/chat', methods=['POST'])
def chat_assistant():
    data = request.json or {}
    user_prompt = data.get('message', '').strip()

    if not user_prompt:
        return jsonify({'reply': 'Please say something so I can help!'})

    foods = foods_list
    gemini_key = app.config.get('GEMINI_API_KEY')
    if gemini_key:
        try:
            food_list = []
            for f in foods:
                food_list.append({
                    'id': f.food_id,
                    'name': f.food_name,
                    'cuisine': f.cuisine,
                    'category': f.category,
                    'price': f.price,
                    'veg': f.veg_nonveg,
                    'spice': f.spice_level,
                    'calories': f.calories,
                    'description': f.description
                })

            system_instruction = (
                "You are BiteWise, a friendly, expert AI Food Recommendation chatbot. "
                "The user will describe what they want to eat or ask questions. "
                "Here is the database catalog of available foods: " + json.dumps(food_list) + "\n"
                "If the user asks for food recommendations, analyze their taste preferences, budget, "
                "spice, and diet class from their prompt. Recommend 1 to 3 relevant foods from the catalog. "
                "IMPORTANT: For every food you recommend, you MUST include a clickable HTML link exactly in this format: "
                "<a href='/recommendation-direct?food_id=FOOD_ID' class='chat-food-link'>FOOD_NAME</a>. "
                "Detail the macros (calories, protein) and explain briefly why it matches their prompt. "
                "If the prompt is just a general greeting or nutrition questions, respond helpfully and briefly, "
                "suggesting they ask for a recommendation (e.g. 'I want a high protein lunch under ₹300')."
            )

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
            headers = {'Content-Type': 'application/json'}
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": system_instruction},
                            {"text": f"User prompt: {user_prompt}"}
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.3,
                    "maxOutputTokens": 400
                }
            }

            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            if resp.status_code == 200:
                result = resp.json()
                reply_text = result['candidates'][0]['content']['parts'][0]['text']
                return jsonify({'reply': reply_text})
        except Exception as e:
            print(f"Gemini API Exception: {e}")

    # FALLBACK
    prompt_lower = user_prompt.lower()
    diet_term = None
    if 'veg' in prompt_lower and 'non' not in prompt_lower:
        diet_term = 'Veg'
    elif 'non-veg' in prompt_lower or 'chicken' in prompt_lower or 'meat' in prompt_lower or 'fish' in prompt_lower:
        diet_term = 'Non-Veg'

    cuisine_term = None
    for c in ['indian', 'italian', 'chinese', 'american', 'japanese', 'mexican']:
        if c in prompt_lower:
            cuisine_term = c.capitalize()

    spice_term = None
    if 'spicy' in prompt_lower or 'hot' in prompt_lower or 'fire' in prompt_lower:
        spice_term = 'High'
    elif 'mild' in prompt_lower or 'bland' in prompt_lower or 'less spice' in prompt_lower:
        spice_term = 'Low'

    budget_term = None
    import re
    prices = re.findall(r'(?:under|below|rs\.?|₹)\s?(\d+)', prompt_lower)
    if prices:
        budget_term = float(prices[0])

    matches = []
    for f in foods:
        if diet_term and diet_term == 'Veg' and f.veg_nonveg != 'Veg':
            continue
        if cuisine_term and f.cuisine != cuisine_term:
            continue
        if spice_term and f.spice_level != spice_term:
            continue
        if budget_term and f.price > budget_term:
            continue
        matches.append(f)

    if not matches:
        scores = []
        for f in foods:
            score = 0
            text = f"{f.food_name} {f.cuisine} {f.veg_nonveg} {f.description or ''}".lower()
            for word in prompt_lower.split():
                if len(word) > 3 and word in text:
                    score += 1
            if score > 0:
                scores.append((score, f))
        scores.sort(key=lambda x: x[0], reverse=True)
        matches = [x[1] for x in scores[:3]]

    if matches:
        links = []
        for f in matches[:3]:
            links.append(
                f"• <a href='/recommendation-direct?food_id={f.food_id}' "
                f"class='chat-food-link'>{f.food_name}</a> "
                f"({f.cuisine}, ₹{int(f.price)}, {f.calories} kcal)"
            )
        reply = (
            f"Based on your request, I found some great suggestions from our database:<br><br>"
            + "<br>".join(links) +
            f"<br><br>Feel free to click on any dish to view its full details and macro profiles!"
        )
    else:
        reply = (
            "I couldn't find any specific dishes matching your exact tags. "
            "Try asking for something like: <em>'I want an Indian vegetarian dish under ₹300'</em>."
        )

    return jsonify({'reply': reply})

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', '').lower() in {'1', 'true', 'yes'}
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=debug_mode, port=port)
