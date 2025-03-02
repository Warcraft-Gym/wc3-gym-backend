from app import app
import os
from flask import request, jsonify, redirect
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from flasgger import swag_from
from custom_exceptions import NotFoundException

# Index endpoint
@app.route('/', methods=['GET'])
def index():
    return redirect('/apidocs/')

# Login endpoint to generate JWT token
@app.route('/login', methods=['POST'])
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
    if data['token'] == os.getenv('admin_token'):
        access_token = create_access_token(identity='admin')
        return jsonify(access_token=access_token), 200
    return jsonify({"msg": "Bad admin token"}), 401