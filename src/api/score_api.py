import logging
from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt_identity
from custom_exceptions import NotFoundException
from src.dtos.map_dto import MapDTO
from src.util.query_util import QueryUtil
from flasgger import swag_from

logger = logging.getLogger(__name__)

score_blueprint = Blueprint('score_api', __name__)

@score_blueprint.route('/season/<int:season_id>/calculate/', methods=['POST'])
@jwt_required()
@swag_from({
    'summary': 'Calculate the scores of a given season',
    'description': 'Calculates series, match and team scores for the given season.',
    'tags': ['score'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'season_id', 'in': 'path', 'type': 'integer', 'required': True, 'description': 'The ID of the season to calculate'},
    ],
    'responses': {
        201: {'description': 'Score calculated successfully'},
        500: {'description': 'Internal server error'}
    }
})
def calc_score(season_id: int):
    try:
        teams = {}
        season = score_blueprint.season_app_service.get_season(season_id)
        if season:
            season = season.to_dict()

        query = QueryUtil.parseQuery("season_id == " + str(season["id"]))
        matches = score_blueprint.match_app_service.search(query)

        for match in matches:
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
        
        for key in teams:
            score_blueprint.score_app_service.updateTeamScore(teams[key], season_id)

        return jsonify(season)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500