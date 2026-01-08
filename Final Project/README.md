# AI Teaching Assistant

An intelligent web application that helps teachers create comprehensive lesson plans using AI.

## Features

- 🤖 **AI-Powered Lesson Generation**: Create detailed lesson plans by chatting with an AI assistant
- 📝 **Automatic Worksheet Creation**: Generates student worksheets and teacher summaries
- 🔄 **Interactive Refinement**: Modify and refine lesson plans through natural conversation
- 💾 **Save & Export**: Save lesson plans to your dashboard and export as PDF or Word documents
- 🔐 **Google Authentication**: Secure login with Google
- 🌓 **Dark Mode**: Customizable interface with dark/light mode support

## Setup Instructions

### Prerequisites
- Python 3.8+
- MongoDB (running locally or a connection string)
- Google Cloud Project (for OAuth)
- OpenAI API Key

### Installation

1. **Create and activate a virtual environment** (recommended):
   ```bash
   # Windows PowerShell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   
   # Windows Command Prompt
   python -m venv venv
   venv\Scripts\activate
   
   # macOS/Linux
   python -m venv venv
   source venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set up environment variables in a `.env` file:
   ```
   SECRET_KEY=your_secret_key
   OPENAI_API_KEY=your_openai_key
   GOOGLE_CLIENT_ID=your_google_client_id
   GOOGLE_CLIENT_SECRET=your_google_client_secret
   # Optional: Mail settings for help center
   MAIL_SERVER=smtp.gmail.com
   MAIL_PORT=587
   MAIL_USE_TLS=True
   MAIL_USERNAME=your_email
   MAIL_PASSWORD=your_app_password
   ```

4. Run the application:
   ```bash
   python app.py
   ```

5. Open your browser and navigate to `http://localhost:5000`

**Note:** Make sure your virtual environment is activated before running the app. You'll know it's activated when you see `(venv)` at the beginning of your command prompt.

## Project Structure

- `app.py`: Main application entry point
- `controllers/`: Request handlers and business logic
  - `routes.py`: API endpoints and view functions
  - `services.py`: AI integration and conversation logic
- `models/`: Database models (User, Database connection)
- `templates/`: HTML templates
- `static/`: CSS and client-side assets

## Technologies Used

- **Backend**: Flask, Python
- **Database**: MongoDB
- **AI**: OpenAI GPT-3.5 Turbo
- **Authentication**: Google OAuth 2.0
- **Document Generation**: ReportLab (PDF), python-docx (Word)
