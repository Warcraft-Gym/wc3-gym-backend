import logging

from flasgger import swag_from
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.exceptions import NotFoundException
from app.schemas.team import Team
from app.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

team_blueprint = Blueprint("team_api", __name__)


# Team endpoints
@team_blueprint.route("/teams", methods=["POST"])
@jwt_required()
@swag_from(
    {
        "summary": "Add a new team",
        "description": "Create a new team with the provided name.",
        "tags": ["teams"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "body", "in": "body", "required": True, "schema": Team.schema()}
        ],
        "responses": {
            201: {"description": "Team created successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def add_team():
    try:
        data = request.json
        team = team_blueprint.team_app_service.create_team(Team(data))
        if team:
            team = team.to_dict()
        return jsonify(team), 201
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@team_blueprint.route("/teams/<int:team_id>", methods=["PUT"])
@jwt_required()
@swag_from(
    {
        "summary": "Update a team",
        "description": "Update the name of an existing team.",
        "tags": ["teams"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "team_id", "in": "path", "type": "integer", "required": True},
            {"name": "body", "in": "body", "required": False, "schema": Team.schema()},
        ],
        "responses": {
            200: {"description": "Team updated successfully"},
            404: {"description": "Team not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def update_team(team_id):
    try:
        data = request.json
        team = team_blueprint.team_app_service.update_team(team_id, Team(data))
        if team:
            team = team.to_dict()
        return jsonify(team)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@team_blueprint.route("/teams/<int:team_id>", methods=["DELETE"])
@jwt_required()
@swag_from(
    {
        "summary": "Delete a team",
        "description": "Delete a team by its ID.",
        "tags": ["teams"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "team_id", "in": "path", "type": "integer", "required": True}
        ],
        "responses": {
            204: {"description": "Team deleted successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def delete_team(team_id):
    try:
        team_blueprint.team_app_service.delete_team(team_id)
        return f"Team Deleted: {team_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@team_blueprint.route("/teams/<int:team_id>", methods=["GET"])
@swag_from(
    {
        "summary": "Get a team",
        "description": "Retrieve a team by its ID.",
        "tags": ["teams"],
        "parameters": [
            {"name": "team_id", "in": "path", "type": "integer", "required": True}
        ],
        "responses": {
            200: {"description": "Team retrieved successfully"},
            404: {"description": "Team not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_team(team_id):
    try:
        team = team_blueprint.team_app_service.get_team(team_id)
        if team:
            team = team.to_dict()
        return jsonify(team)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@team_blueprint.route("/teams/<int:team_id>/seasons/<int:season_id>", methods=["GET"])
@swag_from(
    {
        "summary": "Get a team for a specific season",
        "description": "Retrieve a team by its ID with all information related to a specific season",
        "tags": ["teams"],
        "parameters": [
            {"name": "team_id", "in": "path", "type": "integer", "required": True},
            {"name": "season_id", "in": "path", "type": "integer", "required": True},
        ],
        "responses": {
            200: {"description": "Team retrieved successfully"},
            404: {"description": "Team not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_team_season(team_id, season_id):
    try:
        team = team_blueprint.team_app_service.get_team_season(team_id, season_id)
        if team:
            team = team.to_dict()
        return jsonify(team)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@team_blueprint.route("/teams/season/<int:season_id>", methods=["GET"])
@swag_from(
    {
        "summary": "Get all teams for a specific season",
        "description": "Retrieve all teams with all information related to a specific season",
        "tags": ["teams"],
        "parameters": [
            {"name": "season_id", "in": "path", "type": "integer", "required": True}
        ],
        "responses": {
            200: {"description": "Team retrieved successfully"},
            404: {"description": "Team not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def getAll_season(season_id):
    try:
        teams = team_blueprint.team_app_service.get_teams_season(season_id)
        out = []
        if teams:
            for team in teams:
                out.append(team.to_dict())
        return jsonify(out)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@team_blueprint.route("/teams/season/<int:season_id>/basic", methods=["GET"])
@swag_from(
    {
        "summary": "Get all teams for a specific season (basic info)",
        "description": "Retrieve all teams with season info but without user data for a specific season",
        "tags": ["teams"],
        "parameters": [
            {"name": "season_id", "in": "path", "type": "integer", "required": True}
        ],
        "responses": {
            200: {"description": "Teams retrieved successfully"},
            404: {"description": "Teams not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def getAll_season_basic(season_id):
    try:
        teams = team_blueprint.team_app_service.get_teams_season_basic(season_id)
        out = []
        if teams:
            for team in teams:
                out.append(team.to_dict())
        return jsonify(out)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@team_blueprint.route(
    "/teams/addPlayers/<int:team_id>/seasons/<int:season_id>", methods=["POST"]
)
@jwt_required()
@swag_from(
    {
        "summary": "Add players to a team for a season",
        "description": "Add players to a team for a season using their IDs.",
        "tags": ["teams"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "team_id", "in": "path", "type": "integer", "required": True},
            {"name": "season_id", "in": "path", "type": "integer", "required": True},
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "player_ids": {"type": "array", "items": {"type": "integer"}}
                    },
                    "required": ["player_ids"],
                },
            },
        ],
        "responses": {
            200: {"description": "Players added successfully"},
            404: {"description": "Team not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def addPlayers(team_id, season_id):
    try:
        data = request.json
        team = team_blueprint.team_app_service.addPlayers(
            team_id, season_id, data.get("player_ids")
        )
        if team:
            team = team.to_dict()
        return jsonify(team)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@team_blueprint.route(
    "/teams/removePlayers/<int:team_id>/seasons/<int:season_id>", methods=["POST"]
)
@jwt_required()
@swag_from(
    {
        "summary": "Removes players from a team for a season",
        "description": "Removes players from a team for a season using their IDs.",
        "tags": ["teams"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "team_id", "in": "path", "type": "integer", "required": True},
            {"name": "season_id", "in": "path", "type": "integer", "required": True},
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "player_ids": {"type": "array", "items": {"type": "integer"}}
                    },
                    "required": ["player_ids"],
                },
            },
        ],
        "responses": {
            200: {"description": "Players removed successfully"},
            404: {"description": "Team not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def removePlayers(team_id, season_id):
    try:
        data = request.json
        team = team_blueprint.team_app_service.removePlayers(
            team_id, season_id, data.get("player_ids")
        )
        if team:
            team = team.to_dict()
        return jsonify(team)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@team_blueprint.route(
    "/teams/<int:team_id>/seasons/<int:season_id>/coaches", methods=["PUT"]
)
@jwt_required()
@swag_from(
    {
        "summary": "Set team coaches for a season",
        "description": "Set up to 3 coaches for a team in a specific season. Replaces existing coaches.",
        "tags": ["teams"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "team_id", "in": "path", "type": "integer", "required": True},
            {"name": "season_id", "in": "path", "type": "integer", "required": True},
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "coach_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "maxItems": 3,
                            "description": "Array of user IDs to set as coaches (max 3)",
                        }
                    },
                    "required": ["coach_ids"],
                },
            },
        ],
        "responses": {
            200: {"description": "Coaches set successfully"},
            400: {"description": "Invalid request (e.g., more than 3 coaches)"},
            404: {"description": "Team or season not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def set_coaches(team_id, season_id):
    try:
        data = request.json
        coach_ids = data.get("coach_ids", [])

        if len(coach_ids) > 3:
            return jsonify(
                {"error": "Cannot assign more than 3 coaches per team per season"}
            ), 400

        team = team_blueprint.team_app_service.setCoaches(team_id, season_id, coach_ids)
        if team:
            team = team.to_dict()
        return jsonify(team), 200
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@team_blueprint.route("/teams", methods=["GET"])
@swag_from(
    {
        "summary": "Get all teams",
        "description": "Retrieve all teams.",
        "tags": ["teams"],
        "responses": {
            200: {"description": "Teams retrieved successfully"},
            404: {"description": "Teams not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_all_teams():
    try:
        teams = team_blueprint.team_app_service.getAll()
        out = []
        if teams:
            for team in teams:
                out.append(team.to_dict())
        return jsonify(out)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@team_blueprint.route("/teams/basic", methods=["GET"])
@swag_from(
    {
        "summary": "Get all teams (basic info only)",
        "description": "Retrieve all teams with basic information only (id, name, long_name, discord_role). No user or season data included.",
        "tags": ["teams"],
        "responses": {
            200: {"description": "Teams retrieved successfully"},
            404: {"description": "Teams not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_all_teams_basic():
    try:
        teams = team_blueprint.team_app_service.getAll_basic()
        out = []
        if teams:
            for team in teams:
                out.append(team.to_dict())
        return jsonify(out)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@team_blueprint.route("/teams/search", methods=["POST"])
@swag_from(
    {
        "summary": "Search teams by criteria",
        "description": "Search teams by criteria using a custom query format.",
        "tags": ["teams"],
        "parameters": [
            {
                "name": "query",
                "in": "query",
                "type": "string",
                "required": False,
                "description": """
                Search criteria in the following format
                and | or conditions are supported but no brackets

                key operator value and key operator value

                e.g.:
                name ilike xxxx or id == 12
                Operators supported: ==, !=, >, >=, <, <=, ilike
            """,
            }
        ],
        "responses": {
            200: {"description": "Teams retrieved successfully"},
            404: {"description": "Teams not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def search_teams():
    try:
        query_param = request.args.get("query", "")
        query = QueryUtil.parseQuery(query_param)
        if not query or not query.elementA:
            raise Exception(f"No valid query found: {query_param}")
        teams = team_blueprint.team_app_service.search(query)
        out = []
        if teams:
            for team in teams:
                out.append(team.to_dict())
        return jsonify(out)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@jwt_required()
@team_blueprint.route(
    "/teams/w3c_sync/<int:team_id>/seasons/<int:season_id>", methods=["POST"]
)
@swag_from(
    {
        "summary": "Sync w3c information for each user of the team",
        "description": "Sync w3c information for each user of the team",
        "tags": ["teams"],
        "parameters": [
            {
                "name": "team_id",
                "in": "path",
                "type": "integer",
                "required": True,
                "description": "The ID of the team to sync",
            },
            {"name": "season_id", "in": "path", "type": "integer", "required": True},
        ],
        "responses": {
            204: {"description": "Team users synced successfully"},
            404: {"description": "Team not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def sync_w3c_users_season(team_id, season_id):
    try:
        cache_key = f"w3c_sync:{team_id}:{season_id}"
        last_sync_time = team_blueprint.cache.get(cache_key)

        if last_sync_time:
            return "Sync already performed today", 429

        team = team_blueprint.team_app_service.syncW3CStatsTeam(team_id, season_id)
        if team:
            team = team.to_dict()

        team_blueprint.cache.set(
            cache_key, True, timeout=86400
        )  # Store in cache for 24 hours

        team = team_blueprint.team_app_service.syncW3CStatsTeam(team_id, season_id)
        if team:
            team = team.to_dict()
        return jsonify(team)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@jwt_required()
@team_blueprint.route("/teams/<int:team_id>/image", methods=["POST"])
@swag_from(
    {
        "summary": "Upload or update a team's image",
        "description": "Allows a user to upload or modify a team's image stored in binary format",
        "tags": ["teams"],
        "consumes": ["multipart/form-data"],
        "parameters": [
            {
                "name": "team_id",
                "in": "path",
                "type": "integer",
                "required": True,
                "description": "The ID of the team",
            },
            {
                "name": "image",
                "in": "formData",
                "type": "file",
                "required": True,
                "description": "Binary image file",
            },
        ],
        "responses": {
            200: {"description": "Image successfully uploaded"},
            400: {"description": "Invalid image format"},
            404: {"description": "Team not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def upload_team_image(team_id):
    try:
        if "image" not in request.files:
            return jsonify({"error": "No image provided"}), 400

        file = request.files["image"]  # Get binary image
        file_data = file.read()  # Read binary data

        team_blueprint.team_app_service.update_team_icon(team_id, file_data)

        return jsonify({"message": "Image uploaded successfully"}), 200
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@team_blueprint.route("/teams/<int:team_id>/image", methods=["GET"])
@swag_from(
    {
        "summary": "Retrieve a team's image",
        "description": "Fetches and returns the stored binary image for a team",
        "tags": ["teams"],
        "produces": ["image/png", "image/jpeg"],
        "parameters": [
            {
                "name": "team_id",
                "in": "path",
                "type": "integer",
                "required": True,
                "description": "The ID of the team",
            }
        ],
        "responses": {
            200: {
                "description": "Image successfully retrieved",
                "content": {"image/png": {}, "image/jpeg": {}},
            },
            404: {"description": "Team not found or no image available"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_team_image(team_id):
    """Returns the stored image of a team"""
    try:
        team_icon = team_blueprint.team_app_service.get_team_icon(team_id)
        if not team_icon:
            return jsonify({"error": "Image not found"}), 404

        # Add cache headers for browser caching (cache for 1 hour)
        return (
            team_icon,
            200,
            {
                "Content-Type": "image/png",
                "Cache-Control": "public, max-age=3600",
                "ETag": f"team-{team_id}",
            },
        )
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
