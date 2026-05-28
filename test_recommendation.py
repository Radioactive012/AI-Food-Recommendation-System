import unittest
import os
import sys
from app import app, db
from models.models import Food, User, Rating, RecommendationHistory
from ml.similarity_model import RecommendationEngine

class RecommendationEngineTestCase(unittest.TestCase):
    def setUp(self):
        # Configure app for testing
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:' # In-memory database
        self.app_context = app.app_context()
        self.app_context.push()
        
        # Ensure tables exist
        db.create_all()
        
        # Clear all records to ensure a clean state
        db.session.query(Rating).delete()
        db.session.query(RecommendationHistory).delete()
        db.session.query(Food).delete()
        db.session.query(User).delete()
        db.session.commit()
        
        # Populate mock foods
        self.mock_foods = [
            Food(
                food_id='f1',
                food_name='Veg Salad',
                cuisine='Italian',
                category='Lunch',
                calories=150,
                protein=4.0,
                carbs=10.0,
                fats=2.0,
                spice_level='Low',
                veg_nonveg='Veg',
                price=180.0,
                meal_type='Light',
                description='Fresh green salad with olive oil'
            ),
            Food(
                food_id='f2',
                food_name='Spicy Chicken Biryani',
                cuisine='Indian',
                category='Dinner',
                calories=650,
                protein=35.0,
                carbs=75.0,
                fats=18.0,
                spice_level='High',
                veg_nonveg='Non-Veg',
                price=320.0,
                meal_type='Heavy',
                description='Spicy layered rice cooked with chicken'
            ),
            Food(
                food_id='f3',
                food_name='Paneer Butter Masala',
                cuisine='Indian',
                category='Lunch',
                calories=450,
                protein=18.0,
                carbs=14.0,
                fats=32.0,
                spice_level='Medium',
                veg_nonveg='Veg',
                price=260.0,
                meal_type='Heavy',
                description='Cottage cheese cooked in rich butter gravy'
            )
        ]
        for f in self.mock_foods:
            db.session.add(f)
        db.session.commit()
        
        self.engine = RecommendationEngine()

    def tearDown(self):
        db.session.remove()
        self.app_context.pop()

    def test_rule_based_filtering_veg(self):
        """Verify that a vegetarian user does not receive non-vegetarian items."""
        user_profile = {
            'diet_type': 'Veg',
            'cuisine_preference': 'Indian',
            'spice_preference': 'Medium',
            'health_goal': 'Healthy Eating',
            'mood_preference': 'Neutral',
            'budget': 500
        }
        suggestions = self.engine.get_recommendations(user_profile, self.mock_foods, limit=5)
        
        # Verify suggestions only contain Veg
        for item in suggestions:
            self.assertEqual(item['food'].veg_nonveg, 'Veg')
            self.assertNotEqual(item['food'].food_name, 'Spicy Chicken Biryani')

    def test_cuisine_scoring_match(self):
        """Verify that preferred cuisine increases scores and is ranked higher."""
        user_profile = {
            'diet_type': 'Non-Veg',
            'cuisine_preference': 'Indian',
            'spice_preference': 'High',
            'health_goal': 'Maintenance',
            'mood_preference': 'Neutral',
            'budget': 500
        }
        suggestions = self.engine.get_recommendations(user_profile, self.mock_foods, limit=5)
        
        # Indian dishes should top the list
        first_suggestion = suggestions[0]['food']
        self.assertEqual(first_suggestion.cuisine, 'Indian')

    def test_health_goal_weight_loss(self):
        """Weight loss goal should prefer lower calorie options."""
        user_profile = {
            'diet_type': 'Veg',
            'cuisine_preference': 'Italian',
            'spice_preference': 'Low',
            'health_goal': 'Weight Loss',
            'mood_preference': 'Neutral',
            'budget': 500
        }
        suggestions = self.engine.get_recommendations(user_profile, self.mock_foods, limit=5)
        
        # Veg salad (150 kcal) should be ranked higher than Paneer Butter Masala (450 kcal)
        first_suggestion = suggestions[0]['food']
        self.assertEqual(first_suggestion.food_name, 'Veg Salad')

    def test_health_goal_muscle_gain(self):
        """Muscle gain goal should prefer higher protein options."""
        user_profile = {
            'diet_type': 'Non-Veg',
            'cuisine_preference': 'Indian',
            'spice_preference': 'High',
            'health_goal': 'Muscle Gain',
            'mood_preference': 'Neutral',
            'budget': 500
        }
        suggestions = self.engine.get_recommendations(user_profile, self.mock_foods, limit=5)
        
        # Spicy Chicken Biryani (35g protein) should be first
        first_suggestion = suggestions[0]['food']
        self.assertEqual(first_suggestion.food_name, 'Spicy Chicken Biryani')

if __name__ == '__main__':
    unittest.main()
