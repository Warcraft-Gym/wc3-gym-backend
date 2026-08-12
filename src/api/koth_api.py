import logging
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from custom_exceptions import NotFoundException
from src.schemas.koth_event import KothEvent
from src.schemas.koth_signup import KothSignup
from src.schemas.koth_match import KothMatch
from flasgger import swag_from

logger = logging.getLogger(__name__)

koth_blueprint = Blueprint('koth_api', __name__)

# ============ Event Endpoints ============
@koth_blueprint.route('/koth/events', methods=['GET'])
@swag_from({
    'summary': 'Get all KOTH events',
    'description': 'Retrieve all King of the Hill events.',
    'tags': ['koth'],
    'responses': {
        200: {'description': 'List of KOTH events'},
        500: {'description': 'Internal server error'}
    }
})
def get_all_events():
    try:
        events = koth_blueprint.koth_app_service.get_all_events()
        return jsonify([e.to_dict() for e in events]), 200
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@koth_blueprint.route('/koth/events/active', methods=['GET'])
@swag_from({
    'summary': 'Get active KOTH event',
    'description': 'Retrieve the currently active King of the Hill event with all signups and matches.',
    'tags': ['koth'],
    'responses': {
        200: {'description': 'Active KOTH event'},
        404: {'description': 'No active event found'},
        500: {'description': 'Internal server error'}
    }
})
def get_active_event():
    try:
        event = koth_blueprint.koth_app_service.get_active_event()
        return jsonify(event.to_dict()), 200
    except NotFoundException as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@koth_blueprint.route('/koth/events/<int:event_id>', methods=['GET'])
@swag_from({
    'summary': 'Get KOTH event by ID',
    'description': 'Retrieve a specific King of the Hill event with all signups and matches.',
    'tags': ['koth'],

    'parameters': [
        {'name': 'event_id', 'in': 'path', 'type': 'integer', 'required': True}
    ],
    'responses': {
        200: {'description': 'KOTH event details'},
        404: {'description': 'Event not found'},
        500: {'description': 'Internal server error'}
    }
})
def get_event(event_id):
    try:
        event = koth_blueprint.koth_app_service.get_event(event_id)
        return jsonify(event.to_dict()), 200
    except NotFoundException as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@koth_blueprint.route('/koth/events', methods=['POST'])
@jwt_required()
@swag_from({
    'summary': 'Create a new KOTH event',
    'description': 'Create a new King of the Hill event.',
    'tags': ['koth'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'description': {'type': 'string'},
                    'event_date': {'type': 'string', 'format': 'date-time'},
                    'is_active': {'type': 'boolean'},
                    'bracket_1_threshold': {'type': 'integer', 'default': 1450},
                    'bracket_2_threshold': {'type': 'integer', 'default': 1600}
                },
                'required': ['name', 'event_date']
            }
        }
    ],
    'responses': {
        201: {'description': 'Event created successfully'},
        500: {'description': 'Internal server error'}
    }
})
def create_event():
    try:
        data = request.json
        event = koth_blueprint.koth_app_service.create_event(KothEvent(data))
        return jsonify(event.to_dict()), 201
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@koth_blueprint.route('/koth/events/<int:event_id>', methods=['PUT'])
@jwt_required()
@swag_from({
    'summary': 'Update a KOTH event',
    'description': 'Update an existing King of the Hill event.',
    'tags': ['koth'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'event_id', 'in': 'path', 'type': 'integer', 'required': True},
        {'name': 'body', 'in': 'body', 'required': True}
    ],
    'responses': {
        200: {'description': 'Event updated successfully'},
        404: {'description': 'Event not found'},
        500: {'description': 'Internal server error'}
    }
})
def update_event(event_id):
    try:
        data = request.json
        event = koth_blueprint.koth_app_service.update_event(event_id, KothEvent(data))
        return jsonify(event.to_dict()), 200
    except NotFoundException as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@koth_blueprint.route('/koth/events/<int:event_id>/activate', methods=['POST'])
