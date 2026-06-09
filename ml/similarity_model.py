import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import LabelEncoder
import os
import pickle
import re

class RecommendationEngine:
    def __init__(self):
        self.vectorizer = TfidfVectorizer(stop_words='english')
        
    def _get_food_metadata_string(self, food):
        """Converts food attributes to a single descriptive string for TF-IDF."""
        desc = getattr(food, 'description', None) or ""
        ingredients = getattr(food, 'ingredients', None) or ""
        meal_type = getattr(food, 'meal_type', None) or ""
        return f"{food.cuisine} {food.veg_nonveg} {food.spice_level} spice {food.category} {meal_type} {desc} {ingredients}".lower()

    def get_recommendations(self, user_profile, all_foods, rating_history=None, limit=6, user_allergies=None, all_ratings=None):
        """
        Hybrid recommendation function matching users with foods.
        Combines:
        1. Rule-based constraints (Diet type filtering + allergy filtering)
        2. Attribute scoring weights (Cuisine, spice, health goals, mood, budget)
        3. Content-based filtering (TF-IDF + Cosine Similarity of description tags)
        4. Collaborative filtering (user-item rating similarity)
        5. ML Rating prediction (Random Forest) if rating history is present
        """
        if not all_foods:
            return []

        # Normalise allergy list
        if user_allergies is None:
            user_allergies = []
        user_allergies_lower = [a.strip().lower() for a in user_allergies if a.strip()]

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

            # Allergy filtering: skip foods containing user's allergens
            if user_allergies_lower:
                food_allergens = [a.strip().lower() for a in (food.allergens or '').replace('|', ',').split(',') if a.strip()]
                if any(ua in food_allergens for ua in user_allergies_lower):
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

        # 4. PHASE 4: Collaborative Filtering
        cf_scores = self._collaborative_filtering_scores(
            rating_history, filtered_foods, all_foods, all_ratings=all_ratings
        )

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
            elif user_health == 'Diabetes-Friendly':
                # Low carbs, moderate protein, low sugar (approximated by low carbs)
                if food.carbs <= 30:
                    score += 5
                    explanations.append("is low in carbs (diabetes-friendly)")
                elif food.carbs <= 45:
                    score += 2
                elif food.carbs > 60:
                    score -= 3
                if food.protein >= 15:
                    score += 2
                    explanations.append("has good protein content for blood sugar stability")
            elif user_health == 'Heart-Healthy':
                # Low fat, low sodium (approximated by low fat), high fiber foods
                if food.fats <= 10:
                    score += 5
                    explanations.append("is low in fat (heart-healthy)")
                elif food.fats <= 18:
                    score += 2
                elif food.fats > 30:
                    score -= 3
                if food.calories <= 400:
                    score += 2
                    explanations.append("has moderate calories for cardiovascular health")

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

            # Add Collaborative Filtering score (+6 max)
            cf_bonus = cf_scores.get(food.food_id, 0)
            if cf_bonus > 0:
                score += cf_bonus
                explanations.append("users with similar tastes also enjoyed this dish")
                
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

    def _collaborative_filtering_scores(self, rating_history, candidate_foods, all_foods, all_ratings=None):
        """
        Hybrid collaborative filtering:
        1. Attribute overlap with items the user liked
        2. Cross-user patterns from stored ratings when available
        Returns a dict of {food_id: bonus_score}.
        """
        cf_scores = {}
        if not rating_history:
            return cf_scores

        liked_ids = {r.food_id for r in rating_history if r.rating >= 4}
        rated_ids = {r.food_id for r in rating_history}
        if not liked_ids:
            return cf_scores

        liked_foods = [f for f in all_foods if f.food_id in liked_ids]
        if liked_foods:
            liked_attrs = set()
            for food in liked_foods:
                liked_attrs.add(food.cuisine.lower())
                liked_attrs.add(food.category.lower())
                liked_attrs.add(food.spice_level.lower())
                liked_attrs.add(food.veg_nonveg.lower())
                if food.meal_type:
                    liked_attrs.add(food.meal_type.lower())

            for food in candidate_foods:
                if food.food_id in rated_ids:
                    continue
                food_attrs = {
                    food.cuisine.lower(), food.category.lower(),
                    food.spice_level.lower(), food.veg_nonveg.lower()
                }
                if food.meal_type:
                    food_attrs.add(food.meal_type.lower())
                overlap = len(food_attrs & liked_attrs)
                if overlap >= 3:
                    cf_scores[food.food_id] = min(overlap * 1.5, 6)
                elif overlap >= 2:
                    cf_scores[food.food_id] = overlap

        if all_ratings and hasattr(all_ratings[0] if all_ratings else None, 'user_id'):
            peer_users = {
                rating.user_id for rating in all_ratings
                if rating.food_id in liked_ids and rating.rating >= 4 and rating.user_id
            }
            for rating in all_ratings:
                if (
                    rating.user_id in peer_users
                    and rating.rating >= 4
                    and rating.food_id not in rated_ids
                ):
                    cf_scores[rating.food_id] = min(cf_scores.get(rating.food_id, 0) + 2, 8)

        return cf_scores

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

    def generate_meal_plan(self, all_foods, user_profile, days=7, user_allergies=None):
        """
        Generate a weekly meal plan with Breakfast, Lunch, Dinner, and Snack for each day.
        Distributes foods across days while respecting diet, allergies, and calorie targets.
        """
        if user_allergies is None:
            user_allergies = []
        user_allergies_lower = [a.strip().lower() for a in user_allergies if a.strip()]
        user_diet = user_profile.get('diet_type', 'Veg')

        # Filter foods by diet + allergies
        eligible = []
        for food in all_foods:
            if user_diet == 'Veg' and food.veg_nonveg != 'Veg':
                continue
            if user_diet == 'Vegan':
                desc = (food.description or "").lower()
                name = food.food_name.lower()
                if food.veg_nonveg != 'Veg' or any(x in name or x in desc for x in ['milk', 'cheese', 'paneer', 'egg', 'butter', 'ghee', 'cream', 'alfredo', 'mozzarella', 'pancake']):
                    continue
            if user_allergies_lower:
                food_allergens = [a.strip().lower() for a in (food.allergens or '').replace('|', ',').split(',') if a.strip()]
                if any(ua in food_allergens for ua in user_allergies_lower):
                    continue
            eligible.append(food)

        if not eligible:
            return []

        # Categorize foods by meal category
        breakfasts = [f for f in eligible if f.category == 'Breakfast']
        lunches = [f for f in eligible if f.category == 'Lunch']
        dinners = [f for f in eligible if f.category == 'Dinner']
        snacks = [f for f in eligible if f.category == 'Snacks']

        # Fallbacks if categories are empty
        if not breakfasts:
            breakfasts = [f for f in eligible if f.meal_type == 'Light'][:5] or eligible[:3]
        if not lunches:
            lunches = eligible[:5]
        if not dinners:
            dinners = eligible[:5]
        if not snacks:
            snacks = [f for f in eligible if f.meal_type == 'Light'][:5] or eligible[:3]

        # Health goal calorie targets
        health_goal = user_profile.get('health_goal', 'Healthy Eating')
        daily_cal_target = 2000
        if health_goal == 'Weight Loss':
            daily_cal_target = 1500
        elif health_goal == 'Muscle Gain':
            daily_cal_target = 2500
        elif health_goal == 'Diabetes-Friendly':
            daily_cal_target = 1800
        elif health_goal == 'Heart-Healthy':
            daily_cal_target = 1800

        plan = []
        used_ids = set()

        for day in range(days):
            day_plan = {'day_index': day, 'slots': {}}

            for slot_name, pool in [('Breakfast', breakfasts), ('Lunch', lunches), ('Dinner', dinners), ('Snack', snacks)]:
                # Try to pick an unused food, fallback to any
                candidates = [f for f in pool if f.food_id not in used_ids]
                if not candidates:
                    candidates = pool
                # Score by health goal fit
                best = sorted(candidates, key=lambda f: self._meal_plan_score(f, health_goal, daily_cal_target, slot_name), reverse=True)
                pick = best[0] if best else pool[0]
                day_plan['slots'][slot_name] = pick
                used_ids.add(pick.food_id)

            plan.append(day_plan)

        return plan

    def _meal_plan_score(self, food, health_goal, daily_cal_target, slot):
        """Score a food item for meal plan slot suitability."""
        score = 0
        slot_cal_target = daily_cal_target * {'Breakfast': 0.25, 'Lunch': 0.35, 'Dinner': 0.30, 'Snack': 0.10}.get(slot, 0.25)

        # Calorie closeness
        cal_diff = abs(food.calories - slot_cal_target)
        score += max(0, 10 - cal_diff / 30)

        if health_goal == 'Weight Loss' and food.calories <= 350:
            score += 5
        elif health_goal == 'Muscle Gain' and food.protein >= 20:
            score += 5
        elif health_goal == 'Diabetes-Friendly' and food.carbs <= 35:
            score += 5
        elif health_goal == 'Heart-Healthy' and food.fats <= 12:
            score += 5

        # Prefer matching category
        slot_to_cat = {'Breakfast': 'Breakfast', 'Lunch': 'Lunch', 'Dinner': 'Dinner', 'Snack': 'Snacks'}
        if food.category == slot_to_cat.get(slot):
            score += 8

        # Add randomness to avoid monotony
        score += np.random.uniform(0, 3)
        return score


