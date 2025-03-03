import logging
import traceback
from app import app
from flask import request, jsonify
from flask_jwt_extended import jwt_required
from custom_exceptions import NotFoundException
from flasgger import swag_from
from src.dtos.series_dto import SeriesDTO

logger = logging.getLogger(__name__)

#series endpoints
@app.route('/series', methods=['POST'])
@jwt_required()
@swag_from({
    'summary': 'Add a new series',
    'description': 'Create a new series with the provided data',
    'tags': ['series'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': SeriesDTO.schema()
        }
    ],
    'responses': {
        201: {'description': 'Series created successfully'},
        500: {'description': 'Internal server error'}
    }
})
def add_series():
    try:
        data = request.json
        series = app.series_app_service.create_series(SeriesDTO(data))
        return jsonify(series), 201
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/series/<int:series_id>', methods=['PUT'])
@jwt_required()
@swag_from({
    'summary': 'Updates a series',
    'description': 'Update the series data of an existing series',
    'tags': ['series'],
    'security': [{'BearerAuth': []}],
    'parameters': [
        {'name': 'series_id', 'in': 'path', 'type': 'integer', 'required': True},
        {
            'name': 'body',
            'in': 'body',
            'required': False,
            'schema': SeriesDTO.schema()
        }
    ],
    'responses': {
        200: {'description': 'series updated successfully'},
        404: {'description': 'series not found'},
        500: {'description': 'Internal server error'}
    }
})
def update_series(series_id):
    try:
        data = request.json
        series = app.series_app_service.update_series(series_id, SeriesDTO(data))
        return jsonify(series)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500
    
@app.route('/series/<int:series_id>', methods=['DELETE'])
@jwt_required()
@swag_from({
    'summary': 'Delete a series',
    'description': 'Delete a series by its ID.',
    'tags': ['series'],
    'security': [{'BearerAuth': []}],
    'parameters': [{'name': 'series_id', 'in': 'path', 'type': 'integer', 'required': True}],
    'responses': {
        204: {'description': 'season deleted successfully'},
        500: {'description': 'Internal server error'}
    }
})

def delete_series(series_id):
    try:
        app.series_app_service.delete_series(series_id)
        return f"series Deleted: {series_id}", 204
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500

@app.route('/series/<int:series_id>', methods=['GET'])
@swag_from({
    'summary': 'Get a series',
    'description': 'Retrieve a series by its ID.',
    'tags': ['series'],
    'parameters': [{'name': 'series_id', 'in': 'path', 'type': 'integer', 'required': True}],
    'responses': {
        200: {'description': 'season retrieved successfully'},
        404: {'description': 'season not found'},
        500: {'description': 'Internal server error'}
    }
})

def get_series(series_id):
    try:
        series = app.series_app_service.get_series(series_id)
        return jsonify(series)
    except NotFoundException as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500
    
@app.route('/series', methods=['GET'])
@swag_from({
    'summary': 'Get all series',
    'description': 'Return all series',
    'tags': ['series'],
    'responses': {
        200: {'description': 'series retrieved successfully'},
        500: {'description': 'Internal server error'}
    }
})
def get_all_series():
    try:
        series = app.series_app_service.getAll()
        return jsonify(series)
    except Exception as e:
        logger.error(e)
        return jsonify({"error": str(e)}), 500