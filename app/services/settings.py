import logging

from app.exceptions import DBException, NotFoundException
from app.models.settings import DBSettings
from app.schemas.settings import Settings
from app.services.base import BaseService

logger = logging.getLogger(__name__)


class SettingsService(BaseService):
    def add(self, settings: Settings):
        """Add a new setting"""
        with self.get_session() as session:
            new_setting = DBSettings.add(session, settings.to_db_dict())
            if not new_setting:
                raise DBException("Setting could not be created!")
            return Settings.from_dbsettings(new_setting)

    def update(self, settings: Settings):
        """Update a setting"""
        with self.get_session() as session:
            updated_setting = DBSettings.update(
                session, settings.id, **settings.to_db_dict()
            )
            if not updated_setting:
                raise NotFoundException("Setting not found")
            return Settings.from_dbsettings(updated_setting)

    def delete(self, setting_id):
        """Delete a setting by id"""
        with self.get_session() as session:
            DBSettings.delete(session, setting_id)

    def get(self, setting_id):
        """Get a setting by id"""
        with self.get_session() as session:
            setting = session.get(DBSettings, setting_id)
            if not setting:
                raise NotFoundException(f"Setting with id '{setting_id}' not found")
            return Settings.from_dbsettings(setting)

    def getAll(self):
        """Get all settings"""
        with self.get_session() as session:
            result = []
            settings = DBSettings.getAll(session)
            for setting in settings:
                result.append(Settings.from_dbsettings(setting))
            return result

    def get_settings_dict(self):
        """Get all settings as a dictionary"""
        with self.get_session() as session:
            return DBSettings.get_all_as_dict(session)

    def get_by_key(self, key):
        """Get a setting by key (helper method for API)"""
        with self.get_session() as session:
            setting = DBSettings.get_by_key(session, key)
            if not setting:
                raise NotFoundException(f"Setting with key '{key}' not found")
            return Settings.from_dbsettings(setting)

    def get_setting(self, key):
        """Get a single setting by key"""
        setting_dto = self.get_by_key(key)
        return setting_dto.to_dict() if setting_dto else None

    def get_all_settings(self):
        """Get all settings"""
        settings_dtos = self.getAll()
        return [s.to_dict() for s in settings_dtos]

    def update_setting(self, key, value, description=None):
        """Update or create a single setting"""
        try:
            # Try to get existing setting by key
            existing_dto = self.get_by_key(key)
            # Update it
            settings_dto = Settings(
                id=existing_dto.id, key=key, value=value, description=description
            )
            updated = self.update(settings_dto)
            return updated.to_dict()
        except Exception:
            # If not found, create new setting
            settings_dto = Settings(key=key, value=value, description=description)
            created = self.add(settings_dto)
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
        setting_dto = self.get_by_key(key)
        self.delete(setting_dto.id)
