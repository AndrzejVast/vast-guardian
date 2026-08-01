from flask import Flask
from .routes.dashboard import dashboard
from config.settings import HOST, PORT

def create_app():
    app = Flask(__name__)
    app.register_blueprint(dashboard)
    return app
