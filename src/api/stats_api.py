import logging
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from flasgger import swag_from
import csv
import io

logger = logging.getLogger(__name__)

stats_blueprint = Blueprint('stats_api', __name__)

@stats_blueprint.route('/stats/career', methods=['GET'])
@swag_from({
    'summary': 'Get all player career stats',
    'description': 'Retrieve career statistics for all players, ordered by rating',
    'tags': ['stats'],
    'responses': {
        200: {'description': 'Career stats retrieved successfully'},
        500: {'description': 'Internal server error'}
    }
})
def get_all_career_stats():
    try:
        stats = stats_blueprint.stats_service.get_all_career_stats()
        out = []
        if stats:
            for stat in stats:
                out.append(stat.to_dict())
        return jsonify(out)
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@stats_blueprint.route('/stats/career/<int:stat_id>', methods=['GET'])
@swag_from({
    'summary': 'Get career stats for a specific player',
    'description': 'Retrieve career statistics for a single player by user ID',
    'tags': ['stats'],
    'parameters': [{'name': 'user_id', 'in': 'path', 'type': 'integer', 'required': True}],
    'responses': {
        200: {'description': 'Career stats retrieved successfully'},
        404: {'description': 'Stats not found'},
        500: {'description': 'Internal server error'}
    }
})
def get_career_stats_by_user(stat_id):
    try:
        stat = stats_blueprint.stats_service.get_career_stats_by_user(stat_id)
        if stat:
            return jsonify(stat.to_dict())
        return jsonify({"error": "Stats not found"}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@stats_blueprint.route('/stats/career/<int:stat_id>', methods=['PUT'])
@jwt_required()
@swag_from({
    'summary': 'Update career stats',
    'description': 'Update historical baseline values and user link for career stats',
    'tags': ['stats'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'stat_id', 'in': 'path', 'type': 'integer', 'required': True},
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'user_id': {'type': 'integer', 'nullable': True},
                    'historical_rating': {'type': 'integer'},
                    'historical_series_won': {'type': 'integer'},
                    'historical_series_lost': {'type': 'integer'},
                    'historical_games_won': {'type': 'integer'},
                    'historical_games_lost': {'type': 'integer'},
                    'historical_seasons_played': {'type': 'integer'}
                }
            }
        }
    ],
    'responses': {
        200: {'description': 'Stats updated successfully'},
        404: {'description': 'Stats not found'},
        500: {'description': 'Internal server error'}
    }
})
def update_career_stats(stat_id):
    try:
        data = request.get_json()
        from src.schemas.player_career_stats import PlayerCareerStats
        stat_dto = PlayerCareerStats(data)
        stat = stats_blueprint.stats_service.update_career_stats(stat_id, stat_dto)
        if stat:
            return jsonify(stat.to_dict()), 200
        return jsonify({"error": "Stats not found"}), 404
    except Exception as e:
        logger.error(f"Error updating stats: {e}")
        return jsonify({"error": str(e)}), 500

@stats_blueprint.route('/stats/career/<int:stat_id>', methods=['DELETE'])
@jwt_required()
@swag_from({
    'summary': 'Delete career stats',
    'description': 'Delete career statistics record',
    'tags': ['stats'],
    'security': [{'BearerAuth': []}],
    'parameters': [{'name': 'stat_id', 'in': 'path', 'type': 'integer', 'required': True}],
    'responses': {
        200: {'description': 'Stats deleted successfully'},
        404: {'description': 'Stats not found'},
        500: {'description': 'Internal server error'}
    }
})
def delete_career_stats(stat_id):
    try:
        success = stats_blueprint.stats_service.delete_career_stats(stat_id)
        if success:
            return jsonify({"success": True}), 200
        return jsonify({"error": "Stats not found"}), 404
    except Exception as e:
        logger.error(f"Error deleting stats: {e}")
        return jsonify({"error": str(e)}), 500

@stats_blueprint.route('/stats/career/import-csv', methods=['POST'])
@jwt_required()
@swag_from({
    'summary': 'Import historical player stats from CSV',
    'description': 'One-time import of historical stats. Requires CSV file upload with columns: NAME, RATING, WON Series, LOST Series, WINRATE (x2), WON Games, LOST Games, Seasons PLAYED, AVG NUM Series',
    'tags': ['stats'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {
            'name': 'file',
            'in': 'formData',
            'type': 'file',
            'required': True,
            'description': 'CSV file with historical stats'
        }
    ],
    'responses': {
        200: {'description': 'Import successful with summary'},
        400: {'description': 'Invalid file or format'},
        500: {'description': 'Internal server error'}
    }
})
def import_historical_csv():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        if not file.filename.endswith('.csv'):
            return jsonify({"error": "File must be a CSV"}), 400
        
        # Read CSV content with flexible encoding (handles Windows files)
        try:
            # Try UTF-8 first
            stream = io.StringIO(file.stream.read().decode("UTF-8"), newline=None)
        except UnicodeDecodeError:
            # Fallback to Windows-1252 encoding
            file.stream.seek(0)
            stream = io.StringIO(file.stream.read().decode("Windows-1252"), newline=None)
        
        csv_input = csv.DictReader(stream)
        
        result = stats_blueprint.stats_service.import_historical_stats(csv_input)
        
        return jsonify({
            "success": True,
            "imported": result['imported'],
            "skipped": result['skipped'],
            "errors": result['errors']
        }), 200
        
    except Exception as e:
        logger.error(f"Error importing CSV: {e}")
        return jsonify({"error": str(e)}), 500

@stats_blueprint.route('/stats/career/recalculate', methods=['POST'])
@jwt_required()
@swag_from({
    'summary': 'Recalculate all player career stats',
    'description': 'Combines historical baseline with ALL series data in the database to update player stats. Always uses complete series history for accurate career totals. Run this after importing data or to refresh stats.',
    'tags': ['stats'],
    'security': [{'BearerAuth': []}],
    'responses': {
        200: {'description': 'Recalculation successful with summary'},
        500: {'description': 'Internal server error'}
    }
})
def recalculate_stats():
    try:
        result = stats_blueprint.stats_service.recalculate_all_stats()
        
        return jsonify({
            "success": True,
            "updated": result['updated'],
            "errors": result['errors']
        }), 200
        
    except Exception as e:
        logger.error(f"Error recalculating stats: {e}")
        return jsonify({"error": str(e)}), 500
