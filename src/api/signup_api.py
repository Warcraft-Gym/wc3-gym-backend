import logging
import os
from flask import Blueprint, request, jsonify
from flasgger import swag_from
from datetime import datetime, timedelta, timezone
from src.util.query_util import QueryUtil
import secrets


logger = logging.getLogger(__name__)

signup_blueprint = Blueprint('signup_api', __name__)

# Simple in-memory token store: token -> {discord_id, discord_tag, season_id, expires_at}
# This is intentionally simple; for production consider persistent storage.
_token_store = {}


def _cleanup_expired():
    # use timezone-aware UTC now
    now = datetime.now(timezone.utc)
    expired = [t for t, v in _token_store.items() if v['expires_at'] <= now]
    for t in expired:
        del _token_store[t]


@signup_blueprint.route('/signup-helper', methods=['POST'])
@swag_from({
    'summary': 'Create a one-time signup URL (bot use)',
    'description': 'Protected endpoint for the Discord bot to request a one-time signup URL. Requires BOT client token.',
    'tags': ['signup'],
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
                    'season_id': {'type': 'string', 'description': 'Optional season id to prefill on signup'},
                    'ttl_minutes': {'type': 'integer', 'description': 'Token TTL in minutes (optional, default 30)'}
                },
                'required': ['client_token','discord_id','discord_tag']
            }
        }
    ],
    'responses': {
        200: {'description': 'Returns JSON with signup_url and token'},
        400: {'description': 'Missing parameters'},
        401: {'description': 'Unauthorized (invalid client_token)'},
        500: {'description': 'Internal server error'}
    }
})
def create_signup_helper():
    try:
        data = request.json or {}
        client_token = data.get('client_token') or request.args.get('client_token')
        expected = os.getenv('BOT_CLIENT_TOKEN') or ''
        if not expected or str(client_token) != str(expected):
            return jsonify({'error': 'unauthorized'}), 401

        discord_id = data.get('discord_id') or request.args.get('discord_id')
        discord_tag = data.get('discord_tag') or request.args.get('discord_tag')
        season_id = data.get('season_id') or request.args.get('season_id')
        ttl_minutes = int(data.get('ttl_minutes') or request.args.get('ttl_minutes') or 30)

        if not discord_id or not discord_tag:
            return jsonify({'error': 'missing parameters'}), 400

        # cleanup store
        _cleanup_expired()

        token = secrets.token_urlsafe(16)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        _token_store[token] = {
            'discord_id': str(discord_id),
            'discord_tag': str(discord_tag),
            'season_id': str(season_id) if season_id else None,
            'expires_at': expires_at
        }

        frontend = os.getenv('FRONTEND_URL') or request.host_url.rstrip('/')
        signup_url = f"{frontend}#/signup?token={token}"

        return jsonify({'signup_url': signup_url, 'token': token})
    except Exception as e:
        logger.exception('Error in create_signup_helper')
        return jsonify({'error': str(e)}), 500


@signup_blueprint.route('/signup-token/<token>', methods=['GET'])
@swag_from({
    'summary': 'Get stored signup token details',
    'description': 'Return token metadata (used by the public signup page to validate token).',
    'tags': ['signup']
})
def get_signup_token(token):
    try:
        _cleanup_expired()
        entry = _token_store.get(token)
        if not entry:
            return jsonify({'error': 'not_found'}), 404
        # Do not return expires_at as datetime object directly
        return jsonify({
            'discord_id': entry['discord_id'],
            'discord_tag': entry['discord_tag'],
            'season_id': entry['season_id']
        })
    except Exception as e:
        logger.exception('Error in get_signup_token')
        return jsonify({'error': str(e)}), 500


@signup_blueprint.route('/signup-token/<token>', methods=['DELETE'])
@swag_from({
    'summary': 'Consume (delete) a signup token',
    'description': 'Remove a token after it has been used by the public signup page.',
    'tags': ['signup']
})
def delete_signup_token(token):
    try:
        if token in _token_store:
            del _token_store[token]
            return jsonify({'status': 'deleted'})
        return jsonify({'error': 'not_found'}), 404
    except Exception as e:
        logger.exception('Error in delete_signup_token')
        return jsonify({'error': str(e)}), 500


@signup_blueprint.route('/signup', methods=['POST'])
@swag_from({
    'summary': 'Create user via one-time signup token',
    'description': 'Public endpoint used by the public signup page to create a user using a one-time token. This bypasses normal auth but requires a valid token.',
    'tags': ['signup'],
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
                    'season_id': {'type': 'string', 'description': 'Optional season id to register the user for (ignored if token contains season_id).'},
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

        # Use the attached application services (assigned in app bootstrap)
        if not hasattr(signup_blueprint, 'user_app_service'):
            logger.error('user_app_service not available on signup_blueprint')
            return jsonify({'error': 'server_misconfigured'}), 500

        # Create DTO directly using existing DTO class to keep shape
        from src.schemas.user import User

        # If a user already exists with this discord id, update that user instead of creating a new one
        existing_users = []
        try:
            # search expects a query string like 'discordId==<value>'
            query = QueryUtil.parseQuery(f"discordId == {entry.get('discord_id')} or discordTag == {entry.get('discord_tag')}")    
            existing_users = signup_blueprint.user_app_service.search(query)
        except Exception:
            logger.exception('Error searching for existing user by discord id')
            return jsonify({'error': 'Error searching for existing user by discord id'}), 500

        if existing_users and len(existing_users) > 0:
            # update first matched user
            existing = existing_users[0]
            try:
                user_dto = User(user_payload)
                user = signup_blueprint.user_app_service.update_user(existing.id, user_dto)
            except Exception as ue:
                # If updating an existing user fails, do NOT create a new user.
                # Return an error so the client/bot can surface the failure and retry/investigate.
                logger.exception('Failed to update existing user: %s', ue)
                return jsonify({'error': 'Failed to update existing user'}), 500
        else:
            # create new user
            user = signup_blueprint.user_app_service.create_user(User(user_payload))

        # Determine season to register the user for:
        # prefer the season_id encoded in the token, otherwise accept season_id from the request body
        season_id = entry.get('season_id') or data.get('season_id') or data.get('seasonId')
        if season_id and hasattr(signup_blueprint, 'season_app_service'):
            try:
                signup_blueprint.season_app_service.addUserSignup(int(season_id), [user.id])
            except Exception as se:
                # If adding the user to the season fails, return an error so the client
                # can surface that signup failed. Do NOT consume the token so an admin
                # or retry flow can inspect/resolve the issue.
                logger.exception('Failed to add user to season: %s', se)
                return jsonify({'error': 'Failed to add user to season'}), 500

        # consume the token
        try:
            if token in _token_store:
                del _token_store[token]
        except Exception:
            logger.exception('Failed to delete token after signup')

        # return created user and ensure discord fields are present in response
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
