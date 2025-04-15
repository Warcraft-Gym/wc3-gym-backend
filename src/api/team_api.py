import logging
from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required
from custom_exceptions import NotFoundException
from flasgger import swag_from
from src.dtos.team_dto import TeamDTO
from src.util.query_util import QueryUtil

logger = logging.getLogger(__name__)

team_blueprint = Blueprint('team_api', __name__)

# Team endpoints
@team_blueprint.route('/teams', methods=['POST'])
@jwt_required()
@swag_from({
    'summary': 'Add a new team',
    'description': 'Create a new team with the provided name.',
    'tags': ['teams'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': TeamDTO.schema()
        }
    ],
    'responses': {
        201: {'description': 'Team created successfully'},
        500: {'description': 'Internal server error'}
    }
})
def add_team():
    try:
        data = request.json
        team = team_blueprint.team_app_service.create_team(TeamDTO(data))
        if team:
            team = team.to_dict()
        return jsonify(team), 201
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@team_blueprint.route('/teams/<int:team_id>', methods=['PUT'])
@jwt_required()
@swag_from({
    'summary': 'Update a team',
    'description': 'Update the name of an existing team.',
    'tags': ['teams'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'team_id', 'in': 'path', 'type': 'integer', 'required': True},
        {
            'name': 'body',
            'in': 'body',
            'required': False,
            'schema': TeamDTO.schema()
        }
    ],
    'responses': {
        200: {'description': 'Team updated successfully'},
        404: {'description': 'Team not found'},
        500: {'description': 'Internal server error'}
    }
})
def update_team(team_id):
    try:
        data = request.json
        team = team_blueprint.team_app_service.update_team(team_id, TeamDTO(data))
        if team:
            team = team.to_dict()
        return jsonify(team)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@team_blueprint.route('/teams/<int:team_id>', methods=['DELETE'])
@jwt_required()
@swag_from({
    'summary': 'Delete a team',
    'description': 'Delete a team by its ID.',
    'tags': ['teams'],
    'security': [{'BearerAuth': []}],
    'parameters': [{'name': 'team_id', 'in': 'path', 'type': 'integer', 'required': True}],
    'responses': {
        204: {'description': 'Team deleted successfully'},
        500: {'description': 'Internal server error'}
    }
})
def delete_team(team_id):
    try:
        team_blueprint.team_app_service.delete_team(team_id)
        return f"Team Deleted: {team_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@team_blueprint.route('/teams/<int:team_id>', methods=['GET'])
@swag_from({
    'summary': 'Get a team',
    'description': 'Retrieve a team by its ID.',
    'tags': ['teams'],
    'parameters': [{'name': 'team_id', 'in': 'path', 'type': 'integer', 'required': True}],
    'responses': {
        200: {'description': 'Team retrieved successfully'},
        404: {'description': 'Team not found'},
        500: {'description': 'Internal server error'}
    }
})
def get_team(team_id):
    try:
        team = team_blueprint.team_app_service.get_team(team_id)
        if team:
            team = team.to_dict()
        return jsonify(team)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@team_blueprint.route('/teams/<int:team_id>/seasons/<int:season_id>', methods=['GET'])
@swag_from({
    'summary': 'Get a team for a specific season',
    'description': 'Retrieve a team by its ID with all information related to a specific season',
    'tags': ['teams'],
    'parameters': [{'name': 'team_id', 'in': 'path', 'type': 'integer', 'required': True},
                   {'name': 'season_id', 'in': 'path', 'type': 'integer', 'required': True}],
    'responses': {
        200: {'description': 'Team retrieved successfully'},
        404: {'description': 'Team not found'},
        500: {'description': 'Internal server error'}
    }
})
def get_team_season(team_id, season_id):
    try:
        team = team_blueprint.team_app_service.get_team_season(team_id, season_id)
        if team:
            team = team.to_dict()
        return jsonify(team)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
    

@team_blueprint.route('/teams/season/<int:season_id>', methods=['GET'])
@swag_from({
    'summary': 'Get all teams for a specific season',
    'description': 'Retrieve all teams with all information related to a specific season',
    'tags': ['teams'],
    'parameters': [{'name': 'season_id', 'in': 'path', 'type': 'integer', 'required': True}],
    'responses': {
        200: {'description': 'Team retrieved successfully'},
        404: {'description': 'Team not found'},
        500: {'description': 'Internal server error'}
    }
})
def getAll_season(season_id):
    try:
        teams = team_blueprint.team_app_service.get_teams_season(season_id)
        out = []
        if teams:
            for team in teams:
                out.append(team.to_dict())
        return jsonify(out)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@team_blueprint.route('/teams/addPlayers/<int:team_id>/seasons/<int:season_id>', methods=['POST'])
