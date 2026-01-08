"""
Database Models and Operations
MongoDB connection and operations following the flow diagram
"""
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import logging
from bson import ObjectId
from datetime import datetime
from config import MONGODB_URI, MONGODB_DB_NAME

logger = logging.getLogger(__name__)

class Database:
    """MongoDB database connection manager"""
    
    def __init__(self, connection_string=None, db_name=None):
        # Use config values if not provided
        if connection_string is None:
            connection_string = MONGODB_URI
        if db_name is None:
            db_name = MONGODB_DB_NAME
        try:
            self.client = MongoClient(connection_string, serverSelectionTimeoutMS=5000)
            # Test connection
            self.client.admin.command('ping')
            self.db = self.client[db_name]
            self._create_indexes()
            logger.info(f"Connected to MongoDB database: {db_name}")
        except ConnectionFailure as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
    
    def _create_indexes(self):
        """Create database indexes for performance"""
        try:
            # Users collection indexes
            self.db.users.create_index("email", unique=True)
            self.db.users.create_index("id", unique=True)
            
            # Conversations collection indexes
            self.db.conversations.create_index("user_id")
            self.db.conversations.create_index([("user_id", 1), ("updated_at", -1)])
            self.db.conversations.create_index("is_favorite")
            
            # Messages collection indexes
            self.db.messages.create_index("conversation_id")
            self.db.messages.create_index([("conversation_id", 1), ("created_at", 1)])
            
            # Lesson plans collection indexes
            self.db.lesson_plans.create_index("conversation_id", unique=True)
            
            # User preferences collection indexes
            self.db.user_preferences.create_index("user_id", unique=True)
            
            logger.info("Database indexes created successfully")
        except Exception as e:
            logger.error(f"Error creating indexes: {e}")
    
    def get_collection(self, collection_name):
        """Get a collection by name"""
        return self.db[collection_name]
    
    def close(self):
        """Close database connection"""
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")

# Global database instance
_db_instance = None

def get_db():
    """Get database instance (singleton pattern)"""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()  # Will use MONGODB_URI and MONGODB_DB_NAME from config
    return _db_instance

def convert_objectid_to_string(obj):
    """Convert ObjectId to string for JSON serialization"""
    if isinstance(obj, ObjectId):
        return str(obj)
    elif isinstance(obj, dict):
        return {k: convert_objectid_to_string(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_objectid_to_string(item) for item in obj]
    return obj