@jwt_required()
@swag_from({
    'summary': 'Set event as active',
    'description': 'Set a KOTH event as active and deactivate all others.',
    'tags': ['koth'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'event_id', 'in': 'path', 'type': 'integer', 'required': True}
    ],
    'responses': {
        200: {'description': 'Event activated successfully'},
        500: {'description': 'Internal server error'}
    }
})
def activate_event(event_id):
    try:
        event = koth_blueprint.koth_app_service.set_active_event(event_id)
        return jsonify(event.to_dict()), 200
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@koth_blueprint.route('/koth/events/<int:event_id>', methods=['DELETE'])
@jwt_required()
@swag_from({
    'summary': 'Delete a KOTH event',
    'description': 'Delete a King of the Hill event and all associated signups and matches.',
    'tags': ['koth'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'event_id', 'in': 'path', 'type': 'integer', 'required': True}
    ],
    'responses': {
        204: {'description': 'Event deleted successfully'},
        500: {'description': 'Internal server error'}
    }
})
def delete_event(event_id):
    try:
        koth_blueprint.koth_app_service.delete_event(event_id)
        return '', 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

# ============ Signup Endpoints ============
@koth_blueprint.route('/koth/events/<int:event_id>/signups', methods=['GET'])
@swag_from({
    'summary': 'Get signups for an event',
    'description': 'Retrieve all signups for a specific KOTH event.',
    'tags': ['koth'],
    'parameters': [
        {'name': 'event_id', 'in': 'path', 'type': 'integer', 'required': True}
    ],
    'responses': {
        200: {'description': 'List of signups'},
        500: {'description': 'Internal server error'}
    }
})
def get_event_signups(event_id):
    try:
        signups = koth_blueprint.koth_app_service.get_signups_by_event(event_id)
        return jsonify([s.to_dict() for s in signups]), 200
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@koth_blueprint.route('/koth/signups', methods=['POST'])
@swag_from({
    'summary': 'Create a signup (Twitch/Nightbot endpoint)',
    'description': 'Create a KOTH signup with automatic W3C MMR validation and bracket assignment. Requires KOTH_NIGHTBOT_TOKEN for authentication.',
    'tags': ['koth'],
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'client_token': {'type': 'string', 'description': 'Bot client token for authentication'},
                    'twitch_username': {'type': 'string', 'description': 'Twitch username'},
                    'battle_tag': {'type': 'string', 'description': 'W3Champions BattleTag'},
                    'race': {'type': 'string', 'description': 'Optional race (orc, human, undead, nightelf, random)'}
                },
                'required': ['client_token', 'twitch_username', 'battle_tag']
            }
        }
    ],
    'responses': {
        201: {'description': 'Signup created successfully'},
        400: {'description': 'Validation error'},
        401: {'description': 'Unauthorized - invalid client token'},
        500: {'description': 'Internal server error'}
    }
})
def create_signup():
    try:
        data = request.json
        
        # Verify KOTH_NIGHTBOT_TOKEN from settings
        client_token = data.get('client_token')
        setting = koth_blueprint.koth_app_service.settings_app_service.get_setting('KOTH_NIGHTBOT_TOKEN')
        expected = setting.get('value') if setting else None
        
        if not expected or str(client_token) != str(expected):
            return jsonify({'error': 'Unauthorized - invalid client token'}), 401
        
        twitch_username = data.get('twitch_username')
        battle_tag = data.get('battle_tag')
        race = data.get('race')  # Optional
        
        if not twitch_username or not battle_tag:
            return jsonify({'error': 'Missing required fields'}), 400
        
        signup = koth_blueprint.koth_app_service.create_signup_from_twitch(
            twitch_username=twitch_username,
            battle_tag=battle_tag,
            preferred_race=race
        )
        return jsonify(signup.to_dict()), 201
    except NotFoundException as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@koth_blueprint.route('/koth/signup', methods=['GET'])
