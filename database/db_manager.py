import os
import csv
from werkzeug.security import generate_password_hash
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, inspect, text
from sqlalchemy.exc import IntegrityError
from models.models import db, Food, Admin
import uuid


def _add_missing_columns(table_name, columns):
    inspector = inspect(db.engine)
    if table_name not in inspector.get_table_names():
        return

    existing_columns = {column['name'] for column in inspector.get_columns(table_name)}
    dialect = db.engine.dialect
    preparer = dialect.identifier_preparer
    changed = False

    for column_name, column_type, options in columns:
        if column_name in existing_columns:
            continue

        column_type_sql = column_type.compile(dialect=dialect)
        statement = (
            f"ALTER TABLE {preparer.quote(table_name)} "
            f"ADD COLUMN {preparer.quote(column_name)} {column_type_sql}"
        )
        if options:
            statement += f" {options}"
        db.session.execute(text(statement))
        changed = True

    if changed:
        db.session.commit()


def _migrate_schema():
    """Add new columns to existing SQLite tables when needed."""
    _add_missing_columns('users', [
        ('learned_prefs', Text(), ''),
        ('is_verified', Boolean(), 'DEFAULT FALSE NOT NULL'),
        ('otp_code', String(6), ''),
        ('otp_expiry', DateTime(), ''),
    ])
    _add_missing_columns('foods', [
        ('meal_type', String(20), ''),
        ('image_url', String(255), ''),
        ('description', Text(), ''),
        ('ingredients', Text(), ''),
        ('allergens', Text(), ''),
    ])
    _add_missing_columns('ratings', [
        ('review', Text(), ''),
        ('created_at', DateTime(), 'DEFAULT CURRENT_TIMESTAMP'),
    ])
    _add_missing_columns('meal_plans', [
        ('session_id', String(64), ''),
        ('plan_name', String(100), "DEFAULT 'My Meal Plan'"),
        ('created_at', DateTime(), 'DEFAULT CURRENT_TIMESTAMP'),
    ])
    _add_missing_columns('meal_plan_items', [
        ('day_index', Integer(), ''),
        ('slot', String(20), ''),
    ])


def _food_from_csv_row(row):
    return Food(
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
        description=row.get('description', ''),
        ingredients=row.get('ingredients', ''),
        allergens=row.get('allergens', ''),
    )


def _seed_missing_foods_from_csv(app):
    csv_path = os.path.join(app.root_path, 'datasets', 'foods.csv')
    if not os.path.exists(csv_path):
        print(f"Warning: datasets/foods.csv not found at {csv_path}. Skipping food seeding.")
        return

    existing_ids = {food_id for (food_id,) in db.session.query(Food.food_id).all()}
    inserted = 0

    with open(csv_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['food_id'] in existing_ids:
                continue
            db.session.add(_food_from_csv_row(row))
            inserted += 1

    if inserted:
        try:
            db.session.commit()
            print(f"Seeded {inserted} missing foods from {csv_path}.")
        except IntegrityError:
            db.session.rollback()
            print("Food seed skipped because another instance inserted the missing CSV rows.")
    else:
        print(f"Foods table already has all CSV seed items ({len(existing_ids)} items).")


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
        _migrate_schema()
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
            
        # Seed any CSV foods that are not already present. Existing rows are
        # left untouched so admin edits are not overwritten on startup.
        _seed_missing_foods_from_csv(app)
