import os
from flask import Blueprint, request, jsonify, redirect
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, create_refresh_token
from flasgger import swag_from
from datetime import timedelta
from custom_exceptions import NotFoundException

login_blueprint = Blueprint('login_api', __name__)

# Index endpoint
@login_blueprint.route('/', methods=['GET'])
def index():
    return redirect('/apidocs/')

# Login endpoint to generate JWT token
@login_blueprint.route('/login', methods=['POST'])
@swag_from({
    'tags': ['Authentication'],
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'token': {
                        'type': 'string',
                        'description': 'The authentication token'
                    }
                }
            }
        }
    ],
    'responses': {
        200: {
            'description': 'Successfully generated JWT token',
            'schema': {
                'type': 'object',
                'properties': {
                    'access_token': {
                        'type': 'string',
                        'description': 'The JWT access token',
                        'example' : "this_is_my_token"
                    },
                    'refresh_token': {
                        'type': 'string',
                        'description': 'The JWT refresh token'
                    }
                }
            }
        },
        401: {
            'description': 'Invalid credentials'
        }
    }
})
def login():
    data = request.json
    if data['token'] == os.getenv('ADMIN_TOKEN'):
        access_token = create_access_token(identity='admin',expires_delta=timedelta(minutes=15))
        refresh_token = create_refresh_token(identity='admin')
        return jsonify(access_token=access_token, refresh_token=refresh_token), 200
    return jsonify({"msg": "Bad admin token"}), 401

@swag_from({
    'tags': ['Authentication'],
    'security': [{'RefreshAuth': []}],
    'parameters': [
    ],
    'responses': {
        200: {
            'description': 'Successfully generated JWT token',
            'schema': {
                'type': 'object',
                'properties': {
                    'access_token': {
                        'type': 'string',
                        'description': 'The JWT access token',
                        'example' : "this_is_my_token"
                    }
                }
            }
        },
        401: {
            'description': 'Invalid credentials'
        }
    }
})
@login_blueprint.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    current_user = get_jwt_identity()
    new_access_token = create_access_token(identity=current_user, expires_delta=timedelta(minutes=15))
    return jsonify(access_token=new_access_token), 200