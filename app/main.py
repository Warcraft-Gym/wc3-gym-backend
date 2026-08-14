"""The application factory.

Importing this module defines create_app and imports the layers below it.
It opens no database connection and creates no tables. Everything that
touches the database happens inside create_app, so a test or a script can
import any app module without a reachable database.

The server calls the factory itself, as "app.main:create_app()", so no
application is built at import.
"""

import enum
import logging
import os

from dotenv import load_dotenv
from flasgger import Swagger
from flask import Flask
from flask.json.provider import DefaultJSONProvider
from flask_caching import Cache
from flask_cors import CORS
from flask_jwt_extended import JWTManager

from app.api.config_api import config_blueprint
from app.api.draft_series_api import draft_series_blueprint
from app.api.fantasy_api import fantasy_blueprint
from app.api.import_export_api import import_blueprint
from app.api.koth_api import koth_blueprint
from app.api.login_api import login_blueprint
from app.api.map_api import map_blueprint
from app.api.match_api import match_blueprint
from app.api.public_api import public_api_blueprint
from app.api.score_api import score_blueprint
from app.api.season_api import season_blueprint
from app.api.series_api import series_blueprint
from app.api.stats_api import stats_blueprint
from app.api.team_api import team_blueprint
from app.api.user_api import user_blueprint
from app.database.draft_series_db_service import DraftSeriesDBService
from app.database.engine import init_engine, init_schema
from app.database.fantasy_bet_db_service import FantasyBetDBService
from app.database.fantasy_team_db_service import FantasyTeamDBService
from app.database.koth_db_service import KothDBService
from app.database.map_db_service import MapDBService
from app.database.match_db_service import MatchDBService
from app.database.player_career_stats_db_service import PlayerCareerStatsDBService
from app.database.season_db_service import SeasonDBService
from app.database.series_db_service import SeriesDBService
from app.database.settings_db_service import SettingsDBService
from app.database.team_db_service import TeamDBService
from app.database.team_season_db_service import TeamSeasonDBService
from app.database.user_db_service import UserDBService
from app.service.draft_series_service import DraftSeriesAppService
from app.service.fantasy_bet_service import FantasyBetAppService
from app.service.fantasy_score_service import FantasyScoreAppService
from app.service.fantasy_team_service import FantasyTeamAppService
from app.service.koth_service import KothAppService
from app.service.map_service import MapAppService
from app.service.match_service import MatchAppService
from app.service.player_career_stats_service import PlayerCareerStatsAppService
from app.service.score_service import ScoreAppService
from app.service.season_service import SeasonAppService
from app.service.series_service import SeriesAppService
from app.service.settings_service import SettingsAppService
from app.service.team_service import TeamAppService
from app.service.user_service import UserAppService

logger = logging.getLogger(__name__)

SWAGGER_CONFIG = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec",
            "route": "/apispec.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/apidocs/",
}

SWAGGER_TEMPLATE = {
    "swagger": "2.0",
    "info": {
        "title": "GNL Backend API",
        "description": "API for Gym Newbie League Backend Data",
        "version": "1.0.0",
    },
    "basePath": "/",
    "definitions": {},
    "schemes": ["http", "https"],
    "securityDefinitions": {
        "BearerAuth": {"type": "apiKey", "name": "Authorization", "in": "header"},
        "RefreshAuth": {"type": "apiKey", "name": "Authorization", "in": "header"},
    },
}


class CustomJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, enum.Enum):
            return obj.value
        return super().default(obj)


def create_app(db_url=None):
    """Build the application: engine, schema, services, blueprints.

    Reads the environment when the caller passes no db_url.
    """
    load_dotenv()
    # A wrong LOG_LEVEL must not stop the application.
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    )

    engine = init_engine(db_url)
    init_schema(engine)

    app = Flask(__name__)
    CORS(app)

    app.config["CACHE_TYPE"] = "SimpleCache"  # In-memory caching
    cache = Cache(app)

    app.json = CustomJSONProvider(app)

    Swagger(app, template=SWAGGER_TEMPLATE, config=SWAGGER_CONFIG)

    app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY")
    app.config["JWT_ALGORITHM"] = os.getenv("JWT_ALGORITHM", "HS256")
    JWTManager(app)

    # The database services share the engine in app/database/engine.py.
    user_service = UserDBService()
    team_service = TeamDBService()
    match_service = MatchDBService()
    season_service = SeasonDBService()
    series_service = SeriesDBService()
    draft_series_service = DraftSeriesDBService()
    map_service = MapDBService()
    team_season_service = TeamSeasonDBService()
    fantasy_bet_service = FantasyBetDBService()
    fantasy_team_service = FantasyTeamDBService()
    settings_service = SettingsDBService()
    koth_service = KothDBService()
    stats_db_service = PlayerCareerStatsDBService()

    settings_app_service = SettingsAppService(settings_service=settings_service)
    user_app_service = UserAppService(
        user_service=user_service, settings_app_service=settings_app_service
    )
    team_app_service = TeamAppService(
        team_service=team_service, user_app_service=user_app_service
    )
    match_app_service = MatchAppService(match_service=match_service)
    season_app_service = SeasonAppService(season_service=season_service)
    score_app_service = ScoreAppService(
        match_service=match_service,
        serires_service=series_service,
        team_service=team_service,
        team_season_service=team_season_service,
        season_service=season_service,
        settings_service=settings_service,
    )
    series_app_service = SeriesAppService(
        series_service=series_service,
        score_app_service=score_app_service,
        user_app_service=user_app_service,
    )
    draft_series_app_service = DraftSeriesAppService(
        draft_series_service=draft_series_service
    )
    map_app_service = MapAppService(map_service=map_service)
    fantasy_bet_app_service = FantasyBetAppService(
        fantasy_bet_service=fantasy_bet_service,
        settings_app_service=settings_app_service,
    )
    fantasy_team_app_service = FantasyTeamAppService(
        fantasy_team_service=fantasy_team_service
    )
    fantasy_score_app_service = FantasyScoreAppService(
        fantasy_team_service=fantasy_team_app_service,
        fantasy_bet_service=fantasy_bet_app_service,
        series_app_service=series_app_service,
        team_app_service=team_app_service,
    )
    koth_app_service = KothAppService(
        koth_service=koth_service, settings_app_service=settings_app_service
    )
    stats_app_service = PlayerCareerStatsAppService(
        stats_db_service=stats_db_service, series_service=series_service
    )

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

    # Give the blueprint the JSON provider so the services can serialize with
    # the same provider without reaching for the application context.
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

    logger.debug("Application built")
    return app
