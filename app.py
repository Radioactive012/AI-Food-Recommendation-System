import os
import re
import concurrent.futures
from functools import wraps
from datetime import datetime, timedelta
import secrets
from urllib.parse import urlsplit
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from database.db_manager import init_db
from ml.similarity_model import RecommendationEngine, parse_natural_language_search, apply_nl_constraints
from models.models import db, User, Food, Rating, MealPlan, MealPlanItem
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

ALL_ALLERGENS = ['Gluten', 'Dairy', 'Nuts', 'Peanuts', 'Eggs', 'Soy', 'Fish', 'Shellfish', 'Sesame']


def get_foods():
    return Food.query.order_by(Food.food_name.asc()).all()


def get_food(food_id):
    if not food_id:
        return None
    return db.session.get(Food, food_id)


def get_user_allergies():
    """Get allergies from logged-in user or session."""
    user_id = session.get('user_id')
    if user_id:
        user = db.session.get(User, user_id)
        if user:
            return user.get_allergies_list()
    return session.get('allergies', [])


def add_to_history(food_id):
    history = session.get('history', [])
    existing = next((item for item in history if item.get('food_id') == food_id), None)
    if existing:
        existing['timestamp'] = datetime.now().isoformat()
    else:
        history.append({'food_id': food_id, 'timestamp': datetime.now().isoformat()})
    session['history'] = history[-20:]
    session.modified = True


VITAMIN_KEYWORDS = {
    'Vit C': ('tomato', 'pepper', 'lemon', 'lime', 'berry', 'berries', 'spinach', 'broccoli', 'basil', 'parsley', 'orange', 'avocado'),
    'Iron': ('spinach', 'lentil', 'lentils', 'dal', 'chickpea', 'kidney bean', 'beef', 'paneer', 'tofu', 'quinoa'),
    'Calcium': ('milk', 'cheese', 'yogurt', 'paneer', 'cream', 'mozzarella', 'parmesan', 'butter', 'ghee', 'egg'),
    'Vit D': ('egg', 'eggs', 'salmon', 'tuna', 'fish'),
    'Vit A': ('carrot', 'spinach', 'sweet potato', 'egg', 'eggs', 'butter', 'cheese', 'tomato'),
    'Vit B12': ('egg', 'eggs', 'chicken', 'beef', 'salmon', 'tuna', 'fish', 'milk', 'cheese'),
    'Folate': ('spinach', 'lentil', 'lentils', 'dal', 'chickpea', 'broccoli', 'avocado'),
}


def get_food_vitamins(food):
    """Estimate notable vitamins/minerals from ingredients for dashboard display."""
    ing = f"{food.ingredients or ''} {food.description or ''}".lower()
    vitamins = []
    for label, keywords in VITAMIN_KEYWORDS.items():
        if any(keyword in ing for keyword in keywords):
            vitamins.append(label)
    if food.category == 'Breakfast' and 'oatmeal' in ing and 'Iron' not in vitamins:
        vitamins.append('Iron')
    if food.veg_nonveg == 'Veg' and 'Fiber' not in vitamins and len(vitamins) < 4:
        vitamins.append('Fiber')
    return vitamins[:4]


def learn_preference(food):
    """Track cuisine/category frequency for long-term preference learning."""
    pref_data = session.get('learned_prefs', {'cuisines': {}, 'categories': {}, 'diet_counts': {}})
    cuisine = food.cuisine
    category = food.category
    diet = food.veg_nonveg
    pref_data['cuisines'][cuisine] = pref_data['cuisines'].get(cuisine, 0) + 1
    pref_data['categories'][category] = pref_data['categories'].get(category, 0) + 1
    pref_data['diet_counts'][diet] = pref_data['diet_counts'].get(diet, 0) + 1
    session['learned_prefs'] = pref_data
    session.modified = True

    user_id = session.get('user_id')
    if user_id:
        user = db.session.get(User, user_id)
        if user:
            user.learned_prefs = json.dumps(pref_data)
            db.session.commit()


