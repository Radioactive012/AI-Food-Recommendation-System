import uuid
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

def generate_uuid():
    return str(uuid.uuid4())

class User(db.Model):
    __tablename__ = 'users'
    
    user_id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    age = db.Column(db.Integer, nullable=True)
    gender = db.Column(db.String(20), nullable=True)
    diet_type = db.Column(db.String(20), nullable=True)      # 'Veg', 'Non-Veg', 'Vegan'
    spice_preference = db.Column(db.String(10), nullable=True) # 'Low', 'Medium', 'High'
    health_goal = db.Column(db.String(50), nullable=True)     # 'Weight Loss', 'Muscle Gain', 'Maintenance', 'Healthy Eating', 'Diabetes-Friendly', 'Heart-Healthy'
    mood_preference = db.Column(db.String(50), nullable=True) # 'Stressed', 'Energetic', 'Tired', 'Neutral'
    allergies = db.Column(db.Text, nullable=True)             # Comma-separated: 'Gluten,Dairy,Nuts'
    learned_prefs = db.Column(db.Text, nullable=True)         # JSON: cuisine/category frequency counts
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    ratings = db.relationship('Rating', backref='user', lazy=True, cascade="all, delete-orphan")
    history = db.relationship('RecommendationHistory', backref='user', lazy=True, cascade="all, delete-orphan")
    meal_plans = db.relationship('MealPlan', backref='user', lazy=True, cascade="all, delete-orphan")

    def get_allergies_list(self):
        if not self.allergies:
            return []
        return [a.strip() for a in self.allergies.split(',') if a.strip()]

class Food(db.Model):
    __tablename__ = 'foods'
    
    food_id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    food_name = db.Column(db.String(100), nullable=False)
    cuisine = db.Column(db.String(50), nullable=False)     # 'Indian', 'Italian', 'Chinese', etc.
    category = db.Column(db.String(50), nullable=False)    # 'Breakfast', 'Lunch', 'Dinner', 'Snacks'
    calories = db.Column(db.Integer, nullable=False)
    protein = db.Column(db.Float, nullable=False)           # grams
    carbs = db.Column(db.Float, nullable=False)             # grams
    fats = db.Column(db.Float, nullable=False)              # grams
    spice_level = db.Column(db.String(10), nullable=False) # 'Low', 'Medium', 'High'
    veg_nonveg = db.Column(db.String(10), nullable=False)  # 'Veg', 'Non-Veg'
    price = db.Column(db.Float, nullable=False)
    meal_type = db.Column(db.String(20), nullable=True)     # 'Heavy', 'Light', 'Snack'
    image_url = db.Column(db.String(255), nullable=True)
    description = db.Column(db.Text, nullable=True)
    ingredients = db.Column(db.Text, nullable=True)         # Comma-separated: 'paneer,yogurt,spices,oil'
    allergens = db.Column(db.Text, nullable=True)           # Comma-separated: 'Dairy,Gluten'
    
    # Relationships
    ratings = db.relationship('Rating', backref='food', lazy=True, cascade="all, delete-orphan")
    history = db.relationship('RecommendationHistory', backref='food', lazy=True, cascade="all, delete-orphan")

    def get_ingredients_list(self):
        if not self.ingredients:
            return []
        return [i.strip() for i in self.ingredients.split(',') if i.strip()]

    def get_allergens_list(self):
        if not self.allergens:
            return []
        return [a.strip() for a in self.allergens.split(',') if a.strip()]

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
            'description': self.description,
            'ingredients': self.ingredients,
            'allergens': self.allergens,
        }

class Rating(db.Model):
    __tablename__ = 'ratings'
    
    rating_id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    user_id = db.Column(db.String(36), db.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False)
    food_id = db.Column(db.String(36), db.ForeignKey('foods.food_id', ondelete='CASCADE'), nullable=False)
    rating = db.Column(db.Integer, nullable=False) # 1 to 5
    review = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class RecommendationHistory(db.Model):
    __tablename__ = 'recommendation_history'
    
    history_id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    user_id = db.Column(db.String(36), db.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False)
    recommended_food_id = db.Column(db.String(36), db.ForeignKey('foods.food_id', ondelete='CASCADE'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class MealPlan(db.Model):
    __tablename__ = 'meal_plans'

    plan_id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    user_id = db.Column(db.String(36), db.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=True)
    session_id = db.Column(db.String(64), nullable=True)
    plan_name = db.Column(db.String(100), default='My Meal Plan')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    items = db.relationship('MealPlanItem', backref='meal_plan', lazy=True, cascade="all, delete-orphan",
                            order_by='MealPlanItem.day_index, MealPlanItem.slot')

class MealPlanItem(db.Model):
    __tablename__ = 'meal_plan_items'

    item_id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    plan_id = db.Column(db.String(36), db.ForeignKey('meal_plans.plan_id', ondelete='CASCADE'), nullable=False)
    food_id = db.Column(db.String(36), db.ForeignKey('foods.food_id', ondelete='CASCADE'), nullable=False)
    day_index = db.Column(db.Integer, nullable=False)   # 0=Monday .. 6=Sunday
    slot = db.Column(db.String(20), nullable=False)      # 'Breakfast', 'Lunch', 'Dinner', 'Snack'

    food = db.relationship('Food', lazy=True)

class Admin(db.Model):
    __tablename__ = 'admin'
    
    admin_id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
