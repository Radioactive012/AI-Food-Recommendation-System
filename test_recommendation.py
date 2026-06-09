import unittest
import os
from unittest.mock import Mock, patch

# Keep route tests isolated from the developer's local SQLite file. This must be
# set before importing app because app.py initializes SQLAlchemy at import time.
ORIGINAL_DATABASE_URL = os.environ.get('DATABASE_URL')
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import app
from ml.similarity_model import RecommendationEngine
from models.models import db, Food
from database.db_manager import init_db


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


class FlaskRouteTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_admin_username = os.environ.get('ADMIN_USERNAME')
        cls.original_admin_password = os.environ.get('ADMIN_PASSWORD')

    def setUp(self):
        app.config['TESTING'] = True
        app.config['OPENROUTER_API_KEY'] = ''
        app.config['OPENROUTER_MODEL'] = 'nvidia/nemotron-3-ultra-550b-a55b:free'
        app.config['OPENROUTER_TIMEOUT_SECONDS'] = 55
        os.environ['ADMIN_USERNAME'] = 'admin'
        os.environ['ADMIN_PASSWORD'] = 'secret'
        self.client = app.test_client()

        with app.app_context():
            db.drop_all()
            db.create_all()
            db.session.add_all([
                Food(
                    food_id='veg_spicy_dinner',
                    food_name='Veg Spicy Dinner Bowl',
                    cuisine='Indian',
                    category='Dinner',
                    calories=360,
                    protein=18.0,
                    carbs=48.0,
                    fats=8.0,
                    spice_level='High',
                    veg_nonveg='Veg',
                    price=220.0,
                    meal_type='Heavy',
                    image_url='',
                    description='Spicy vegetarian dinner bowl with lentils and rice.',
                ),
                Food(
                    food_id='chicken_biryani',
                    food_name='Chicken Biryani',
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
                    image_url='',
                    description='Spicy layered rice cooked with chicken.',
                ),
                Food(
                    food_id='protein_salad',
                    food_name='Protein Salad',
                    cuisine='American',
                    category='Lunch',
                    calories=260,
                    protein=22.0,
                    carbs=20.0,
                    fats=6.0,
                    spice_level='Low',
                    veg_nonveg='Veg',
                    price=180.0,
                    meal_type='Light',
                    image_url='',
                    description='Fresh high protein vegetarian salad.',
                ),
                Food(
                    food_id='chicken_wrap',
                    food_name='Chicken Protein Wrap',
                    cuisine='American',
                    category='Lunch',
                    calories=390,
                    protein=30.0,
                    carbs=32.0,
                    fats=10.0,
                    spice_level='Low',
                    veg_nonveg='Non-Veg',
                    price=250.0,
                    meal_type='Light',
                    image_url='',
                    description='Grilled chicken wrap with high protein filling.',
                ),
            ])
            db.session.commit()

    @classmethod
    def tearDownClass(cls):
        if cls.original_admin_username is None:
            os.environ.pop('ADMIN_USERNAME', None)
        else:
            os.environ['ADMIN_USERNAME'] = cls.original_admin_username

        if cls.original_admin_password is None:
            os.environ.pop('ADMIN_PASSWORD', None)
        else:
            os.environ['ADMIN_PASSWORD'] = cls.original_admin_password

        with app.app_context():
            db.drop_all()
            init_db(app)

        if ORIGINAL_DATABASE_URL is None:
            os.environ.pop('DATABASE_URL', None)
        else:
            os.environ['DATABASE_URL'] = ORIGINAL_DATABASE_URL

    def post_recommendations(self, search_query, diet='Veg'):
        return self.client.post('/recommendations', data={
            'search_query': search_query,
            'diet': diet,
            'spice': 'Medium',
            'health_goal': 'Healthy Eating',
            'mood': 'Neutral',
            'budget': '1000',
        })

    def post_chat(self, message):
        return self.client.post('/api/chat', json={'message': message})

    def test_biryani_with_veg_filter_returns_empty(self):
        response = self.post_recommendations('biryani', diet='Veg')
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('Nothing matched', body)
        self.assertNotIn('Chicken Biryani', body)

    def test_unknown_search_does_not_fallback_to_generic_results(self):
        response = self.post_recommendations('zzzzzz', diet='Veg')
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('Nothing matched', body)
        self.assertNotIn('Protein Salad', body)

    def test_category_spice_diet_search_matches_expected_dish(self):
        response = self.post_recommendations('veg spicy dinner', diet='Veg')
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('Veg Spicy Dinner Bowl', body)
        self.assertNotIn('Chicken Biryani', body)

    def test_vegetarian_search_does_not_match_nonvegetarian_text(self):
        response = self.post_recommendations('vegetarian dinner', diet='Non-Veg')
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('Veg Spicy Dinner Bowl', body)
        self.assertNotIn('Chicken Biryani', body)

    def test_invalid_ratings_return_400_for_json(self):
        for rating in ['abc', '0', '6']:
            response = self.client.post('/submit-rating', json={
                'food_id': 'protein_salad',
                'rating': rating,
            })
            self.assertEqual(response.status_code, 400)

    def test_rating_rejects_unknown_food(self):
        response = self.client.post('/submit-rating', json={
            'food_id': 'missing',
            'rating': '5',
        })

        self.assertEqual(response.status_code, 400)

    def test_save_food_adds_once_and_rejects_invalid_ids(self):
        first = self.client.post('/save-food', json={'food_id': 'protein_salad'})
        second = self.client.post('/save-food', json={'food_id': 'protein_salad'})
        missing = self.client.post('/save-food', json={'food_id': 'missing'})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(missing.status_code, 404)
        with self.client.session_transaction() as sess:
            saved = [item for item in sess['history'] if item['food_id'] == 'protein_salad']
        self.assertEqual(len(saved), 1)

    def test_admin_requires_login(self):
        response = self.client.get('/admin')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login', response.location)

    def test_admin_create_update_delete_persist(self):
        login = self.client.post('/admin/login', data={
            'username': 'admin',
            'password': 'secret',
        })
        self.assertEqual(login.status_code, 302)

        create = self.client.post('/admin/save', data={
            'food_name': 'Test Taco',
            'cuisine': 'Mexican',
            'category': 'Lunch',
            'meal_type': 'Snack',
            'veg_nonveg': 'Veg',
            'spice_level': 'Medium',
            'price': '150',
            'calories': '240',
            'protein': '10',
            'carbs': '30',
            'fats': '7',
            'image_url': '',
            'description': 'A test taco.',
        })
        self.assertEqual(create.status_code, 302)

        with app.app_context():
            food = Food.query.filter_by(food_name='Test Taco').first()
            self.assertIsNotNone(food)
            food_id = food.food_id

        update = self.client.post('/admin/save', data={
            'food_id': food_id,
            'food_name': 'Updated Taco',
            'cuisine': 'Mexican',
            'category': 'Dinner',
            'meal_type': 'Heavy',
            'veg_nonveg': 'Veg',
            'spice_level': 'High',
            'price': '180',
            'calories': '300',
            'protein': '12',
            'carbs': '35',
            'fats': '8',
            'image_url': '',
            'description': 'An updated test taco.',
        })
        self.assertEqual(update.status_code, 302)

        with app.app_context():
            updated = db.session.get(Food, food_id)
            self.assertEqual(updated.food_name, 'Updated Taco')
            self.assertEqual(updated.category, 'Dinner')

        delete = self.client.post(f'/admin/delete/{food_id}')
        self.assertEqual(delete.status_code, 302)

        with app.app_context():
            self.assertIsNone(db.session.get(Food, food_id))

    def test_admin_login_rejects_external_next_redirect(self):
        response = self.client.post('/admin/login?next=https://evil.example', data={
            'username': 'admin',
            'password': 'secret',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/admin')

    def test_admin_login_accepts_internal_next_redirect(self):
        response = self.client.post('/admin/login?next=/admin', data={
            'username': 'admin',
            'password': 'secret',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/admin')

    def test_chat_nonveg_chicken_under_budget_excludes_veg(self):
        response = self.post_chat('non veg chicken under 300')
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIn('Chicken Protein Wrap', body['reply'])
        self.assertNotIn('Protein Salad', body['reply'])
        self.assertNotIn('Veg Spicy Dinner Bowl', body['reply'])

    def test_chat_spicy_veg_indian_under_budget_excludes_nonveg(self):
        response = self.post_chat('spicy veg indian under 300')
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIn('Veg Spicy Dinner Bowl', body['reply'])
        self.assertNotIn('Chicken Biryani', body['reply'])
        self.assertNotIn('Chicken Protein Wrap', body['reply'])

    def test_chat_high_protein_lunch_prioritizes_protein_match(self):
        response = self.post_chat('high protein lunch under 300')
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        first_link_index = body['reply'].find('/recommendation-direct?food_id=')
        chicken_index = body['reply'].find('Chicken Protein Wrap')
        salad_index = body['reply'].find('Protein Salad')
        self.assertGreaterEqual(chicken_index, first_link_index)
        self.assertGreaterEqual(salad_index, first_link_index)
        self.assertLess(chicken_index, salad_index)
        self.assertNotIn('Veg Spicy Dinner Bowl', body['reply'])

    def test_chat_greeting_does_not_return_random_food_links(self):
        response = self.post_chat('hello')
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIn('Tell me what you feel like eating', body['reply'])
        self.assertNotIn('/recommendation-direct?food_id=', body['reply'])

    def test_chat_unknown_query_returns_no_match(self):
        response = self.post_chat('zzzzzz')
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("couldn't find a database dish", body['reply'])
        self.assertNotIn('/recommendation-direct?food_id=', body['reply'])

    @patch('app.requests.post')
    def test_chat_uses_openrouter_nemotron_model(self, mock_post):
        app.config['OPENROUTER_API_KEY'] = 'test-openrouter-key'
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'choices': [
                {
                    'message': {
                        'content': "Try <a href='/recommendation-direct?food_id=protein_salad' class='chat-food-link'>Protein Salad</a>."
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        response = self.client.post('/api/chat', json={'message': 'high protein veg lunch'})
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIn('Protein Salad', body['reply'])
        call_kwargs = mock_post.call_args.kwargs
        self.assertEqual(mock_post.call_args.args[0], 'https://openrouter.ai/api/v1/chat/completions')
        self.assertEqual(call_kwargs['json']['model'], 'nvidia/nemotron-3-ultra-550b-a55b:free')
        self.assertEqual(call_kwargs['json']['messages'][0]['role'], 'system')
        self.assertIn('Urban Diner', call_kwargs['json']['messages'][0]['content'])
        self.assertEqual(call_kwargs['json']['messages'][1], {'role': 'user', 'content': 'high protein veg lunch'})
        self.assertNotIn('system', call_kwargs['json'])
        self.assertEqual(call_kwargs['json']['max_tokens'], 220)
        self.assertEqual(call_kwargs['json']['reasoning'], {'exclude': True})
        self.assertEqual(call_kwargs['headers']['Authorization'], 'Bearer test-openrouter-key')
        self.assertEqual(call_kwargs['timeout'], 65)


if __name__ == '__main__':
    unittest.main()
