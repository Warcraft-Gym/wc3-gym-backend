from src.database.model.DBSettings import DBSettings

class SettingsDTO:
    def __init__(self, id=None, key=None, value=None, description=None):
        self.id = id
        self.key = key
        self.value = value
        self.description = description
    
    @classmethod
    def from_dbsettings(cls, db_settings: DBSettings):
        """Create DTO from database model"""
        if not db_settings:
            return None
        return cls(
            id=db_settings.id,
            key=db_settings.key,
            value=db_settings.value,
            description=db_settings.description
        )
    
    def to_dict(self):
        """Convert DTO to dictionary"""
        return {
            'id': self.id,
            'key': self.key,
            'value': self.value,
            'description': self.description
        }
    
    def to_db_dict(self):
        """Convert DTO to dictionary for database operations"""
        db_dict = {}
        if self.key is not None:
            db_dict['key'] = self.key
        if self.value is not None:
            db_dict['value'] = self.value
        if self.description is not None:
            db_dict['description'] = self.description
        return db_dict
