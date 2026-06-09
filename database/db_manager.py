import os
import csv
from werkzeug.security import generate_password_hash
from models.models import db, Food, Admin
import uuid

def init_db(app):
    """
    Initializes the database:
    1. Creates all tables.
    2. Seeds foods from datasets/foods.csv if the foods table is empty.
    3. Seeds a default admin account if the admin table is empty.
    """
    with app.app_context():
        # Create all tables if they don't exist
        db.create_all()
        print("Database tables checked/created successfully.")
        
        # Check if admin table is empty and seed an admin only when credentials
        # are provided through the environment.
        admin_count = Admin.query.count()
        if admin_count == 0:
            admin_username = os.environ.get("ADMIN_USERNAME")
            admin_password = os.environ.get("ADMIN_PASSWORD")
            if admin_username and admin_password:
                default_admin = Admin(
                    admin_id=str(uuid.uuid4()),
                    username=admin_username,
                    password=generate_password_hash(admin_password, method='pbkdf2:sha256')
                )
                db.session.add(default_admin)
                db.session.commit()
                print(f"Default admin created (username: {admin_username}).")
            else:
                print("Skipping admin seed; set ADMIN_USERNAME and ADMIN_PASSWORD to create one.")
            
        # Check if foods table is empty and seed from datasets/foods.csv
        food_count = Food.query.count()
        if food_count == 0:
            csv_path = os.path.join(app.root_path, 'datasets', 'foods.csv')
            if os.path.exists(csv_path):
                print(f"Seeding foods from {csv_path}...")
                with open(csv_path, mode='r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Clean up values
                        food = Food(
                            food_id=row['food_id'],
                            food_name=row['food_name'],
                            cuisine=row['cuisine'],
                            category=row['category'],
                            calories=int(row['calories']),
                            protein=float(row['protein']),
                            carbs=float(row['carbs']),
                            fats=float(row['fats']),
                            spice_level=row['spice_level'],
                            veg_nonveg=row['veg_nonveg'],
                            price=float(row['price']),
                            meal_type=row.get('meal_type', 'Heavy'),
                            image_url=row.get('image_url', ''),
                            description=row.get('description', '')
                        )
                        db.session.add(food)
                db.session.commit()
                print(f"Successfully seeded {Food.query.count()} foods.")
            else:
                print(f"Warning: datasets/foods.csv not found at {csv_path}. Skipping food seeding.")
        else:
            print(f"Foods table already seeded with {food_count} items.")
