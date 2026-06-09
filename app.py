import os
import re
import concurrent.futures
from functools import wraps
from datetime import datetime
from urllib.parse import urlsplit
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from database.db_manager import init_db
from ml.similarity_model import RecommendationEngine
from models.models import db, User, Food
import requests
import json

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

init_db(app)

# Initialize Recommendation Engine
engine = RecommendationEngine()
openrouter_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

SEARCH_ALIASES = {
    'veg': {'veg', 'vegetarian'},
    'vegetarian': {'veg', 'vegetarian'},
    'nonveg': {'non-veg', 'non veg', 'nonvegetarian', 'non vegetarian', 'chicken', 'meat', 'fish', 'tuna'},
    'non-veg': {'non-veg', 'non veg', 'nonvegetarian', 'non vegetarian', 'chicken', 'meat', 'fish', 'tuna'},
    'non': {'non-veg', 'non veg', 'nonvegetarian', 'non vegetarian'},
    'spicy': {'high spice', 'spicy', 'hot', 'schezwan'},
    'hot': {'high spice', 'spicy', 'hot'},
    'mild': {'low spice', 'mild', 'low'},
    'protein': {'protein', 'high protein'},
    'healthy': {'healthy', 'clean', 'salad', 'light', 'wholesome'},
    'breakfast': {'breakfast'},
    'lunch': {'lunch'},
    'dinner': {'dinner'},
    'snack': {'snack', 'snacks'},
}


def get_foods():
    return Food.query.order_by(Food.food_name.asc()).all()


def get_food(food_id):
    if not food_id:
        return None
    return db.session.get(Food, food_id)


def add_to_history(food_id):
    history = session.get('history', [])
    existing = next((item for item in history if item.get('food_id') == food_id), None)
    if existing:
        existing['timestamp'] = datetime.now().isoformat()
    else:
        history.append({'food_id': food_id, 'timestamp': datetime.now().isoformat()})
    session['history'] = history[-20:]
    session.modified = True


def admin_credentials_configured():
    return bool(os.environ.get('ADMIN_USERNAME') and os.environ.get('ADMIN_PASSWORD'))


def admin_is_logged_in():
    return session.get('admin_logged_in') is True


