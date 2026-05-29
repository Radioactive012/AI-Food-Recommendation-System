import os
import secrets
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    # Use SECRET_KEY in production. The generated fallback keeps local demos working
    # without committing a reusable session-signing secret.
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    
    # Database Configuration
    # Fallback to SQLite if DATABASE_URL is not provided or empty
    db_url = os.environ.get('DATABASE_URL')
    
    if not db_url:
        db_url = 'sqlite:///food_recommendation.db'
    
    # SQLAlchemy connection string adjustment for PyMySQL
    if db_url.startswith('mysql://'):
        db_url = db_url.replace('mysql://', 'mysql+pymysql://')
        
    SQLALCHEMY_DATABASE_URI = db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Gemini API Configuration
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
