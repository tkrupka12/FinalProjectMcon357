# Google Sign-In Setup Guide

To enable Google Sign-In and save conversation history, you need to set up Google OAuth credentials.

## Steps to Set Up Google OAuth:

1. **Go to Google Cloud Console**
   - Visit: https://console.cloud.google.com/
   - Sign in with your Google account

2. **Create a New Project** (or select existing)
   - Click "Select a project" → "New Project"
   - Give it a name like "Lesson Plan Assistant"
   - Click "Create"

3. **Enable Google+ API**
   - Go to "APIs & Services" → "Library"
   - Search for "Google+ API" or "Google Identity API"
   - Click "Enable"

4. **Create OAuth 2.0 Credentials**
   - Go to "APIs & Services" → "Credentials"
   - Click "Create Credentials" → "OAuth client ID"
   - If prompted, configure consent screen first:
     - Choose "External" user type
     - Fill in app name: "Lesson Plan Assistant"
     - Add your email as support email
     - Add your email as developer contact
     - Save and continue
   - For Application type, choose "Web application"
   - Name it: "Lesson Plan Assistant Web"
   - Add authorized JavaScript origins:
     - `http://localhost:5000`
     - `http://127.0.0.1:5000`
   - Add authorized redirect URIs:
     - `http://localhost:5000/auth/google/callback`
     - `http://127.0.0.1:5000/auth/google/callback`
   - Click "Create"

5. **Copy Your Client ID**
   - After creating, you'll see a popup with your Client ID
   - Copy the Client ID (looks like: `123456789-abc123def456.apps.googleusercontent.com`)

6. **Add to Your Config**
   - Open `config.py`
   - Replace `YOUR_GOOGLE_CLIENT_ID_HERE` with your actual Client ID:
     ```python
     GOOGLE_CLIENT_ID = 'your-actual-client-id-here.apps.googleusercontent.com'
     ```

7. **Restart the Application**
   - Stop your current Flask app
   - Run: `python chatbot_auth_app.py`
   - The Google Sign-In button should now work!

## Alternative: Quick Test Mode

If you want to test without setting up Google OAuth immediately, you can:
- Use the app without authentication (temporarily disable login requirement)
- Or manually add users to the database for testing

## Troubleshooting

- **"Invalid client"**: Make sure you copied the full Client ID
- **"Redirect URI mismatch"**: Make sure you added the exact URLs to authorized redirect URIs
- **Sign-in button not showing**: Check browser console for JavaScript errors
- **Can't sign in**: Make sure you enabled the Google Identity API

## Security Note

- Never commit your actual Client ID to public repositories
- Use environment variables in production:
  ```bash
  export GOOGLE_CLIENT_ID='your-client-id'
  ```

