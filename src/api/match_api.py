import logging

from flasgger import swag_from
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from custom_exceptions import NotFoundException
from src.schemas.match import Match
from src.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

match_blueprint = Blueprint("match_api", __name__)


# Match endpoints
@match_blueprint.route("/matches", methods=["POST"])
@jwt_required()
@swag_from(
    {
        "summary": " Add a new match",
        "description": "Creates a new match between two teams with the given teams and score.",
        "tags": ["matches"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "body", "in": "body", "required": True, "schema": Match.schema()}
        ],
        "responses": {
            201: {"description": "Match created successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def add_match():
    try:
        data = request.json
        match = match_blueprint.match_app_service.create_match(Match(data))
        if match:
            match = match.to_dict()
        return jsonify(match), 201
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@match_blueprint.route("/matches/<int:match_id>", methods=["PUT"])
@jwt_required()
@swag_from(
    {
        "summary": "Update a match",
        "description": "Update the data of an existing matcht.",
        "tags": ["matches"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "match_id", "in": "path", "type": "integer", "required": True},
            {"name": "body", "in": "body", "required": False, "schema": Match.schema()},
        ],
        "responses": {
            200: {"description": "Match updated successfully"},
            404: {"description": "Match not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def update_match(match_id):
    try:
        data = request.json
        match = match_blueprint.match_app_service.update_match(match_id, Match(data))
        if match:
            match = match.to_dict()
        return jsonify(match)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@match_blueprint.route("/matches/<int:match_id>", methods=["DELETE"])
@jwt_required()
@swag_from(
    {
        "summary": "Delete a match",
        "description": "Delete a match by its ID.",
        "tags": ["matches"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "match_id", "in": "path", "type": "integer", "required": True}
        ],
        "responses": {
            204: {"description": "Match deleted successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def delete_match(match_id):
    try:
        match_blueprint.match_app_service.delete_match(match_id)
        return f"Match Deleted: {match_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@match_blueprint.route("/matches/<int:match_id>", methods=["GET"])
@swag_from(
    {
        "summary": "Get a match",
        "description": "Retrieve a match by its ID.",
        "tags": ["matches"],
        "parameters": [
            {"name": "match_id", "in": "path", "type": "integer", "required": True}
        ],
        "responses": {
            200: {"description": "Match retrieved successfully"},
            404: {"description": "Match not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_match(match_id):
    try:
        match = match_blueprint.match_app_service.get_match(match_id)
        if match:
            match = match.to_dict()
        return jsonify(match)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@match_blueprint.route("/matches/search", methods=["POST"])
@swag_from(
    {
        "summary": "Search matches by criteria",
        "description": "Search matches by criteria using a custom query format.",
        "tags": ["matches"],
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
            200: {"description": "Matches retrieved successfully"},
            404: {"description": "Matches not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def search_match():
    try:
        query_param = request.args.get("query", "")
        query = QueryUtil.parseQuery(query_param)
        if not query or not query.elementA:
            raise Exception(f"No valid query found: {query_param}")
        matches = match_blueprint.match_app_service.search(query)

        out = []
        if matches:
            for match in matches:
                out.append(match.to_dict())
        return jsonify(out)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
