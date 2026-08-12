import logging
from src.database.settings_db_service import SettingsDBService
from src.schemas.settings import Settings

logger = logging.getLogger(__name__)

class SettingsAppService:
    def __init__(self, settings_service: SettingsDBService):
        self.settings_service = settings_service
    
    def get_setting(self, key):
        """Get a single setting by key"""
        setting_dto = self.settings_service.get_by_key(key)
        return setting_dto.to_dict() if setting_dto else None
    
    def get_all_settings(self):
        """Get all settings"""
        settings_dtos = self.settings_service.getAll()
        return [s.to_dict() for s in settings_dtos]
    
    def get_settings_dict(self):
        """Get all settings as a dictionary"""
        return self.settings_service.get_settings_dict()
    
    def update_setting(self, key, value, description=None):
        """Update or create a single setting"""
        try:
            # Try to get existing setting by key
            existing_dto = self.settings_service.get_by_key(key)
            # Update it
            settings_dto = Settings(id=existing_dto.id, key=key, value=value, description=description)
            updated = self.settings_service.update(settings_dto)
            return updated.to_dict()
        except Exception:
            # If not found, create new setting
            settings_dto = Settings(key=key, value=value, description=description)
            created = self.settings_service.add(settings_dto)
            return created.to_dict()
    
    def update_settings(self, settings_dict):
        """Update multiple settings"""
        updated = []
        for key, value in settings_dict.items():
            result = self.update_setting(key, value)
            updated.append(result)
        return updated
    
    def delete_setting(self, key):
        """Delete a setting by key"""
        # Get setting by key first to find its ID
        setting_dto = self.settings_service.get_by_key(key)
        self.settings_service.delete(setting_dto.id)
