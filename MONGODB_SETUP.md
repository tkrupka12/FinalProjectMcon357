# MongoDB Setup Guide

## Option 1: MongoDB Atlas (Cloud - Recommended) ⭐

MongoDB Atlas is a free cloud database service. This is the easiest option.

### Steps:

1. **Sign up for MongoDB Atlas**
   - Go to https://www.mongodb.com/cloud/atlas/register
   - Create a free account

2. **Create a Free Cluster**
   - Click "Build a Database"
   - Choose the FREE tier (M0)
   - Select a cloud provider and region (choose closest to you)
   - Click "Create"

3. **Create Database User**
   - Go to "Database Access" in the left menu
   - Click "Add New Database User"
   - Choose "Password" authentication
   - Enter a username and password (save these!)
   - Set privileges to "Atlas Admin" or "Read and write to any database"
   - Click "Add User"

4. **Configure Network Access**
   - Go to "Network Access" in the left menu
   - Click "Add IP Address"
   - Click "Allow Access from Anywhere" (for development) or add your IP
   - Click "Confirm"

5. **Get Your Connection String**
   - Go to "Database" in the left menu
   - Click "Connect" on your cluster
   - Choose "Connect your application"
   - Copy the connection string (looks like: `mongodb+srv://username:password@cluster0.xxxxx.mongodb.net/`)
   - Replace `<password>` with your database user password
   - Replace `<username>` with your database username

6. **Update .env file**
   - Open your `.env` file
   - Update `MONGODB_URI` with your connection string:
     ```
     MONGODB_URI=mongodb+srv://yourusername:yourpassword@cluster0.xxxxx.mongodb.net/
     ```

## Option 2: Local MongoDB Installation

### Windows Installation:

1. **Download MongoDB Community Server**
   - Go to https://www.mongodb.com/try/download/community
   - Select Windows, MSI package
   - Download and run the installer

2. **Install MongoDB**
   - Run the installer
   - Choose "Complete" installation
   - Install as a Windows Service (recommended)
   - Install MongoDB Compass (optional GUI tool)

3. **Verify Installation**
   - MongoDB should start automatically as a service
   - The default connection is: `mongodb://localhost:27017/`

4. **Update .env file**
   - Your `.env` file already has the correct local connection:
     ```
     MONGODB_URI=mongodb://localhost:27017/
     ```

## Testing the Connection

After setting up, test your connection by running:
```bash
python app.py
```

If you see "Database initialized successfully" in the logs, you're connected!

## Troubleshooting

- **Connection refused**: MongoDB service is not running (for local) or network access not configured (for Atlas)
- **Authentication failed**: Wrong username/password in connection string
- **Timeout**: Check firewall settings or network access in Atlas
