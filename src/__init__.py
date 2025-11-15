import logging
import os
from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_caching import Cache
from src.database.user_db_service import UserDBService
from src.database.team_db_service import TeamDBService
from src.database.match_db_service import MatchDBService
from src.database.season_db_service import SeasonDBService
from src.database.series_db_service import SeriesDBService
from src.database.fantasy_bet_db_service import FantasyBetDBService
from src.database.fantasy_team_db_service import FantasyTeamDBService
from src.database.map_db_service import MapDBService
from src.database.team_season_db_service import TeamSeasonDBService
from src.service.user_service import UserAppService
from src.service.team_service import TeamAppService
from src.service.match_service import MatchAppService
from src.service.season_service import SeasonAppService
from src.service.series_service import SeriesAppService
from src.service.score_service import ScoreAppService
from src.service.map_service import MapAppService
from src.service.fantasy_bet_service import FantasyBetAppService
from src.service.fantasy_team_service import FantasyTeamAppService
from src.service.fantasy_score_service import FantasyScoreAppService
from flasgger import Swagger
import enum
from flask.json.provider import DefaultJSONProvider

# Register Blueprints
from src.api.login_api import login_blueprint
from src.api.user_api import user_blueprint
from src.api.team_api import team_blueprint
from src.api.match_api import match_blueprint
from src.api.season_api import season_blueprint
from src.api.series_api import series_blueprint
from src.api.import_export_api import import_blueprint
from src.api.signup_api import signup_blueprint
from src.api.map_api import map_blueprint
from src.api.score_api import score_blueprint
from src.api.fantasy_api import fantasy_blueprint

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.DEBUG)

logger = logging.getLogger(__name__)

app = Flask(__name__)

logger.debug("Flask App Created!")
CORS(app)

logger.debug("Cors enabled!")

app.config['CACHE_TYPE'] = 'SimpleCache'  # In-memory caching


cache = Cache(app)
cache.init_app(app)

logger.debug("Cache initialized!")


class CustomJSONProvider(DefaultJSONProvider):
    def __init__(self, app):
        super().__init__(app)

    def default(self, obj):
        if isinstance(obj, enum.Enum):
            return obj.value
        return super().default(obj)
    
app.json  = CustomJSONProvider(app)

logger.debug("Custom JSON Provider registered!")

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
        },
        "RefreshAuth": {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header"
        }
    }
}

swag = Swagger(app, template=template, config=swagger_config)

logger.debug("Swagger initialized!")

# Initialize JWT
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY')
app.config['JWT_ALGORITHM'] = os.getenv('JWT_ALGORITHM', 'HS256')  
jwt = JWTManager(app)

logger.debug("JWT initialized!")


# Initialize services with database URL from environment variables
db_url = os.getenv('DB_URL')
user_service = UserDBService(db_url=db_url)
team_service = TeamDBService(db_url=db_url)
match_service = MatchDBService(db_url=db_url)
season_service = SeasonDBService(db_url=db_url)
series_service = SeriesDBService(db_url=db_url)
map_service = MapDBService(db_url=db_url)
team_season_service = TeamSeasonDBService(db_url=db_url)
fantasy_bet_service = FantasyBetDBService(db_url=db_url)
fantasy_team_service = FantasyTeamDBService(db_url=db_url)

logger.debug("DB Services initialized!")

# Initialize application services
user_app_service = UserAppService(user_service=user_service)
team_app_service = TeamAppService(team_service=team_service, user_app_service=user_app_service)
match_app_service = MatchAppService(match_service=match_service)
season_app_service = SeasonAppService(season_service=season_service)
score_app_service = ScoreAppService(match_service=match_service, serires_service=series_service, team_service=team_service, team_season_service=team_season_service)
series_app_service = SeriesAppService(series_service=series_service, score_app_service=score_app_service, user_app_service=user_app_service)
map_app_service = MapAppService(map_service=map_service)
fantasy_bet_app_service = FantasyBetAppService(fantasy_bet_service=fantasy_bet_service)
fantasy_team_app_service = FantasyTeamAppService(fantasy_team_service=fantasy_team_service)
fantasy_score_app_service = FantasyScoreAppService(fantasy_team_service=fantasy_team_app_service,
                                                    fantasy_bet_service=fantasy_bet_app_service,
                                                    series_app_service=series_app_service,
                                                    team_app_service=team_app_service)


logger.debug("App services initialized!")

import_blueprint.user_app_service = user_app_service
import_blueprint.season_app_service = season_app_service
import_blueprint.team_app_service = team_app_service
import_blueprint.match_app_service = match_app_service
import_blueprint.series_app_service = series_app_service
import_blueprint.map_app_service = map_app_service
import_blueprint.score_app_service = score_app_service
import_blueprint.fantasy_bet_app_service = fantasy_bet_app_service
import_blueprint.fantasy_team_app_service = fantasy_team_app_service

user_blueprint.user_app_service = user_app_service
signup_blueprint.user_app_service = user_app_service
signup_blueprint.season_app_service = season_app_service
season_blueprint.season_app_service = season_app_service
team_blueprint.team_app_service = team_app_service
team_blueprint.cache = cache
match_blueprint.match_app_service = match_app_service
series_blueprint.series_app_service = series_app_service
map_blueprint.map_app_service = map_app_service
fantasy_blueprint.fantasy_bet_app_service = fantasy_bet_app_service
fantasy_blueprint.fantasy_team_app_service = fantasy_team_app_service
fantasy_blueprint.fantasy_score_app_service = fantasy_score_app_service
fantasy_blueprint.season_app_service = season_app_service

score_blueprint.season_app_service = season_app_service
score_blueprint.match_app_service = match_app_service
score_blueprint.series_app_service = series_app_service
score_blueprint.score_app_service = score_app_service
score_blueprint.team_app_service = team_app_service

app.register_blueprint(login_blueprint)
app.register_blueprint(user_blueprint)
app.register_blueprint(team_blueprint)
app.register_blueprint(match_blueprint)
app.register_blueprint(season_blueprint)
app.register_blueprint(import_blueprint)
app.register_blueprint(signup_blueprint)
app.register_blueprint(series_blueprint)
app.register_blueprint(map_blueprint)
app.register_blueprint(score_blueprint)
app.register_blueprint(fantasy_blueprint)

logger.debug("API blueprints registered!")


logger.debug("App succesfully initialized!")