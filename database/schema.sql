-- Database Schema for AI-Powered Personalized Food Recommendation System

-- Users Table
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    age INT,
    gender VARCHAR(20),
    diet_type VARCHAR(20),      -- 'Veg', 'Non-Veg', 'Vegan'
    spice_preference VARCHAR(10),-- 'Low', 'Medium', 'High'
    health_goal VARCHAR(50),     -- 'Weight Loss', 'Muscle Gain', 'Maintenance', 'Healthy Eating', 'Diabetes-Friendly', 'Heart-Healthy'
    mood_preference VARCHAR(50), -- 'Stressed', 'Energetic', 'Tired', 'Neutral'
    allergies TEXT,              -- Comma-separated: 'Gluten,Dairy,Nuts'
    learned_prefs TEXT,          -- JSON preference frequency data
    is_verified BOOLEAN DEFAULT 0 NOT NULL,
    otp_code VARCHAR(6),
    otp_expiry TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Foods Table
CREATE TABLE IF NOT EXISTS foods (
    food_id VARCHAR(36) PRIMARY KEY,
    food_name VARCHAR(100) NOT NULL,
    cuisine VARCHAR(50) NOT NULL,     -- 'Indian', 'Italian', 'Chinese', 'Mexican', 'American', 'Japanese'
    category VARCHAR(50) NOT NULL,    -- 'Breakfast', 'Lunch', 'Dinner', 'Snacks'
    calories INT NOT NULL,
    protein FLOAT NOT NULL,           -- grams
    carbs FLOAT NOT NULL,             -- grams
    fats FLOAT NOT NULL,              -- grams
    spice_level VARCHAR(10) NOT NULL, -- 'Low', 'Medium', 'High'
    veg_nonveg VARCHAR(10) NOT NULL,  -- 'Veg', 'Non-Veg'
    price FLOAT NOT NULL,
    meal_type VARCHAR(20),            -- 'Heavy', 'Light', 'Snack'
    image_url VARCHAR(255),
    description TEXT,
    ingredients TEXT,                  -- Comma-separated ingredient list
    allergens TEXT                     -- Pipe-separated: 'Gluten|Dairy|Nuts'
);

-- Ratings Table
CREATE TABLE IF NOT EXISTS ratings (
    rating_id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    food_id VARCHAR(36) NOT NULL,
    rating INT CHECK (rating BETWEEN 1 AND 5),
    review TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (food_id) REFERENCES foods(food_id) ON DELETE CASCADE
);

-- Recommendation History Table
CREATE TABLE IF NOT EXISTS recommendation_history (
    history_id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    recommended_food_id VARCHAR(36) NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (recommended_food_id) REFERENCES foods(food_id) ON DELETE CASCADE
);

-- Meal Plans Table
CREATE TABLE IF NOT EXISTS meal_plans (
    plan_id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36),
    session_id VARCHAR(64),
    plan_name VARCHAR(100) DEFAULT 'My Meal Plan',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Meal Plan Items Table
CREATE TABLE IF NOT EXISTS meal_plan_items (
    item_id VARCHAR(36) PRIMARY KEY,
    plan_id VARCHAR(36) NOT NULL,
    food_id VARCHAR(36) NOT NULL,
    day_index INT NOT NULL,      -- 0=Monday .. 6=Sunday
    slot VARCHAR(20) NOT NULL,    -- 'Breakfast', 'Lunch', 'Dinner', 'Snack'
    FOREIGN KEY (plan_id) REFERENCES meal_plans(plan_id) ON DELETE CASCADE,
    FOREIGN KEY (food_id) REFERENCES foods(food_id) ON DELETE CASCADE
);

-- Admin Table
CREATE TABLE IF NOT EXISTS admin (
    admin_id VARCHAR(36) PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL
);
