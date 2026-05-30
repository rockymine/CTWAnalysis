"""Flask app for the CTW map viewer."""
from __future__ import annotations

import logging

import matplotlib
matplotlib.use("Agg")  # non-interactive backend; must be set before pyplot is imported

from flask import Flask

from map_viewer.routes import (
    concept,
    config,
    layout_config,
    map_data,
    minecraft,
    pages,
    regions,
    source_maps,
    spawns,
    teams,
    wools,
)


def create_app() -> Flask:
    app = Flask(__name__)

    app.register_blueprint(pages.bp)
    app.register_blueprint(concept.bp)
    app.register_blueprint(config.bp)
    app.register_blueprint(layout_config.bp)
    app.register_blueprint(source_maps.bp)
    app.register_blueprint(map_data.bp)
    app.register_blueprint(regions.bp)
    app.register_blueprint(teams.bp)
    app.register_blueprint(spawns.bp)
    app.register_blueprint(wools.bp)
    app.register_blueprint(minecraft.bp)

    return app


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CTW map viewer server")
    parser.add_argument("--port", type=int, default=7891)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("werkzeug").setLevel(logging.INFO)

    app = create_app()
    url = f"http://localhost:{args.port}"
    print(f"Map viewer running at {url}", flush=True)

    if not args.no_browser:
        import webbrowser
        webbrowser.open(url)

    app.run(host="127.0.0.1", port=args.port, debug=False)
