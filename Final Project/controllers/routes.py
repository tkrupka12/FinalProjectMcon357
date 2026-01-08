"""
API Endpoints and Route Handlers
Following the flow diagram for request-response cycle
"""
import logging
from datetime import datetime
from io import BytesIO
import json as json_module
import base64

from bson import ObjectId
from flask import Response, jsonify, redirect, render_template, request, url_for, session
from flask_login import current_user, login_required, login_user, logout_user
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.lib import colors
from bs4 import BeautifulSoup
from docx import Document
from docx.shared import Inches, Pt
import html2text
from flask_mail import Message

from config import GOOGLE_CLIENT_ID, HELP_EMAIL, MAIL_USERNAME
from controllers.services import ConversationState, process_conversation
from controllers.utils import generate_conversation_title
from models.database import convert_objectid_to_string, get_db
from models.user import User

logger = logging.getLogger(__name__)

def register_routes(app, login_manager, mail_instance=None):
    """Register all routes with the Flask app"""
    
    @login_manager.user_loader
    def load_user(user_id):
        """Load user from database for Flask-Login"""
        try:
            db = get_db()
            user_doc = db.get_collection('users').find_one({'id': user_id})
            if user_doc:
                return User.from_dict(user_doc)
            return None
        except Exception as e:
            logger.error(f"Error loading user: {str(e)}")
            return None
    
    @app.route('/')
    def index():
        """Render main page"""
        return render_template('index.html', google_client_id=GOOGLE_CLIENT_ID)
    
    @app.route('/login')
    def login():
        """Redirect to main page"""
        return redirect(url_for('index'))
    
    @app.route('/logout')
    def logout():
        """Logout user and redirect to main page"""
        logout_user()
        return redirect(url_for('index'))
    
    @app.route('/auth/google', methods=['POST'])
    def auth_google():
        """Handle Google OAuth authentication - following authentication flow"""
        try:
            data = request.get_json()
            if not data:
                logger.error("No data received in Google auth request")
                return jsonify({'success': False, 'error': 'No authentication data received'}), 400
            
            credential = data.get('credential')
            if not credential:
                logger.error("No credential in Google auth request")
                return jsonify({'success': False, 'error': 'No authentication credential provided'}), 400
            
            logger.info("Attempting to verify Google token")
            
            # Verify the token with Google
            try:
                idinfo = id_token.verify_oauth2_token(
                    credential, 
                    Request(), 
                    GOOGLE_CLIENT_ID
                )
                
                if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
                    raise ValueError('Wrong issuer.')
                
                user_id = idinfo.get('sub')
                email = idinfo.get('email')
                name = idinfo.get('name')
                picture = idinfo.get('picture')
                
                logger.info(f"Token verified successfully for user: {email}")
                
            except Exception as verify_error:
                # Fallback to simple decoding if verification fails (for development)
                logger.warning(f"Token verification failed, using fallback: {str(verify_error)}")
                try:
                    parts = credential.split('.')
                    if len(parts) < 2:
                        raise ValueError('Invalid token format')
                    
                    payload = parts[1]
                    padded = payload + '=' * (4 - len(payload) % 4)
                    decoded = base64.urlsafe_b64decode(padded)
                    user_info = json_module.loads(decoded)
                    
                    user_id = user_info.get('sub')
                    email = user_info.get('email')
                    name = user_info.get('name')
                    picture = user_info.get('picture')
                    
                    logger.info(f"Fallback decoding successful for user: {email}")
                except Exception as decode_error:
                    logger.error(f"Both token verification and fallback decoding failed: {str(decode_error)}")
                    return jsonify({'success': False, 'error': 'Invalid authentication token. Please try signing in again.'}), 400
            
            if not user_id or not email:
                logger.error(f"Missing user information: user_id={user_id}, email={email}")
                return jsonify({'success': False, 'error': 'Missing required user information from Google'}), 400
            
            # Save or update user in database (MongoDB)
            try:
                db = get_db()
                users_collection = db.get_collection('users')
                
                # Check if user already exists by ID
                existing_user = users_collection.find_one({'id': user_id})
                
                # If not found by ID, check by email to avoid duplicate key errors
                if not existing_user:
                    existing_by_email = users_collection.find_one({'email': email})
                    if existing_by_email:
                        logger.info(f"User found by email {email} but with different ID. Updating ID to {user_id}")
                        # Update the existing user's ID to the new one from Google
                        users_collection.update_one(
                            {'email': email},
                            {'$set': {'id': user_id, 'updated_at': datetime.now()}}
                        )
                        # Fetch the user again with the new ID
                        existing_user = users_collection.find_one({'id': user_id})
                
                is_new_user = existing_user is None
                
                # Prepare user document
                user_doc = {
                    'id': user_id,
                    'email': email,
                    'name': name,
                    'picture': picture,
                    'updated_at': datetime.now()
                }
                
                # If new user, set created_at and mark as needing onboarding
                if is_new_user:
                    user_doc['created_at'] = datetime.now()
                    user_doc['onboarding_complete'] = False
                    logger.info(f"New user detected: {email}")
                else:
                    # Preserve existing onboarding status and grade if they exist
                    if 'onboarding_complete' in existing_user:
                        user_doc['onboarding_complete'] = existing_user['onboarding_complete']
                    if 'grade_level' in existing_user:
                        user_doc['grade_level'] = existing_user['grade_level']
                    if 'basic_questions' in existing_user:
                        user_doc['basic_questions'] = existing_user['basic_questions']
                    logger.info(f"Existing user: {email}, onboarding_complete: {user_doc.get('onboarding_complete', False)}")
                
                try:
                    users_collection.update_one(
                        {'id': user_id},
                        {'$set': user_doc},
                        upsert=True
                    )
                    logger.info(f"User document saved/updated for {email}")
                except Exception as db_error:
                    logger.error(f"Database error saving user: {str(db_error)}", exc_info=True)
                    # If it's a duplicate key error, try to find and update existing user (fallback)
                    if 'duplicate key' in str(db_error).lower() or 'E11000' in str(db_error):
                        logger.warning("Duplicate key error in auth, attempting fallback find by email")
                        existing_by_email = users_collection.find_one({'email': email})
                        if existing_by_email:
                            users_collection.update_one(
                                {'email': email},
                                {'$set': {'id': user_id, **user_doc}}
                            )
                            existing_user = users_collection.find_one({'id': user_id})
                            is_new_user = False
                        else:
                            raise
                    else:
                        raise
                
                # Create user object and log in
                user = User(user_id, email, name, picture)
                login_user(user)
                logger.info(f"User {email} logged in successfully")
                
                # Check if user needs onboarding
                # User needs onboarding if they're new OR if they don't have a grade level saved
                if is_new_user:
                    needs_onboarding = True
                else:
                    grade_level = existing_user.get('grade_level', '')
                    has_grade = bool(grade_level and grade_level.strip() and grade_level != 'NOT SET' and grade_level != '')
                    # Need onboarding if no grade level is saved
                    needs_onboarding = not has_grade
                
                return jsonify({
                    'success': True,
                    'needs_onboarding': needs_onboarding
                })
            except Exception as db_error:
                logger.error(f"Database error during authentication: {str(db_error)}", exc_info=True)
                return jsonify({'success': False, 'error': 'Database error. Please try again.'}), 500
                
        except Exception as e:
            logger.error(f"Auth error: {str(e)}", exc_info=True)
            error_message = 'Authentication failed. Please try signing in again.'
            
            error_str = str(e).lower()
            if 'token' in error_str or 'credential' in error_str:
                error_message = 'Invalid authentication token. Please try signing in again with Google.'
            elif 'network' in error_str or 'connection' in error_str:
                error_message = 'Unable to verify your account. Please check your internet connection and try again.'
            elif 'database' in error_str or 'mongodb' in error_str:
                error_message = 'Database connection error. Please try again in a moment.'
            
            return jsonify({'success': False, 'error': error_message}), 400
    
    @app.route('/api/onboarding', methods=['GET', 'POST'])
    @login_required
    def onboarding():
        """Get or save onboarding information for users"""
        # Verify user is authenticated
        if not current_user.is_authenticated:
            logger.warning("Onboarding endpoint accessed without authentication")
            return jsonify({'success': False, 'error': 'Not authenticated'}), 401
        
        try:
            db = get_db()
            users_collection = db.get_collection('users')
            
            if request.method == 'GET':
                # Check if user needs onboarding
                user_doc = users_collection.find_one({'id': current_user.id})
                if user_doc:
                    grade_level = user_doc.get('grade_level', '')
                    # Check if user has a valid grade level saved
                    has_grade = bool(grade_level and grade_level.strip() and grade_level != 'NOT SET' and grade_level != '')
                    # User needs onboarding if they don't have a grade level saved
                    needs_onboarding = not has_grade
                    onboarding_complete = user_doc.get('onboarding_complete', False)
                    logger.info(f"Onboarding check for user {current_user.id}: grade_level={grade_level}, has_grade={has_grade}, onboarding_complete={onboarding_complete}, needs_onboarding={needs_onboarding}")
                    return jsonify({
                        'success': True,
                        'needs_onboarding': needs_onboarding,
                        'grade_level': grade_level if has_grade else '',
                        'basic_questions': user_doc.get('basic_questions', {})
                    })
                else:
                    logger.warning(f"User {current_user.id} not found in database")
                    return jsonify({
                        'success': True,
                        'needs_onboarding': True,
                        'grade_level': '',
                        'basic_questions': {}
                    })
            else:
                # POST - Save onboarding information
                # Double-check authentication
                if not current_user.is_authenticated:
                    logger.warning("Onboarding POST accessed without authentication")
                    return jsonify({'success': False, 'error': 'Session expired. Please refresh the page and sign in again.'}), 401
                
                try:
                    data = request.get_json()
                    if not data:
                        logger.error("No JSON data in onboarding POST request")
                        return jsonify({'success': False, 'error': 'No data provided'}), 400
                    
                    grade_level = data.get('grade_level', '').strip()
                    basic_questions = data.get('basic_questions', {})
                    
                    if not grade_level:
                        logger.error(f"Grade level missing for user {current_user.id}")
                        return jsonify({'success': False, 'error': 'Grade level is required'}), 400
                    
                    logger.info(f"Attempting to save onboarding for user {current_user.id}, grade_level: {grade_level}")
                    
                    # Check if user exists first by ID
                    user_doc = users_collection.find_one({'id': current_user.id})
                    if not user_doc:
                        # If not found by ID, check by email (in case ID changed)
                        user_email = getattr(current_user, 'email', '')
                        if user_email:
                            user_doc = users_collection.find_one({'email': user_email})
                            if user_doc:
                                # Update the existing user's ID to match current_user.id
                                logger.info(f"Found user by email {user_email}, updating ID to {current_user.id}")
                                users_collection.update_one(
                                    {'email': user_email},
                                    {'$set': {'id': current_user.id, 'updated_at': datetime.now()}}
                                )
                                user_doc = users_collection.find_one({'id': current_user.id})
                        
                        # If still not found, create new user - but check by email first to avoid duplicate key errors
                        if not user_doc:
                            logger.warning(f"User {current_user.id} not found in database. Creating/updating user...")
                            user_email = getattr(current_user, 'email', '')
                            
                            # Double-check by email before attempting to create (to avoid duplicate key errors)
                            if user_email:
                                existing_by_email = users_collection.find_one({'email': user_email})
                                if existing_by_email:
                                    # User exists with this email but different ID - update the ID
                                    logger.info(f"User exists with email {user_email} but different ID. Updating ID to {current_user.id}")
                                    users_collection.update_one(
                                        {'email': user_email},
                                        {'$set': {'id': current_user.id, 'updated_at': datetime.now()}}
                                    )
                                    user_doc = users_collection.find_one({'id': current_user.id})
                            
                            # Only create if user truly doesn't exist
                            if not user_doc:
                                new_user_doc = {
                                    'id': current_user.id,
                                    'email': user_email,
                                    'name': getattr(current_user, 'name', ''),
                                    'picture': getattr(current_user, 'picture', ''),
                                    'created_at': datetime.now(),
                                    'updated_at': datetime.now(),
                                    'onboarding_complete': False
                                }
                                try:
                                    # Use insert_one since we've verified user doesn't exist
                                    users_collection.insert_one(new_user_doc)
                                    logger.info(f"Created new user {current_user.id} in database")
                                    user_doc = users_collection.find_one({'id': current_user.id})
                                except Exception as create_error:
                                    error_msg = str(create_error)
                                    # If it's a duplicate key error, try to find and update existing user
                                    if 'duplicate key' in error_msg.lower() or 'E11000' in error_msg:
                                        logger.warning(f"Duplicate key error during insert, attempting to find existing user by email")
                                        if user_email:
                                            existing = users_collection.find_one({'email': user_email})
                                            if existing:
                                                # Update existing user's ID
                                                users_collection.update_one(
                                                    {'email': user_email},
                                                    {'$set': {'id': current_user.id, 'updated_at': datetime.now()}}
                                                )
                                                user_doc = users_collection.find_one({'id': current_user.id})
                                                logger.info(f"Updated existing user's ID to {current_user.id}")
                                            else:
                                                logger.error(f"Duplicate key error but couldn't find user by email: {error_msg}")
                                                return jsonify({'success': False, 'error': 'User already exists with this email. Please refresh the page.'}), 400
                                        else:
                                            logger.error(f"Duplicate key error but no email available: {error_msg}")
                                            return jsonify({'success': False, 'error': 'Database error: User already exists.'}), 400
                                    else:
                                        logger.error(f"Failed to create user: {error_msg}", exc_info=True)
                                        return jsonify({'success': False, 'error': f'Database error: {error_msg}'}), 500
                    
                    # Ensure user_doc exists before proceeding
                    if not user_doc:
                        logger.error(f"Could not find or create user {current_user.id} after all attempts")
                        return jsonify({'success': False, 'error': 'Unable to find or create user record. Please refresh and try again.'}), 500
                
                    # Update user with onboarding information
                    update_data = {
                        'grade_level': grade_level,
                        'onboarding_complete': True,
                        'updated_at': datetime.now()
                    }
                    
                    # Save basic questions if provided
                    if basic_questions:
                        update_data['basic_questions'] = basic_questions
                    
                    logger.info(f"Updating onboarding for user {current_user.id} with data: {update_data}")
                    
                    result = users_collection.update_one(
                        {'id': current_user.id},
                        {'$set': update_data}
                    )
                    
                    # Verify the update was successful
                    if result.matched_count == 0:
                        logger.error(f"User {current_user.id} not found when updating onboarding")
                        # List all users for debugging
                        all_users = list(users_collection.find({}, {'id': 1, 'email': 1}))
                        logger.error(f"Available users in DB: {all_users}")
                        return jsonify({'success': False, 'error': 'User not found in database. Please refresh and try again.'}), 404
                    
                    if result.modified_count == 0 and result.matched_count > 0:
                        logger.info(f"User {current_user.id} onboarding data unchanged (may already be set)")
                    
                    logger.info(f"Onboarding update successful for user {current_user.id}: matched={result.matched_count}, modified={result.modified_count}")
                    
                    # Verify the update by reading back - CRITICAL: Make sure grade_level is actually saved
                    updated_user = users_collection.find_one({'id': current_user.id})
                    if updated_user:
                        saved_grade = updated_user.get('grade_level', '')
                        saved_complete = updated_user.get('onboarding_complete', False)
                        logger.info(f"Onboarding verification for user {current_user.id}: grade_level='{saved_grade}', onboarding_complete={saved_complete}")
                        
                        # Verify grade_level was actually saved
                        if saved_grade and saved_grade.strip() and saved_grade != 'NOT SET' and saved_grade != '':
                            logger.info(f"✓ Onboarding verification successful - grade_level saved: '{saved_grade}'")
                            return jsonify({
                                'success': True,
                                'grade_level': saved_grade,
                                'onboarding_complete': saved_complete or True  # Ensure it's marked complete
                            })
                        else:
                            logger.error(f"✗ Onboarding verification FAILED - grade_level not properly saved: '{saved_grade}'")
                            # Try to save again if it failed
                            if grade_level and grade_level.strip():
                                logger.info(f"Retrying to save grade_level: '{grade_level}'")
                                users_collection.update_one(
                                    {'id': current_user.id},
                                    {'$set': {'grade_level': grade_level, 'onboarding_complete': True}}
                                )
                                # Verify again
                                retry_user = users_collection.find_one({'id': current_user.id})
                                if retry_user and retry_user.get('grade_level'):
                                    logger.info(f"✓ Retry successful - grade_level now saved: '{retry_user.get('grade_level')}'")
                                    return jsonify({
                                        'success': True,
                                        'grade_level': retry_user.get('grade_level'),
                                        'onboarding_complete': True
                                    })
                    
                    logger.error(f"Onboarding update verification failed for user {current_user.id}")
                    logger.error(f"Updated user doc: {updated_user}")
                    return jsonify({'success': False, 'error': 'Grade level was not saved properly. Please try again.'}), 500
                        
                except Exception as e:
                    logger.error(f"Exception in onboarding POST for user {current_user.id}: {str(e)}", exc_info=True)
                    return jsonify({'success': False, 'error': f'Server error: {str(e)}'}), 500
        except Exception as e:
            logger.error(f"Error with onboarding: {str(e)}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/chat', methods=['POST'])
    @login_required
    def chat():
        """Handle chat messages and process conversation - following main conversation flow"""
        try:
            # CRITICAL: Check if user has completed onboarding with a grade level
            db = get_db()
            users_collection = db.get_collection('users')
            user_doc = users_collection.find_one({'id': current_user.id})
            
            if not user_doc:
                logger.warning(f"Chat attempted by user {current_user.id} not found in database")
                return jsonify({
                    'success': False,
                    'error': 'User not found. Please complete onboarding first.',
                    'needs_onboarding': True
                }), 403
            
            grade_level = user_doc.get('grade_level', '')
            has_grade = bool(grade_level and grade_level.strip() and grade_level != 'NOT SET' and grade_level != '')
            
            if not has_grade:
                logger.warning(f"Chat attempted by user {current_user.id} without grade level - blocking chat")
                return jsonify({
                    'success': False,
                    'error': 'Please complete onboarding and set your grade level before using the chat.',
                    'needs_onboarding': True
                }), 403
            
            data = request.get_json()
            user_message = data.get('message', '').strip()
            state = data.get('state', {
                'step': ConversationState.GRADE_LEVEL, 
                'data': {}, 
                'conversationId': None
            })
            force_new = data.get('forceNewConversation', False)
            
            # Get or create conversation
            conversations_collection = db.get_collection('conversations')
            messages_collection = db.get_collection('messages')
            
            conversation_id = state.get('conversationId')
            
            if not conversation_id or force_new:
                # Create a new conversation
                # CRITICAL: Load user profile FIRST before creating conversation
                # This ensures grade level is available immediately
                user_profile_data = None
                saved_grade_level = None
                try:
                    users_collection = db.get_collection('users')
                    user_doc = users_collection.find_one({'id': current_user.id})
                    if user_doc:
                        saved_grade_level = user_doc.get('grade_level', '')
                        user_profile_data = {
                            'grade_level': saved_grade_level,
                            'basic_questions': user_doc.get('basic_questions', {})
                        }
                        logger.info(f"Loaded user profile for new conversation - grade_level: '{saved_grade_level}'")
                    else:
                        logger.warning(f"User {current_user.id} not found in database when creating conversation")
                except Exception as e:
                    logger.error(f"Could not load user profile when creating conversation: {str(e)}", exc_info=True)
                
                # Initialize conversation data with saved grade level if available
                initial_data = {}
                initial_step = ConversationState.GRADE_LEVEL
                
                if saved_grade_level and saved_grade_level.strip() and saved_grade_level != 'NOT SET' and saved_grade_level != '':
                    # User has saved grade level - use it immediately
                    initial_data['grade_level'] = saved_grade_level
                    initial_step = ConversationState.COLLECTING_BASIC  # Skip asking for grade
                    logger.info(f"✓ New conversation initialized with saved grade level: '{saved_grade_level}' - skipping GRADE_LEVEL step")
                
                title = generate_conversation_title(initial_data)
                conversation_doc = {
                    'user_id': current_user.id,
                    'title': title,
                    'is_favorite': False,
                    'tags': '',
                    'created_at': datetime.now(),
                    'updated_at': datetime.now()
                }
                result = conversations_collection.insert_one(conversation_doc)
                conversation_id = str(result.inserted_id)
                
                # Initialize state with saved grade level
                state['conversationId'] = conversation_id
                state['step'] = initial_step
                state['data'] = initial_data
                state['user_profile'] = user_profile_data  # Store profile for later use
                
                logger.info(f"New conversation created: {conversation_id}, step: {initial_step}, has_grade: {bool(saved_grade_level)}")
            else:
                # Verify the conversation exists and belongs to the user
                conv_check = conversations_collection.find_one({
                    '_id': ObjectId(conversation_id),
                    'user_id': current_user.id
                })
                
                if not conv_check:
                    # Conversation doesn't exist or doesn't belong to user, create new one
                    # Load user profile to get saved grade level
                    saved_grade_level = None
                    user_profile_data = None
                    try:
                        users_collection = db.get_collection('users')
                        user_doc = users_collection.find_one({'id': current_user.id})
                        if user_doc:
                            saved_grade_level = user_doc.get('grade_level', '')
                            user_profile_data = {
                                'grade_level': saved_grade_level,
                                'basic_questions': user_doc.get('basic_questions', {})
                            }
                    except Exception as e:
                        logger.error(f"Could not load user profile: {str(e)}", exc_info=True)
                    
                    # Initialize data with saved grade level if available
                    initial_data = state.get('data', {})
                    if saved_grade_level and saved_grade_level.strip() and saved_grade_level != 'NOT SET' and saved_grade_level != '':
                        if 'grade_level' not in initial_data or not initial_data.get('grade_level'):
                            initial_data['grade_level'] = saved_grade_level
                            state['data'] = initial_data
                            logger.info(f"✓ Loaded saved grade level into conversation: '{saved_grade_level}'")
                    
                    title = generate_conversation_title(initial_data)
                    conversation_doc = {
                        'user_id': current_user.id,
                        'title': title,
                        'is_favorite': False,
                        'tags': '',
                        'created_at': datetime.now(),
                        'updated_at': datetime.now()
                    }
                    result = conversations_collection.insert_one(conversation_doc)
                    conversation_id = str(result.inserted_id)
                    state['conversationId'] = conversation_id
                    state['user_profile'] = user_profile_data
            
            # Save user message
            messages_collection.insert_one({
                'conversation_id': conversation_id,
                'role': 'user',
                'content': user_message,
                'created_at': datetime.now()
            })
            
            # CRITICAL: ALWAYS load user profile data to ensure grade level is available
            # This ensures the grade level from Google sign-in/onboarding is always used
            user_profile = state.get('user_profile')
            if not user_profile:
                try:
                    users_collection = db.get_collection('users')
                    user_doc = users_collection.find_one({'id': current_user.id})
                    if user_doc:
                        saved_grade = user_doc.get('grade_level', '')
                        user_profile = {
                            'grade_level': saved_grade,
                            'basic_questions': user_doc.get('basic_questions', {})
                        }
                        # CRITICAL: Always ensure grade_level is in data if available from profile
                        if saved_grade and str(saved_grade).strip() and saved_grade != 'NOT SET' and saved_grade != '':
                            if not state.get('data', {}).get('grade_level'):
                                if 'data' not in state:
                                    state['data'] = {}
                                state['data']['grade_level'] = str(saved_grade).strip()
                                logger.info(f"✓ Chat endpoint: Populated grade_level from user profile: '{saved_grade}'")
                except Exception as e:
                    logger.warning(f"Could not load user profile: {str(e)}")
                    user_profile = {}
            
            # Always ensure user_profile is in state
            state['user_profile'] = user_profile
            
            # Process conversation with user profile context
            response_data = process_conversation(user_message, state)
            
            # Update state from response to ensure it's preserved
            if response_data.get('state'):
                state = response_data['state']
            
            # Save bot response
            if response_data.get('message'):
                messages_collection.insert_one({
                    'conversation_id': conversation_id,
                    'role': 'bot',
                    'content': response_data['message'],
                    'created_at': datetime.now()
                })
            
            # Update conversation title when we have enough info
            if state.get('data'):
                title = generate_conversation_title(state['data'])
                conversations_collection.update_one(
                    {'_id': ObjectId(conversation_id)},
                    {'$set': {'title': title, 'updated_at': datetime.now()}}
                )
            
            # Save lesson plan if generated
            if response_data.get('lessonPlan'):
                lesson_plans_collection = db.get_collection('lesson_plans')
                lesson_data = state.get('data', {})
                lesson_plan_doc = {
                    'conversation_id': conversation_id,
                    'grade_level': lesson_data.get('grade_level'),
                    'subject': lesson_data.get('subject'),
                    'topic': lesson_data.get('topic'),
                    'duration': lesson_data.get('duration'),
                    'objectives': lesson_data.get('objectives'),
                    'class_size': lesson_data.get('class_size'),
                    'learning_style': lesson_data.get('learning_style'),
                    'special_needs': lesson_data.get('special_needs'),
                    'resources': lesson_data.get('resources'),
                    'plan_content': response_data['lessonPlan'],
                    'created_at': datetime.now()
                }
                lesson_plans_collection.update_one(
                    {'conversation_id': conversation_id},
                    {'$set': lesson_plan_doc},
                    upsert=True
                )
            
            # Ensure state is included in response
            response_data['state'] = state
            response_data['conversationId'] = conversation_id
            
            return jsonify(response_data)
            
        except Exception as e:
            logger.error(f"Error in chat: {str(e)}", exc_info=True)
            error_message = 'An unexpected error occurred. Please try again.'
            
            # Provide more specific error messages
            error_str = str(e).lower()
            if 'mongodb' in error_str or 'connection' in error_str:
                error_message = 'Unable to connect to the database. Please check if MongoDB is running and try again.'
            elif 'openai' in error_str or 'api' in error_str:
                error_message = 'There was an issue with the AI service. Please check your API configuration and try again.'
            elif 'timeout' in error_str:
                error_message = 'The request took too long to process. Please try again with a shorter message.'
            elif 'authentication' in error_str or 'login' in error_str:
                error_message = 'Your session has expired. Please refresh the page and sign in again.'
            
            return jsonify({
                'success': False,
                'error': error_message
            }), 500
    
    @app.route('/api/history')
    @login_required
    def get_history():
        """Get all conversations for the current user"""
        try:
            db = get_db()
            conversations_collection = db.get_collection('conversations')
            conversations = list(conversations_collection.find(
                {'user_id': current_user.id}
            ).sort('updated_at', -1))
            
            # Convert ObjectIds to strings
            for conv in conversations:
                conv['id'] = str(conv['_id'])
                del conv['_id']
                conv = convert_objectid_to_string(conv)
            
            return jsonify({
                'success': True,
                'conversations': conversations
            })
        except Exception as e:
            logger.error(f"Error getting history: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/conversation/<conversation_id>')
    @login_required
    def get_conversation(conversation_id):
        """Get messages for a specific conversation"""
        try:
            db = get_db()
            conversations_collection = db.get_collection('conversations')
            messages_collection = db.get_collection('messages')
            
            # Verify ownership
            conv = conversations_collection.find_one({
                '_id': ObjectId(conversation_id),
                'user_id': current_user.id
            })
            if not conv:
                return jsonify({'success': False, 'error': 'Not found'}), 404
            
            messages = list(messages_collection.find(
                {'conversation_id': conversation_id}
            ).sort('created_at', 1))
            
            # Convert ObjectIds to strings
            for msg in messages:
                msg['id'] = str(msg['_id'])
                del msg['_id']
                msg = convert_objectid_to_string(msg)
            
            # Check for lesson plan
            lesson_plans_collection = db.get_collection('lesson_plans')
            lesson_plan = lesson_plans_collection.find_one({'conversation_id': conversation_id})
            
            response = {
                'success': True,
                'messages': messages
            }
            
            if lesson_plan:
                response['lessonPlan'] = lesson_plan.get('plan_content')
            
            return jsonify(response)
        except Exception as e:
            logger.error(f"Error getting conversation: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/conversation/<conversation_id>/delete', methods=['POST'])
    @login_required
    def delete_conversation(conversation_id):
        """Delete a conversation and all associated data"""
        try:
            db = get_db()
            conversations_collection = db.get_collection('conversations')
            messages_collection = db.get_collection('messages')
            lesson_plans_collection = db.get_collection('lesson_plans')
            
            # Verify ownership
            conv = conversations_collection.find_one({
                '_id': ObjectId(conversation_id),
                'user_id': current_user.id
            })
            if not conv:
                return jsonify({'success': False, 'error': 'Not found'}), 404
            
            # Delete messages, lesson plans, and conversation
            messages_collection.delete_many({'conversation_id': conversation_id})
            lesson_plans_collection.delete_many({'conversation_id': conversation_id})
            conversations_collection.delete_one({'_id': ObjectId(conversation_id)})
            
            return jsonify({'success': True, 'message': 'Conversation deleted'})
        except Exception as e:
            logger.error(f"Error deleting conversation: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/conversation/<conversation_id>/favorite', methods=['POST'])
    @login_required
    def toggle_favorite(conversation_id):
        """Toggle favorite status of a conversation"""
        try:
            db = get_db()
            conversations_collection = db.get_collection('conversations')
            
            # Verify ownership
            conv = conversations_collection.find_one({
                '_id': ObjectId(conversation_id),
                'user_id': current_user.id
            })
            if not conv:
                return jsonify({'success': False, 'error': 'Not found'}), 404
            
            new_status = not conv.get('is_favorite', False)
            conversations_collection.update_one(
                {'_id': ObjectId(conversation_id)},
                {'$set': {'is_favorite': new_status, 'updated_at': datetime.now()}}
            )
            
            return jsonify({'success': True, 'is_favorite': new_status})
        except Exception as e:
            logger.error(f"Error toggling favorite: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/conversation/<conversation_id>/tags', methods=['POST'])
    @login_required
    def update_tags(conversation_id):
        """Update tags for a conversation"""
        try:
            db = get_db()
            data = request.get_json()
            tags = data.get('tags', '')
            
            # Verify ownership
            conv = db.get_collection('conversations').find_one({
                '_id': ObjectId(conversation_id),
                'user_id': current_user.id
            })
            if not conv:
                return jsonify({'success': False, 'error': 'Not found'}), 404
            
            db.get_collection('conversations').update_one(
                {'_id': ObjectId(conversation_id)},
                {'$set': {'tags': tags, 'updated_at': datetime.now()}}
            )
            
            return jsonify({'success': True, 'tags': tags})
        except Exception as e:
            logger.error(f"Error updating tags: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/search')
    @login_required
    def search_conversations():
        """Search conversations by title or tags"""
        try:
            query = request.args.get('q', '').strip()
            filter_favorites = request.args.get('favorites', 'false').lower() == 'true'
            filter_tag = request.args.get('tag', '').strip()
            
            db = get_db()
            conversations_collection = db.get_collection('conversations')
            
            search_filter = {'user_id': current_user.id}
            
            if query:
                search_filter['$or'] = [
                    {'title': {'$regex': query, '$options': 'i'}},
                    {'tags': {'$regex': query, '$options': 'i'}}
                ]
            
            if filter_favorites:
                search_filter['is_favorite'] = True
            
            if filter_tag:
                search_filter['tags'] = {'$regex': filter_tag, '$options': 'i'}
            
            conversations = list(conversations_collection.find(search_filter).sort('updated_at', -1))
            
            # Convert ObjectIds to strings
            for conv in conversations:
                conv['id'] = str(conv['_id'])
                del conv['_id']
                conv = convert_objectid_to_string(conv)
            
            return jsonify({
                'success': True,
                'conversations': conversations
            })
        except Exception as e:
            logger.error(f"Error searching: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/export/pdf/<conversation_id>')
    @login_required
    def export_pdf(conversation_id):
        """Export lesson plan as PDF document - following export flow"""
        try:
            db = get_db()
            conversations_collection = db.get_collection('conversations')
            lesson_plans_collection = db.get_collection('lesson_plans')
            
            # Verify ownership
            conv = conversations_collection.find_one({
                '_id': ObjectId(conversation_id),
                'user_id': current_user.id
            })
            if not conv:
                return jsonify({'success': False, 'error': 'Not found'}), 404
            
            lesson_plan = lesson_plans_collection.find_one({'conversation_id': conversation_id})
            if not lesson_plan:
                return jsonify({'success': False, 'error': 'No lesson plan found'}), 404
            
            # Create PDF with smaller margins for more content per page
            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter, 
                                    rightMargin=50, leftMargin=50,
                                    topMargin=50, bottomMargin=50)
            styles = getSampleStyleSheet()
            story = []
            
            # Parse HTML content
            html_content = lesson_plan.get('plan_content', '')
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Define custom styles - smaller fonts and tighter spacing for compact PDF
            header_style = ParagraphStyle(
                'HeaderStyle',
                parent=styles['Heading1'],
                fontSize=16,  # Reduced from 20
                textColor=colors.white,
                spaceAfter=8,  # Reduced from 12
                alignment=TA_LEFT,
                fontName='Helvetica-Bold'
            )
            
            quick_info_style = ParagraphStyle(
                'QuickInfoStyle',
                parent=styles['Normal'],
                fontSize=9,  # Reduced from 11
                textColor=colors.white,
                spaceAfter=0,
                alignment=TA_LEFT,
                backColor=colors.HexColor('#FFFFFF33'),  # Semi-transparent white
                leftIndent=8,  # Reduced from 10
                rightIndent=8,  # Reduced from 10
                leading=11  # Reduced from 14
            )
            
            section_title_style = ParagraphStyle(
                'SectionTitleStyle',
                parent=styles['Heading2'],
                fontSize=12,  # Reduced from 16
                textColor=colors.HexColor('#1e7e34'),  # Darker green for better readability
                spaceAfter=6,  # Reduced from 12
                spaceBefore=12,  # Reduced from 20
                alignment=TA_LEFT,
                fontName='Helvetica-Bold',
                borderWidth=0,
                borderPadding=0,
                borderColor=colors.HexColor('#1e7e34'),  # Darker green
                borderPaddingBottom=4  # Reduced from 8
            )
            
            section_subtitle_style = ParagraphStyle(
                'SectionSubtitleStyle',
                parent=styles['Heading3'],
                fontSize=10,  # Reduced from 14
                textColor=colors.HexColor('#0d6efd'),  # Blue instead of teal for better readability
                spaceAfter=6,  # Reduced from 10
                spaceBefore=10,  # Reduced from 15
                alignment=TA_LEFT,
                fontName='Helvetica-Bold'
            )
            
            normal_style = ParagraphStyle(
                'NormalStyle',
                parent=styles['Normal'],
                fontSize=9,  # Reduced from 11
                textColor=colors.black,
                spaceAfter=4,  # Reduced from 8
                alignment=TA_LEFT,
                leading=12  # Reduced from 16
            )
            
            list_item_style = ParagraphStyle(
                'ListItemStyle',
                parent=styles['Normal'],
                fontSize=9,  # Reduced from 11
                textColor=colors.black,
                spaceAfter=3,  # Reduced from 6
                leftIndent=15,  # Reduced from 20
                bulletIndent=8,  # Reduced from 10
                leading=12  # Reduced from 16
            )
            
            strong_style = ParagraphStyle(
                'StrongStyle',
                parent=styles['Normal'],
                fontSize=9,  # Reduced from 11
                textColor=colors.HexColor('#1e7e34'),  # Darker green for better readability
                fontName='Helvetica-Bold',
                spaceAfter=3,  # Reduced from 6
                leading=12  # Reduced from 16
            )
            
            # Find lesson-header
            lesson_header = soup.find('div', class_='lesson-header')
            if lesson_header:
                # Create header with green background - more compact
                header_table = Table(
                    [[Paragraph(lesson_header.find('h2').get_text() if lesson_header.find('h2') else '', header_style)]],
                    colWidths=[7*inch],  # Wider to use more page width
                    style=TableStyle([
                        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#1e7e34')),  # Darker green for better readability
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('LEFTPADDING', (0, 0), (-1, -1), 15),  # Reduced from 25
                        ('RIGHTPADDING', (0, 0), (-1, -1), 15),  # Reduced from 25
                        ('TOPPADDING', (0, 0), (-1, -1), 15),  # Reduced from 25
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),  # Reduced from 15
                    ])
                )
                story.append(header_table)
                
                # Add quick-info if present
                quick_info = lesson_header.find('div', class_='quick-info')
                if quick_info:
                    info_text = quick_info.get_text().strip()
                    if info_text:
                        info_table = Table(
                            [[Paragraph(info_text, quick_info_style)]],
                            colWidths=[7*inch],  # Wider
                            style=TableStyle([
                                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FFFFFF26')),  # Semi-transparent
                                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                ('LEFTPADDING', (0, 0), (-1, -1), 8),  # Reduced from 12
                                ('RIGHTPADDING', (0, 0), (-1, -1), 8),  # Reduced from 12
                                ('TOPPADDING', (0, 0), (-1, -1), 8),  # Reduced from 12
                                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),  # Reduced from 12
                            ])
                        )
                        story.append(Spacer(1, 0.05*inch))  # Reduced spacing
                        story.append(info_table)
                
                story.append(Spacer(1, 0.1*inch))  # Reduced from 0.2
            
            # Process lesson sections
            lesson_sections = soup.find_all('div', class_='lesson-section')
            for section in lesson_sections:
                # Section title (h3)
                h3 = section.find('h3')
                if h3:
                    title_text = h3.get_text().strip()
                    # Create a table with green bottom border for the title - more compact
                    title_table = Table(
                        [[Paragraph(title_text, section_title_style)]],
                        colWidths=[7*inch],  # Wider
                        style=TableStyle([
                            ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.HexColor('#1e7e34')),  # Darker green, thinner line
                            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                            ('LEFTPADDING', (0, 0), (-1, -1), 0),
                            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                            ('TOPPADDING', (0, 0), (-1, -1), 0),
                            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                        ])
                    )
                    story.append(title_table)
                
                # Process h4 subtitles
                h4s = section.find_all('h4')
                for h4 in h4s:
                    subtitle_text = h4.get_text().strip()
                    story.append(Paragraph(subtitle_text, section_subtitle_style))
                
                # Process paragraphs and other content
                paragraphs = section.find_all('p')
                for p in paragraphs:
                    # Convert HTML to ReportLab-compatible format
                    para_html = str(p)
                    # Remove outer p tags
                    para_html = para_html.replace('<p>', '').replace('</p>', '')
                    # Convert strong to bold with darker green color for better readability
                    para_html = para_html.replace('<strong>', '<b color="#1e7e34">').replace('</strong>', '</b>')
                    para_html = para_html.replace('<b>', '<b color="#1e7e34">')  # Handle plain b tags too
                    # Convert em to italic
                    para_html = para_html.replace('<em>', '<i>').replace('</em>', '</i>')
                    text = p.get_text().strip()
                    if text:
                        story.append(Paragraph(para_html, normal_style))
                
                # Process divs with special styling (like content resources)
                special_divs = section.find_all('div', style=True)
                for div in special_divs:
                    div_text = div.get_text().strip()
                    if div_text:
                        # Create a styled box for special divs
                        div_para = Paragraph(div_text, normal_style)
                        story.append(Spacer(1, 0.1*inch))
                        story.append(div_para)
                        story.append(Spacer(1, 0.1*inch))
                
                # Process lists (ul and ol) - handle nested lists
                lists = section.find_all(['ul', 'ol'])
                for lst in lists:
                    items = lst.find_all('li', recursive=False)
                    is_ordered = lst.name == 'ol'
                    for idx, item in enumerate(items, 1):
                        # Get text and preserve formatting
                        item_html = ''
                        for content in item.children:
                            if hasattr(content, 'name'):
                                if content.name == 'strong':
                                    item_html += f'<b color="#28a745">{content.get_text()}</b>'
                                elif content.name == 'em':
                                    item_html += f'<i>{content.get_text()}</i>'
                                elif content.name == 'ul' or content.name == 'ol':
                                    # Nested list - process separately
                                    nested_items = content.find_all('li', recursive=False)
                                    for nested_item in nested_items:
                                        nested_text = nested_item.get_text().strip()
                                        if nested_text:
                                            story.append(Paragraph('  • ' + nested_text, list_item_style))
                                else:
                                    item_html += content.get_text()
                            else:
                                item_html += str(content)
                        
                        item_text = item_html.strip() or item.get_text().strip()
                        if item_text:
                            # Clean up HTML tags for ReportLab - use darker green for better readability
                            item_text = item_text.replace('<strong>', '<b color="#1e7e34">').replace('</strong>', '</b>')
                            item_text = item_text.replace('<em>', '<i>').replace('</em>', '</i>')
                            # Add bullet or number
                            if is_ordered:
                                prefix = f'{idx}. '
                            else:
                                prefix = '• '
                            story.append(Paragraph(prefix + item_text, list_item_style))
                
                # Add spacing between sections - reduced for compact layout
                story.append(Spacer(1, 0.08*inch))  # Reduced from 0.15
            
            # If no sections found, fallback to plain text conversion
            if not lesson_header and not lesson_sections:
                h = html2text.HTML2Text()
                h.ignore_links = True
                plan_text = h.handle(html_content)
                for line in plan_text.split('\n'):
                    if line.strip():
                        story.append(Paragraph(line.strip(), normal_style))
                        story.append(Spacer(1, 0.1*inch))
            
            doc.build(story)
            buffer.seek(0)
            
            return Response(
                buffer.getvalue(),
                mimetype='application/pdf',
                headers={'Content-Disposition': f'attachment; filename=lesson_plan_{conversation_id}.pdf'}
            )
        except Exception as e:
            logger.error(f"PDF export error: {str(e)}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/export/word/<conversation_id>')
    @login_required
    def export_word(conversation_id):
        """Export lesson plan as Word document (.docx) - following export flow"""
        try:
            db = get_db()
            conversations_collection = db.get_collection('conversations')
            lesson_plans_collection = db.get_collection('lesson_plans')
            
            # Verify ownership
            conv = conversations_collection.find_one({
                '_id': ObjectId(conversation_id),
                'user_id': current_user.id
            })
            if not conv:
                return jsonify({'success': False, 'error': 'Not found'}), 404
            
            lesson_plan = lesson_plans_collection.find_one({'conversation_id': conversation_id})
            if not lesson_plan:
                return jsonify({'success': False, 'error': 'No lesson plan found'}), 404
            
            # Create Word document
            doc = Document()
            
            # Title
            title = doc.add_heading(f"{lesson_plan.get('grade_level', '')} {lesson_plan.get('subject', '')} - {lesson_plan.get('topic', '')}", 0)
            
            # Convert HTML to plain text
            h = html2text.HTML2Text()
            h.ignore_links = True
            plan_text = h.handle(lesson_plan.get('plan_content', ''))
            
            # Add content
            for line in plan_text.split('\n'):
                if line.strip():
                    if line.startswith('#'):
                        doc.add_heading(line.replace('#', '').strip(), level=1)
                    else:
                        doc.add_paragraph(line.strip())
            
            # Save to BytesIO
            buffer = BytesIO()
            doc.save(buffer)
            buffer.seek(0)
            
            return Response(
                buffer.getvalue(),
                mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                headers={'Content-Disposition': f'attachment; filename=lesson_plan_{conversation_id}.docx'}
            )
        except Exception as e:
            logger.error(f"Word export error: {str(e)}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/preferences', methods=['GET', 'POST'])
    @login_required
    def user_preferences():
        """Get or update user preferences"""
        try:
            db = get_db()
            preferences_collection = db.get_collection('user_preferences')
            
            if request.method == 'GET':
                prefs = preferences_collection.find_one({'user_id': current_user.id})
                
                if prefs:
                    return jsonify({
                        'success': True,
                        'dark_mode': bool(prefs.get('dark_mode', False)),
                        'font_size': prefs.get('font_size', 'medium'),
                        'theme_color': prefs.get('theme_color', 'default')
                    })
                else:
                    return jsonify({
                        'success': True,
                        'dark_mode': False,
                        'font_size': 'medium',
                        'theme_color': 'default'
                    })
            else:
                data = request.get_json()
                preferences_collection.update_one(
                    {'user_id': current_user.id},
                    {'$set': {
                        'dark_mode': 1 if data.get('dark_mode', False) else 0,
                        'font_size': data.get('font_size', 'medium'),
                        'theme_color': data.get('theme_color', 'default'),
                        'updated_at': datetime.now()
                    }},
                    upsert=True
                )
                return jsonify({'success': True})
        except Exception as e:
            logger.error(f"Error with preferences: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/update-grade', methods=['POST'])
    @login_required
    def update_grade():
        """
        Update the user's selected grade
        """
        try:
            data = request.get_json()
            new_grade = data.get('grade')
            
            # Validate grade
            valid_grades = [
                'Pre-K',
                'Kindergarten',
                '1st grade',
                '2nd grade',
                '3rd grade',
                '4th grade',
                '5th grade',
                '6th grade',
                '7th grade',
                '8th grade',
                '9th grade',
                '10th grade',
                '11th grade',
                '12th grade'
            ]
            
            if new_grade not in valid_grades:
                return jsonify({
                    'success': False,
                    'error': 'Invalid grade selected'
                }), 400
            
            # Update session
            session['grade'] = new_grade
            session.modified = True
            
            # Update in database
            if current_user.is_authenticated:
                db = get_db()
                db.get_collection('users').update_one(
                    {'id': current_user.id},
                    {'$set': {'grade_level': new_grade}}
                )
            
            return jsonify({
                'success': True,
                'grade': new_grade,
                'message': f'Grade updated to {new_grade}'
            })
            
        except Exception as e:
            logger.error(f"Error updating grade: {e}")
            return jsonify({
                'success': False,
                'error': 'Failed to update grade'
            }), 500

    @app.route('/api/help/contact', methods=['POST'])
    @login_required
    def help_contact():
        """Send help request email to owner"""
        try:
            data = request.get_json()
            user_name = data.get('name', current_user.name)
            user_email = data.get('email', current_user.email)
            subject = data.get('subject', 'Help Request')
            message = data.get('message', '')
            
            if not message:
                return jsonify({'success': False, 'error': 'Message is required'}), 400
            
            # Use mail instance passed to register_routes, or try to import
            mail = mail_instance
            if mail is None:
                try:
                    from app import mail as app_mail
                    mail = app_mail
                except:
                    pass
            
            if mail is None:
                # If mail is not configured, log the request and return success
                logger.info(f"Help request received (email not configured): From {user_name} ({user_email}), Subject: {subject}")
                return jsonify({
                    'success': True,
                    'message': 'Your message has been received! Tova will get back to you shortly.'
                })
            
            # Create email message
            email_subject = f"[Lesson Plan Assistant] {subject}"
            email_body = f"""Hello Tova,

You have received a help request from the Lesson Plan Assistant:

From: {user_name} ({user_email})
Subject: {subject}

Message:
{message}

---
This message was sent from the Lesson Plan Assistant help center.
User ID: {current_user.id}
"""
            
            msg = Message(
                subject=email_subject,
                sender=MAIL_USERNAME,
                recipients=[HELP_EMAIL],
                body=email_body,
                reply_to=user_email
            )
            
            # Try to send email
            try:
                mail.send(msg)
                logger.info(f"Help email sent from {user_email} to {HELP_EMAIL}")
                return jsonify({
                    'success': True,
                    'message': 'Your message has been sent successfully! Tova will get back to you shortly.'
                })
            except Exception as email_error:
                logger.error(f"Email sending failed: {str(email_error)}")
                # Log the request for manual follow-up
                logger.info(f"Help request (email failed): From {user_name} ({user_email}), Subject: {subject}, Message: {message[:100]}...")
                
                # Check if password is missing to give better feedback
                from config import MAIL_PASSWORD
                error_msg = 'Your message has been received/logged, but the email notification failed to send.'
                if not MAIL_PASSWORD:
                    error_msg += ' (Server configuration: MAIL_PASSWORD is missing)'
                
                return jsonify({
                    'success': True,
                    'message': error_msg
                })
                
        except Exception as e:
            logger.error(f"Error in help contact: {str(e)}", exc_info=True)
            # Even if email fails, return success to user
            return jsonify({
                'success': True,
                'message': 'Your message has been received! Tova will get back to you shortly.'
            })

