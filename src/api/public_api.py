import logging
import os
import json
from flask import Blueprint, request, jsonify
from flasgger import swag_from
from datetime import datetime, timedelta, timezone
from src.util.query_util import QueryUtil
from werkzeug.utils import secure_filename
import secrets
import requests
import os

logger = logging.getLogger(__name__)

public_api_blueprint = Blueprint('public_api', __name__)

# Simple in-memory token store: token -> {discord_id, discord_tag, season_id, expires_at, access_type}
# access_type can be 'signup' or 'dashboard'
_token_store = {}

def _cleanup_expired():
    # use timezone-aware UTC now
    now = datetime.now(timezone.utc)
    expired = [t for t, v in _token_store.items() if v['expires_at'] <= now]
    for t in expired:
        del _token_store[t]

def _notify_discord_series_update(series, player_name, action, uploaded_files=None):
    """Send series update notification to Discord bot webhook with optional file attachments
    
    This function is designed to be non-blocking - if Discord notifications fail,
    the series update operation will still succeed.
    """
    try:
        bot_webhook_url = os.getenv('BOT_WEBHOOK_URL')
        bot_client_token = os.getenv('BOT_CLIENT_TOKEN')
        
        if not bot_webhook_url or not bot_client_token:
            logger.debug('Discord webhook not configured, skipping notification')
            return False
            
        # Prepare multipart form data for files
        if uploaded_files:
            # Create multipart form data manually using requests
            files_dict = {}

            # Use the custom JSON provider attached to the blueprint to handle enums
            series_json = public_api_blueprint.json_provider.dumps(
                series.to_dict() if hasattr(series, 'to_dict') else series
            )

            data_dict = {
                'series': series_json,
                'player_name': player_name,
                'action': action,
                'auth_token': bot_client_token
            }
            
            # Add files to requests files dict
            for file_key, file_info in uploaded_files.items():
                files_dict[file_key] = (file_info['filename'], file_info['data'], file_info['content_type'])
            
            # Send webhook request with files
            response = requests.post(
                bot_webhook_url,
                data=data_dict,
                files=files_dict,
                timeout=30  # Increased timeout for file uploads
            )
        else:
            # Send regular JSON payload using the json provider attached to the blueprint
            payload = {
                'series': series.to_dict() if hasattr(series, 'to_dict') else series,
                'player_name': player_name,
                'action': action,
                'auth_token': bot_client_token
            }

            response = requests.post(
                bot_webhook_url,
                data=public_api_blueprint.json_provider.dumps(payload),
                timeout=5,
                headers={'Content-Type': 'application/json'}
            )
        
        if response.status_code == 200:
            logger.info(f'Successfully notified Discord of series update: {action}')
            return True
        else:
            logger.warning(f'Discord webhook returned status {response.status_code}: {response.text}')
            return False
            
    except requests.exceptions.Timeout:
        logger.warning('Discord webhook request timed out - continuing without notification')
        return False
    except requests.exceptions.ConnectionError:
        logger.warning('Discord webhook connection failed - bot may be offline')
        return False
    except Exception as e:
        logger.warning(f'Discord notification failed: {e} - series update will continue')
        return False

