from app import app
from flask import request, jsonify, redirect
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from custom_exceptions import NotFoundException

# Login endpoint to generate JWT token
@app.route('/', methods=['GET'])
def index():
    return redirect('/apidocs/')

# Login endpoint to generate JWT token
@app.route('/login', methods=['POST'])
def login():
    data = request.json
    # For demonstration purposes, we are using a hardcoded user
    if data['token'] == 'this_is_my_token':
        access_token = create_access_token(identity={'username': 'admin'})
        return jsonify(access_token=access_token), 200
    return jsonify({"msg": "Bad username or password"}), 401