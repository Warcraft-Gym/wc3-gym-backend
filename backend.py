from . import app
from flask import request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity


# Login endpoint to generate JWT token
@app.route('/', methods=['GET'])
def index():
    return "Hello World", 200

# Login endpoint to generate JWT token
@app.route('/login', methods=['POST'])
def login():
    data = request.json
    # For demonstration purposes, we are using a hardcoded user
    if data['token'] == 'this_is_my_token':
        access_token = create_access_token(identity={'username': 'admin'})
        return jsonify(access_token=access_token), 200
    return jsonify({"msg": "Bad username or password"}), 401

# User endpoints
@app.route('/users', methods=['POST'])
def add_user():
    data = request.json
    user = app.user_app_service.create_user(name=data['name'], email=data['email'])
    return jsonify(user), 201

@app.route('/users/<int:user_id>', methods=['PUT'])
@jwt_required()
def update_user(user_id):
    data = request.json
    user = app.user_app_service.update_user(user_id, name=data.get('name'), email=data.get('email'))
    return jsonify(user)

@app.route('/users/<int:user_id>', methods=['DELETE'])
@jwt_required()
def delete_user(user_id):
    app.user_app_service.delete_user(user_id)
    return '', 204

@app.route('/users/<int:user_id>', methods=['GET'])
@jwt_required()
def get_user(user_id):
    user = app.user_app_service.get_user(user_id)
    return jsonify(user)

# Team endpoints
@app.route('/teams', methods=['POST'])
@jwt_required()
def add_team():
    data = request.json
    team = app.team_app_service.create_team(name=data['name'])
    return jsonify(team), 201

@app.route('/teams/<int:team_id>', methods=['PUT'])
@jwt_required()
def update_team(team_id):
    data = request.json
    team = app.team_app_service.update_team(team_id, name=data.get('name'))
    return jsonify(team)

@app.route('/teams/<int:team_id>', methods=['DELETE'])
@jwt_required()
def delete_team(team_id):
    app.team_app_service.delete_team(team_id)
    return '', 204

@app.route('/teams/<int:team_id>', methods=['GET'])
@jwt_required()
def get_team(team_id):
    team = app.team_app_service.get_team(team_id)
    return jsonify(team)

# Match endpoints
@app.route('/matches', methods=['POST'])
@jwt_required()
def add_match():
    data = request.json
    match = app.match_app_service.create_match(team1_id=data['team1_id'], team2_id=data['team2_id'], score=data['score'])
    return jsonify(match), 201

@app.route('/matches/<int:match_id>', methods=['PUT'])
@jwt_required()
def update_match(match_id):
    data = request.json
    match = app.match_app_service.update_match(match_id, score=data.get('score'))
    return jsonify(match)

@app.route('/matches/<int:match_id>', methods=['DELETE'])
@jwt_required()
def delete_match(match_id):
    app.match_app_service.delete_match(match_id)
    return '', 204

@app.route('/matches/<int:match_id>', methods=['GET'])
@jwt_required()
def get_match(match_id):
    match = app.match_app_service.get_match(match_id)
    return jsonify(match)