@public_api_blueprint.route('/public-access-helper', methods=['POST'])
@swag_from({
    'summary': 'Create a one-time public access URL (bot use)',
    'description': 'Protected endpoint for the Discord bot to request a one-time public access URL. Requires BOT client token.',
    'tags': ['public'],
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'client_token': {'type': 'string', 'description': 'Shared client token between bot and backend'},
                    'discord_id': {'type': 'string', 'description': 'Discord user id to prefill'},
                    'discord_tag': {'type': 'string', 'description': 'Discord user tag (name#discriminator)'},
                    'season_id': {'type': 'string', 'description': 'Optional season id'},
                    'access_type': {'type': 'string', 'description': 'Type of access: signup or dashboard', 'enum': ['signup', 'dashboard']},
                    'ttl_minutes': {'type': 'integer', 'description': 'Token TTL in minutes (optional, default 30)'}
                },
                'required': ['client_token','discord_id','discord_tag','access_type']
            }
        }
    ],
    'responses': {
        200: {'description': 'Returns JSON with access_url and token'},
        400: {'description': 'Missing parameters'},
        401: {'description': 'Unauthorized (invalid client_token)'},
        500: {'description': 'Internal server error'}
    }
})
def create_public_access_helper():
    try:
        data = request.json or {}
        client_token = data.get('client_token') or request.args.get('client_token')
        expected = os.getenv('BOT_CLIENT_TOKEN') or ''
        if not expected or str(client_token) != str(expected):
            return jsonify({'error': 'unauthorized'}), 401

        discord_id = data.get('discord_id') or request.args.get('discord_id')
        discord_tag = data.get('discord_tag') or request.args.get('discord_tag')
        season_id = data.get('season_id') or request.args.get('season_id')
        access_type = data.get('access_type') or request.args.get('access_type')
        ttl_minutes = int(data.get('ttl_minutes') or request.args.get('ttl_minutes') or 30)

        if not discord_id or not discord_tag or not access_type:
            return jsonify({'error': 'missing parameters'}), 400

        if access_type not in ['signup', 'dashboard']:
            return jsonify({'error': 'invalid access_type'}), 400

        # cleanup store
        _cleanup_expired()

        token = secrets.token_urlsafe(16)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        _token_store[token] = {
            'discord_id': str(discord_id),
            'discord_tag': str(discord_tag),
            'season_id': str(season_id) if season_id else None,
            'access_type': access_type,
            'expires_at': expires_at
        }

        frontend = os.getenv('FRONTEND_URL') or request.host_url.rstrip('/')
        
        # Route based on access type
        if access_type == 'signup':
            access_url = f"{frontend}#/signup?token={token}"
        elif access_type == 'dashboard':
            access_url = f"{frontend}#/player-dashboard?token={token}"

        return jsonify({'access_url': access_url, 'token': token})
    except Exception as e:
        logger.exception('Error in create_public_access_helper')
        return jsonify({'error': str(e)}), 500

@public_api_blueprint.route('/public-token/<token>', methods=['GET'])
@swag_from({
    'summary': 'Get stored public access token details',
    'description': 'Return token metadata (used by public pages to validate token).',
    'tags': ['public']
})
def get_public_token(token):
    try:
        _cleanup_expired()
        entry = _token_store.get(token)
        if not entry:
            return jsonify({'error': 'not_found'}), 404
        return jsonify({
            'discord_id': entry['discord_id'],
            'discord_tag': entry['discord_tag'],
            'season_id': entry['season_id'],
            'access_type': entry['access_type']
        })
    except Exception as e:
        logger.exception('Error in get_public_token')
        return jsonify({'error': str(e)}), 500

@public_api_blueprint.route('/public-token/<token>', methods=['DELETE'])
@swag_from({
    'summary': 'Consume (delete) a public access token',
    'description': 'Remove a token after it has been used.',
    'tags': ['public']
})
def delete_public_token(token):
    try:
        if token in _token_store:
            del _token_store[token]
            return jsonify({'status': 'deleted'})
        return jsonify({'error': 'not_found'}), 404
    except Exception as e:
        logger.exception('Error in delete_public_token')
        return jsonify({'error': str(e)}), 500