def parse_natural_language_search(query):
    """
    Parse a natural language query into structured search constraints.
    Example: 'healthy vegetarian Italian dinner under 500 calories' ->
    {diet: 'Veg', cuisine: 'Italian', category: 'Dinner', max_calories: 500, health_keywords: ['healthy']}
    """
    query_lower = query.lower().strip()
    if not query_lower:
        return {}

    constraints = {}

    # Diet detection
    if re.search(r'\b(vegan)\b', query_lower):
        constraints['diet'] = 'Vegan'
    elif re.search(r'\bnon[\s-]?(veg|vegetarian)\b', query_lower):
        constraints['diet'] = 'Non-Veg'
    elif re.search(r'\b(veg|vegetarian)\b', query_lower):
        constraints['diet'] = 'Veg'

    # Cuisine detection
    cuisines = ['indian', 'italian', 'chinese', 'american', 'japanese', 'mexican']
    for c in cuisines:
        if c in query_lower:
            constraints['cuisine'] = c.capitalize()
            break

    # Category / meal time
    meal_map = {
        'breakfast': 'Breakfast', 'lunch': 'Lunch', 'dinner': 'Dinner',
        'snack': 'Snacks', 'snacks': 'Snacks'
    }
    for term, cat in meal_map.items():
        if re.search(rf'\b{re.escape(term)}\b', query_lower):
            constraints['category'] = cat
            break

    # Calorie constraint
    cal_match = re.search(r'(?:under|below|less than|max(?:imum)?)\s*(\d+)\s*(?:cal|kcal|calories)', query_lower)
    if cal_match:
        constraints['max_calories'] = int(cal_match.group(1))

    # Protein constraint
    prot_match = re.search(r'(?:at least|min(?:imum)?|over|more than)\s*(\d+)\s*(?:g|gram)?\s*protein', query_lower)
    if prot_match:
        constraints['min_protein'] = int(prot_match.group(1))

    # Budget constraint
    budget_match = re.search(r'(?:under|below|within|less than|max(?:imum)?|budget(?: of)?)\s*(?:rs\.?|₹)?\s*(\d+(?:\.\d+)?)', query_lower)
    if budget_match and 'max_calories' not in constraints:  # avoid double-matching calorie numbers
        constraints['max_budget'] = float(budget_match.group(1))

    # Spice level
    if any(term in query_lower for term in ['spicy', 'hot', 'fiery']):
        constraints['spice'] = 'High'
    elif any(term in query_lower for term in ['mild', 'not spicy', 'bland']):
        constraints['spice'] = 'Low'

    # Health keywords
    health_keywords = []
    if any(term in query_lower for term in ['healthy', 'clean', 'light', 'wholesome']):
        health_keywords.append('healthy')
    if any(term in query_lower for term in ['high protein', 'protein rich', 'protein']):
        health_keywords.append('high_protein')
    if any(term in query_lower for term in ['low calorie', 'diet', 'weight loss']):
        health_keywords.append('low_calorie')
    if any(term in query_lower for term in ['diabetes', 'diabetic', 'low carb', 'sugar free']):
        health_keywords.append('diabetes_friendly')
    if any(term in query_lower for term in ['heart healthy', 'heart', 'low fat', 'cardiac']):
        health_keywords.append('heart_healthy')
    if health_keywords:
        constraints['health_keywords'] = health_keywords

    return constraints


def apply_nl_constraints(foods, constraints):
    """Filter and sort foods based on parsed NL constraints."""
    filtered = list(foods)

    if 'diet' in constraints:
        diet = constraints['diet']
        if diet == 'Veg':
            filtered = [f for f in filtered if f.veg_nonveg == 'Veg']
        elif diet == 'Non-Veg':
            filtered = [f for f in filtered if f.veg_nonveg == 'Non-Veg']

    if 'cuisine' in constraints:
        filtered = [f for f in filtered if f.cuisine.lower() == constraints['cuisine'].lower()]

    if 'category' in constraints:
        filtered = [f for f in filtered if f.category == constraints['category']]

    if 'max_calories' in constraints:
        filtered = [f for f in filtered if f.calories <= constraints['max_calories']]

    if 'min_protein' in constraints:
        filtered = [f for f in filtered if f.protein >= constraints['min_protein']]

    if 'max_budget' in constraints:
        filtered = [f for f in filtered if f.price <= constraints['max_budget']]

    if 'spice' in constraints:
        filtered = [f for f in filtered if f.spice_level == constraints['spice']]

    return filtered
