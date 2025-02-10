from src.database.model.DBUser import DBUser
class UserDTO:
    def __init__(self, id: int, name: str, email: str):
        self.id = id
        self.name = name
        self.email = email

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email
        }

    @classmethod
    def from_dbuser(cls, user: DBUser):
        return cls(
            id=user.id,
            name=user.name,
            email=user.email
        )
