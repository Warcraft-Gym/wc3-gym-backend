import logging

from app.exceptions import NotFoundException
from app.models.settings import (
    Settings,
    SettingsCreate,
    SettingsPublic,
    SettingsUpdate,
)
from app.services.base import BaseService

logger = logging.getLogger(__name__)


class SettingsService(BaseService):
    def add(self, settings: SettingsCreate):
        """Add a new setting"""
        with self.get_session() as session:
            new_setting = Settings.add(session, settings.model_dump())
            return SettingsPublic.model_validate(new_setting)

    def update(self, setting_id, settings: SettingsUpdate):
        """Update a setting"""
        with self.get_session() as session:
            updated_setting = Settings.update(
                session, setting_id, **settings.model_dump(exclude_unset=True)
            )
            if not updated_setting:
                raise NotFoundException("Setting not found")
            return SettingsPublic.model_validate(updated_setting)

    def delete(self, setting_id):
        """Delete a setting by id"""
        with self.get_session() as session:
            Settings.delete(session, setting_id)

    def get(self, setting_id):
        """Get a setting by id"""
        with self.get_session() as session:
            setting = session.get(Settings, setting_id)
            if not setting:
                raise NotFoundException(f"Setting with id '{setting_id}' not found")
            return SettingsPublic.model_validate(setting)

    def getAll(self):
        """Get all settings"""
        with self.get_session() as session:
            return [
                SettingsPublic.model_validate(setting)
                for setting in Settings.getAll(session)
            ]

    def get_settings_dict(self):
        """Get all settings as a dictionary"""
        with self.get_session() as session:
            return Settings.get_all_as_dict(session)

    def get_by_key(self, key):
        """Get a setting by key (helper method for API)"""
        with self.get_session() as session:
            setting = Settings.get_by_key(session, key)
            if not setting:
                raise NotFoundException(f"Setting with key '{key}' not found")
            return SettingsPublic.model_validate(setting)

    def get_setting(self, key):
        """Get a single setting by key"""
        setting = self.get_by_key(key)
        return setting.to_dict() if setting else None

    def get_all_settings(self):
        """Get all settings"""
        return [setting.to_dict() for setting in self.getAll()]

    def update_setting(self, key, value, description=None):
        """Update or create a single setting"""
        try:
            # Try to get existing setting by key
            existing = self.get_by_key(key)
            updated = self.update(
                existing.id,
                SettingsUpdate(key=key, value=value, description=description),
            )
            return updated.to_dict()
        except Exception:
            # If not found, create new setting
            created = self.add(
                SettingsCreate(key=key, value=value, description=description)
            )
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
        setting = self.get_by_key(key)
        self.delete(setting.id)
