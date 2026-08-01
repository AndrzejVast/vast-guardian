from . import create_app
from config.settings import HOST, PORT

app = create_app()

if __name__ == "__main__":
    app.run(host=HOST, port=PORT)
