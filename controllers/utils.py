"""
Utility Functions and Helpers
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def generate_conversation_title(data):
    """Generate a conversation title from the provided data"""
    if data.get('topic') and data.get('grade_level') and data.get('subject'):
        return f"{data.get('grade_level', '')} {data.get('subject', '')} - {data.get('topic', '')}"
    elif data.get('grade_level') and data.get('subject'):
        return f"{data.get('grade_level', '')} {data.get('subject', '')}"
    return f"Lesson Plan - {datetime.now().strftime('%B %d, %Y')}"
