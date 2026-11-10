"""Entry point for App Engine (gunicorn main:app) and for local `flask --app main run`."""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=8080)
