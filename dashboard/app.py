from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

from flask import Flask, abort, jsonify, render_template, request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings
from core.focus import PomodoroSyncService
from core.mood import palette as mood_palette
from core.store import Store

settings = load_settings()
store = Store(settings)
focus_sync = PomodoroSyncService(store, settings)

app = Flask(
    __name__,
    template_folder=str(Path(__file__).resolve().parent / "templates"),
)


def _parse_month(value: str) -> date:
    """Parse a 'YYYY-MM' string into the first day of that month; fall back to today."""
    if value:
        try:
            year, month = value.split("-")
            return date(int(year), int(month), 1)
        except (ValueError, TypeError):
            pass
    return date.today().replace(day=1)


@app.route("/")
def index():
    return render_template("index.html", port=settings.dashboard_port)


@app.route("/note/<int:note_id>")
def note_page(note_id: int):
    note = store.get_note_by_id(note_id)
    if not note:
        abort(404)
    return render_template("note.html", note=note)


def _structure_payload(target: date) -> dict:
    """Month-scoped breakdown (driven by the structure card's own month picker)."""
    exercise_summary = store.get_exercise_month_summary(target)
    focus_summary = store.get_focus_month_summary(target=target)
    mood_distribution = store.get_mood_distribution(target)
    return {
        "month": target.strftime("%Y-%m"),
        "activity_breakdown": store.get_exercise_activity_breakdown(target),
        "focus_project_breakdown": store.get_focus_project_breakdown(target),
        "mood_distribution": mood_distribution,
        "mood_total_days": sum(row["count"] for row in mood_distribution),
        "exercise_total_minutes": exercise_summary["total_duration_minutes"],
        "focus_total_seconds": focus_summary["total_focus_seconds"],
    }


@app.route("/api/summary")
def summary():
    sync_result = focus_sync.sync()
    today = date.today()
    this_month = today.replace(day=1)
    weeks = 12

    return jsonify(
        {
            "this_month": this_month.strftime("%Y-%m"),
            # figures = current month snapshot
            "exercise_summary": store.get_exercise_month_summary(this_month),
            "focus_summary": store.get_focus_month_summary(target=this_month),
            # heatmap + side stats = rolling window ending today (NOT month-scoped)
            "heatmap_weeks": weeks,
            "exercise_heatmap": store.get_exercise_heatmap_rolling(weeks),
            "focus_heatmap": store.get_focus_heatmap_rolling(weeks),
            "exercise_window": store.get_exercise_window_stats(weeks),
            "focus_window": store.get_focus_window_stats(weeks),
            "mood_heatmap": store.get_mood_heatmap_rolling(weeks),
            "mood_window": store.get_mood_window_stats(weeks),
            "mood_calendar": store.get_mood_calendar_month(this_month),
            "mood_palette": mood_palette(),
            # structure = month-scoped (starts at current month, browsable via its own picker)
            "structure": _structure_payload(this_month),
            "focus_sync": focus_sync.status_dict(sync_result),
            "recent_notes": store.list_notes(limit=8),
            "available_months": store.get_available_months(),
        }
    )


@app.route("/api/structure")
def structure():
    target = _parse_month(request.args.get("month", ""))
    return jsonify(_structure_payload(target))


@app.route("/api/mood-calendar")
def mood_calendar():
    target = _parse_month(request.args.get("month", ""))
    return jsonify(store.get_mood_calendar_month(target))


@app.route("/api/notes")
def notes():
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip() or None
    return jsonify(
        {
            "notes": store.search_notes(query=query or None, category=category, limit=60),
            "categories": store.get_note_categories(),
            "configured_categories": settings.note_categories,
        }
    )


@app.route("/api/notes/<int:note_id>")
def note_detail(note_id: int):
    note = store.get_note_by_id(note_id)
    if not note:
        abort(404)
    return jsonify(note)


@app.route("/api/notes/<int:note_id>/category", methods=["POST"])
def update_note_category(note_id: int):
    payload = request.get_json(silent=True) or {}
    category = str(payload.get("category", "")).strip()
    if not category:
        return jsonify({"error": "category is required"}), 400
    note = store.get_note_by_id(note_id)
    if not note:
        abort(404)
    path = store.update_note_category(note_id, category)
    updated = store.get_note_by_id(note_id)
    return jsonify(
        {
            "ok": True,
            "category": updated["category"],
            "file_path": str(path),
            "note": updated,
        }
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=settings.dashboard_port, debug=False)
