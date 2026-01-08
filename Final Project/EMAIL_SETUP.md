# Email Setup Guide for Help Center

The "Contact Us" feature uses Flask-Mail to send emails via Gmail. For this to work, you need to configure your Gmail account to allow the application to send emails.

## Step 1: Generate an App Password

Since standard passwords don't work with third-party apps (due to 2FA and security policies), you need a Google App Password.

1.  Go to your **Google Account** settings (https://myaccount.google.com/).
2.  Select **Security** from the left panel.
3.  Under "How you sign in to Google", ensure **2-Step Verification** is **ON**. (It is required for App Passwords).
4.  Click on **2-Step Verification**.
5.  Scroll to the bottom and look for **App passwords**. (If not visible, search "App passwords" in the top search bar).
6.  Click **>** to create a new one.
7.  **App name**: Enter "Lesson Plan App" (or any name).
8.  Click **Create**.
9.  Copy the 16-character password generated (e.g., `abcd efgh ijkl mnop`).

## Step 2: Update Configuration

1.  Open `config.py` in your project folder.
2.  Locate the email configuration section:

    ```python
    # Email Configuration for Help Center
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = 'programmcon357@gmail.com'
    MAIL_PASSWORD = 'YOUR_APP_PASSWORD_HERE'  # <--- Paste your 16-char App Password here
    HELP_EMAIL = 'programmcon357@gmail.com'
    ```

3.  Paste your App Password into the `MAIL_PASSWORD` field. You can keep or remove the spaces in the password.
4.  Save the file.

## Step 3: Restart the Application

1.  Stop the running server (Ctrl+C).
2.  Start it again: `python app.py`.

Now the contact form should successfully send emails!

