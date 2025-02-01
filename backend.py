from flask import Flask
from flask import jsonify
import json
from . import app

@app.route("/")
def init():
    return "Hello World"