@swag_from({
    'summary': 'Create a signup via URL parameters (Nightbot compatible)',
    'description': 'Create a KOTH signup using query parameters. Compatible with Nightbot and other chat bots that cannot send JSON body. Requires KOTH_NIGHTBOT_TOKEN for authentication.',
    'tags': ['koth'],
    'parameters': [
        {'name': 'token', 'in': 'query', 'type': 'string', 'required': True, 'description': 'Bot client token'},
        {'name': 'twitch', 'in': 'query', 'type': 'string', 'required': True, 'description': 'Twitch username'},
        {'name': 'battletag', 'in': 'query', 'type': 'string', 'required': True, 'description': 'W3Champions BattleTag'},
        {'name': 'race', 'in': 'query', 'type': 'string', 'required': False, 'description': 'Optional race (orc, human, undead, nightelf, random)'}
    ],
    'responses': {
        200: {'description': 'Signup created successfully'},
        400: {'description': 'Validation error or missing parameters'},
        401: {'description': 'Unauthorized - invalid client token'},
        500: {'description': 'Internal server error'}
    }
})
def create_signup_nightbot():
    """
    Nightbot-compatible signup endpoint using query parameters.
    Usage: GET /koth/signup?token=KOTH_TOKEN&twitch=username&battletag=Name%231234
    """
    try:
        # Get parameters from query string
        client_token = request.args.get('token')
        twitch_username = request.args.get('twitch')
        battle_tag = request.args.get('battletag')
        race = request.args.get('race')  # Optional
        
        # Verify KOTH_NIGHTBOT_TOKEN from settings
        setting = koth_blueprint.koth_app_service.settings_app_service.get_setting('KOTH_NIGHTBOT_TOKEN')
        expected = setting.get('value') if setting else None
        
        if not expected or str(client_token) != str(expected):
            return jsonify({'error': 'Unauthorized - invalid client token'}), 401
        
        if not twitch_username or not battle_tag:
            return jsonify({'error': 'Missing required parameters: token, twitch, battletag'}), 400
        
        signup = koth_blueprint.koth_app_service.create_signup_from_twitch(
            twitch_username=twitch_username,
            battle_tag=battle_tag,
            preferred_race=race
        )
        
        # Return simple success message for chat display
        return jsonify({
            'success': True,
            'message': f'{twitch_username} signed up for Bracket {signup.bracket} ({signup.mmr} MMR)'
        }), 200
    except NotFoundException as e:
        return jsonify({'error': str(e)}), 404
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(e)
        return jsonify({'error': str(e)}), 500

@koth_blueprint.route('/koth/signups/admin', methods=['POST'])
@jwt_required()
@swag_from({
    'summary': 'Create a signup manually (Admin)',
    'description': 'Manually create a KOTH signup with automatic W3C MMR validation and bracket assignment. For admin UI use.',
    'tags': ['koth'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'twitch_username': {'type': 'string', 'description': 'Twitch username (optional)'},
                    'battle_tag': {'type': 'string', 'description': 'W3Champions BattleTag'},
                    'race': {'type': 'string', 'description': 'Preferred race (optional): orc, human, undead, nightelf, random'}
                },
                'required': ['battle_tag']
            }
        }
    ],
    'responses': {
        201: {'description': 'Signup created successfully'},
        400: {'description': 'Validation error'},
        404: {'description': 'Event not found'},
        500: {'description': 'Internal server error'}
    }
})
def create_signup_admin():
    try:
        data = request.json
        
        twitch_username = data.get('twitch_username', '')
        battle_tag = data.get('battle_tag')
        race = data.get('race')
        
        if not battle_tag:
            return jsonify({'error': 'BattleTag is required'}), 400
        
        signup = koth_blueprint.koth_app_service.create_signup_from_twitch(
            twitch_username=twitch_username,
            battle_tag=battle_tag,
            preferred_race=race
        )
        return jsonify(signup.to_dict()), 201
    except NotFoundException as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@koth_blueprint.route('/koth/signups/<int:signup_id>/bracket', methods=['PUT'])
