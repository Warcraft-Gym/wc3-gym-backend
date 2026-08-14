import logging
import secrets

from flasgger import swag_from
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

logger = logging.getLogger(__name__)

config_blueprint = Blueprint("config_api", __name__)


@config_blueprint.route("/config/settings", methods=["GET"])
@swag_from(
    {
        "summary": "Get all settings",
        "description": "Retrieve all configuration settings from database",
        "tags": ["config"],
        "responses": {
            200: {
                "description": "Settings retrieved successfully",
                "schema": {
                    "type": "object",
                    "properties": {
                        "settings": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "key": {"type": "string"},
                                    "value": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                            },
                        }
                    },
                },
            },
            500: {"description": "Internal server error"},
        },
    }
)
def get_settings():
    try:
        settings = config_blueprint.settings_app_service.get_all_settings()
        return jsonify({"settings": settings}), 200
    except Exception as e:
        logger.error(f"Error retrieving settings: {e}")
        return jsonify({"error": str(e)}), 500


@config_blueprint.route("/config/settings/<key>", methods=["GET"])
@swag_from(
    {
        "summary": "Get a single setting",
        "description": "Retrieve a specific setting by key",
        "tags": ["config"],
        "parameters": [
            {
                "name": "key",
                "in": "path",
                "type": "string",
                "required": True,
                "description": "Setting key",
            }
        ],
        "responses": {
            200: {"description": "Setting retrieved successfully"},
            404: {"description": "Setting not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def get_setting(key):
    try:
        setting = config_blueprint.settings_app_service.get_setting(key)
        if not setting:
            return jsonify({"error": f"Setting '{key}' not found"}), 404
        return jsonify(setting), 200
    except Exception as e:
        logger.error(f"Error retrieving setting {key}: {e}")
        return jsonify({"error": str(e)}), 500


@config_blueprint.route("/config/settings", methods=["PUT"])
@jwt_required()
@swag_from(
    {
        "summary": "Update settings",
        "description": "Update one or more configuration settings",
        "tags": ["config"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "settings": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                            "example": {
                                "current_wc3_season": "22",
                                "current_gnl_season": "5",
                            },
                        }
                    },
                    "required": ["settings"],
                },
            }
        ],
        "responses": {
            200: {"description": "Settings updated successfully"},
            400: {"description": "Invalid request"},
            500: {"description": "Internal server error"},
        },
    }
)
def update_settings():
    try:
        data = request.json
        settings = data.get("settings", {})

        if not settings:
            return jsonify({"error": "No settings provided"}), 400

        updated = config_blueprint.settings_app_service.update_settings(settings)

        return jsonify(
            {"message": "Settings updated successfully", "updated": updated}
        ), 200

    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        return jsonify({"error": str(e)}), 500


@config_blueprint.route("/config/settings/<key>", methods=["PUT"])
@jwt_required()
@swag_from(
    {
        "summary": "Update a single setting",
        "description": "Update a specific setting by key",
        "tags": ["config"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {
                "name": "key",
                "in": "path",
                "type": "string",
                "required": True,
                "description": "Setting key",
            },
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["value"],
                },
            },
        ],
        "responses": {
            200: {"description": "Setting updated successfully"},
            400: {"description": "Invalid request"},
            500: {"description": "Internal server error"},
        },
    }
)
def update_setting(key):
    try:
        data = request.json
        value = data.get("value")
        description = data.get("description")

        if value is None:
            return jsonify({"error": "Value is required"}), 400

        setting = config_blueprint.settings_app_service.update_setting(
            key, value, description
        )

        return jsonify(
            {"message": f"Setting '{key}' updated successfully", "setting": setting}
        ), 200

    except Exception as e:
        logger.error(f"Error updating setting {key}: {e}")
        return jsonify({"error": str(e)}), 500


@config_blueprint.route("/config/settings/<key>", methods=["DELETE"])
@jwt_required()
@swag_from(
    {
        "summary": "Delete a setting",
        "description": "Delete a specific setting by key",
        "tags": ["config"],
        "security": [{"BearerAuth": []}],
        "parameters": [
            {
                "name": "key",
                "in": "path",
                "type": "string",
                "required": True,
                "description": "Setting key",
            }
        ],
        "responses": {
            200: {"description": "Setting deleted successfully"},
            404: {"description": "Setting not found"},
            500: {"description": "Internal server error"},
        },
    }
)
def delete_setting(key):
    try:
        deleted = config_blueprint.settings_app_service.delete_setting(key)
        if not deleted:
            return jsonify({"error": f"Setting '{key}' not found"}), 404

        return jsonify({"message": f"Setting '{key}' deleted successfully"}), 200

    except Exception as e:
        logger.error(f"Error deleting setting {key}: {e}")
        return jsonify({"error": str(e)}), 500


@config_blueprint.route("/config/koth/nightbot-token", methods=["POST"])
@jwt_required()
@swag_from(
    {
        "summary": "Generate new KOTH Nightbot token",
        "description": "Generate a new secure token for KOTH Nightbot integration",
        "tags": ["config"],
        "security": [{"BearerAuth": []}],
        "responses": {
            200: {
                "description": "Token generated successfully",
                "schema": {
                    "type": "object",
                    "properties": {
                        "token": {"type": "string"},
                        "message": {"type": "string"},
                    },
                },
            },
            500: {"description": "Internal server error"},
        },
    }
)
def generate_nightbot_token():
    """Generate a new secure token for KOTH Nightbot integration"""
    try:
        # Generate a secure random token (64 characters hex)
        new_token = secrets.token_hex(32)

        # Store in settings
        config_blueprint.settings_app_service.update_setting(
            "KOTH_NIGHTBOT_TOKEN",
            new_token,
            "Secure token for KOTH Nightbot command integration",
        )

        return jsonify(
            {
                "token": new_token,
                "message": "KOTH Nightbot token generated successfully",
            }
        ), 200

    except Exception as e:
        logger.error(f"Error generating Nightbot token: {e}")
        return jsonify({"error": str(e)}), 500


@config_blueprint.route("/config/koth/nightbot-token", methods=["GET"])
@jwt_required()
@swag_from(
    {
        "summary": "Get current KOTH Nightbot token",
        "description": "Retrieve the current KOTH Nightbot integration token",
        "tags": ["config"],
        "security": [{"BearerAuth": []}],
        "responses": {
            200: {
                "description": "Token retrieved successfully",
                "schema": {
                    "type": "object",
                    "properties": {
                        "token": {"type": "string"},
                        "exists": {"type": "boolean"},
                    },
                },
            },
            500: {"description": "Internal server error"},
        },
    }
)
def get_nightbot_token():
    """Get the current KOTH Nightbot token"""
    try:
        setting = config_blueprint.settings_app_service.get_setting(
            "KOTH_NIGHTBOT_TOKEN"
        )

        if setting:
            return jsonify({"token": setting.get("value"), "exists": True}), 200
        else:
            return jsonify({"token": None, "exists": False}), 200

    except Exception as e:
        logger.error(f"Error retrieving Nightbot token: {e}")
        return jsonify({"error": str(e)}), 500
