import logging
from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt_identity
from custom_exceptions import NotFoundException
from src.schemas.map import Map
from src.util.query_util import QueryUtil
from flasgger import swag_from

logger = logging.getLogger(__name__)

score_blueprint = Blueprint('score_api', __name__)

# Global dictionary to track calculation progress per season
calculation_progress = {}

@score_blueprint.route('/season/<int:season_id>/calculate/status', methods=['GET'])
@swag_from({
    'summary': 'Get calculation progress for a season',
    'description': 'Returns the current progress of score calculation for a season.',
    'tags': ['score'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'season_id', 'in': 'path', 'type': 'integer', 'required': True, 'description': 'The ID of the season'},
    ],
    'responses': {
        200: {'description': 'Progress status retrieved'},
        404: {'description': 'No calculation in progress'}
    }
})
def get_calc_status(season_id: int):
    """Get the current calculation progress for a season"""
    progress = calculation_progress.get(season_id)
    
    if not progress:
        return jsonify({
            'status': 'idle',
            'progress': 0,
            'total': 0,
            'current': 0,
            'message': 'No calculation in progress'
        }), 200
    
    return jsonify(progress), 200

@score_blueprint.route('/season/<int:season_id>/calculate/', methods=['POST'])
@jwt_required()
@swag_from({
    'summary': 'Calculate the scores of a given season',
    'description': 'Calculates series, match and team scores for the given season. This is a long-running synchronous operation that updates progress tracking.',
    'tags': ['score'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'season_id', 'in': 'path', 'type': 'integer', 'required': True, 'description': 'The ID of the season to calculate'},
    ],
    'responses': {
        200: {'description': 'Score calculated successfully'},
        409: {'description': 'Calculation already in progress'},
        500: {'description': 'Internal server error'}
    }
})
def calc_score(season_id: int):
    # Check if calculation is already in progress for this season
    if season_id in calculation_progress and calculation_progress[season_id]['status'] == 'running':
        return jsonify({
            'error': 'Calculation already in progress for this season',
            'progress': calculation_progress[season_id]
        }), 409
    
    # Initialize progress tracking
    calculation_progress[season_id] = {
        'status': 'running',
        'progress': 0,
        'total': 0,
        'current': 0,
        'message': 'Starting calculation...'
    }
    
    # Perform calculation synchronously
    try:
        result = perform_calculation(season_id)
        return jsonify(result), 200
    except NotFoundException as e:
        logger.error(f"Season not found: {e}")
        calculation_progress[season_id]['status'] = 'error'
        calculation_progress[season_id]['message'] = f'Error: {str(e)}'
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(f"Error calculating scores: {e}")
        calculation_progress[season_id]['status'] = 'error'
        calculation_progress[season_id]['message'] = f'Error: {str(e)}'
        return jsonify({"error": str(e)}), 500

def perform_calculation(season_id: int):
    """Perform the actual score calculation with progress tracking"""
    try:
        teams = {}
        season = score_blueprint.season_app_service.get_season(season_id)
        if season:
            season = season.to_dict()

        query = QueryUtil.parseQuery("season_id == " + str(season["id"]))
        matches = score_blueprint.match_app_service.search(query)
        
        total_matches = len(matches)
        
        # Update progress - initialization complete
        calculation_progress[season_id]['total'] = total_matches
        calculation_progress[season_id]['message'] = f'Processing {total_matches} matches...'

        for index, match in enumerate(matches):
            # Update progress for current match
            calculation_progress[season_id]['current'] = index + 1
            calculation_progress[season_id]['progress'] = int(((index + 1) / total_matches) * 100)
            calculation_progress[season_id]['message'] = f'Processing match {index + 1} of {total_matches}'
            
            query = QueryUtil.parseQuery("match_id == " + str(match.id))
            series = score_blueprint.series_app_service.search(query)
            team1_points = 0
            team2_points = 0

            for singleSeries in series:
                try:
                    if singleSeries.player1_score == None or singleSeries.player2_score == None:
                        continue
                    calculatedSeries = score_blueprint.score_app_service.calculateSeriesScore(singleSeries)
                except Exception as e:
                    raise Exception(str(e) + " for series with id " + str(singleSeries.id))
                
                score_blueprint.series_app_service.update_series(calculatedSeries.id, calculatedSeries)
                team1_points += calculatedSeries.player1_points
                team2_points += calculatedSeries.player2_points

            match.team1_score = team1_points
            match.team2_score = team2_points

            teams[match.team1.id] = match.team1
            teams[match.team2.id] = match.team2

            score_blueprint.match_app_service.update_match(match.id, match)
        
        # Update team scores
        calculation_progress[season_id]['message'] = 'Updating team standings...'
        for key in teams:
            score_blueprint.score_app_service.updateTeamScore(teams[key], season_id)

        # Mark as complete
        calculation_progress[season_id]['status'] = 'completed'
        calculation_progress[season_id]['progress'] = 100
        calculation_progress[season_id]['message'] = 'Calculation completed successfully'
        
        return season
        
    except NotFoundException as e:
        logger.error(f"Season not found: {e}")
        calculation_progress[season_id]['status'] = 'error'
        calculation_progress[season_id]['message'] = f'Error: {str(e)}'
        raise
    except Exception as e:
        logger.error(f"Error calculating scores: {e}")
        calculation_progress[season_id]['status'] = 'error'
        calculation_progress[season_id]['message'] = f'Error: {str(e)}'
        raise