@jwt_required()
@swag_from({
    'summary': 'Update signup bracket',
    'description': 'Manually update a player\'s bracket assignment.',
    'tags': ['koth'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'signup_id', 'in': 'path', 'type': 'integer', 'required': True},
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'bracket': {'type': 'integer', 'enum': [1, 2, 3]}
                },
                'required': ['bracket']
            }
        }
    ],
    'responses': {
        200: {'description': 'Bracket updated successfully'},
        400: {'description': 'Invalid bracket value'},
        404: {'description': 'Signup not found'},
        500: {'description': 'Internal server error'}
    }
})
def update_signup_bracket(signup_id):
    try:
        data = request.json
        signup = koth_blueprint.koth_app_service.update_signup_bracket(signup_id, data.get('bracket'))
        return jsonify(signup.to_dict()), 200
    except NotFoundException as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@koth_blueprint.route('/koth/signups/<int:signup_id>/king', methods=['POST'])
@jwt_required()
@swag_from({
    'summary': 'Set player as king',
    'description': 'Set a player as the king of their bracket (overwrites existing kings).',
    'tags': ['koth'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'signup_id', 'in': 'path', 'type': 'integer', 'required': True}
    ],
    'responses': {
        200: {'description': 'King status set'},
        404: {'description': 'Signup not found'},
        500: {'description': 'Internal server error'}
    }
})
def set_king(signup_id):
    try:
        signup = koth_blueprint.koth_app_service.set_king(signup_id)
        return jsonify(signup.to_dict()), 200
    except NotFoundException as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@koth_blueprint.route('/koth/signups/<int:signup_id>/add-king', methods=['POST'])
@jwt_required()
@swag_from({
    'summary': 'Add player as king',
    'description': 'Add a player as king of their bracket (keeps existing kings).',
    'tags': ['koth'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'signup_id', 'in': 'path', 'type': 'integer', 'required': True}
    ],
    'responses': {
        200: {'description': 'King status added'},
        404: {'description': 'Signup not found'},
        500: {'description': 'Internal server error'}
    }
})
def add_king(signup_id):
    try:
        signup = koth_blueprint.koth_app_service.add_king(signup_id)
        return jsonify(signup.to_dict()), 200
    except NotFoundException as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@koth_blueprint.route('/koth/signups/<int:signup_id>/king', methods=['DELETE'])
@jwt_required()
@swag_from({
    'summary': 'Remove king status',
    'description': 'Remove king status from a player.',
    'tags': ['koth'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'signup_id', 'in': 'path', 'type': 'integer', 'required': True}
    ],
    'responses': {
        200: {'description': 'King status removed'},
        404: {'description': 'Signup not found'},
        500: {'description': 'Internal server error'}
    }
})
def unset_king(signup_id):
    try:
        signup = koth_blueprint.koth_app_service.unset_king(signup_id)
        return jsonify(signup.to_dict()), 200
    except NotFoundException as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@koth_blueprint.route('/koth/signups/<int:signup_id>', methods=['DELETE'])
@jwt_required()
@swag_from({
    'summary': 'Delete a signup',
    'description': 'Remove a player signup from an event.',
    'tags': ['koth'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'signup_id', 'in': 'path', 'type': 'integer', 'required': True}
    ],
    'responses': {
        204: {'description': 'Signup deleted successfully'},
        500: {'description': 'Internal server error'}
    }
})
def delete_signup(signup_id):
    try:
        koth_blueprint.koth_app_service.delete_signup(signup_id)
        return '', 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