def require_admin(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not admin_credentials_configured():
            flash('Set ADMIN_USERNAME and ADMIN_PASSWORD to enable inventory management.', 'error')
            return redirect(url_for('admin_login'))
        if not admin_is_logged_in():
            flash('Please sign in as admin to manage inventory.', 'error')
            return redirect(url_for('admin_login', next=request.path))
        return view_func(*args, **kwargs)
    return wrapper


def safe_redirect_target(target):
    if not target:
        return None

    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return None
    if not parts.path.startswith('/'):
        return None
    if target.startswith('//'):
        return None
    return target


def normalize_search_terms(search_query):
    phrases = re.findall(r'[a-z0-9]+(?:[-\s][a-z0-9]+)?', search_query.lower())
    terms = []
    skip_next = False
    words = re.findall(r'[a-z0-9]+', search_query.lower())
    for index, word in enumerate(words):
        if skip_next:
            skip_next = False
            continue
        if word == 'non' and index + 1 < len(words) and words[index + 1] in {'veg', 'vegetarian'}:
            terms.append('nonveg')
            skip_next = True
        else:
            terms.append(word)
    for phrase in phrases:
        collapsed = phrase.replace(' ', '').replace('-', '')
        if collapsed == 'nonveg' and 'nonveg' not in terms:
            terms.append('nonveg')
    return [term for term in terms if len(term) > 1]


def searchable_food_text(food):
    macro_tags = []
    if food.protein >= 15:
        macro_tags.extend(['protein', 'high protein'])
    if food.calories <= 300:
        macro_tags.extend(['light', 'low calorie'])
    if food.calories >= 500:
        macro_tags.append('heavy')

    parts = [
        food.food_name,
        food.cuisine,
        food.category,
        food.meal_type or '',
        food.veg_nonveg,
        food.spice_level,
        f'{food.spice_level} spice',
        food.description or '',
        *macro_tags,
    ]
    if food.veg_nonveg == 'Veg':
        parts.extend(['veg', 'vegetarian'])
    elif food.veg_nonveg == 'Non-Veg':
        parts.extend(['non-veg', 'non veg', 'nonvegetarian'])
    if food.spice_level == 'High':
        parts.extend(['spicy', 'hot'])
    elif food.spice_level == 'Low':
        parts.append('mild')
    return ' '.join(str(part).lower() for part in parts)


def food_matches_search(food, search_query):
    terms = normalize_search_terms(search_query)
    if not terms:
        return True
    text = searchable_food_text(food)
    for term in terms:
        if term in {'veg', 'vegetarian'}:
            if food.veg_nonveg != 'Veg':
                return False
            continue
        if term in {'nonveg', 'non-veg', 'non'}:
            if food.veg_nonveg != 'Non-Veg':
                return False
            continue
        if term in {'spicy', 'hot'}:
            if food.spice_level != 'High' and not any(alias in text for alias in SEARCH_ALIASES[term]):
                return False
            continue
        if term == 'mild':
            if food.spice_level != 'Low' and not any(alias in text for alias in SEARCH_ALIASES[term]):
                return False
            continue
        aliases = SEARCH_ALIASES.get(term, {term})
        if not any(alias in text for alias in aliases):
            return False
    return True

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
    foods = get_foods()
    return render_template(
        'index.html',
        user_profile=user_profile,
        featured_foods=foods[:3],
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

    # Fetch all foods from the current database inventory.
    all_foods = get_foods()

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

    # Strict search: if a query is present, only query matches continue.
    if search_query:
        all_foods = [food for food in all_foods if food_matches_search(food, search_query)]

    # Calculate Recommendations
    suggestions = engine.get_recommendations(
        user_profile=user_profile,
        all_foods=all_foods,
        rating_history=user_ratings,
        limit=6
    )

    return render_template(
        'recommendations.html',
        suggestions=suggestions,
        user_profile=session.get('preferences', {}),
        active_page='hitlist'
    )

@app.route('/history')
def history():
    history_items = []
    foods_dict = {f.food_id: f for f in get_foods()}
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

    try:
        rating_int = int(rating_val)
    except (TypeError, ValueError):
        rating_int = None

    food = get_food(food_id)

    if not food_id or rating_int is None or not 1 <= rating_int <= 5 or not food:
        if request.is_json:
            return jsonify({'status': 'error', 'message': 'Please submit a valid 1-5 rating for an existing dish.'}), 400
        flash('Please submit a valid 1-5 rating for an existing dish.', 'error')
        return redirect(url_for('index'))

    ratings = session.get('ratings', [])
    ratings.append({
        'food_id': food_id,
        'rating': rating_int,
        'review': review
    })
    session['ratings'] = ratings
    add_to_history(food_id)
    session.modified = True

    if request.is_json:
        return jsonify({'status': 'success', 'message': 'Thank you for rating!'})

    flash('Thank you for rating this recommendation!', 'success')
    return redirect(url_for('index'))

@app.route('/recommendation-direct')
def direct_food_info():
    food_id = request.args.get('food_id')
    food = get_food(food_id)
    if not food:
        flash("Dish not found.", "error")
        return redirect(url_for('index'))

    add_to_history(food.food_id)

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

@app.route('/save-food', methods=['POST'])
def save_food():
    if request.is_json:
        data = request.json or {}
        food_id = data.get('food_id')
    else:
        food_id = request.form.get('food_id')

    food = get_food(food_id)
    if not food:
        if request.is_json:
            return jsonify({'status': 'error', 'message': 'Dish not found.'}), 404
        flash('Dish not found.', 'error')
        return redirect(url_for('index'))

    add_to_history(food.food_id)
    if request.is_json:
        return jsonify({'status': 'success', 'message': 'Saved to your hitlist.'})
    flash('Saved to your hitlist.', 'success')
    return redirect(url_for('history'))


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if not admin_credentials_configured():
        return render_template(
            'admin_login.html',
            active_page='admin',
            setup_missing=True
        ), 503

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if username == os.environ.get('ADMIN_USERNAME') and password == os.environ.get('ADMIN_PASSWORD'):
            session['admin_logged_in'] = True
            flash('Admin signed in.', 'success')
            return redirect(safe_redirect_target(request.args.get('next')) or url_for('admin_dashboard'))

        flash('Invalid admin credentials.', 'error')
        return render_template('admin_login.html', active_page='admin', setup_missing=False), 401

    return render_template('admin_login.html', active_page='admin', setup_missing=False)


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    flash('Admin signed out.', 'success')
    return redirect(url_for('admin_login'))


@app.route('/admin')
@require_admin
def admin_dashboard():
    return render_template(
        'admin.html',
        foods=[food.to_dict() for food in get_foods()],
        active_page='admin'
    )

@app.route('/admin/save', methods=['POST'])
@require_admin
def admin_save_food():
    def required_text(field):
        return request.form.get(field, '').strip()

    def number_value(field, cast=float):
        raw_value = request.form.get(field, '').strip()
        try:
            value = cast(raw_value)
        except (TypeError, ValueError):
            raise ValueError(field)
        if value < 0:
            raise ValueError(field)
        return value

    try:
        food_name = required_text('food_name')
        cuisine = required_text('cuisine')
        category = required_text('category')
        meal_type = required_text('meal_type') or 'Heavy'
        veg_nonveg = required_text('veg_nonveg')
        spice_level = required_text('spice_level')
        description = required_text('description')
        price = number_value('price')
        calories = number_value('calories', int)
        protein = number_value('protein')
        carbs = number_value('carbs')
        fats = number_value('fats')
    except ValueError:
        flash('Please enter valid non-negative nutrition and price values.', 'error')
        return redirect(url_for('admin_dashboard'))

    if not food_name or not cuisine or not category or not veg_nonveg or not spice_level or not description:
        flash('Please fill all required food details.', 'error')
        return redirect(url_for('admin_dashboard'))

    allowed_values = {
        'cuisine': {'Indian', 'Italian', 'Chinese', 'American', 'Japanese', 'Mexican'},
        'category': {'Breakfast', 'Lunch', 'Dinner', 'Snacks'},
        'meal_type': {'Light', 'Heavy', 'Snack'},
        'veg_nonveg': {'Veg', 'Non-Veg'},
        'spice_level': {'Low', 'Medium', 'High'},
    }
    submitted_values = {
        'cuisine': cuisine,
        'category': category,
        'meal_type': meal_type,
        'veg_nonveg': veg_nonveg,
        'spice_level': spice_level,
    }
    if any(value not in allowed_values[field] for field, value in submitted_values.items()):
        flash('Please choose valid cuisine, category, diet, meal type, and spice options.', 'error')
        return redirect(url_for('admin_dashboard'))

    food_id = request.form.get('food_id', '').strip()
    food = get_food(food_id) if food_id else Food()
    if food_id and not food:
        flash('Food item not found for update.', 'error')
        return redirect(url_for('admin_dashboard'))

    food.food_name = food_name
    food.cuisine = cuisine
    food.category = category
    food.meal_type = meal_type
    food.veg_nonveg = veg_nonveg
    food.spice_level = spice_level
    food.price = price
    food.calories = calories
    food.protein = protein
    food.carbs = carbs
    food.fats = fats
    food.image_url = required_text('image_url')
    food.description = description

    if not food_id:
        db.session.add(food)

    db.session.commit()
    flash(f'{food.food_name} saved.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete/<food_id>', methods=['POST'])
@require_admin
def admin_delete_food(food_id):
    food = get_food(food_id)
    if not food:
        flash('Food item not found.', 'error')
        return redirect(url_for('admin_dashboard'))

    food_name = food.food_name
    db.session.delete(food)
    db.session.commit()
    flash(f'{food_name} deleted.', 'success')
    return redirect(url_for('admin_dashboard'))

# --- CHATBOT API ---

def build_chat_food_catalog(foods):
    return [
        {
            'id': f.food_id,
            'name': f.food_name,
            'cuisine': f.cuisine,
            'category': f.category,
            'price': f.price,
            'veg': f.veg_nonveg,
            'spice': f.spice_level,
            'calories': f.calories,
            'protein': f.protein,
            'description': f.description
        }
        for f in foods
    ]


def score_food_for_chat_prompt(food, prompt):
    prompt_terms = normalize_search_terms(prompt)
    if not prompt_terms:
        return 0

    text = searchable_food_text(food)
    score = 0
    for term in prompt_terms:
        if term in {'veg', 'vegetarian'} and food.veg_nonveg == 'Veg':
            score += 4
            continue
        if term in {'nonveg', 'non-veg', 'non'} and food.veg_nonveg == 'Non-Veg':
            score += 4
            continue
        aliases = SEARCH_ALIASES.get(term, {term})
        if any(alias in text for alias in aliases):
            score += 2
        elif len(term) > 3 and term in text:
            score += 1
    return score


def select_chat_context_foods(user_prompt, foods, limit=10):
    scored = [(score_food_for_chat_prompt(food, user_prompt), food) for food in foods]
    scored.sort(key=lambda item: (item[0], item[1].protein, -item[1].price), reverse=True)
    matched = [food for score, food in scored if score > 0]
    if matched:
        return matched[:limit]
    return foods[:limit]


CHAT_CUISINES = ['indian', 'italian', 'chinese', 'american', 'japanese', 'mexican']
CHAT_MEAL_TYPES = {
    'breakfast': 'Breakfast',
    'lunch': 'Lunch',
    'dinner': 'Dinner',
    'snack': 'Snacks',
    'snacks': 'Snacks',
}
CHAT_GREETING_TERMS = {'hi', 'hello', 'hey', 'yo', 'sup', 'namaste'}
CHAT_STOPWORDS = {
    'a', 'an', 'and', 'any', 'are', 'below', 'best', 'budget', 'can', 'dish',
    'eat', 'food', 'for', 'from', 'give', 'good', 'have', 'i', 'in', 'is',
    'like', 'max', 'me', 'need', 'option', 'please', 'recommend', 'show',
    'something', 'suggest', 'than', 'the', 'to', 'try', 'under', 'want',
    'with', 'within', 'would',
}
CHAT_CONSTRAINT_TERMS = {
    'american', 'below', 'breakfast', 'chinese', 'dinner',
    'healthy', 'high', 'hot', 'indian', 'italian', 'japanese', 'less', 'light',
    'low', 'lunch', 'mexican', 'mild', 'non', 'nonveg', 'protein',
    'rs', 'snack', 'snacks', 'spicy', 'veg', 'vegetarian',
}


def is_chat_greeting(prompt):
    words = re.findall(r'[a-z]+', prompt.lower())
    if not words:
        return False
    return len(words) <= 3 and any(word in CHAT_GREETING_TERMS for word in words)


def parse_chat_constraints(prompt):
    prompt_lower = prompt.lower()
    words = re.findall(r'[a-z0-9]+', prompt_lower)
    normalized_terms = normalize_search_terms(prompt_lower)

    has_nonveg = (
        bool(re.search(r'\bnon[\s-]?(veg|vegetarian)\b', prompt_lower))
        or any(term in normalized_terms for term in {'nonveg', 'non-veg'})
        or any(word in prompt_lower for word in ['chicken', 'fish', 'meat', 'beef', 'tuna', 'salmon'])
    )
    has_veg = (
        not has_nonveg
        and (
            bool(re.search(r'\b(veg|vegetarian)\b', prompt_lower))
            or any(term in normalized_terms for term in {'veg', 'vegetarian'})
        )
    )

    budget = None
    budget_patterns = [
        r'(?:under|below|within|less than|max(?:imum)?|budget(?: of)?)\s*(?:rs\.?|₹)?\s*(\d+(?:\.\d+)?)',
        r'(?:rs\.?|₹)\s*(\d+(?:\.\d+)?)',
    ]
    for pattern in budget_patterns:
        match = re.search(pattern, prompt_lower)
        if match:
            try:
                budget = float(match.group(1))
                break
            except ValueError:
                budget = None

    cuisine = next((c.capitalize() for c in CHAT_CUISINES if c in prompt_lower), None)

    meal_category = None
    for term, category in CHAT_MEAL_TYPES.items():
        if re.search(rf'\b{re.escape(term)}\b', prompt_lower):
            meal_category = category
            break

    spice = None
    if any(term in prompt_lower for term in ['spicy', 'hot', 'high spice', 'fire']):
        spice = 'High'
    elif any(term in prompt_lower for term in ['mild', 'less spice', 'low spice', 'bland']):
        spice = 'Low'
    elif 'medium spice' in prompt_lower:
        spice = 'Medium'

    health_goal = None
    if any(term in prompt_lower for term in ['high protein', 'protein', 'muscle', 'gym']):
        health_goal = 'high_protein'
    elif any(term in prompt_lower for term in ['weight loss', 'low calorie', 'healthy', 'light']):
        health_goal = 'light'

    search_terms = []
    for term in normalized_terms:
        if term.isdigit() or term in CHAT_STOPWORDS or term in CHAT_CONSTRAINT_TERMS:
            continue
        if len(term) > 2 and term not in search_terms:
            search_terms.append(term)

    return {
        'diet': 'Non-Veg' if has_nonveg else 'Veg' if has_veg else None,
        'budget': budget,
        'cuisine': cuisine,
        'meal_category': meal_category,
        'spice': spice,
        'health_goal': health_goal,
        'search_terms': search_terms,
    }


def chat_prompt_has_recommendation_intent(prompt, constraints):
    if constraints['search_terms']:
        return True
    if any(constraints[key] for key in ['diet', 'budget', 'cuisine', 'meal_category', 'spice', 'health_goal']):
        return True
    recommendation_words = {'recommend', 'suggest', 'eat', 'food', 'dish', 'meal', 'hungry'}
    prompt_words = set(re.findall(r'[a-z]+', prompt.lower()))
    return bool(recommendation_words & prompt_words)


def food_matches_chat_constraints(food, constraints):
    if constraints['diet'] and food.veg_nonveg != constraints['diet']:
        return False
    if constraints['budget'] is not None and food.price > constraints['budget']:
        return False
    if constraints['cuisine'] and food.cuisine != constraints['cuisine']:
        return False
    if constraints['meal_category'] and food.category != constraints['meal_category']:
        return False
    if constraints['spice'] and food.spice_level != constraints['spice']:
        return False
    if constraints['search_terms']:
        text = searchable_food_text(food)
        if not all(term in text for term in constraints['search_terms']):
            return False
    return True


def score_food_for_chat_constraints(food, constraints):
    score = 0
    if constraints['diet'] and food.veg_nonveg == constraints['diet']:
        score += 8
    if constraints['cuisine'] and food.cuisine == constraints['cuisine']:
        score += 6
    if constraints['meal_category'] and food.category == constraints['meal_category']:
        score += 5
    if constraints['spice'] and food.spice_level == constraints['spice']:
        score += 4
    if constraints['budget'] is not None:
        score += 3
        score += max(0, min(3, (constraints['budget'] - food.price) / 100))
    if constraints['health_goal'] == 'high_protein':
        score += min(food.protein / 4, 8)
    elif constraints['health_goal'] == 'light':
        if food.calories <= 300:
            score += 6
        elif food.calories <= 400:
            score += 3
    text = searchable_food_text(food)
    score += sum(2 for term in constraints['search_terms'] if term in text)
    return score


def select_chat_recommendations(user_prompt, foods, limit=10):
    constraints = parse_chat_constraints(user_prompt)
    if not chat_prompt_has_recommendation_intent(user_prompt, constraints):
        return [], constraints

    matches = [food for food in foods if food_matches_chat_constraints(food, constraints)]
    scored = [(score_food_for_chat_constraints(food, constraints), food) for food in matches]
    scored.sort(key=lambda item: (item[0], item[1].protein, -item[1].price), reverse=True)
    return [food for score, food in scored[:limit]], constraints


def build_local_chat_reply(matches):
    links = []
    for food in matches[:3]:
        links.append(
            f"• <a href='/recommendation-direct?food_id={food.food_id}' "
            f"class='chat-food-link'>{food.food_name}</a> "
            f"({food.cuisine}, {food.veg_nonveg}, ₹{int(food.price)}, "
            f"{food.calories} kcal, {food.protein:g}g protein)"
        )
    return (
        "Based on your request, I found these database matches:<br><br>"
        + "<br>".join(links)
        + "<br><br>Click any dish to view its full details and macro profile."
    )


def build_chat_system_instruction(foods):
    food_list = build_chat_food_catalog(foods)
    return (
        "You are Urban Diner, a friendly, expert AI Food Recommendation chatbot. "
        "The user will describe what they want to eat or ask food questions. "
        "Here is a relevant shortlist from the available food catalog: " + json.dumps(food_list) + "\n"
        "If the user asks for food recommendations, analyze their taste preferences, budget, "
        "spice, diet class, health intent, and meal timing from their prompt. "
        "Recommend 1 to 3 relevant foods from this shortlist only. "
        "Never invent dishes, prices, food IDs, nutrition values, or availability outside this shortlist. "
        "IMPORTANT: For every food you recommend, include a clickable HTML link exactly in this format: "
        "<a href='/recommendation-direct?food_id=FOOD_ID' class='chat-food-link'>FOOD_NAME</a>. "
        "Detail useful macros like calories and protein, mention price when relevant, and explain briefly why it matches. "
        "Keep the reply concise and do not show hidden reasoning. "
        "If the prompt is a greeting or a broad nutrition question, respond helpfully and briefly, "
        "suggesting they ask for a recommendation such as 'I want a high protein lunch under ₹300'."
    )


def extract_openrouter_reply(result):
    content = result.get('content')
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get('type') == 'text' and item.get('text'):
                text_parts.append(str(item['text']))
        if text_parts:
            return ''.join(text_parts).strip()

    choices = result.get('choices') or []
    if not choices:
        return ''
    message = choices[0].get('message') or {}
    content = message.get('content', '')
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get('text') or item.get('content')
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
        return ''.join(parts).strip()
    return str(content).strip() if content else ''


def post_openrouter_with_deadline(headers, payload):
    timeout_seconds = app.config.get('OPENROUTER_TIMEOUT_SECONDS', 20)
    request_timeout = max(timeout_seconds + 10, 30)
    future = openrouter_executor.submit(
        requests.post,
        'https://openrouter.ai/api/v1/chat/completions',
        headers=headers,
        json=payload,
        timeout=request_timeout
    )
    try:
        return future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError:
        print(f"OpenRouter API timed out after {timeout_seconds} seconds.")
        return None


@app.route('/api/chat', methods=['POST'])
def chat_assistant():
    data = request.json or {}
    user_prompt = data.get('message', '').strip()

    if not user_prompt:
        return jsonify({'reply': 'Please say something so I can help!'})

    foods = get_foods()

    if is_chat_greeting(user_prompt):
        return jsonify({
            'reply': (
                "Hey! Tell me what you feel like eating, for example "
                "<em>'spicy veg Indian under ₹300'</em> or "
                "<em>'high protein lunch'</em>."
            )
        })

    chat_context_foods, chat_constraints = select_chat_recommendations(user_prompt, foods)
    if not chat_context_foods:
        if chat_prompt_has_recommendation_intent(user_prompt, chat_constraints):
            return jsonify({
                'reply': (
                    "I couldn't find a database dish matching those exact details. "
                    "Try changing the budget, cuisine, diet, or spice level."
                )
            })
        return jsonify({
            'reply': (
                "I can help you pick from our food database. Try asking for something like "
                "<em>'I want a high protein lunch under ₹300'</em>."
            )
        })

    system_instruction = build_chat_system_instruction(chat_context_foods)

    openrouter_key = app.config.get('OPENROUTER_API_KEY')
    if openrouter_key:
        try:
            headers = {
                'Authorization': f'Bearer {openrouter_key}',
                'Content-Type': 'application/json',
                'HTTP-Referer': app.config.get('OPENROUTER_SITE_URL', 'http://127.0.0.1:8080'),
                'X-Title': 'Urban Diner Food Recommendation System',
            }
            payload = {
                'model': app.config.get('OPENROUTER_MODEL', 'nvidia/nemotron-3-ultra-550b-a55b:free'),
                'messages': [
                    {'role': 'system', 'content': system_instruction},
                    {'role': 'user', 'content': user_prompt},
                ],
                'temperature': 0.35,
                'max_tokens': 220,
                'reasoning': {'exclude': True},
            }
            resp = post_openrouter_with_deadline(headers, payload)
            if resp and resp.status_code == 200:
                reply_text = extract_openrouter_reply(resp.json())
                if reply_text:
                    return jsonify({'reply': reply_text})
            elif resp:
                print(f"OpenRouter API Error: {resp.status_code} {resp.text[:300]}")
        except Exception as e:
            print(f"OpenRouter API Exception: {e}")

    # Local fallback keeps the chat usable when OpenRouter is not configured,
    # rate-limited, or temporarily unavailable.
    return jsonify({'reply': build_local_chat_reply(chat_context_foods)})

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', '').lower() in {'1', 'true', 'yes'}
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=debug_mode, port=port)
