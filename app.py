import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from models.models import db, User, Food, Rating, RecommendationHistory, Admin
from database.db_manager import init_db
from ml.similarity_model import RecommendationEngine
import requests
import json

app = Flask(__name__)
app.config.from_object(Config)

# Initialize Database
db.init_app(app)

# Track database initialization to run it once dynamically
_db_initialized = False

@app.before_request
def setup_db_on_first_request():
    global _db_initialized
    if not _db_initialized:
        # Avoid running seeder when executing unit tests
        if not app.config.get('TESTING'):
            init_db(app)
        _db_initialized = True

# Initialize Recommendation Engine
engine = RecommendationEngine()

# Helpers
def is_logged_in():
    return 'user_id' in session

def current_user():
    if is_logged_in():
        return User.query.filter_by(user_id=session['user_id']).first()
    return None

# Context processor to expose common variables to templates
@app.context_processor
def inject_user():
    return dict(
        current_user=current_user(),
        is_logged_in=is_logged_in()
    )

# --- ROUTES ---

@app.route('/')
def index():
    if not is_logged_in():
        return redirect(url_for('login'))
    
    user = current_user()
    return render_template('index.html', user_profile=user, active_page='home')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if is_logged_in():
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        
        # Check Admin credentials
        admin = Admin.query.filter_by(username=email).first()
        if admin and check_password_hash(admin.password, password):
            session['user_id'] = admin.admin_id
            session['user_name'] = admin.username
            session['is_admin'] = True
            flash('Admin successfully logged in!', 'success')
            return redirect(url_for('admin_dashboard'))
            
        # Check regular user credentials
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.user_id
            session['user_name'] = user.name
            session['is_admin'] = False
            flash(f'Welcome back, {user.name}!', 'success')
            return redirect(url_for('index'))
            
        flash('Invalid email or password.', 'error')
        
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if is_logged_in():
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        age = request.form.get('age')
        gender = request.form.get('gender')
        diet_type = request.form.get('diet_type')
        spice_preference = request.form.get('spice_preference')
        health_goal = request.form.get('health_goal')
        
        if not name or not email or not password:
            flash('Please fill in all required fields.', 'error')
            return render_template('register.html')
            
        # Check if email exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('An account with this email already exists.', 'error')
            return render_template('register.html')
            
        # Hash password and create user
        hashed_pw = generate_password_hash(password)
        new_user = User(
            user_id=str(uuid.uuid4()),
            name=name,
            email=email,
            password=hashed_pw,
            age=int(age) if age else None,
            gender=gender,
            diet_type=diet_type,
            spice_preference=spice_preference,
            health_goal=health_goal,
            mood_preference='Neutral'
        )
        
        try:
            db.session.add(new_user)
            db.session.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error occurred: {str(e)}', 'error')
            
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Successfully logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/recommendations', methods=['POST'])
def get_recommendation_results():
    if not is_logged_in():
        return redirect(url_for('login'))
        
    # Get user profile context
    user = current_user()
    
    # Extract preferences from request form
    cuisine = request.form.get('cuisine', '').strip()
    diet = request.form.get('diet', 'Veg')
    spice = request.form.get('spice', 'Medium')
    health_goal = request.form.get('health_goal', 'Healthy Eating')
    mood = request.form.get('mood', 'Neutral')
    budget = request.form.get('budget', 500)
    search_query = request.form.get('search_query', '').strip()
    
    # Save these as current preferences for the logged-in user
    if user:
        user.diet_type = diet
        user.spice_preference = spice
        user.health_goal = health_goal
        user.mood_preference = mood
        if cuisine:
            user.cuisine_preference = cuisine
        db.session.commit()
        
    # Fetch all foods
    all_foods = Food.query.all()
    
    # Fetch ratings history for ML predictor training
    user_ratings = Rating.query.filter_by(user_id=user.user_id).all() if user else []
    
    # Construct user profile dictionary for the engine
    user_profile = {
        'diet_type': diet,
        'cuisine_preference': cuisine,
        'spice_preference': spice,
        'health_goal': health_goal,
        'mood_preference': mood,
        'budget': budget,
        'age': user.age if user else 25
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
    
    # Log recommended foods to history
    if user and suggestions:
        try:
            for item in suggestions:
                hist = RecommendationHistory(
                    history_id=str(uuid.uuid4()),
                    user_id=user.user_id,
                    recommended_food_id=item['food'].food_id
                )
                db.session.add(hist)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Error logging history: {e}")
            
    return render_template('recommendations.html', suggestions=suggestions)

@app.route('/history')
def history():
    if not is_logged_in():
        return redirect(url_for('login'))
        
    user = current_user()
    if not user:
        return redirect(url_for('login'))
        
    # Fetch user recommendation history sorted by newest first
    history_items = RecommendationHistory.query.filter_by(user_id=user.user_id)\
        .order_by(RecommendationHistory.timestamp.desc())\
        .limit(20).all()
        
    return render_template('history.html', history_items=history_items, active_page='history')

@app.route('/submit-rating', methods=['POST'])
def submit_rating():
    if not is_logged_in():
        return redirect(url_for('login'))
        
    user = current_user()
    food_id = request.form.get('food_id')
    rating_val = request.form.get('rating')
    review = request.form.get('review', '').strip()
    
    if not food_id or not rating_val:
        flash('Missing rating details.', 'error')
        return redirect(url_for('index'))
        
    try:
        new_rating = Rating(
            rating_id=str(uuid.uuid4()),
            user_id=user.user_id,
            food_id=food_id,
            rating=int(rating_val),
            review=review
        )
        db.session.add(new_rating)
        db.session.commit()
        flash('Thank you for rating this recommendation!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Failed to save rating: {str(e)}', 'error')
        
    return redirect(url_for('index'))

@app.route('/recommendation-direct')
def direct_food_info():
    if not is_logged_in():
        return redirect(url_for('login'))
        
    food_id = request.args.get('food_id')
    food = Food.query.filter_by(food_id=food_id).first()
    if not food:
        flash("Dish not found.", "error")
        return redirect(url_for('index'))
        
    # Serve this food as a single recommendation item
    dummy_item = {
        'food': food,
        'score': 15,
        'explanation': "Served directly from your assistant selection."
    }
    return render_template('recommendations.html', suggestions=[dummy_item])

# --- ADMIN PANEL ---

@app.route('/admin')
def admin_dashboard():
    if not is_logged_in() or not session.get('is_admin', False):
        flash('Admin authorization required.', 'error')
        return redirect(url_for('login'))
        
    all_foods = Food.query.all()
    return render_template('admin.html', foods=all_foods, active_page='admin')

@app.route('/admin/save', methods=['POST'])
def admin_save_food():
    if not is_logged_in() or not session.get('is_admin', False):
        return redirect(url_for('login'))
        
    food_id = request.form.get('food_id', '').strip()
    food_name = request.form.get('food_name', '').strip()
    cuisine = request.form.get('cuisine', '')
    category = request.form.get('category', '')
    meal_type = request.form.get('meal_type', 'Heavy')
    veg_nonveg = request.form.get('veg_nonveg', 'Veg')
    spice_level = request.form.get('spice_level', 'Medium')
    price = float(request.form.get('price', 0))
    calories = int(request.form.get('calories', 0))
    protein = float(request.form.get('protein', 0))
    carbs = float(request.form.get('carbs', 0))
    fats = float(request.form.get('fats', 0))
    image_url = request.form.get('image_url', '').strip()
    description = request.form.get('description', '').strip()
    
    if not food_name or price <= 0:
        flash('Invalid food inputs.', 'error')
        return redirect(url_for('admin_dashboard'))
        
    try:
        if food_id:
            # Update existing food
            food = Food.query.filter_by(food_id=food_id).first()
            if food:
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
                food.image_url = image_url
                food.description = description
                flash('Food item successfully updated!', 'success')
            else:
                flash('Food item to update was not found.', 'error')
        else:
            # Create new food
            new_food = Food(
                food_id=str(uuid.uuid4()),
                food_name=food_name,
                cuisine=cuisine,
                category=category,
                meal_type=meal_type,
                veg_nonveg=veg_nonveg,
                spice_level=spice_level,
                price=price,
                calories=calories,
                protein=protein,
                carbs=carbs,
                fats=fats,
                image_url=image_url,
                description=description
            )
            db.session.add(new_food)
            flash('Food item successfully created!', 'success')
            
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'Database error: {str(e)}', 'error')
        
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete/<food_id>', methods=['POST'])
def admin_delete_food(food_id):
    if not is_logged_in() or not session.get('is_admin', False):
        return redirect(url_for('login'))
        
    food = Food.query.filter_by(food_id=food_id).first()
    if food:
        try:
            db.session.delete(food)
            db.session.commit()
            flash('Food item successfully deleted!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Failed to delete item: {str(e)}', 'error')
    else:
        flash('Food item not found.', 'error')
        
    return redirect(url_for('admin_dashboard'))

