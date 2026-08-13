import logging

from flasgger import swag_from
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from custom_exceptions import NotFoundException
from src.schemas.season import Season
from src.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

season_blueprint = Blueprint("season_api", __name__)


# season endpoints
@season_blueprint.route("/seasons", methods=["POST"])
@jwt_required()
@swag_from(
    {
        "summary": "Add a new season",
        "description": "Create a new season with the provided name.",
        "tags": ["seasons"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "body", "in": "body", "required": True, "schema": Season.schema()}
        ],
        "responses": {
            201: {"description": "Season created successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def add_season():
    try:
        data = request.json
        season = season_blueprint.season_app_service.create_season(Season(data))
        if season:
            season = season.to_dict()
        return jsonify(season), 201
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@season_blueprint.route("/seasons/<int:season_id>", methods=["PUT"])
@jwt_required()
@swag_from(
    {
        "summary": "Update a season",
        "description": "Update the name of an existing season.",
        "tags": ["seasons"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "season_id", "in": "path", "type": "integer", "required": True},
            {
                "name": "body",
                "in": "body",
                "required": False,
                "schema": Season.schema(),
            },
        ],
        "responses": {
            200: {"description": "season updated successfully"},
            404: {"description": "season not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def update_season(season_id):
    try:
        data = request.json
        season = season_blueprint.season_app_service.update_season(
            season_id, Season(data)
        )
        if season:
            season = season.to_dict()
        return jsonify(season)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@season_blueprint.route("/seasons/<int:season_id>", methods=["DELETE"])
@jwt_required()
@swag_from(
    {
        "summary": "Delete a season",
        "description": "Delete a season by its ID.",
        "tags": ["seasons"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "season_id", "in": "path", "type": "integer", "required": True}
        ],
        "responses": {
            204: {"description": "season deleted successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def delete_season(season_id):
    try:
        season_blueprint.season_app_service.delete_season(season_id)
        return f"season Deleted: {season_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@season_blueprint.route("/seasons/<int:season_id>", methods=["GET"])
@swag_from(
    {
        "summary": "Get a season",
        "description": "Retrieve a season by its ID.",
        "tags": ["seasons"],
        "parameters": [
            {"name": "season_id", "in": "path", "type": "integer", "required": True}
        ],
        "responses": {
            200: {"description": "season retrieved successfully"},
            404: {"description": "season not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_season(season_id):
    try:
        season = season_blueprint.season_app_service.get_season(season_id)
        if season:
            season = season.to_dict()
        return jsonify(season)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@season_blueprint.route("/seasons/addTeams/<int:season_id>", methods=["POST"])
@jwt_required()
@swag_from(
    {
        "summary": "Add teams to season",
        "description": "Add teams to season by providing a list of team ids.",
        "tags": ["seasons"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "season_id", "in": "path", "type": "integer", "required": True},
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "team_ids": {"type": "array", "items": {"type": "integer"}}
                    },
                    "required": ["team_ids"],
                },
            },
        ],
        "responses": {
            200: {"description": "Added teams to season successfully"},
            404: {"description": "Season or Teams not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def add_teams(season_id):
    try:
        data = request.json
        season = season_blueprint.season_app_service.addTeams(
            season_id, data.get("team_ids")
        )
        if season:
            season = season.to_dict()
        return jsonify(season)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@season_blueprint.route("/seasons/removeTeams/<int:season_id>", methods=["POST"])
@jwt_required()
@swag_from(
    {
        "summary": "Remove teams from season",
        "description": "Remove teams from season by providing a list of team ids.",
        "tags": ["seasons"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "season_id", "in": "path", "type": "integer", "required": True},
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "team_ids": {"type": "array", "items": {"type": "integer"}}
                    },
                    "required": ["team_ids"],
                },
            },
        ],
        "responses": {
            200: {"description": "Removed teams from season successfully"},
            404: {"description": "Season or Teams not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def remove_teams(season_id):
    try:
        data = request.json
        season = season_blueprint.season_app_service.removeTeams(
            season_id, data.get("team_ids")
        )
        if season:
            season = season.to_dict()
        return jsonify(season)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@season_blueprint.route("/seasons", methods=["GET"])
@swag_from(
    {
        "summary": "Get all seasons",
        "description": "Return all seasons",
        "tags": ["seasons"],
        "responses": {
            200: {"description": "seasons retrieved successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_all():
    try:
        seasons = season_blueprint.season_app_service.getAll()
        out = []
        if seasons:
            for season in seasons:
                out.append(season.to_dict())
        return jsonify(out)
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@season_blueprint.route("/seasons/search", methods=["POST"])
@swag_from(
    {
        "summary": "Search seasons by criteria",
        "description": "Search seasons by criteria using a custom query format.",
        "tags": ["seasons"],
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
            200: {"description": "Seasons retrieved successfully"},
            404: {"description": "Seasons not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def search_seasons():
    try:
        query_param = request.args.get("query", "")
        query = QueryUtil.parseQuery(query_param)
        if not query or not query.elementA:
            raise Exception(f"No valid query found: {query_param}")
        seasons = season_blueprint.season_app_service.search(query)
        out = []
        if seasons:
            for season in seasons:
                out.append(season.to_dict())
        return jsonify(out)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@season_blueprint.route("/seasons/addMaps/<int:season_id>", methods=["POST"])
@jwt_required()
@swag_from(
    {
        "summary": "Add maps to season",
        "description": "Add maps to season by providing a list of map ids.",
        "tags": ["seasons"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "season_id", "in": "path", "type": "integer", "required": True},
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "map_ids": {"type": "array", "items": {"type": "integer"}}
                    },
                    "required": ["map_ids"],
                },
            },
        ],
        "responses": {
            200: {"description": "Added maps to season successfully"},
            404: {"description": "Season or Maps not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def add_maps(season_id):
    try:
        data = request.json
        season = season_blueprint.season_app_service.addMaps(
            season_id, data.get("map_ids")
        )
        if season:
            season = season.to_dict()
        return jsonify(season)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@season_blueprint.route("/seasons/removeMaps/<int:season_id>", methods=["POST"])
@jwt_required()
@swag_from(
    {
        "summary": "Remove maps from season",
        "description": "Remove maps from season by providing a list of map ids.",
        "tags": ["seasons"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "season_id", "in": "path", "type": "integer", "required": True},
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "map_ids": {"type": "array", "items": {"type": "integer"}}
                    },
                    "required": ["map_ids"],
                },
            },
        ],
        "responses": {
            200: {"description": "Removed maps from season successfully"},
            404: {"description": "Season or Maps not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def remove_maps(season_id):
    try:
        data = request.json
        season = season_blueprint.season_app_service.removeMaps(
            season_id, data.get("map_ids")
        )
        if season:
            season = season.to_dict()
        return jsonify(season)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@season_blueprint.route("/seasons/addUserSignup/<int:season_id>", methods=["POST"])
@jwt_required()
@swag_from(
    {
        "summary": "Add user signups to season",
        "description": "Add signup users to season by providing a list of user ids.",
        "tags": ["seasons"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "season_id", "in": "path", "type": "integer", "required": True},
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "user_ids": {"type": "array", "items": {"type": "integer"}}
                    },
                    "required": ["user_ids"],
                },
            },
        ],
        "responses": {
            200: {"description": "Added user signups to season successfully"},
            404: {"description": "Season or Users not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def add_user_signup(season_id):
    try:
        data = request.json
        season = season_blueprint.season_app_service.addUserSignup(
            season_id, data.get("user_ids")
        )
        if season:
            season = season.to_dict()
        return jsonify(season)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@season_blueprint.route("/seasons/removeUserSignup/<int:season_id>", methods=["POST"])
@jwt_required()
@swag_from(
    {
        "summary": "Remove user signups from season",
        "description": "Remove signup users from season by providing a list of user ids.",
        "tags": ["seasons"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "season_id", "in": "path", "type": "integer", "required": True},
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "user_ids": {"type": "array", "items": {"type": "integer"}}
                    },
                    "required": ["user_ids"],
                },
            },
        ],
        "responses": {
            200: {"description": "Removed user signups from season successfully"},
            404: {"description": "Season or Users not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def remove_user_signup(season_id):
    try:
        data = request.json
        season = season_blueprint.season_app_service.removeUserSignup(
            season_id, data.get("user_ids")
        )
        if season:
            season = season.to_dict()
        return jsonify(season)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@season_blueprint.route("/seasons/<int:season_id>/signups", methods=["GET"])
@swag_from(
    {
        "summary": "Get signed up users for a season",
        "description": "Retrieve all users signed up for a specific season.",
        "tags": ["seasons"],
        "parameters": [
            {"name": "season_id", "in": "path", "type": "integer", "required": True}
        ],
        "responses": {
            200: {"description": "Signed up users retrieved successfully"},
            404: {"description": "Season not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_season_signups(season_id):
    try:
        users = season_blueprint.season_app_service.getSignedUpUsers(season_id)
        out = []
        if users:
            for user in users:
                out.append(user.to_dict())
        return jsonify(out)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
