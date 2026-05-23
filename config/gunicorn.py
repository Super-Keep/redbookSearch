# -*- encoding: utf-8 -*-
"""
@Time      :    2026-05-14
@Author    :    Levi Fang 000592
@File      :    gunicorn.py
@Desc      :    Gunicorn configuration for social media crawl service
"""
import os

# bind ip and port
port = int(os.environ.get('PORT', 5081))
bind = f'0.0.0.0:{port}'

# worker numbers
workers = 2

# Hand over the process to supervisor management
daemon = 'false'

# worker mode
worker_class = 'sync'

# max worker connections
worker_connections = 1200

# Process file path
pidfile = '/tmp/gunicorn_social_media.pid'

# Set the maximum number of pending connections
backlog = 2048

# Disable keepalives
keepalive = 0

# access log path
accesslog = './logs/gunicorn_access.log'

# error log path
errorlog = './logs/gunicorn_error.log'

# log level
loglevel = 'info'

# worker timeout (seconds)
# XHS search + AI analysis may take long, set to 120s
timeout = 120
