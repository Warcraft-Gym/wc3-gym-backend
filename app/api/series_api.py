import logging
import traceback

from flasgger import swag_from
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.exceptions import NotFoundException
from app.schemas.series import Series
from app.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

series_blueprint = Blueprint("series_api", __name__)


# series endpoints
@series_blueprint.route("/series", methods=["POST"])
@jwt_required()
@swag_from(
    {
        "summary": "Add a new series",
        "description": "Create a new series with the provided data",
        "tags": ["series"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "body", "in": "body", "required": True, "schema": Series.schema()}
        ],
        "responses": {
            201: {"description": "Series created successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def add_series():
    try:
        data = request.json
        series = series_blueprint.series_app_service.create_series(Series(data))
        if series:
            series = series.to_dict()
        return jsonify(series), 201
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@series_blueprint.route("/series/<int:series_id>", methods=["PUT"])
@jwt_required()
@swag_from(
    {
        "summary": "Updates a series",
        "description": "Update the series data of an existing series",
        "tags": ["series"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "series_id", "in": "path", "type": "integer", "required": True},
            {
                "name": "body",
                "in": "body",
                "required": False,
                "schema": Series.schema(),
            },
        ],
        "responses": {
            200: {"description": "series updated successfully"},
            404: {"description": "series not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def update_series(series_id):
    try:
        data = request.json
        series = series_blueprint.series_app_service.update_series(
            series_id, Series(data)
        )
        if series:
            series = series.to_dict()
        return jsonify(series)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@series_blueprint.route("/series/<int:series_id>", methods=["DELETE"])
@jwt_required()
@swag_from(
    {
        "summary": "Delete a series",
        "description": "Delete a series by its ID.",
        "tags": ["series"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "series_id", "in": "path", "type": "integer", "required": True}
        ],
        "responses": {
            204: {"description": "season deleted successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def delete_series(series_id):
    try:
        series_blueprint.series_app_service.delete_series(series_id)
        return f"series Deleted: {series_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@series_blueprint.route("/series/<int:series_id>", methods=["GET"])
@swag_from(
    {
        "summary": "Get a series",
        "description": "Retrieve a series by its ID.",
        "tags": ["series"],
        "parameters": [
            {"name": "series_id", "in": "path", "type": "integer", "required": True}
        ],
        "responses": {
            200: {"description": "season retrieved successfully"},
            404: {"description": "season not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_series(series_id):
    try:
        series = series_blueprint.series_app_service.get_series(series_id)
        if series:
            series = series.to_dict()
        return jsonify(series)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@series_blueprint.route("/series/search", methods=["POST"])
@swag_from(
    {
        "summary": "Search series by criteria",
        "description": "Search series by criteria using a custom query format.",
        "tags": ["series"],
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
            200: {"description": "Series retrieved successfully"},
            404: {"description": "Series not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def search_series():
    try:
        query_param = request.args.get("query", "")
        query = QueryUtil.parseQuery(query_param)
        if not query or not query.elementA:
            raise Exception(f"No valid query found: {query_param}")
        series_l = series_blueprint.series_app_service.search(query)
        out = []
        if series_l:
            for series in series_l:
                out.append(series.to_dict())
        return jsonify(out)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@series_blueprint.route(
    "/series/season/<int:season_id>/playday/<int:playday>/search", methods=["POST"]
)
@swag_from(
    {
        "summary": "Search series of a season of a playday",
        "description": "Return series matching the search query for a specific season and a specific playday",
        "tags": ["series"],
        "parameters": [
            {"name": "season_id", "in": "path", "type": "integer", "required": True},
            {"name": "playday", "in": "path", "type": "integer", "required": True},
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
            },
        ],
        "responses": {
            200: {"description": "series retrieved successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def search_series_by_season_and_playday(season_id: int, playday: int):
    try:
        query_param = request.args.get("query", "")
        query = QueryUtil.parseQuery(query_param)
        series_l = series_blueprint.series_app_service.searchForSeasonAndPlayday(
            season_id, playday, query
        )
        out = []
        if series_l:
            for series in series_l:
                out.append(series.to_dict())
        return jsonify(out)
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@series_blueprint.route("/series/season/<int:season_id>", methods=["GET"])
@swag_from(
    {
        "summary": "Get all series for a season",
        "description": "Return all series for a specific season",
        "tags": ["series"],
        "parameters": [
            {"name": "season_id", "in": "path", "type": "integer", "required": True}
        ],
        "responses": {
            200: {"description": "series retrieved successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_series_by_season(season_id: int):
    try:
        series_l = series_blueprint.series_app_service.searchForSeason(season_id, None)
        out = []
        if series_l:
            for series in series_l:
                out.append(series.to_dict())
        return jsonify(out)
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@series_blueprint.route("/series/season/<int:season_id>/search", methods=["POST"])
@swag_from(
    {
        "summary": "Search series of a season",
        "description": "Return series matching the search query for a specific season",
        "tags": ["series"],
        "parameters": [
            {"name": "season_id", "in": "path", "type": "integer", "required": True},
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
            },
        ],
        "responses": {
            200: {"description": "series retrieved successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def search_series_by_season(season_id: int):
    try:
        query_param = request.args.get("query", "")
        query = QueryUtil.parseQuery(query_param)
        series_l = series_blueprint.series_app_service.searchForSeason(season_id, query)
        out = []
        if series_l:
            for series in series_l:
                out.append(series.to_dict())
        return jsonify(out)
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
