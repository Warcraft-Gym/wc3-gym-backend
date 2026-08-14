import logging

from flasgger import swag_from
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.exceptions import NotFoundException
from app.schemas.fantasy_bet import FantasyBet
from app.schemas.fantasy_team import FantasyTeam
from app.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

fantasy_blueprint = Blueprint("fantasy_api", __name__)


# Team endpoints
@fantasy_blueprint.route("/fantasy/teams", methods=["POST"])
@jwt_required()
@swag_from(
    {
        "summary": "Add a new fantasy team",
        "description": "Create a new fantasy team with the provided name.",
        "tags": ["fantasy"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": FantasyTeam.schema(),
            }
        ],
        "responses": {
            201: {"description": "Team created successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def add_fantasy_team():
    try:
        data = request.json
        team = fantasy_blueprint.fantasy_team_app_service.create_fantasy_team(
            FantasyTeam(data)
        )
        if team:
            team = team.to_dict()
        return jsonify(team), 201
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@fantasy_blueprint.route("/fantasy/teams/<int:team_id>", methods=["PUT"])
@jwt_required()
@swag_from(
    {
        "summary": "Update a fantasy team",
        "description": "Update an existing fantasy team.",
        "tags": ["fantasy"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "team_id", "in": "path", "type": "integer", "required": True},
            {
                "name": "body",
                "in": "body",
                "required": False,
                "schema": FantasyTeam.schema(),
            },
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
        team = fantasy_blueprint.fantasy_team_app_service.update_fantasy_team(
            team_id, FantasyTeam(data)
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


@fantasy_blueprint.route("/fantasy/teams/<int:team_id>", methods=["DELETE"])
@jwt_required()
@swag_from(
    {
        "summary": "Delete a team",
        "description": "Delete a team by its ID.",
        "tags": ["fantasy"],
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
        fantasy_blueprint.fantasy_team_app_service.delete_fantasy_team(team_id)
        return f"Team Deleted: {team_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@fantasy_blueprint.route("/fantasy/teams/<int:team_id>", methods=["GET"])
@swag_from(
    {
        "summary": "Get a team",
        "description": "Retrieve a team by its ID.",
        "tags": ["fantasy"],
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
        team = fantasy_blueprint.fantasy_team_app_service.get_fantasy_team(team_id)
        if team:
            team = team.to_dict()
        return jsonify(team)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@fantasy_blueprint.route("/fantasy/teams/addPlayers/<int:team_id>", methods=["POST"])
@jwt_required()
@swag_from(
    {
        "summary": "Add players to a fantasy team for a season",
        "description": "Add players to a fantasy team for a season using their IDs.",
        "tags": ["fantasy"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "team_id", "in": "path", "type": "integer", "required": True},
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
def addPlayers(team_id):
    try:
        data = request.json
        team = fantasy_blueprint.fantasy_team_app_service.addFantasyPlayers(
            team_id, data.get("player_ids")
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


@fantasy_blueprint.route("/fantasy/teams/removePlayers/<int:team_id>", methods=["POST"])
@jwt_required()
@swag_from(
    {
        "summary": "Removes players from a fantasy team for a season",
        "description": "Removes players from a fantasy team for a season using their IDs.",
        "tags": ["fantasy"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "team_id", "in": "path", "type": "integer", "required": True},
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
def removePlayers(team_id):
    try:
        data = request.json
        team = fantasy_blueprint.fantasy_team_app_service.removeFantasyPlayers(
            team_id, data.get("player_ids")
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


@fantasy_blueprint.route("/fantasy/teams", methods=["GET"])
@swag_from(
    {
        "summary": "Get all fantasy teams",
        "description": "Retrieve all fantasy teams.",
        "tags": ["fantasy"],
        "responses": {
            200: {"description": "Teams retrieved successfully"},
            404: {"description": "Teams not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_all_teams():
    try:
        teams = fantasy_blueprint.fantasy_team_app_service.getAll_fantasy_teams()
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


@fantasy_blueprint.route("/fantasy/teams/search", methods=["POST"])
@swag_from(
    {
        "summary": "Search teams by criteria",
        "description": "Search teams by criteria using a custom query format.",
        "tags": ["fantasy"],
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
        teams = fantasy_blueprint.fantasy_team_app_service.search_fantasy_teams(query)
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


# Bet endpoints
@fantasy_blueprint.route("/fantasy/bets", methods=["POST"])
@jwt_required()
@swag_from(
    {
        "summary": "Add a new fantasy bet",
        "description": "Create a new fantasy bet with the provided name.",
        "tags": ["fantasy"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": FantasyBet.schema(),
            }
        ],
        "responses": {
            201: {"description": "Bet created successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def add_fantasy_bet():
    try:
        data = request.json
        bet = fantasy_blueprint.fantasy_bet_app_service.create_fantasy_bet(
            FantasyBet(data)
        )
        if bet:
            bet = bet.to_dict()
        return jsonify(bet), 201
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error creating fantasy bet: {e}")
        return jsonify({"error": str(e)}), 500


@fantasy_blueprint.route("/fantasy/bets/<int:bet_id>", methods=["PUT"])
@jwt_required()
@swag_from(
    {
        "summary": "Update a fantasy bet",
        "description": "Update an existing fantasy bet.",
        "tags": ["fantasy"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "bet_id", "in": "path", "type": "integer", "required": True},
            {
                "name": "body",
                "in": "body",
                "required": False,
                "schema": FantasyBet.schema(),
            },
        ],
        "responses": {
            200: {"description": "Bet updated successfully"},
            404: {"description": "Bet not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def update_bet(bet_id):
    try:
        data = request.json
        bet = fantasy_blueprint.fantasy_bet_app_service.update_fantasy_bet(
            bet_id, FantasyBet(data)
        )
        if bet:
            bet = bet.to_dict()
        return jsonify(bet)
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        return jsonify({"error": str(e)}), 400
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@fantasy_blueprint.route("/fantasy/bets/<int:bet_id>", methods=["DELETE"])
@jwt_required()
@swag_from(
    {
        "summary": "Delete a bet",
        "description": "Delete a bet by its ID.",
        "tags": ["fantasy"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "bet_id", "in": "path", "type": "integer", "required": True}
        ],
        "responses": {
            204: {"description": "Bet deleted successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def delete_bet(bet_id):
    try:
        fantasy_blueprint.fantasy_bet_app_service.delete_fantasy_bet(bet_id)
        return f"Bet Deleted: {bet_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@fantasy_blueprint.route("/fantasy/bets/<int:bet_id>", methods=["GET"])
@swag_from(
    {
        "summary": "Get a bet",
        "description": "Retrieve a bet by its ID.",
        "tags": ["fantasy"],
        "parameters": [
            {"name": "bet_id", "in": "path", "type": "integer", "required": True}
        ],
        "responses": {
            200: {"description": "Bet retrieved successfully"},
            404: {"description": "Bet not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_bet(bet_id):
    try:
        bet = fantasy_blueprint.fantasy_bet_app_service.get_fantasy_bet(bet_id)
        if bet:
            bet = bet.to_dict()
        return jsonify(bet)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@fantasy_blueprint.route("/fantasy/bets", methods=["GET"])
@swag_from(
    {
        "summary": "Get all fantasy bets",
        "description": "Retrieve all fantasy bets.",
        "tags": ["fantasy"],
        "responses": {
            200: {"description": "bets retrieved successfully"},
            404: {"description": "bets not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_all_bets():
    try:
        bets = fantasy_blueprint.fantasy_bet_app_service.getAll_fantasy_bets()
        out = []
        if bets:
            for bet in bets:
                out.append(bet.to_dict())
        return jsonify(out)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@fantasy_blueprint.route("/fantasy/bets/search", methods=["POST"])
@swag_from(
    {
        "summary": "Search bets by criteria",
        "description": "Search bets by criteria using a custom query format.",
        "tags": ["fantasy"],
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
            200: {"description": "bets retrieved successfully"},
            404: {"description": "bets not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def search_bets():
    try:
        query_param = request.args.get("query", "")
        query = QueryUtil.parseQuery(query_param)
        if not query or not query.elementA:
            raise Exception(f"No valid query found: {query_param}")
        bets = fantasy_blueprint.fantasy_bet_app_service.search_fantasy_bets(query)
        out = []
        if bets:
            for bet in bets:
                out.append(bet.to_dict())
        return jsonify(out)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@fantasy_blueprint.route(
    "/fantasy/teams/<int:team_id>/season/<int:season_id>/breakdown", methods=["GET"]
)
@swag_from(
    {
        "summary": "Get detailed score breakdown for a fantasy team",
        "description": "Returns a detailed breakdown showing how each component of the fantasy team score was calculated.",
        "tags": ["fantasy"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {
                "name": "team_id",
                "in": "path",
                "type": "integer",
                "required": True,
                "description": "The ID of the fantasy team",
            },
            {
                "name": "season_id",
                "in": "path",
                "type": "integer",
                "required": True,
                "description": "The ID of the season",
            },
        ],
        "responses": {
            200: {
                "description": "Score breakdown retrieved successfully",
                "schema": {
                    "type": "object",
                    "properties": {
                        "team_id": {"type": "integer"},
                        "team_name": {"type": "string"},
                        "season_id": {"type": "integer"},
                        "season_name": {"type": "string"},
                        "player_breakdown": {"type": "array"},
                        "bench_breakdown": {"type": "array"},
                        "team_breakdown": {"type": "object"},
                        "race_breakdown": {"type": "object"},
                        "bet_breakdown": {"type": "array"},
                        "totals": {"type": "object"},
                    },
                },
            },
            404: {"description": "Fantasy team or season not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_fantasy_team_breakdown(team_id: int, season_id: int):
    try:
        season = fantasy_blueprint.season_app_service.get_season(season_id)
        if not season:
            return jsonify({"error": f"Season with id {season_id} not found"}), 404

        breakdown = fantasy_blueprint.fantasy_score_app_service.getTeamScoreBreakdown(
            team_id, season
        )
        return jsonify(breakdown), 200
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@fantasy_blueprint.route("/fantasy/season/<int:season_id>/calculate/", methods=["POST"])
@jwt_required()
@swag_from(
    {
        "summary": "Calculate the fantasy scores of a given season",
        "description": "Calculates all fantasy team scores for the given season.",
        "tags": ["fantasy"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {
                "name": "season_id",
                "in": "path",
                "type": "integer",
                "required": True,
                "description": "The ID of the season to calculate",
            },
        ],
        "responses": {
            204: {"description": "Score calculated successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def calc_fantasy_score(season_id: int):
    try:
        season = fantasy_blueprint.season_app_service.get_season(season_id)
        fantasy_blueprint.fantasy_score_app_service.calculateTeamScores(season)

        return "Fantasy Scores Calcuated Successfully", 204
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