def get_top_learned_preference(pref_type):
    """Get the most frequent cuisine or category from learned preferences."""
    pref_data = session.get('learned_prefs', {})
    counts = pref_data.get(pref_type, {})
    if not counts:
        return None
    return max(counts, key=counts.get)


def admin_credentials_configured():
    return bool(os.environ.get('ADMIN_USERNAME') and os.environ.get('ADMIN_PASSWORD'))


def admin_is_logged_in():
    return session.get('admin_logged_in') is True


def dev_otp_reset_enabled():
    """Allow the local OTP reset helper only outside production deployments."""
    production_flags = {
        os.environ.get('VERCEL'),
        os.environ.get('FLASK_ENV'),
        os.environ.get('ENV'),
        os.environ.get('APP_ENV'),
    }
    is_production = '1' in production_flags or 'production' in production_flags
    return os.environ.get('ENABLE_DEV_OTP_RESET') == '1' and not is_production


def start_user_session(user):
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
    session['allergies'] = user.get_allergies_list()
    if user.learned_prefs:
        try:
            session['learned_prefs'] = json.loads(user.learned_prefs)
        except (TypeError, ValueError):
            pass


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
        food.ingredients or '',
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
        is_logged_in=current_user is not None,
        all_allergens=ALL_ALLERGENS,
        user_allergies=get_user_allergies(),
        get_food_vitamins=get_food_vitamins,
        password_reset_enabled=dev_otp_reset_enabled(),
    )

def generate_otp():
    return "".join(secrets.choice("0123456789") for _ in range(6))


# --- ROUTES ---

@app.route('/favicon.ico')
def favicon():
    return redirect(url_for('static', filename='favicon.svg'))

@app.route('/')
def index():
    # If the user has preferences saved in session, pass them.
    user_profile = session.get('preferences', {})

    # Apply learned preference hints
    top_cuisine = get_top_learned_preference('cuisines')
    if top_cuisine and not user_profile.get('cuisine_preference'):
        user_profile['learned_cuisine'] = top_cuisine

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

        if not user.is_verified or user.otp_code or user.otp_expiry:
            user.is_verified = True
            user.otp_code = None
            user.otp_expiry = None
            db.session.commit()

        start_user_session(user)
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

        # Collect allergies from form
        selected_allergies = request.form.getlist('allergies')
        allergies_str = ','.join(selected_allergies) if selected_allergies else None

        user = User(
            name=name,
            email=email,
            password=generate_password_hash(password, method='pbkdf2:sha256'),
            age=optional_int(request.form.get('age')),
            gender=request.form.get('gender') or None,
            diet_type=request.form.get('diet_type') or 'Veg',
            spice_preference=request.form.get('spice_preference') or 'Medium',
            health_goal=request.form.get('health_goal') or 'Healthy Eating',
            mood_preference=request.form.get('mood_preference') or 'Neutral',
            allergies=allergies_str,
            is_verified=True,
            otp_code=None,
            otp_expiry=None
        )
        db.session.add(user)
        db.session.commit()

        start_user_session(user)
        flash(f'Welcome to Urban Diner, {user.name}.', 'success')
        return redirect(url_for('index'))

    return render_template('register.html', active_page='login')

@app.route('/logout')
def logout():
    was_logged_in = 'user_id' in session
    session.clear()
    if was_logged_in:
        flash('You have been signed out successfully.', 'success')
    else:
        flash('Preferences and history reset successfully.', 'success')
    return redirect(url_for('index'))


@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    flash('Email verification is no longer required. Please sign in.', 'info')
    return redirect(url_for('login'))


