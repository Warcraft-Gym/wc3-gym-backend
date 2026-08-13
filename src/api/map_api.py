import logging

from flasgger import swag_from
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from custom_exceptions import NotFoundException
from src.schemas.map import Map
from src.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

map_blueprint = Blueprint("map_api", __name__)


# Map endpoints
@map_blueprint.route("/maps", methods=["POST"])
@jwt_required()
@swag_from(
    {
        "summary": "Add a new map",
        "description": "Create a new map with the provided details.",
        "tags": ["maps"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "body", "in": "body", "required": True, "schema": Map.schema()}
        ],
        "responses": {
            201: {"description": "Map created successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def add_map():
    try:
        data = request.json
        map = map_blueprint.map_app_service.create_map(Map(data))
        if map:
            map = map.to_dict()
        return jsonify(map), 201
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@map_blueprint.route("/maps/<int:map_id>", methods=["PUT"])
@jwt_required()
@swag_from(
    {
        "summary": "Update an existing map",
        "description": "Update the details of an existing map.",
        "tags": ["maps"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {
                "name": "map_id",
                "in": "path",
                "type": "integer",
                "required": True,
                "description": "The ID of the map to update",
            },
            {"name": "body", "in": "body", "required": True, "schema": Map.schema()},
        ],
        "responses": {
            201: {"description": "Map updated successfully"},
            404: {"description": "Map not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def update_map(map_id):
    try:
        data = request.json
        map = map_blueprint.map_app_service.update_map(map_id, Map(data))
        if map:
            map = map.to_dict()
        return jsonify(map)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@map_blueprint.route("/maps/<int:map_id>", methods=["DELETE"])
@jwt_required()
@swag_from(
    {
        "summary": "Delete an existing map",
        "description": "Delete a map by their ID.",
        "tags": ["maps"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {
                "name": "map_id",
                "in": "path",
                "type": "integer",
                "required": True,
                "description": "The ID of the map to delete",
            }
        ],
        "responses": {
            204: {"description": "Map deleted successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def delete_map(map_id):
    try:
        map_blueprint.map_app_service.delete_map(map_id)
        return f"Map Deleted: {map_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@map_blueprint.route("/maps/<int:map_id>", methods=["GET"])
@swag_from(
    {
        "summary": "Get a map by ID",
        "description": "Retrieve a map by their ID.",
        "tags": ["maps"],
        "parameters": [
            {
                "name": "map_id",
                "in": "path",
                "type": "integer",
                "required": True,
                "description": "The ID of the map to retrieve",
            }
        ],
        "responses": {
            200: {"description": "map retrieved successfully"},
            404: {"description": "map not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_map(map_id):
    try:
        map = map_blueprint.map_app_service.get_map(map_id)
        if map:
            map = map.to_dict()
        return jsonify(map)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@map_blueprint.route("/maps", methods=["GET"])
@swag_from(
    {
        "summary": "Get all maps",
        "description": "Retrieve all maps.",
        "tags": ["maps"],
        "responses": {
            200: {"description": "Maps retrieved successfully"},
            404: {"description": "Maps not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_AllMap():
    try:
        maps = map_blueprint.map_app_service.getAll()
        out = []
        if maps:
            for map in maps:
                out.append(map.to_dict())
        return jsonify(out)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@map_blueprint.route("/maps/search", methods=["POST"])
@swag_from(
    {
        "summary": "Search maps by criteria",
        "description": "Search maps by criteria using a custom query format.",
        "tags": ["maps"],
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
            200: {"description": "Maps retrieved successfully"},
            404: {"description": "Maps not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def search_maps():
    try:
        query_param = request.args.get("query", "")
        query = QueryUtil.parseQuery(query_param)
        if not query or not query.elementA:
            raise Exception(f"No valid query found: {query_param}")
        maps = map_blueprint.map_app_service.search(query)
        out = []
        if maps:
            for map in maps:
                out.append(map.to_dict())
        return jsonify(out)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
