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
from src.database.draft_series_db_service import DraftSeriesDBService
from src.database.fantasy_bet_db_service import FantasyBetDBService
from src.database.fantasy_team_db_service import FantasyTeamDBService
from src.database.map_db_service import MapDBService
from src.database.team_season_db_service import TeamSeasonDBService
from src.database.settings_db_service import SettingsDBService
from src.database.koth_db_service import KothDBService
from src.service.user_service import UserAppService
from src.service.team_service import TeamAppService
from src.service.koth_service import KothAppService
from src.service.match_service import MatchAppService
from src.service.season_service import SeasonAppService
from src.service.series_service import SeriesAppService
from src.service.draft_series_service import DraftSeriesAppService
from src.service.score_service import ScoreAppService
from src.service.map_service import MapAppService
from src.service.fantasy_bet_service import FantasyBetAppService
from src.service.fantasy_team_service import FantasyTeamAppService
from src.service.fantasy_score_service import FantasyScoreAppService
from src.service.settings_service import SettingsAppService
from src.service.player_career_stats_service import PlayerCareerStatsAppService
from src.database.player_career_stats_db_service import PlayerCareerStatsDBService
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
from src.api.draft_series_api import draft_series_blueprint
from src.api.import_export_api import import_blueprint
from src.api.public_api import public_api_blueprint
from src.api.map_api import map_blueprint
from src.api.score_api import score_blueprint
from src.api.fantasy_api import fantasy_blueprint
from src.api.config_api import config_blueprint
from src.api.koth_api import koth_blueprint
from src.api.stats_api import stats_blueprint

# Load environment variables from .env file
load_dotenv()

# Configure logging
_log_level = getattr(logging, os.getenv('LOG_LEVEL', 'INFO').upper(), logging.INFO)
logging.basicConfig(level=_log_level)

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
# Export the JSON provider instance so other modules can reuse it without importing the Flask
# application context (avoids using `current_app` in services).
json_provider = app.json

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
draft_series_service = DraftSeriesDBService(db_url=db_url)
map_service = MapDBService(db_url=db_url)
team_season_service = TeamSeasonDBService(db_url=db_url)
fantasy_bet_service = FantasyBetDBService(db_url=db_url)
fantasy_team_service = FantasyTeamDBService(db_url=db_url)
settings_service = SettingsDBService(db_url=db_url)
koth_service = KothDBService(db_url=db_url)
stats_db_service = PlayerCareerStatsDBService(db_url=db_url)

logger.debug("DB Services initialized!")

# Initialize application services
settings_app_service = SettingsAppService(settings_service=settings_service)
user_app_service = UserAppService(user_service=user_service, settings_app_service=settings_app_service)
team_app_service = TeamAppService(team_service=team_service, user_app_service=user_app_service)
match_app_service = MatchAppService(match_service=match_service)
season_app_service = SeasonAppService(season_service=season_service)
score_app_service = ScoreAppService(match_service=match_service, serires_service=series_service, team_service=team_service, team_season_service=team_season_service, season_service=season_service, settings_service=settings_service)
series_app_service = SeriesAppService(series_service=series_service, score_app_service=score_app_service, user_app_service=user_app_service)
draft_series_app_service = DraftSeriesAppService(draft_series_service=draft_series_service)
map_app_service = MapAppService(map_service=map_service)
fantasy_bet_app_service = FantasyBetAppService(fantasy_bet_service=fantasy_bet_service, settings_app_service=settings_app_service)
fantasy_team_app_service = FantasyTeamAppService(fantasy_team_service=fantasy_team_service)
fantasy_score_app_service = FantasyScoreAppService(fantasy_team_service=fantasy_team_app_service,
                                                    fantasy_bet_service=fantasy_bet_app_service,
                                                    series_app_service=series_app_service,
                                                    team_app_service=team_app_service)
koth_app_service = KothAppService(koth_service=koth_service, settings_app_service=settings_app_service)
stats_app_service = PlayerCareerStatsAppService(
    stats_db_service=stats_db_service,
    series_service=series_service
)

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
public_api_blueprint.user_app_service = user_app_service
public_api_blueprint.season_app_service = season_app_service
public_api_blueprint.series_app_service = series_app_service
public_api_blueprint.fantasy_team_app_service = fantasy_team_app_service
public_api_blueprint.fantasy_bet_app_service = fantasy_bet_app_service
public_api_blueprint.settings_app_service = settings_app_service
season_blueprint.season_app_service = season_app_service
team_blueprint.team_app_service = team_app_service
team_blueprint.cache = cache
match_blueprint.match_app_service = match_app_service
series_blueprint.series_app_service = series_app_service
draft_series_blueprint.draft_series_app_service = draft_series_app_service
map_blueprint.map_app_service = map_app_service
fantasy_blueprint.fantasy_bet_app_service = fantasy_bet_app_service
fantasy_blueprint.fantasy_team_app_service = fantasy_team_app_service
fantasy_blueprint.fantasy_score_app_service = fantasy_score_app_service
fantasy_blueprint.season_app_service = season_app_service
fantasy_blueprint.settings_app_service = settings_app_service

score_blueprint.season_app_service = season_app_service
score_blueprint.match_app_service = match_app_service
score_blueprint.series_app_service = series_app_service
score_blueprint.score_app_service = score_app_service
score_blueprint.team_app_service = team_app_service

config_blueprint.settings_app_service = settings_app_service

koth_blueprint.koth_app_service = koth_app_service

stats_blueprint.stats_service = stats_app_service

# Provide the custom JSON provider to blueprints so services can serialize
# using the same provider without importing the Flask app/context.
public_api_blueprint.json_provider = app.json

app.register_blueprint(login_blueprint)
app.register_blueprint(user_blueprint)
app.register_blueprint(team_blueprint)
app.register_blueprint(match_blueprint)
app.register_blueprint(season_blueprint)
app.register_blueprint(import_blueprint)
app.register_blueprint(public_api_blueprint)
app.register_blueprint(series_blueprint)
app.register_blueprint(draft_series_blueprint)
app.register_blueprint(map_blueprint)
app.register_blueprint(score_blueprint)
app.register_blueprint(fantasy_blueprint)
app.register_blueprint(config_blueprint)
app.register_blueprint(koth_blueprint)
app.register_blueprint(stats_blueprint)

logger.debug("API blueprints registered!")


logger.debug("App succesfully initialized!")