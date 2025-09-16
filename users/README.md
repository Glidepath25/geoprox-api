GeoProx user directory
=======================

Create users with the helper script:

    python manage_users.py add alice secretpass

Each user is stored as a JSON file containing a salted password hash. Restart the
service after adding or removing users so the in-memory cache is refreshed.