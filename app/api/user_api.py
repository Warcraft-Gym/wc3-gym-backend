import logging

from flasgger import swag_from
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.exceptions import NotFoundException
from app.schemas.user import User
from app.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

user_blueprint = Blueprint("user_api", __name__)


# User endpoints
@user_blueprint.route("/users", methods=["POST"])
@jwt_required()
@swag_from(
    {
        "summary": "Add a new user",
        "description": "Create a new user with the provided details.",
        "tags": ["users"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {"name": "body", "in": "body", "required": True, "schema": User.schema()}
        ],
        "responses": {
            201: {"description": "User created successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def add_user():
    try:
        data = request.json
        user = user_blueprint.user_app_service.create_user(User(data))
        if user:
            user = user.to_dict()
        return jsonify(user), 201
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@user_blueprint.route("/users/<int:user_id>", methods=["PUT"])
@jwt_required()
@swag_from(
    {
        "summary": "Update an existing user",
        "description": "Update the details of an existing user.",
        "tags": ["users"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {
                "name": "user_id",
                "in": "path",
                "type": "integer",
                "required": True,
                "description": "The ID of the user to update",
            },
            {"name": "body", "in": "body", "required": True, "schema": User.schema()},
        ],
        "responses": {
            201: {"description": "User updated successfully"},
            404: {"description": "User not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def update_user(user_id):
    try:
        data = request.json
        user = user_blueprint.user_app_service.update_user(user_id, User(data))
        if user:
            user = user.to_dict()
        return jsonify(user)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@user_blueprint.route("/users/<int:user_id>", methods=["DELETE"])
@jwt_required()
@swag_from(
    {
        "summary": "Delete an existing user",
        "description": "Delete a user by their ID.",
        "tags": ["users"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {
                "name": "user_id",
                "in": "path",
                "type": "integer",
                "required": True,
                "description": "The ID of the user to delete",
            }
        ],
        "responses": {
            204: {"description": "User deleted successfully"},
            500: {"description": "Internal server error"},
        },
    }
)
def delete_user(user_id):
    try:
        user_blueprint.user_app_service.delete_user(user_id)
        return f"User Deleted: {user_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@user_blueprint.route("/users/<int:user_id>", methods=["GET"])
@swag_from(
    {
        "summary": "Get a user by ID",
        "description": "Retrieve a user by their ID.",
        "tags": ["users"],
        "parameters": [
            {
                "name": "user_id",
                "in": "path",
                "type": "integer",
                "required": True,
                "description": "The ID of the user to retrieve",
            }
        ],
        "responses": {
            200: {"description": "User retrieved successfully"},
            404: {"description": "User not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_user(user_id):
    try:
        user = user_blueprint.user_app_service.get_user(user_id)
        if user:
            user = user.to_dict()
        return jsonify(user)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500


@user_blueprint.route("/users", methods=["GET"])
@swag_from(
    {
        "summary": "Get all users",
        "description": "Retrieve all users.",
        "tags": ["users"],
        "responses": {
            200: {"description": "Users retrieved successfully"},
            404: {"description": "Users not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_AllUser():
    try:
        users = user_blueprint.user_app_service.getAll()
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


@user_blueprint.route("/users/search", methods=["POST"])
@swag_from(
    {
        "summary": "Search users by criteria",
        "description": "Search users by criteria using a custom query format.",
        "tags": ["users"],
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
            200: {"description": "Users retrieved successfully"},
            404: {"description": "Users not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def search_users():
    try:
        query_param = request.args.get("query", "")
        query = QueryUtil.parseQuery(query_param)
        if not query or not query.elementA:
            raise Exception(f"No valid query found: {query_param}")
        users = user_blueprint.user_app_service.search(query)
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


@user_blueprint.route("/users/w3c_sync/<int:user_id>", methods=["POST"])
@jwt_required()
@swag_from(
    {
        "summary": "Sync w3c information for a user_id",
        "description": "Sync w3c information for a user_id",
        "tags": ["users"],
        "parameters": [
            {
                "name": "user_id",
                "in": "path",
                "type": "integer",
                "required": True,
                "description": "The ID of the user to sync",
            }
        ],
        "responses": {
            200: {"description": "User synced successfully"},
            404: {"description": "User not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def sync_w3c_user(user_id):
    try:
        user = user_blueprint.user_app_service.updateW3CStats_ById(user_id)
        if user:
            user = user.to_dict()
        return jsonify(user)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
