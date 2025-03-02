import logging
import os
from dotenv import load_dotenv
from flask import Flask
from flask_jwt_extended import JWTManager
from src.database.user_db_service import UserDBService
from src.database.team_db_service import TeamDBService
from src.database.match_db_service import MatchDBService
from src.database.season_db_service import SeasonDBService
from src.database.series_db_service import SeriesDBService
from src.service.user_service import UserAppService
from src.service.team_service import TeamAppService
from src.service.match_service import MatchAppService
from src.service.season_service import SeasonAppService
from src.service.series_service import SeriesAppService
from flasgger import Swagger

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": 'apispec',
            "route": '/apispec.json',
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/apidocs/",
}

template = {
    "swagger": "2.0",
    "info": {
        "title": "GNL Backend API",
        "description": "API for Gym Newbie League Backend Data",
        "version": "1.0.0",
    },
    "basePath": "/",
    "definitions": {
    },
    "schemes": [
        "http",
        "https"
    ],
    "securityDefinitions": {
        "BearerAuth": {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header"
        }
    }
}

swag = Swagger(app, template=template, config=swagger_config)

# Initialize JWT
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY')
app.config['JWT_ALGORITHM'] = os.getenv('JWT_ALGORITHM', 'HS256')  
jwt = JWTManager(app)

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Initialize services with database URL from environment variables
db_url = os.getenv('DB_URL')
user_service = UserDBService(db_url=db_url)
team_service = TeamDBService(db_url=db_url)
match_service = MatchDBService(db_url=db_url)
season_service = SeasonDBService(db_url=db_url)
series_service = SeriesDBService(db_url=db_url)

# Initialize application services
app.user_app_service = UserAppService(user_service=user_service)
app.team_app_service = TeamAppService(team_service=team_service)
app.match_app_service = MatchAppService(match_service=match_service)
app.season_app_service = SeasonAppService(season_service=season_service)
app.series_app_service = SeriesAppService(series_service=series_service)
