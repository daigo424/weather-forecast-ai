SELECT 'CREATE DATABASE airflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow')\gexec

SELECT 'CREATE DATABASE feast'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'feast')\gexec
