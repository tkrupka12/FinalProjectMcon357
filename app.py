"""
AI Teaching Assistant - Main Application Entry Point
Following the Application Initialization Flow from the flow diagram
"""
import logging

from flask import Flask
from flask_login import LoginManager

from config import SECRET_KEY

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Flask app initialization
app = Flask(__name__)
app.secret_key = SECRET_KEY

# Configure session settings to persist across page reloads
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24 hours

# Initialize Flask-Mail (for help center emails)
mail = None
try:
    from flask_mail import Mail
    from config import MAIL_SERVER, MAIL_PORT, MAIL_USE_TLS, MAIL_USERNAME, MAIL_PASSWORD
    if MAIL_SERVER and MAIL_USERNAME:
        app.config['MAIL_SERVER'] = MAIL_SERVER
        app.config['MAIL_PORT'] = MAIL_PORT
        app.config['MAIL_USE_TLS'] = MAIL_USE_TLS
        app.config['MAIL_USERNAME'] = MAIL_USERNAME
        if MAIL_PASSWORD:
            app.config['MAIL_PASSWORD'] = MAIL_PASSWORD
        mail = Mail(app)
        logger.info("Flask-Mail initialized for help center")
    else:
        logger.warning("Mail configuration incomplete - help center emails will be logged only")
except ImportError:
    logger.warning("Flask-Mail not installed - help center emails will be logged only")
    mail = None
except Exception as e:
    logger.warning(f"Flask-Mail initialization failed (emails may not work): {e}")
    mail = None

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'index'

# Initialize database (MongoDB)
try:
    from models.database import get_db
    db = get_db()
    logger.info("Database initialized successfully")
except Exception as e:
    logger.error(f"Database initialization failed: {e}")
    raise

# Register routes
from controllers.routes import register_routes
register_routes(app, login_manager, mail)

if __name__ == '__main__':
    logger.info("Starting AI Teaching Assistant...")
    logger.info("Open your browser and go to http://localhost:5000")
    logger.info("NOTE: Make sure MongoDB is running on localhost:27017")
    app.run(host='127.0.0.1', port=5000, debug=True)