@public_api_blueprint.route('/signup', methods=['POST'])
@swag_from({
    'summary': 'Create user via one-time signup token',
    'description': 'Public endpoint used by the public signup page to create a user using a one-time token.',
    'tags': ['public'],
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'token': {'type': 'string'},
                    'name': {'type': 'string'},
                    'battleTag': {'type': 'string'},
                    'season_id': {'type': 'string', 'description': 'Optional season id'},
                    'race': {'type': 'string'},
                    'mmr': {'type': 'integer'},
                    'country': {'type': 'string'}
                },
                'required': ['token', 'name', 'battleTag']
            }
        }
    ],
    'responses': {
        201: {'description': 'User created successfully'},
        400: {'description': 'Missing parameters or invalid token'},
        404: {'description': 'Token not found/expired'},
        500: {'description': 'Internal server error'}
    }
})
def public_create_user():
    """Create user and optionally assign to season using a one-time token."""
    try:
        data = request.json or {}
        token = data.get('token')
        if not token:
            return jsonify({'error': 'missing token'}), 400

        _cleanup_expired()
        entry = _token_store.get(token)
        if not entry:
            return jsonify({'error': 'token_not_found_or_expired'}), 404

        if entry.get('access_type') != 'signup':
            return jsonify({'error': 'invalid_token_type'}), 400

        # Build user payload. Force discord fields from token to avoid spoofing.
        user_payload = {
            'name': data.get('name'),
            'battleTag': data.get('battleTag'),
            'discordId': entry.get('discord_id'),
            'discordTag': entry.get('discord_tag'),
            'race': data.get('race'),
            'mmr': data.get('mmr'),
            'country': data.get('country')
        }

        # Basic validation
        if not user_payload['name'] or not user_payload['battleTag']:
            return jsonify({'error': 'missing user fields'}), 400

        # Use the attached application services
        if not hasattr(public_api_blueprint, 'user_app_service'):
            logger.error('user_app_service not available on public_api_blueprint')
            return jsonify({'error': 'server_misconfigured'}), 500

        from src.dtos.user_dto import UserDTO

        # Validate BattleTag with W3Champions BEFORE creating/updating user
        if not public_api_blueprint.user_app_service.validateBattleTag(user_payload['battleTag']):
            return jsonify({'error': f"BattleNet name '{user_payload['battleTag']}' is not valid - no W3Champions stats found"}), 400

        # Check for existing user by discord id or tag
        existing_users = []
        try:
            query = QueryUtil.parseQuery(f"discordId == {entry.get('discord_id')} or discordTag == {entry.get('discord_tag')}")    
            existing_users = public_api_blueprint.user_app_service.search(query)
        except Exception:
            logger.exception('Error searching for existing user by discord id')
            return jsonify({'error': 'Error searching for existing user by discord id'}), 500

        if existing_users and len(existing_users) > 0:
            # update first matched user
            existing = existing_users[0]
            try:
                user_dto = UserDTO(user_payload)
                user = public_api_blueprint.user_app_service.update_user(existing.id, user_dto)
            except Exception as ue:
                logger.exception('Failed to update existing user: %s', ue)
                return jsonify({'error': 'Failed to update existing user'}), 500
        else:
            # create new user
            user = public_api_blueprint.user_app_service.create_user(UserDTO(user_payload))

        # Add to season if specified
        season_id = entry.get('season_id') or data.get('season_id') or data.get('seasonId')
        if season_id and hasattr(public_api_blueprint, 'season_app_service'):
            try:
                public_api_blueprint.season_app_service.addUserSignup(int(season_id), [user.id])
            except Exception as se:
                logger.exception('Failed to add user to season: %s', se)
                return jsonify({'error': 'Failed to add user to season'}), 500

        # consume the token
        try:
            if token in _token_store:
                del _token_store[token]
        except Exception:
            logger.exception('Failed to delete token after signup')

        # return created user
        if user:
            try:
                out = user.to_dict()
            except Exception:
                out = user if isinstance(user, dict) else {}
            return jsonify(out), 201
        return jsonify({'error': 'user_creation_failed'}), 500
    except Exception as e:
        logger.exception('Error in public_create_user')
        return jsonify({'error': str(e)}), 500