@jwt_required()
@swag_from({
    'summary': 'Add players to a team for a season',
    'description': 'Add players to a team for a season using their IDs.',
    'tags': ['teams'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'team_id', 'in': 'path', 'type': 'integer', 'required': True},
        {'name': 'season_id', 'in': 'path', 'type': 'integer', 'required': True},
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'player_ids': {'type': 'array', 'items': {'type': 'integer'}}
                },
                'required': ['player_ids']
            }
        }
    ],
    'responses': {
        200: {'description': 'Players added successfully'},
        404: {'description': 'Team not found'},
        500: {'description': 'Internal server error'}
    }
})
def addPlayers(team_id, season_id):
    try:
        data = request.json
        team = team_blueprint.team_app_service.addPlayers(team_id, season_id, data.get("player_ids"))
        if team:
            team = team.to_dict()
        return jsonify(team)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@team_blueprint.route('/teams/removePlayers/<int:team_id>/seasons/<int:season_id>', methods=['POST'])
@jwt_required()
@swag_from({
    'summary': 'Removes players from a team for a season',
    'description': 'Removes players from a team for a season using their IDs.',
    'tags': ['teams'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'team_id', 'in': 'path', 'type': 'integer', 'required': True},
        {'name': 'season_id', 'in': 'path', 'type': 'integer', 'required': True},
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'player_ids': {'type': 'array', 'items': {'type': 'integer'}}
                },
                'required': ['player_ids']
            }
        }
    ],
    'responses': {
        200: {'description': 'Players removed successfully'},
        404: {'description': 'Team not found'},
        500: {'description': 'Internal server error'}
    }
})
def removePlayers(team_id, season_id):
    try:
        data = request.json
        team = team_blueprint.team_app_service.removePlayers(team_id, season_id, data.get("player_ids"))
        if team:
            team = team.to_dict()
        return jsonify(team)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@team_blueprint.route('/teams', methods=['GET'])
@swag_from({
    'summary': 'Get all teams',
    'description': 'Retrieve all teams.',
    'tags': ['teams'],
    'responses': {
        200: {'description': 'Teams retrieved successfully'},
        404: {'description': 'Teams not found'},
        500: {'description': 'Internal server error'}
    }
})
def get_all_teams():
    try:
        teams = team_blueprint.team_app_service.getAll()
        out = []
        if teams:
            for team in teams:
                out.append(team.to_dict())
        return jsonify(out)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@team_blueprint.route('/teams/search', methods=['POST'])
@swag_from({
    'summary': 'Search teams by criteria',
    'description': 'Search teams by criteria using a custom query format.',
    'tags': ['teams'],
    'parameters': [
        {
            'name': 'query',
            'in': 'query',
            'type': 'string',
            'required': False,
            'description': '''
                Search criteria in the following format
                and | or conditions are supported but no brackets

                key operator value and key operator value

                e.g.:
                name ilike xxxx or id == 12
                Operators supported: ==, !=, >, >=, <, <=, ilike
            '''
        }
    ],
    'responses': {
        200: {'description': 'Teams retrieved successfully'},
        404: {'description': 'Teams not found'},
        500: {'description': 'Internal server error'}
    }
})
def search_teams():
    try:
        query_param = request.args.get('query', '')
        query = QueryUtil.parseQuery(query_param)
        if not query or not query.elementA:
            raise Exception(f"No valid query found: {query_param}")
        teams = team_blueprint.team_app_service.search(query)
        out = []
        if teams:
            for team in teams:
                out.append(team.to_dict())
        return jsonify(out)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
    
@jwt_required()
@team_blueprint.route('/teams/w3c_sync/<int:team_id>/seasons/<int:season_id>', methods=['POST'])
@swag_from({
    'summary': 'Sync w3c information for each user of the team',
    'description': 'Sync w3c information for each user of the team',
    'tags': ['teams'],
    'parameters': [
        {'name': 'team_id', 'in': 'path', 'type': 'integer', 'required': True, 'description': 'The ID of the team to sync'},
        {'name': 'season_id', 'in': 'path', 'type': 'integer', 'required': True}
        ],
    'responses': {
        204: {'description': 'Team users synced successfully'},
        404: {'description': 'Team not found'},
        500: {'description': 'Internal server error'}
    }
})
def sync_w3c_users_season(team_id, season_id):
    try:
        team = team_blueprint.team_app_service.syncW3CStatsTeam(team_id, season_id)
        if(team):
            team = team.to_dict()
        return jsonify(team)
        return f"Users synced!", 204
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500