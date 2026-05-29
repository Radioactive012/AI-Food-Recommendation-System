import unittest

from ml.similarity_model import RecommendationEngine


class FoodStub:
    def __init__(
        self,
        food_id,
        food_name,
        cuisine,
        category,
        calories,
        protein,
        carbs,
        fats,
        spice_level,
        veg_nonveg,
        price,
        meal_type,
        description,
    ):
        self.food_id = food_id
        self.food_name = food_name
        self.cuisine = cuisine
        self.category = category
        self.calories = calories
        self.protein = protein
        self.carbs = carbs
        self.fats = fats
        self.spice_level = spice_level
        self.veg_nonveg = veg_nonveg
        self.price = price
        self.meal_type = meal_type
        self.description = description


class RecommendationEngineTestCase(unittest.TestCase):
    def setUp(self):
        self.mock_foods = [
            FoodStub(
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
                description='Fresh green salad with olive oil',
            ),
            FoodStub(
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
                description='Spicy layered rice cooked with chicken',
            ),
            FoodStub(
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
                description='Cottage cheese cooked in rich butter gravy',
            ),
        ]
        self.engine = RecommendationEngine()

    def test_rule_based_filtering_veg(self):
        """Verify that a vegetarian user does not receive non-vegetarian items."""
        user_profile = {
            'diet_type': 'Veg',
            'cuisine_preference': 'Indian',
            'spice_preference': 'Medium',
            'health_goal': 'Healthy Eating',
            'mood_preference': 'Neutral',
            'budget': 500,
        }
        suggestions = self.engine.get_recommendations(user_profile, self.mock_foods, limit=5)

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
            'budget': 500,
        }
        suggestions = self.engine.get_recommendations(user_profile, self.mock_foods, limit=5)

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
            'budget': 500,
        }
        suggestions = self.engine.get_recommendations(user_profile, self.mock_foods, limit=5)

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
            'budget': 500,
        }
        suggestions = self.engine.get_recommendations(user_profile, self.mock_foods, limit=5)

        first_suggestion = suggestions[0]['food']
        self.assertEqual(first_suggestion.food_name, 'Spicy Chicken Biryani')


if __name__ == '__main__':
    unittest.main()
