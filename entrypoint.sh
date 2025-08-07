#!/bin/bash

# Start Gunicorn in the background
gunicorn -c gunicorn_conf.py main:app
