SELECT 'CREATE DATABASE administrative_dbos'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'administrative_dbos')\gexec