@public_api_blueprint.route('/player-series', methods=['GET'])
@swag_from({
    'summary': 'Get player series for dashboard',
    'description': 'Get all series for a player in the current season using a dashboard token.',
    'tags': ['public'],
    'parameters': [
        {
            'name': 'token',
            'in': 'query',
            'required': True,
            'type': 'string',
            'description': 'Dashboard access token'
        }
    ],
    'responses': {
        200: {'description': 'Returns player series data'},
        400: {'description': 'Missing token'},
        404: {'description': 'Token not found/expired or player not found'},
        500: {'description': 'Internal server error'}
    }
})
def get_player_series():
    """Get player's series for dashboard view using a one-time token."""
    try:
        token = request.args.get('token')
        if not token:
            return jsonify({'error': 'missing token'}), 400

        _cleanup_expired()
        entry = _token_store.get(token)
        if not entry:
            return jsonify({'error': 'token_not_found_or_expired'}), 404

        if entry.get('access_type') != 'dashboard':
            return jsonify({'error': 'invalid_token_type'}), 400

        # Find the user by discord_id
        if not hasattr(public_api_blueprint, 'user_app_service'):
            logger.error('user_app_service not available on public_api_blueprint')
            return jsonify({'error': 'server_misconfigured'}), 500

        try:
            query = QueryUtil.parseQuery(f"discordId == {entry.get('discord_id')}")
            users = public_api_blueprint.user_app_service.search(query)
            if not users:
                return jsonify({'error': 'player_not_found'}), 404
            user = users[0]
        except Exception:
            logger.exception('Error finding user by discord id')
            return jsonify({'error': 'Error finding user'}), 500

        # Get series for the user
        if not hasattr(public_api_blueprint, 'series_app_service'):
            logger.error('series_app_service not available on public_api_blueprint')
            return jsonify({'error': 'server_misconfigured'}), 500

        try:
            # Get series where user is player1 or player2
            if entry.get('season_id'):
                # Use the series app service searchForSeason method for season-specific queries
                query = QueryUtil.parseQuery(f"player1_id == {user.id} or player2_id == {user.id}")
                series = public_api_blueprint.series_app_service.searchForSeason(entry.get('season_id'), query)
            else:
                # Search all series for this user
                query = QueryUtil.parseQuery(f"player1_id == {user.id} or player2_id == {user.id}")
                series = public_api_blueprint.series_app_service.search(query)
            
            # Convert to dict format
            series_data = []
            for s in series:
                try:
                    series_dict = s.to_dict() if hasattr(s, 'to_dict') else s
                    series_data.append(series_dict)
                except Exception:
                    series_data.append(s if isinstance(s, dict) else {})

            return jsonify({
                'player': user.to_dict() if hasattr(user, 'to_dict') else user,
                'series': series_data,
                'season_id': entry.get('season_id'),
                'discord_id': entry.get('discord_id'),
                'discord_tag': entry.get('discord_tag')
            })

        except Exception:
            logger.exception('Error getting player series')
            return jsonify({'error': 'Error getting player series'}), 500

    except Exception as e:
        logger.exception('Error in get_player_series')
        return jsonify({'error': str(e)}), 500

