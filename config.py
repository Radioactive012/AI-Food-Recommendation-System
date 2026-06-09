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
        if os.environ.get('VERCEL'):
            db_url = 'sqlite:////tmp/food_recommendation.db'
        else:
            db_url = 'sqlite:///food_recommendation.db'
    
    # SQLAlchemy connection string adjustments
    if db_url.startswith('mysql://'):
        db_url = db_url.replace('mysql://', 'mysql+pymysql://')
    elif db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://')
        
    SQLALCHEMY_DATABASE_URI = db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # OpenRouter API Configuration
    OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
    OPENROUTER_MODEL = os.environ.get('OPENROUTER_MODEL', 'nvidia/nemotron-3-ultra-550b-a55b:free')
    OPENROUTER_SITE_URL = os.environ.get('OPENROUTER_SITE_URL', 'http://127.0.0.1:8080')
    OPENROUTER_TIMEOUT_SECONDS = float(os.environ.get('OPENROUTER_TIMEOUT_SECONDS', 55))
