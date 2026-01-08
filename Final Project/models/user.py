"""
User Model for Flask-Login
"""
from flask_login import UserMixin
from bson import ObjectId

class User(UserMixin):
    """User class for Flask-Login"""
    
    def __init__(self, user_id, email, name, picture):
        self.id = str(user_id)  # Convert ObjectId to string
        self.email = email
        self.name = name
        self.picture = picture
    
    @staticmethod
    def from_dict(user_dict):
        """Create User object from MongoDB document"""
        # Prefer 'id' (Google ID) over '_id' (MongoDB ObjectId) if available
        user_id = user_dict.get('id') or user_dict.get('_id')
        if isinstance(user_id, ObjectId):
            user_id = str(user_id)
        return User(
            user_id=user_id,
            email=user_dict.get('email'),
            name=user_dict.get('name'),
            picture=user_dict.get('picture')
        )
    
    def to_dict(self):
        """Convert User object to dictionary"""
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'picture': self.picture
        }