@public_api_blueprint.route('/player-series/<int:series_id>', methods=['PUT'])
@swag_from({
    'summary': 'Update player series',
    'description': 'Update a series that belongs to the authenticated player using a dashboard token. Supports file uploads for replay files.',
    'tags': ['public'],
    'consumes': ['multipart/form-data'],
    'parameters': [
        {
            'name': 'series_id',
            'in': 'path',
            'required': True,
            'type': 'integer',
            'description': 'Series ID to update'
        },
        {
            'name': 'token',
            'in': 'formData',
            'required': True,
            'type': 'string',
            'description': 'Dashboard access token'
        },
        {
            'name': 'date_time',
            'in': 'formData',
            'required': False,
            'type': 'string',
            'description': 'ISO datetime string'
        },
        {
            'name': 'player1_score',
            'in': 'formData',
            'required': False,
            'type': 'integer'
        },
        {
            'name': 'player2_score',
            'in': 'formData',
            'required': False,
            'type': 'integer'
        },
        {
            'name': 'game1',
            'in': 'formData',
            'required': False,
            'type': 'file',
            'description': 'Game 1 replay file'
        },
        {
            'name': 'game2',
            'in': 'formData',
            'required': False,
            'type': 'file',
            'description': 'Game 2 replay file'
        },
        {
            'name': 'game3',
            'in': 'formData',
            'required': False,
            'type': 'file',
            'description': 'Game 3 replay file (optional)'
        }
    ],
    'responses': {
        200: {'description': 'Series updated successfully'},
        400: {'description': 'Missing token or invalid data'},
        403: {'description': 'Not authorized to update this series'},
        404: {'description': 'Token or series not found'},
        500: {'description': 'Internal server error'}
    }
})
def update_player_series(series_id):
    """Update a series that belongs to the authenticated player."""
    try:
        # Handle both form data and JSON
        if request.content_type and 'multipart/form-data' in request.content_type:
            data = request.form.to_dict()
            files = request.files
        else:
            data = request.json or {}
            files = {}
            
        token = data.get('token')
        if not token:
            return jsonify({'error': 'missing token'}), 400

        _cleanup_expired()
        entry = _token_store.get(token)
        if not entry:
            return jsonify({'error': 'token_not_found_or_expired'}), 404

        if entry.get('access_type') != 'dashboard':
            return jsonify({'error': 'invalid_token_type'}), 400

        # Find the user by discord_id
        if not hasattr(public_api_blueprint, 'user_app_service'):
            logger.error('user_app_service not available on public_api_blueprint')
            return jsonify({'error': 'server_misconfigured'}), 500

        try:
            query = QueryUtil.parseQuery(f"discordId == {entry.get('discord_id')}")
            users = public_api_blueprint.user_app_service.search(query)
            if not users:
                return jsonify({'error': 'player_not_found'}), 404
            user = users[0]
        except Exception:
            logger.exception('Error finding user by discord id')
            return jsonify({'error': 'Error finding user'}), 500

        # Get the series and verify ownership
        if not hasattr(public_api_blueprint, 'series_app_service'):
            logger.error('series_app_service not available on public_api_blueprint')
            return jsonify({'error': 'server_misconfigured'}), 500

        try:
            series = public_api_blueprint.series_app_service.get_series(series_id)
            if not series:
                return jsonify({'error': 'series_not_found'}), 404

            # Check if user is player1 or player2 in this series
            if series.player1_id != user.id and series.player2_id != user.id:
                return jsonify({'error': 'not_authorized_for_this_series'}), 403

            # Track what's being updated for Discord notification
            original_datetime = series.date_time
            original_p1_score = series.player1_score
            original_p2_score = series.player2_score

            # Handle file uploads - prepare for Discord transmission
            uploaded_files = {}
            allowed_extensions = {'w3g'}
            
            # Debug logging
            logger.info(f'Request content type: {request.content_type}')
            logger.info(f'Form data keys: {list(data.keys())}')
            logger.info(f'Files keys: {list(files.keys())}')
            logger.info(f'Files details: {[(k, v.filename if v.filename else "no filename") for k, v in files.items()]}')
            
            def allowed_file(filename):
                return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions
            
            for file_key in ['game1', 'game2', 'game3']:
                if file_key in files and files[file_key].filename:
                    file = files[file_key]
                    logger.info(f'Processing file {file_key}: {file.filename}')
                    if file and allowed_file(file.filename):
                        # Read file data for Discord transmission
                        file.seek(0)  # Reset file pointer
                        file_data = file.read()
                        uploaded_files[file_key] = {
                            'filename': secure_filename(file.filename),
                            'data': file_data,
                            'content_type': file.content_type or 'application/octet-stream'
                        }
                        logger.info(f'Prepared replay file for Discord: {file.filename}')
                    else:
                        logger.warning(f'File {file_key} failed validation: {file.filename}')
                        return jsonify({'error': f'Invalid file type for {file_key}. Only .w3g files are allowed.'}), 400
                else:
                    logger.info(f'No file found for {file_key}')

            logger.info(f'Final uploaded_files keys: {list(uploaded_files.keys())}')
            
            # Determine action: 'score_updated' or 'scheduled'. Frontend may send 'action'.
            action = data.get('action')
            logger.info(f'Action from request: {action}')

            # If the action explicitly indicates a result report, enforce file requirements.
            if action == 'score_updated':
                logger.info('Processing as score update; enforcing replay upload requirements')
                logger.info(f'Game1 in uploaded_files: {"game1" in uploaded_files}')
                logger.info(f'Game2 in uploaded_files: {"game2" in uploaded_files}')

                if 'game1' not in uploaded_files or 'game2' not in uploaded_files:
                    return jsonify({'error': 'Game 1 and Game 2 replay files are required when reporting results.'}), 400

                # Determine if game3 is required based on provided scores
                try:
                    p1 = int(data.get('player1_score'))
                    p2 = int(data.get('player2_score'))
                except Exception:
                    # If scores are missing or invalid, reject
                    return jsonify({'error': 'Invalid or missing player scores for score update.'}), 400

                needs_game3 = (p1 == 2 and p2 == 1) or (p1 == 1 and p2 == 2)
                logger.info(f'Needs game3: {needs_game3}')
                if needs_game3 and 'game3' not in uploaded_files:
                    return jsonify({'error': 'Game 3 replay file is required for 2:1 or 1:2 results.'}), 400
            else:
                # Backwards compatibility: if no explicit action provided, fall back to previous behavior
                scores_being_updated = (
                    'player1_score' in data or 'player2_score' in data
                )
                logger.info(f'Scores being updated (fallback): {scores_being_updated}')
                if scores_being_updated:
                    if 'game1' not in uploaded_files or 'game2' not in uploaded_files:
                        return jsonify({'error': 'Game 1 and Game 2 replay files are required when updating scores.'}), 400

            # Update allowed fields (players can only update date_time and scores)
            if 'date_time' in data and data['date_time']:
                # Parse ISO datetime and convert to Eastern Time
                from datetime import datetime
                if isinstance(data['date_time'], str):
                    try:
                        # Frontend sends datetime in ET format (YYYY-MM-DD HH:MM:SS)
                        # Parse and store directly as naive datetime (no timezone conversion needed)
                        series.date_time = datetime.fromisoformat(data['date_time'].replace(' ', 'T'))
                        
                        logger.info(f'Storing ET datetime: {series.date_time}')
                    except ValueError as e:
                        logger.error(f'Invalid datetime format: {data["date_time"]}, error: {e}')
                        return jsonify({'error': 'Invalid datetime format. Expected format: YYYY-MM-DD HH:MM:SS'}), 400
                else:
                    series.date_time = data['date_time']
            if 'player1_score' in data and data['player1_score'] is not None:
                series.player1_score = int(data['player1_score'])
            if 'player2_score' in data and data['player2_score'] is not None:
                series.player2_score = int(data['player2_score'])

            # Update the series
            updated_series = public_api_blueprint.series_app_service.update_series(series_id, series)
            
            # Determine notification action based on what was updated
            player_name = user.name if hasattr(user, 'name') else entry.get('discord_tag', 'Unknown Player')
            
            # Check if scores were updated
            scores_updated = (
                (original_p1_score != series.player1_score) or 
                (original_p2_score != series.player2_score)
            )
            
            # Check if date/time was updated
            datetime_updated = original_datetime != series.date_time
            
            # Prepare notification data including file data
            notification_data = updated_series.to_dict() if hasattr(updated_series, 'to_dict') else updated_series
            
            # Attempt Discord notifications (non-blocking - app continues regardless of success/failure)
            discord_notified = False
            if scores_updated:
                discord_notified = _notify_discord_series_update(notification_data, player_name, 'score_updated', uploaded_files)
            elif datetime_updated:
                discord_notified = _notify_discord_series_update(notification_data, player_name, 'scheduled', uploaded_files)
            
            result = updated_series.to_dict() if hasattr(updated_series, 'to_dict') else updated_series
            if uploaded_files:
                result['uploaded_files'] = {k: v['filename'] for k, v in uploaded_files.items()}
            
            # Always include Discord notification status in response
            result['discord_notification_sent'] = discord_notified
            
            return jsonify(result)

        except Exception:
            logger.exception('Error updating player series')
            return jsonify({'error': 'Error updating series'}), 500

    except Exception as e:
        logger.exception('Error in update_player_series')
        return jsonify({'error': str(e)}), 500