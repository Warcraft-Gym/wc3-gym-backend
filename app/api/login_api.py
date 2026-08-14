import os
from datetime import timedelta

from flasgger import swag_from
from flask import Blueprint, jsonify, redirect, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt_identity,
    jwt_required,
)

login_blueprint = Blueprint("login_api", __name__)


# Index endpoint
@login_blueprint.route("/", methods=["GET"])
def index():
    return redirect("/apidocs/")


# Login endpoint to generate JWT token
@login_blueprint.route("/login", methods=["POST"])
@swag_from(
    {
        "tags": ["Authentication"],
        "parameters": [
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "token": {
                            "type": "string",
                            "description": "The authentication token",
                        }
                    },
                },
            }
        ],
        "responses": {
            200: {
                "description": "Successfully generated JWT token",
                "schema": {
                    "type": "object",
                    "properties": {
                        "access_token": {
                            "type": "string",
                            "description": "The JWT access token",
                            "example": "this_is_my_token",
                        },
                        "refresh_token": {
                            "type": "string",
                            "description": "The JWT refresh token",
                        },
                    },
                },
            },
            401: {"description": "Invalid credentials"},
        },
    }
)
def login():
    data = request.json
    token_time = int(os.getenv("TOKEN_TIME"))
    if not token_time:
        token_time = 15
    refresh_token_time = int(os.getenv("REFRESH_TOKEN_TIME"))
    if not refresh_token_time:
        refresh_token_time = 300
    if data["token"] == os.getenv("ADMIN_TOKEN"):
        access_token = create_access_token(
            identity="admin", expires_delta=timedelta(minutes=token_time)
        )
        refresh_token = create_refresh_token(
            identity="admin", expires_delta=timedelta(minutes=refresh_token_time)
        )
        return jsonify(access_token=access_token, refresh_token=refresh_token), 200
    return jsonify({"msg": "Bad admin token"}), 401


@swag_from(
    {
        "tags": ["Authentication"],
        "security": [{"RefreshAuth": []}],
        "parameters": [],
        "responses": {
            200: {
                "description": "Successfully generated JWT token",
                "schema": {
                    "type": "object",
                    "properties": {
                        "access_token": {
                            "type": "string",
                            "description": "The JWT access token",
                            "example": "this_is_my_token",
                        }
                    },
                },
            },
            401: {"description": "Invalid credentials"},
        },
    }
)
@login_blueprint.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    current_user = get_jwt_identity()
    token_time = int(os.getenv("TOKEN_TIME"))
    if not token_time:
        token_time = 15

    new_access_token = create_access_token(
        identity=current_user, expires_delta=timedelta(minutes=token_time)
    )
    return jsonify(access_token=new_access_token), 200