# --- CHATBOT API ---

@app.route('/api/chat', methods=['POST'])
def chat_assistant():
    data = request.json or {}
    user_prompt = data.get('message', '').strip()
    
    if not user_prompt:
        return jsonify({'reply': 'Please say something so I can help!'})
        
    # Load all foods context for recommendations
    foods = Food.query.all()
    
    # 1. Check if Gemini API key exists
    gemini_key = app.config.get('GEMINI_API_KEY')
    if gemini_key:
        try:
            # Compile food catalog list for Gemini context
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
            
            # Format system prompt
            system_instruction = (
                "You are BiteWise, an friendly, expert AI Food Recommendation chatbot. "
                "The user will describe what they want to eat or ask questions. "
                "Here is the database catalog of available foods: " + json.dumps(food_list) + "\n"
                "If the user asks for food recommendations, analyze their taste preferences, budget, "
                "spice, and diet class from their prompt. Recommend 1 to 3 relevant foods from the catalog. "
                "IMPORTANT: For every food you recommend, you MUST include a clickable HTML link exactly in this format: "
                "<a href='/recommendation-direct?food_id=FOOD_ID' class='chat-food-link' style='color:#8b5cf6;font-weight:bold;text-decoration:none;'>FOOD_NAME</a>. "
                "Detail the macros (calories, protein) and explain briefly why it matches their prompt. "
                "If the prompt is just general greeting or nutrition questions, respond helpfully and briefly, "
                "suggesting they ask for recommendation (e.g. 'I want a high protein lunch under ₹300')."
            )
            
            # Request Gemini API
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
            else:
                print(f"Gemini API failure ({resp.status_code}): {resp.text}")
        except Exception as e:
            print(f"Gemini API Exception: {e}")
            
    # 2. LOCAL NLP PARSER FALLBACK
    # Parse terms from user prompt
    prompt_lower = user_prompt.lower()
    
    # Diet extraction
    diet_term = None
    if 'veg' in prompt_lower and 'non' not in prompt_lower:
        diet_term = 'Veg'
    elif 'non-veg' in prompt_lower or 'chicken' in prompt_lower or 'meat' in prompt_lower or 'fish' in prompt_lower or 'beef' in prompt_lower:
        diet_term = 'Non-Veg'
        
    # Cuisine extraction
    cuisine_term = None
    for c in ['indian', 'italian', 'chinese', 'american', 'japanese', 'mexican']:
        if c in prompt_lower:
            cuisine_term = c.capitalize()
            
    # Spice extraction
    spice_term = None
    if 'spicy' in prompt_lower or 'hot' in prompt_lower or 'fire' in prompt_lower:
        spice_term = 'High'
    elif 'mild' in prompt_lower or 'bland' in prompt_lower or 'less spice' in prompt_lower:
        spice_term = 'Low'
        
    # Budget extraction (e.g. "under 300", "under ₹400")
    budget_term = None
    import re
    prices = re.findall(r'(?:under|below|rs\.?|₹)\s?(\d+)', prompt_lower)
    if prices:
        budget_term = float(prices[0])
    else:
        # Check if just number exists
        numbers = re.findall(r'\b\d{3}\b', prompt_lower)
        if numbers:
            budget_term = float(numbers[0])
            
    # Filter foods based on extracted tags
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
        
    # If no strict matches, fall back to simple keyword intersections
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
                f"style='color:#8b5cf6;font-weight:bold;text-decoration:none;'>{f.food_name}</a> "
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
            "Try asking for something like: <em>'I want an Indian vegetarian dish under ₹300'</em> "
            "or <em>'Recommend a low calorie Italian lunch'</em>."
        )
        
    return jsonify({'reply': reply})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
