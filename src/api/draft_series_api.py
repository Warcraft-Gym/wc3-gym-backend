import logging
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from custom_exceptions import NotFoundException
from flasgger import swag_from
from src.schemas.draft_series import DraftSeries

logger = logging.getLogger(__name__)

draft_series_blueprint = Blueprint('draft_series_api', __name__)

@draft_series_blueprint.route('/draft-series', methods=['POST'])
@jwt_required()
@swag_from({
    'summary': 'Add a new draft series',
    'description': 'Create a new draft series (visible in admin UI only)',
    'tags': ['draft-series'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': DraftSeries.schema()
        }
    ],
    'responses': {
        201: {'description': 'Draft series created successfully'},
        500: {'description': 'Internal server error'}
    }
})
def add_draft_series():
    try:
        data = request.json
        draft_series = draft_series_blueprint.draft_series_app_service.create_draft_series(DraftSeries(data))
        if draft_series:
            draft_series = draft_series.to_dict()
        return jsonify(draft_series), 201
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@draft_series_blueprint.route('/draft-series/<int:draft_series_id>', methods=['PUT'])
@jwt_required()
@swag_from({
    'summary': 'Update a draft series',
    'description': 'Update the data of an existing draft series',
    'tags': ['draft-series'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'draft_series_id', 'in': 'path', 'type': 'integer', 'required': True},
        {
            'name': 'body',
            'in': 'body',
            'required': False,
            'schema': DraftSeries.schema()
        }
    ],
    'responses': {
        200: {'description': 'Draft series updated successfully'},
        404: {'description': 'Draft series not found'},
        500: {'description': 'Internal server error'}
    }
})
def update_draft_series(draft_series_id):
    try:
        data = request.json
        draft_series = draft_series_blueprint.draft_series_app_service.update_draft_series(draft_series_id, DraftSeries(data))
        if draft_series:
            draft_series = draft_series.to_dict()
        return jsonify(draft_series)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
    
@draft_series_blueprint.route('/draft-series/<int:draft_series_id>', methods=['DELETE'])
@jwt_required()
@swag_from({
    'summary': 'Delete a draft series',
    'description': 'Delete a draft series by its ID.',
    'tags': ['draft-series'],
    'security': [{'BearerAuth': []}],
    'parameters': [{'name': 'draft_series_id', 'in': 'path', 'type': 'integer', 'required': True}],
    'responses': {
        204: {'description': 'Draft series deleted successfully'},
        500: {'description': 'Internal server error'}
    }
})
def delete_draft_series(draft_series_id):
    try:
        draft_series_blueprint.draft_series_app_service.delete_draft_series(draft_series_id)
        return f"Draft series deleted: {draft_series_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@draft_series_blueprint.route('/draft-series/<int:draft_series_id>', methods=['GET'])
@swag_from({
    'summary': 'Get a draft series',
    'description': 'Retrieve a draft series by its ID.',
    'tags': ['draft-series'],
    'parameters': [{'name': 'draft_series_id', 'in': 'path', 'type': 'integer', 'required': True}],
    'responses': {
        200: {'description': 'Draft series retrieved successfully'},
        404: {'description': 'Draft series not found'},
        500: {'description': 'Internal server error'}
    }
})
def get_draft_series(draft_series_id):
    try:
        draft_series = draft_series_blueprint.draft_series_app_service.get_draft_series(draft_series_id)
        if draft_series:
            draft_series = draft_series.to_dict()
        return jsonify(draft_series)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
    
@draft_series_blueprint.route('/draft-series/match/<int:match_id>', methods=['GET'])
@swag_from({
    'summary': 'Get all draft series for a match',
    'description': 'Return all draft series for a specific match',
    'tags': ['draft-series'],
    'parameters': [
        {'name': 'match_id', 'in': 'path', 'type': 'integer', 'required': True}
    ],
    'responses': {
        200: {'description': 'Draft series retrieved successfully'},
        500: {'description': 'Internal server error'}
    }
})
def get_draft_series_by_match(match_id: int):
    try:
        draft_series_list = draft_series_blueprint.draft_series_app_service.get_draft_series_by_match(match_id)
        out = []
        if draft_series_list:
            for draft_series in draft_series_list:
                out.append(draft_series.to_dict())
        return jsonify(out)
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@draft_series_blueprint.route('/draft-series/match/<int:match_id>', methods=['DELETE'])
@jwt_required()
@swag_from({
    'summary': 'Delete all draft series for a match',
    'description': 'Delete all draft series for a specific match',
    'tags': ['draft-series'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'match_id', 'in': 'path', 'type': 'integer', 'required': True}
    ],
    'responses': {
        204: {'description': 'Draft series deleted successfully'},
        500: {'description': 'Internal server error'}
    }
})
def delete_all_draft_series_for_match(match_id: int):
    try:
        draft_series_blueprint.draft_series_app_service.delete_all_drafts_for_match(match_id)
        return f"All draft series deleted for match: {match_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@draft_series_blueprint.route('/draft-series/<int:draft_series_id>/promote', methods=['POST'])
@jwt_required()
@swag_from({
    'summary': 'Promote draft series to real series',
    'description': 'Convert a draft series to a real published series and delete the draft',
    'tags': ['draft-series'],
    'security': [{'BearerAuth': []}],
    'parameters': [{'name': 'draft_series_id', 'in': 'path', 'type': 'integer', 'required': True}],
    'responses': {
        201: {'description': 'Series promoted successfully'},
        404: {'description': 'Draft series not found'},
        500: {'description': 'Internal server error'}
    }
})
def promote_draft_series(draft_series_id):
    try:
        # Get the draft series
        draft_series = draft_series_blueprint.draft_series_app_service.get_draft_series(draft_series_id)
        
        # Convert to series DTO
        series_dto = draft_series_blueprint.draft_series_app_service.convert_to_series(draft_series)
        
        # Create as real series (this will trigger all calculations)
        from src.api.series_api import series_blueprint
        created_series = series_blueprint.series_app_service.create_series(series_dto)
        
        # Delete the draft
        draft_series_blueprint.draft_series_app_service.delete_draft_series(draft_series_id)
        
        if created_series:
            created_series = created_series.to_dict()
        return jsonify(created_series), 201
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
