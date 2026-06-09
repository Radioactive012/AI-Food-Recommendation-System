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
    health_goal = db.Column(db.String(50), nullable=True)     # 'Weight Loss', 'Muscle Gain', 'Maintenance', 'Healthy Eating'
    mood_preference = db.Column(db.String(50), nullable=True) # 'Stressed', 'Energetic', 'Tired', 'Neutral'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    ratings = db.relationship('Rating', backref='user', lazy=True, cascade="all, delete-orphan")
    history = db.relationship('RecommendationHistory', backref='user', lazy=True, cascade="all, delete-orphan")

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
    
    # Relationships
    ratings = db.relationship('Rating', backref='food', lazy=True, cascade="all, delete-orphan")
    history = db.relationship('RecommendationHistory', backref='food', lazy=True, cascade="all, delete-orphan")

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

class Admin(db.Model):
    __tablename__ = 'admin'
    
    admin_id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
