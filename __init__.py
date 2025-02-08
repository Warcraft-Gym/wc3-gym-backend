import logging
import os
from dotenv import load_dotenv
from flask import Flask
from flask_jwt_extended import JWTManager
from src.database.user_db_service import UserDBService
from src.database.team_db_service import TeamDBService
from src.database.match_db_service import MatchDBService
from src.service.user_service import UserAppService
from src.service.team_service import TeamAppService
from src.service.match_service import MatchAppService

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Initialize JWT
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY')
app.config['JWT_ALGORITHM'] = os.getenv('JWT_ALGORITHM', 'HS512')  
jwt = JWTManager(app)

# Configure logging
logging.basicConfig(level=logging.DEBUG)


# Initialize services with database URL from environment variables
db_url = os.getenv('DB_URL')
user_service = UserDBService(db_url=db_url)
team_service = TeamDBService(db_url=db_url)
match_service = MatchDBService(db_url=db_url)

# Initialize application services
app.user_app_service = UserAppService(user_service=user_service)
app.team_app_service = TeamAppService(team_service=team_service)
app.match_app_service = MatchAppService(match_service=match_service)
