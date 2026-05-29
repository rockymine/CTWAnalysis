from __future__ import annotations

from flask import Blueprint, render_template

bp = Blueprint("pages", __name__)


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/editor")
def editor():
    return render_template("editor.html")


@bp.route("/concept")
def concept():
    return render_template("concept.html")


@bp.route("/configure")
def configure():
    from flask import request as req
    map_name = req.args.get("map", "")
    return render_template("configure.html", map_name=map_name)
