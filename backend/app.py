from flask import Flask, jsonify, request
from flask_cors import CORS
from config import Config
from database import get_db_connection

app = Flask(__name__)

# Enable CORS for all routes
CORS(app)

# Import routes
from routes.auth import auth_bp
from routes.students import students_bp
from routes.transactions import transactions_bp
from routes.categories import categories_bp
from routes.budgets import budgets_bp
from routes.dashboard import dashboard_bp
from routes.reports import reports_bp
from routes.account import account_bp
from routes.recurring import recurring_bp
from routes.categorization_rules import categorization_rules_bp
from routes.twin import twin_bp
from routes.affordability import affordability_bp
from routes.simulation import simulation_bp
from routes.forecast import forecast_bp
from routes.anomaly import anomaly_bp
from routes.ai import ai_bp
from routes.agent import agent_bp
from routes.goals import goals_bp
from routes.bank import bank_bp

# Register blueprints
app.register_blueprint(auth_bp, url_prefix="/api/auth")
app.register_blueprint(students_bp, url_prefix="/api/students")
app.register_blueprint(transactions_bp, url_prefix="/api/transactions")
app.register_blueprint(categories_bp, url_prefix="/api/categories")
app.register_blueprint(budgets_bp, url_prefix="/api/budgets")
app.register_blueprint(dashboard_bp, url_prefix="/api/dashboard")
app.register_blueprint(reports_bp, url_prefix="/api/reports")
app.register_blueprint(account_bp, url_prefix="/api/account")
app.register_blueprint(recurring_bp, url_prefix="/api/recurring")
app.register_blueprint(
    categorization_rules_bp,
    url_prefix="/api/categorization-rules"
)
app.register_blueprint(twin_bp, url_prefix="/api/twin")
app.register_blueprint(affordability_bp, url_prefix="/api/affordability")
app.register_blueprint(simulation_bp, url_prefix="/api/simulation")
app.register_blueprint(forecast_bp, url_prefix="/api/forecast")
app.register_blueprint(anomaly_bp, url_prefix="/api/anomalies")
app.register_blueprint(ai_bp, url_prefix="/api/ai")
app.register_blueprint(agent_bp, url_prefix="/api/agent")
app.register_blueprint(goals_bp, url_prefix="/api/goals")
app.register_blueprint(bank_bp, url_prefix="/api/bank")


# Home route
@app.route("/")
def home():
    return jsonify({
        "message": "Welcome to Expendicure API"
    })


# Health check
@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok"
    })


# 404 handler
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "Not found"
    }), 404


# 500 handler
@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "error": "Internal server error"
    }), 500


# Start server
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        debug=Config.DEBUG,
        port=5000
    )