"""Dev entrypoint for the Chiron control dashboard.

    python run.py                 # binds 0.0.0.0:8787 (team-reachable on the LAN)

For a persistent/shared deployment use gunicorn (see README):
    gunicorn -w 1 --threads 8 -b 0.0.0.0:8787 'dashboard:create_app()'
(-w 1 so the in-memory process/job state is single-source-of-truth; --threads for
concurrent pollers.)
"""

from dashboard import config, create_app

app = create_app()

if __name__ == "__main__":
    print(f"Chiron dashboard on http://{config.HOST}:{config.PORT}  (internal network only)")
    app.run(host=config.HOST, port=config.PORT, threaded=True)