# ============ Match Endpoints ============
@koth_blueprint.route('/koth/events/<int:event_id>/matches', methods=['GET'])
@swag_from({
    'summary': 'Get matches for an event',
    'description': 'Retrieve all matches for a specific KOTH event.',
    'tags': ['koth'],
    'parameters': [
        {'name': 'event_id', 'in': 'path', 'type': 'integer', 'required': True}
    ],
    'responses': {
        200: {'description': 'List of matches'},
        500: {'description': 'Internal server error'}
    }
})
def get_event_matches(event_id):
    try:
        matches = koth_blueprint.koth_app_service.get_matches_by_event(event_id)
        return jsonify([m.to_dict() for m in matches]), 200
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@koth_blueprint.route('/koth/matches', methods=['POST'])
@jwt_required()
@swag_from({
    'summary': 'Create a team-based match',
    'description': 'Create a new KOTH match with flexible team configuration. Supports uneven teams (e.g., 2v1, 3v1).',
    'tags': ['koth'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'event_id': {'type': 'integer'},
                    'game_mode': {'type': 'string', 'example': '2v1', 'description': 'e.g., 1v1, 2v1, 2v2, 3v1, FFA'},
                    'num_teams': {'type': 'integer', 'example': 2},
                    'participants': {
                        'type': 'array',
                        'description': 'Each team can have different number of players',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'signup_id': {'type': 'integer'},
                                'team_number': {'type': 'integer', 'description': '1 to num_teams'}
                            }
                        }
                    },
                    'match_date': {'type': 'string', 'format': 'date-time'}
                },
                'required': ['event_id', 'game_mode', 'num_teams', 'participants']
            }
        }
    ],
    'responses': {
        201: {'description': 'Match created successfully'},
        400: {'description': 'Validation error'},
        404: {'description': 'Participant not found'},
        500: {'description': 'Internal server error'}
    }
})
def create_match():
    try:
        data = request.json
        participants = data.pop('participants', [])
        match = koth_blueprint.koth_app_service.create_match(
            KothMatch(data),
            participants
        )
        return jsonify(match.to_dict()), 201
    except NotFoundException as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@koth_blueprint.route('/koth/matches/<int:match_id>', methods=['PUT'])
@jwt_required()
@swag_from({
    'summary': 'Update match',
    'description': 'Update a KOTH match.',
    'tags': ['koth'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'match_id', 'in': 'path', 'type': 'integer', 'required': True},
        {'name': 'body', 'in': 'body', 'required': True}
    ],
    'responses': {
        200: {'description': 'Match updated successfully'},
        404: {'description': 'Match not found'},
        500: {'description': 'Internal server error'}
    }
})
def update_match(match_id):
    try:
        data = request.json
        match = koth_blueprint.koth_app_service.update_match(match_id, KothMatch(data))
        return jsonify(match.to_dict()), 200
    except NotFoundException as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@koth_blueprint.route('/koth/matches/<int:match_id>/result', methods=['PUT'])
@jwt_required()
@swag_from({
    'summary': 'Update match result',
    'description': 'Set the winning team and update all team members as kings.',
    'tags': ['koth'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'match_id', 'in': 'path', 'type': 'integer', 'required': True},
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'winner_team_number': {'type': 'integer', 'example': 1}
                },
                'required': ['winner_team_number']
            }
        }
    ],
    'responses': {
        200: {'description': 'Match result updated'},
        404: {'description': 'Match not found'},
        500: {'description': 'Internal server error'}
    }
})
def update_match_result(match_id):
    try:
        data = request.json
        match = koth_blueprint.koth_app_service.update_match_result(
            match_id,
            data.get('winner_team_number')
        )
        return jsonify(match.to_dict()), 200
    except NotFoundException as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@koth_blueprint.route('/koth/matches/<int:match_id>', methods=['DELETE'])
@jwt_required()
@swag_from({
    'summary': 'Delete a match',
    'description': 'Remove a match from an event.',
    'tags': ['koth'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'match_id', 'in': 'path', 'type': 'integer', 'required': True}
    ],
    'responses': {
        204: {'description': 'Match deleted successfully'},
        500: {'description': 'Internal server error'}
    }
})
def delete_match(match_id):
    try:
        koth_blueprint.koth_app_service.delete_match(match_id)
        return '', 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

# ============ Utility Endpoints ============
@koth_blueprint.route('/koth/events/<int:event_id>/kings', methods=['GET'])
@swag_from({
    'summary': 'Get bracket kings',
    'description': 'Get all kings for each bracket in an event.',
    'tags': ['koth'],
    'parameters': [
        {'name': 'event_id', 'in': 'path', 'type': 'integer', 'required': True}
    ],
    'responses': {
        200: {'description': 'Bracket kings (lists of kings per bracket)'},
        500: {'description': 'Internal server error'}
    }
})
def get_bracket_kings(event_id):
    try:
        kings = koth_blueprint.koth_app_service.get_bracket_kings(event_id)
        return jsonify({k: [king.to_dict() for king in v] for k, v in kings.items()}), 200
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