@app.route('/resend-otp', methods=['POST'])
def resend_otp():
    flash('Email verification is no longer required. Please sign in.', 'info')
    return redirect(url_for('login'))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if not dev_otp_reset_enabled():
        flash('Password reset is disabled for this deployment. Please create a new account or contact the project owner.', 'info')
        return redirect(url_for('login'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if not email:
            flash('Please enter your email address.', 'error')
            return render_template('forgot_password.html')
            
        user = User.query.filter_by(email=email).first()
        if user:
            user.otp_code = generate_otp()
            user.otp_expiry = datetime.utcnow() + timedelta(minutes=10)
            db.session.commit()
            flash('Development reset code generated. Use the code shown on the next screen.', 'success')
            return redirect(url_for('reset_password', email=user.email))
        else:
            print(f"[FORGOT PASSWORD] Requested email not found: {email}")
            flash('If that email exists in our system, a development reset code was generated.', 'info')
            return render_template('forgot_password.html')
            
    return render_template('forgot_password.html')


@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if not dev_otp_reset_enabled():
        flash('Password reset is disabled for this deployment. Please create a new account or contact the project owner.', 'info')
        return redirect(url_for('login'))

    email = request.args.get('email', '').strip().lower() or request.form.get('email', '').strip().lower()
    if not email:
        flash('Email address is required to reset password.', 'error')
        return redirect(url_for('forgot_password'))
        
    user = User.query.filter_by(email=email).first()
    if not user:
        flash('Account not found.', 'error')
        return redirect(url_for('forgot_password'))
        
    if request.method == 'POST':
        otp = request.form.get('otp', '').strip()
        new_password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        if not otp or not new_password:
            flash('Please fill in all fields.', 'error')
            return render_template('reset_password.html', email=email, dev_otp=user.otp_code)
            
        if len(new_password) < 6:
            flash('New password must be at least 6 characters.', 'error')
            return render_template('reset_password.html', email=email, dev_otp=user.otp_code)
            
        if new_password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('reset_password.html', email=email, dev_otp=user.otp_code)
            
        if user.otp_code != otp:
            flash('Incorrect OTP code. Please try again.', 'error')
            return render_template('reset_password.html', email=email, dev_otp=user.otp_code)
            
        if user.otp_expiry and user.otp_expiry < datetime.utcnow():
            flash('This OTP has expired. Please request a new reset code.', 'error')
            return redirect(url_for('forgot_password'))
            
        user.password = generate_password_hash(new_password, method='pbkdf2:sha256')
        user.otp_code = None
        user.otp_expiry = None
        user.is_verified = True
        db.session.commit()
        
        flash('Password has been reset successfully. Please sign in.', 'success')
        return redirect(url_for('login'))
        
    return render_template('reset_password.html', email=email, dev_otp=user.otp_code)


@app.route('/profile', methods=['GET', 'POST'])
def profile():
    user_id = session.get('user_id')
    if not user_id:
        flash('Please sign in to view your profile.', 'error')
        return redirect(url_for('login'))
        
    user = db.session.get(User, user_id)
    if not user:
        session.clear()
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        age_str = request.form.get('age', '').strip()
        gender = request.form.get('gender') or None
        diet_type = request.form.get('diet_type', 'Veg')
        spice_preference = request.form.get('spice_preference', 'Medium')
        health_goal = request.form.get('health_goal', 'Healthy Eating')
        mood_preference = request.form.get('mood_preference', 'Neutral')
        selected_allergies = request.form.getlist('allergies')
        
        if not name:
            flash('Name cannot be empty.', 'error')
            return render_template('profile.html', user=user, active_page='profile')
            
        try:
            age = int(age_str) if age_str else None
        except ValueError:
            flash('Please enter a valid age.', 'error')
            return render_template('profile.html', user=user, active_page='profile')
            
        allergies_str = ','.join(selected_allergies) if selected_allergies else None
        
        # Update
        user.name = name
        user.age = age
        user.gender = gender
        user.diet_type = diet_type
        user.spice_preference = spice_preference
        user.health_goal = health_goal
        user.mood_preference = mood_preference
        user.allergies = allergies_str
        
        db.session.commit()
        
        session['preferences'] = {
            'diet_type': user.diet_type,
            'spice_preference': user.spice_preference,
            'health_goal': user.health_goal,
            'mood_preference': user.mood_preference,
            'cuisine_preference': session.get('preferences', {}).get('cuisine_preference', ''),
            'budget': session.get('preferences', {}).get('budget', 500.0),
            'search_query': session.get('preferences', {}).get('search_query', '')
        }
        session['allergies'] = user.get_allergies_list()
        
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile'))
        
    return render_template('profile.html', user=user, active_page='profile')


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

    if not cuisine:
        learned_cuisine = get_top_learned_preference('cuisines')
        if learned_cuisine:
            cuisine = learned_cuisine

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
    session_food_ids = {r.food_id for r in user_ratings}
    user_id = session.get('user_id')
    if user_id:
        for db_rating in Rating.query.filter_by(user_id=user_id).all():
            if db_rating.food_id not in session_food_ids:
                user_ratings.append(SessionRating(db_rating.food_id, db_rating.rating))

    all_ratings = Rating.query.all()

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

    # Try NL search first — if query looks like natural language
    nl_constraints = {}
    if search_query and len(search_query.split()) >= 3:
        nl_constraints = parse_natural_language_search(search_query)
        if nl_constraints:
            all_foods = apply_nl_constraints(all_foods, nl_constraints)
            # Override form values with NL-extracted values
            if 'diet' in nl_constraints:
                user_profile['diet_type'] = nl_constraints['diet']
            if 'cuisine' in nl_constraints:
                user_profile['cuisine_preference'] = nl_constraints['cuisine']
            if 'spice' in nl_constraints:
                user_profile['spice_preference'] = nl_constraints['spice']
            if 'max_budget' in nl_constraints:
                user_profile['budget'] = nl_constraints['max_budget']

    # Fallback: keyword search if NL didn't extract constraints or query is short
    if search_query and not nl_constraints:
        all_foods = [food for food in all_foods if food_matches_search(food, search_query)]

    user_allergies = get_user_allergies()

    # Calculate Recommendations
    suggestions = engine.get_recommendations(
        user_profile=user_profile,
        all_foods=all_foods,
        rating_history=user_ratings,
        limit=6,
        user_allergies=user_allergies,
        all_ratings=all_ratings,
    )

    return render_template(
        'recommendations.html',
        suggestions=suggestions,
        user_profile=session.get('preferences', {}),
        active_page='home'
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
    existing_idx = next((i for i, r in enumerate(ratings) if r.get('food_id') == food_id), None)
    entry = {'food_id': food_id, 'rating': rating_int, 'review': review}
    if existing_idx is not None:
        ratings[existing_idx] = entry
    else:
        ratings.append(entry)
    session['ratings'] = ratings
    add_to_history(food_id)
    learn_preference(food)
    session.modified = True

    user_id = session.get('user_id')
    if user_id:
        db_rating = Rating.query.filter_by(user_id=user_id, food_id=food_id).order_by(
            Rating.created_at.desc()
        ).first()
        if db_rating:
            db_rating.rating = rating_int
            db_rating.review = review if review else None
        else:
            db.session.add(Rating(
                user_id=user_id,
                food_id=food_id,
                rating=rating_int,
                review=review if review else None,
            ))
        db.session.commit()

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
    learn_preference(food)

    dummy_item = {
        'food': food,
        'score': 15,
        'explanation': "Served directly from your assistant selection."
    }
    return render_template(
        'recommendations.html',
        suggestions=[dummy_item],
        user_profile=session.get('preferences', {}),
        active_page='home'
    )

# --- NUTRITION DASHBOARD ---

@app.route('/nutrition')
def nutrition_dashboard():
    foods = get_foods()
    # Gather stats for the dashboard
    avg_cal = sum(f.calories for f in foods) / len(foods) if foods else 0
    avg_protein = sum(f.protein for f in foods) / len(foods) if foods else 0
    avg_carbs = sum(f.carbs for f in foods) / len(foods) if foods else 0
    avg_fats = sum(f.fats for f in foods) / len(foods) if foods else 0

    # Categorize foods by nutrition buckets
    low_cal = [f for f in foods if f.calories <= 300]
    high_protein = [f for f in foods if f.protein >= 20]
    low_carb = [f for f in foods if f.carbs <= 30]
    low_fat = [f for f in foods if f.fats <= 10]

    # Per-cuisine averages
    cuisine_stats = {}
    for food in foods:
        if food.cuisine not in cuisine_stats:
            cuisine_stats[food.cuisine] = {'count': 0, 'cal': 0, 'protein': 0, 'carbs': 0, 'fats': 0}
        cs = cuisine_stats[food.cuisine]
        cs['count'] += 1
        cs['cal'] += food.calories
        cs['protein'] += food.protein
        cs['carbs'] += food.carbs
        cs['fats'] += food.fats
    for cuisine, cs in cuisine_stats.items():
        n = cs['count']
        cs['avg_cal'] = round(cs['cal'] / n)
        cs['avg_protein'] = round(cs['protein'] / n, 1)
        cs['avg_carbs'] = round(cs['carbs'] / n, 1)
        cs['avg_fats'] = round(cs['fats'] / n, 1)

    food_vitamins = {food.food_id: get_food_vitamins(food) for food in foods}
    vitamin_buckets = {label: [] for label in VITAMIN_KEYWORDS}
    vitamin_buckets['Fiber'] = []
    for food in foods:
        for vitamin in food_vitamins[food.food_id]:
            vitamin_buckets.setdefault(vitamin, []).append(food)

    return render_template(
        'nutrition_dashboard.html',
        foods=foods,
        food_vitamins=food_vitamins,
        vitamin_buckets=vitamin_buckets,
        avg_cal=round(avg_cal),
        avg_protein=round(avg_protein, 1),
        avg_carbs=round(avg_carbs, 1),
        avg_fats=round(avg_fats, 1),
        low_cal=low_cal,
        high_protein=high_protein,
        low_carb=low_carb,
        low_fat=low_fat,
        cuisine_stats=cuisine_stats,
        active_page='nutrition'
    )

# --- MEAL PLANNER ---

@app.route('/meal-planner')
def meal_planner():
    return render_template('meal_planner.html', active_page='meal_planner')

@app.route('/api/generate-meal-plan', methods=['POST'])
def generate_meal_plan_api():
    data = request.json or {}
    days = min(int(data.get('days', 7)), 7)
    health_goal = data.get('health_goal', session.get('preferences', {}).get('health_goal', 'Healthy Eating'))
    diet_type = data.get('diet_type', session.get('preferences', {}).get('diet_type', 'Veg'))

    user_profile = {
        'diet_type': diet_type,
        'health_goal': health_goal,
    }

    user_allergies = get_user_allergies()
    all_foods = get_foods()

    plan = engine.generate_meal_plan(all_foods, user_profile, days=days, user_allergies=user_allergies)

    # Save to DB if logged in
    user_id = session.get('user_id')
    meal_plan = MealPlan(
        user_id=user_id,
        session_id=session.get('_id', ''),
        plan_name=f'{diet_type} {health_goal} Plan',
    )
    db.session.add(meal_plan)
    db.session.flush()  # Ensure plan_id is populated before creating items

    result = []
    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    for day_data in plan:
        day_idx = day_data['day_index']
        day_result = {'day': day_names[day_idx], 'day_index': day_idx, 'slots': {}, 'total_calories': 0, 'total_protein': 0}
        for slot_name, food in day_data['slots'].items():
            day_result['slots'][slot_name] = {
                'food_id': food.food_id,
                'food_name': food.food_name,
                'cuisine': food.cuisine,
                'calories': food.calories,
                'protein': float(food.protein),
                'carbs': float(food.carbs),
                'fats': float(food.fats),
                'price': float(food.price),
                'image_url': food.image_url or '',
                'veg_nonveg': food.veg_nonveg,
            }
            day_result['total_calories'] += food.calories
            day_result['total_protein'] += food.protein

            item = MealPlanItem(
                plan_id=meal_plan.plan_id,
                food_id=food.food_id,
                day_index=day_idx,
                slot=slot_name,
            )
            db.session.add(item)

        day_result['total_protein'] = round(day_result['total_protein'], 1)
        result.append(day_result)

    db.session.commit()

    return jsonify({'status': 'success', 'plan': result, 'plan_id': meal_plan.plan_id})

# --- ALLERGY MANAGEMENT ---

@app.route('/api/allergies', methods=['POST'])
def update_allergies():
    data = request.json or {}
    allergies = data.get('allergies', [])
    # Validate
    valid = [a for a in allergies if a in ALL_ALLERGENS]

    session['allergies'] = valid
    session.modified = True

    # Persist if logged in
    user_id = session.get('user_id')
    if user_id:
        user = db.session.get(User, user_id)
        if user:
            user.allergies = ','.join(valid) if valid else None
            db.session.commit()

    return jsonify({'status': 'success', 'allergies': valid})

# --- REVIEWS ---

@app.route('/reviews')
def reviews_page():
    # Get all ratings from DB with food info
    all_ratings = Rating.query.order_by(Rating.created_at.desc()).limit(50).all()
    foods_dict = {f.food_id: f for f in get_foods()}
    users_dict = {}

    current_user_id = session.get('user_id')
    review_items = []
    for r in all_ratings:
        food = foods_dict.get(r.food_id)
        if not food:
            continue
        if r.user_id not in users_dict:
            users_dict[r.user_id] = db.session.get(User, r.user_id)
        user = users_dict.get(r.user_id)

        review_items.append({
            'rating': r,
            'food': food,
            'user_name': user.name if user else 'Anonymous',
            'can_manage': current_user_id and r.user_id == current_user_id,
            'source': 'db',
            'review_id': r.rating_id,
        })

    if not current_user_id:
        session_ratings = session.get('ratings', [])
        for idx, sr in enumerate(session_ratings):
            food = foods_dict.get(sr['food_id'])
            if not food or not sr.get('review'):
                continue
            review_items.append({
                'rating': type('R', (), {
                    'rating': sr['rating'],
                    'review': sr.get('review', ''),
                    'created_at': datetime.now(),
                })(),
                'food': food,
                'user_name': 'You',
                'can_manage': not current_user_id,
                'source': 'session',
                'session_index': idx,
            })

    review_items.sort(
        key=lambda item: item['rating'].created_at if hasattr(item['rating'], 'created_at') else datetime.min,
        reverse=True,
    )

    return render_template('reviews.html', review_items=review_items, active_page='reviews')


@app.route('/api/reviews/<rating_id>', methods=['PUT', 'DELETE'])
def manage_db_review(rating_id):
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'status': 'error', 'message': 'Sign in to manage reviews.'}), 401

    rating = db.session.get(Rating, rating_id)
    if not rating or rating.user_id != user_id:
        return jsonify({'status': 'error', 'message': 'Review not found.'}), 404

    if request.method == 'DELETE':
        db.session.delete(rating)
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Review deleted.'})

    data = request.json or {}
    try:
        rating_int = int(data.get('rating', rating.rating))
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Rating must be between 1 and 5.'}), 400

    if not 1 <= rating_int <= 5:
        return jsonify({'status': 'error', 'message': 'Rating must be between 1 and 5.'}), 400

    rating.rating = rating_int
    rating.review = (data.get('review') or '').strip() or None
    db.session.commit()
    return jsonify({'status': 'success', 'message': 'Review updated.'})


@app.route('/api/reviews/session/<int:session_index>', methods=['PUT', 'DELETE'])
def manage_session_review(session_index):
    if session.get('user_id'):
        return jsonify({'status': 'error', 'message': 'Use account review management while signed in.'}), 400

    ratings = session.get('ratings', [])
    if session_index < 0 or session_index >= len(ratings):
        return jsonify({'status': 'error', 'message': 'Review not found.'}), 404

    if request.method == 'DELETE':
        ratings.pop(session_index)
        session['ratings'] = ratings
        session.modified = True
        return jsonify({'status': 'success', 'message': 'Review deleted.'})

    data = request.json or {}
    try:
        rating_int = int(data.get('rating', ratings[session_index]['rating']))
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Rating must be between 1 and 5.'}), 400

    if not 1 <= rating_int <= 5:
        return jsonify({'status': 'error', 'message': 'Rating must be between 1 and 5.'}), 400

    ratings[session_index]['rating'] = rating_int
    ratings[session_index]['review'] = (data.get('review') or '').strip()
    session['ratings'] = ratings
    session.modified = True
    return jsonify({'status': 'success', 'message': 'Review updated.'})

# --- GROCERY LIST ---

@app.route('/grocery-list')
def grocery_list_page():
    return render_template('grocery_list.html', active_page='grocery')

@app.route('/api/foods')
def api_foods():
    foods = get_foods()
    return jsonify({
        'status': 'success',
        'foods': [
            {
                'food_id': f.food_id,
                'food_name': f.food_name,
                'cuisine': f.cuisine,
                'veg_nonveg': f.veg_nonveg,
                'category': f.category,
            }
            for f in foods
        ],
    })

@app.route('/api/grocery-list', methods=['POST'])
def generate_grocery_list():
    data = request.json or {}
    food_ids = data.get('food_ids', [])

    if not food_ids:
        # Use latest meal plan if no food ids provided
        plan_id = data.get('plan_id')
        if plan_id:
            items = MealPlanItem.query.filter_by(plan_id=plan_id).all()
            food_ids = list({item.food_id for item in items})
        else:
            return jsonify({'status': 'error', 'message': 'No foods selected'}), 400

    foods = [get_food(fid) for fid in food_ids]
    foods = [f for f in foods if f]

    # Aggregate ingredients
    ingredient_counts = {}
    for food in foods:
        for ingredient in food.get_ingredients_list():
            ingredient_lower = ingredient.strip().lower()
            if ingredient_lower:
                if ingredient_lower not in ingredient_counts:
                    ingredient_counts[ingredient_lower] = {'name': ingredient.strip(), 'count': 0, 'foods': []}
                ingredient_counts[ingredient_lower]['count'] += 1
                if food.food_name not in ingredient_counts[ingredient_lower]['foods']:
                    ingredient_counts[ingredient_lower]['foods'].append(food.food_name)

    # Sort by frequency
    sorted_ingredients = sorted(ingredient_counts.values(), key=lambda x: (-x['count'], x['name']))

    # Categorize
    spices = {'cumin', 'coriander', 'turmeric', 'chili', 'chili powder', 'paprika', 'oregano', 'basil', 'parsley',
              'dill', 'bay leaf', 'cardamom', 'cinnamon', 'saffron', 'mint', 'fenugreek', 'mustard seeds', 'curry leaves',
              'chili flakes', 'vanilla', 'pepper', 'wasabi', 'chili pepper'}
    staples = {'salt', 'oil', 'olive oil', 'sesame oil', 'sugar', 'flour', 'cornstarch', 'baking powder',
               'yeast', 'ghee', 'butter', 'soy sauce', 'vinegar'}
    proteins = {'chicken', 'beef', 'beef patty', 'beef mince', 'salmon', 'tuna', 'egg', 'egg yolk', 'tofu',
                'paneer', 'chickpea', 'kidney beans', 'black beans', 'toor dal', 'urad dal', 'lentil',
                'anchovy', 'fish'}

    categorized = {'Proteins': [], 'Vegetables & Fruits': [], 'Dairy': [], 'Grains & Staples': [], 'Spices & Herbs': [], 'Other': []}

    dairy_items = {'milk', 'cream', 'cheese', 'cheddar cheese', 'mozzarella', 'parmesan', 'feta cheese',
                   'yogurt', 'buttermilk', 'butter', 'ghee', 'almond milk'}

    grains = {'rice', 'basmati rice', 'sushi rice', 'noodles', 'ramen noodles', 'fettuccine', 'pasta',
              'bread', 'sourdough bread', 'baguette', 'burger bun', 'tortilla', 'flour tortilla', 'corn tortilla',
              'oats', 'quinoa', 'granola'}

    for item in sorted_ingredients:
        name_lower = item['name'].lower()
        if name_lower in spices:
            categorized['Spices & Herbs'].append(item)
        elif name_lower in proteins:
            categorized['Proteins'].append(item)
        elif name_lower in dairy_items:
            categorized['Dairy'].append(item)
        elif name_lower in grains or name_lower in staples:
            categorized['Grains & Staples'].append(item)
        else:
            categorized['Vegetables & Fruits'].append(item)

    return jsonify({
        'status': 'success',
        'grocery_list': categorized,
        'total_items': len(sorted_ingredients),
        'foods_count': len(foods),
    })


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
    learn_preference(food)
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
    food.ingredients = required_text('ingredients')
    food.allergens = required_text('allergens')

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
