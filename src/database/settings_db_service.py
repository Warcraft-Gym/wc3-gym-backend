import logging
from src.database.abstract_database_service import AbstractDatabaseService
from src.database.model.DBSettings import DBSettings
from custom_exceptions import DBException
from src.dtos.settings_dto import SettingsDTO

logger = logging.getLogger(__name__)

class SettingsDBService(AbstractDatabaseService):

    def add(self, settings: SettingsDTO):
        """Add a new setting"""
        with self.get_session() as session:
            new_setting = DBSettings.add(session, settings.to_db_dict())
            if not new_setting:
                raise DBException("Setting could not be created!")
            return SettingsDTO.from_dbsettings(new_setting)

    def update(self, settings: SettingsDTO):
        """Update a setting"""
        with self.get_session() as session:
            updated_setting = DBSettings.update(session, settings.id, **settings.to_db_dict())
            if not updated_setting:
                raise DBException("Setting could not be updated!")
            return SettingsDTO.from_dbsettings(updated_setting)

    def delete(self, setting_id):
        """Delete a setting by id"""
        with self.get_session() as session:
            DBSettings.delete(session, setting_id)

    def get(self, setting_id):
        """Get a setting by id"""
        with self.get_session() as session:
            setting = session.query(DBSettings).filter_by(id=setting_id).first()
            if not setting:
                raise DBException(f"Setting with id '{setting_id}' not found")
            return SettingsDTO.from_dbsettings(setting)

    def getAll(self):
        """Get all settings"""
        with self.get_session() as session:
            result = []
            settings = DBSettings.getAll(session)
            for setting in settings:
                result.append(SettingsDTO.from_dbsettings(setting))
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
                raise DBException(f"Setting with key '{key}' not found")
            return SettingsDTO.from_dbsettings(setting)
