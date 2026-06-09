import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import LabelEncoder
import os
import pickle

class RecommendationEngine:
    def __init__(self):
        self.vectorizer = TfidfVectorizer(stop_words='english')
        
    def _get_food_metadata_string(self, food):
        """Converts food attributes to a single descriptive string for TF-IDF."""
        desc = food.description or ""
        return f"{food.cuisine} {food.veg_nonveg} {food.spice_level} spice {food.category} {food.meal_type or ''} {desc}".lower()

    def get_recommendations(self, user_profile, all_foods, rating_history=None, limit=6):
        """
        Hybrid recommendation function matching users with foods.
        Combines:
        1. Rule-based constraints (Diet type filtering)
        2. Attribute scoring weights (Cuisine, spice, health goals, mood, budget)
        3. Content-based filtering (TF-IDF + Cosine Similarity of description tags)
        4. ML Rating prediction (Random Forest) if rating history is present
        """
        if not all_foods:
            return []
            
        # 1. PHASE 1: Rule-Based Filtering
        filtered_foods = []
        user_diet = user_profile.get('diet_type', 'Veg') # Default to Veg for safety
        
        for food in all_foods:
            # Rule: If user is Veg, they only get Veg foods.
            if user_diet == 'Veg' and food.veg_nonveg != 'Veg':
                continue
            # Rule: If user is Vegan, they only get Vegan-friendly options
            # Since we don't have a Vegan flag, let's treat salad, smoothie, oatmeal, stir-fry, fruit as vegan
            if user_diet == 'Vegan':
                is_vegan = False
                desc = (food.description or "").lower()
                name = food.food_name.lower()
                if food.veg_nonveg == 'Veg' and not any(x in name or x in desc for x in ['milk', 'cheese', 'paneer', 'egg', 'butter', 'ghee', 'cream', 'alfredo', 'mozzarella', 'pancake']):
                    is_vegan = True
                if not is_vegan:
                    continue
            filtered_foods.append(food)
            
        if not filtered_foods:
            return []

        # Prepare lists for scoring
        scored_foods = []
        
        # 2. PHASE 2: Multi-Factor Scoring
        user_cuisine = user_profile.get('cuisine_preference')
        user_spice = user_profile.get('spice_preference')
        user_health = user_profile.get('health_goal')
        user_mood = user_profile.get('mood_preference')
        user_budget = float(user_profile.get('budget', 1000))
        
        # 3. PHASE 3: Content-Based Filtering (TF-IDF + Cosine Similarity)
        # Create user preference query string
        user_query_parts = []
        if user_cuisine: user_query_parts.append(user_cuisine)
        if user_diet: user_query_parts.append(user_diet)
        if user_spice: user_query_parts.append(f"{user_spice} spice")
        if user_health: user_query_parts.append(user_health)
        if user_mood: user_query_parts.append(user_mood)
        user_query = " ".join(user_query_parts).lower()
        
        # Build corpus of filtered foods
        corpus = [self._get_food_metadata_string(f) for f in filtered_foods]
        
        # Calculate Cosine Similarities
        try:
            tfidf_matrix = self.vectorizer.fit_transform(corpus)
            user_vector = self.vectorizer.transform([user_query])
            cos_similarities = cosine_similarity(user_vector, tfidf_matrix).flatten()
        except Exception:
            cos_similarities = np.zeros(len(filtered_foods))

        # Check if pre-trained ML model is available or train on rating history
        ml_model = None
        if rating_history and len(rating_history) >= 5:
            # We have enough ratings to try to load or train a predictor
            ml_model = self._train_or_load_ml_model(rating_history, all_foods)

        # Iterate and compile scores
        for idx, food in enumerate(filtered_foods):
            score = 0
            explanations = []
            
            # Match Cuisine (+5)
            if user_cuisine and food.cuisine.lower() == user_cuisine.lower():
                score += 5
                explanations.append(f"matches your preferred cuisine ({food.cuisine})")
                
            # Match Spice (+4)
            if user_spice and food.spice_level.lower() == user_spice.lower():
                score += 4
                explanations.append(f"matches your spice tolerance ({food.spice_level})")
                
            # Match Budget (+2)
            if food.price <= user_budget:
                score += 2
            else:
                score -= 3 # penalty for exceeding budget
                
            # Match Health Goal (+4)
            if user_health == 'Weight Loss':
                if food.calories < 300:
                    score += 4
                    explanations.append("is low in calories (ideal for weight loss)")
                elif food.calories > 500:
                    score -= 2 # penalize very heavy foods for weight loss
            elif user_health == 'Muscle Gain':
                if food.protein >= 20:
                    score += 4
                    explanations.append("is high in protein (supports muscle gain)")
            elif user_health == 'Maintenance':
                if 300 <= food.calories <= 500:
                    score += 4
                    explanations.append("has a balanced calorie profile for maintenance")
            elif user_health == 'Healthy Eating':
                if food.calories < 400 and food.fats < 15:
                    score += 4
                    explanations.append("is a light and wholesome clean eating option")

            # Match Mood (+3)
            comfort_keywords = ['pizza', 'burger', 'cream', 'butter', 'chocolate', 'pancake', 'fried', 'ramen', 'cheese']
            energy_keywords = ['smoothie', 'oatmeal', 'fruit', 'chia', 'salad', 'salmon', 'egg']
            
            food_desc_lower = (food.description or "").lower() + " " + food.food_name.lower()
            
            if user_mood == 'Stressed':
                # Comfort food search
                if any(k in food_desc_lower for k in comfort_keywords) or food.meal_type == 'Heavy':
                    score += 3
                    explanations.append("is a rich comfort food to help with stress")
            elif user_mood == 'Tired':
                # Energy foods
                if any(k in food_desc_lower for k in energy_keywords) or food.category == 'Breakfast':
                    score += 3
                    explanations.append("provides quick, nourishing energy for fatigue")
            elif user_mood == 'Energetic' or user_mood == 'Gym Mode':
                # High protein / satisfying meals
                if food.protein >= 15 or food.meal_type == 'Heavy':
                    score += 3
                    explanations.append("is satisfying and nutrient-dense for an active state")

            # Add Content similarity score (scaled to 10 points max)
            sim_score = cos_similarities[idx]
            score += sim_score * 10
            if sim_score > 0.2:
                explanations.append("matches your taste keywords and tags")
                
            # Predict user rating using ML Model if available (+5 points max based on prediction)
            ml_pred = 0
            if ml_model:
                try:
                    pred_rating = self._predict_single_rating(ml_model, user_profile, food)
                    # Scaled prediction: mapping 1-5 rating to 0-5 bonus points
                    score += pred_rating
                    if pred_rating >= 4.0:
                        explanations.append("our ML model predicts you will love this dish")
                except Exception:
                    pass

            # Construct explanation text
            if not explanations:
                explanation_str = "Recommended based on your dietary preferences."
            else:
                # Combine distinct matches
                explanation_str = "Recommended because it " + ", and it ".join(explanations) + "."
                
            scored_foods.append({
                'food': food,
                'score': score,
                'similarity_score': float(sim_score),
                'explanation': explanation_str
            })
            
        # Sort by score descending
        scored_foods.sort(key=lambda x: x['score'], reverse=True)
        return scored_foods[:limit]

    def _train_or_load_ml_model(self, rating_history, all_foods):
        """
        Helper to train a Random Forest model using the user ratings history.
        """
        try:
            # Build training dataframe
            rows = []
            for r in rating_history:
                # Get the food item
                food_item = next((f for f in all_foods if f.food_id == r.food_id), None)
                if not food_item:
                    continue
                # Compile feature vector
                row = {
                    'rating': r.rating,
                    # Food Features
                    'calories': food_item.calories,
                    'protein': food_item.protein,
                    'carbs': food_item.carbs,
                    'fats': food_item.fats,
                    'price': food_item.price,
                    'veg_nonveg': 1 if food_item.veg_nonveg == 'Veg' else 0,
                    # User features from rating context or generic
                    'user_age': 25, # default fallback
                }
                rows.append(row)
                
            if len(rows) < 5:
                return None
                
            df = pd.DataFrame(rows)
            X = df.drop('rating', axis=1)
            y = df['rating']
            
            rf = RandomForestRegressor(n_estimators=10, random_state=42)
            rf.fit(X, y)
            return rf
        except Exception:
            return None

    def _predict_single_rating(self, model, user_profile, food):
        """Predicts rating for a single food item using the trained model."""
        # Align features with training features
        features = pd.DataFrame([{
            'calories': food.calories,
            'protein': food.protein,
            'carbs': food.carbs,
            'fats': food.fats,
            'price': food.price,
            'veg_nonveg': 1 if food.veg_nonveg == 'Veg' else 0,
            'user_age': int(user_profile.get('age', 25) or 25)
        }])
        pred = model.predict(features)[0]
        return float(pred)
