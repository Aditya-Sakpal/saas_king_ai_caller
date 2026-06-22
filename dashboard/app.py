"""Spice Garden admin dashboard.

Manage table allocation and menu availability. Every toggle writes straight
to PostgreSQL, so the agent's booking tools (built next) read the same data.

Run:  python dashboard/app.py   ->   http://localhost:8001
"""
import json
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from db import get_conn

app = FastAPI(title="Spice Garden Admin")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.get("/", response_class=HTMLResponse)
def admin(request: Request):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM menu_items ORDER BY category, name")
        menu = cur.fetchall()
        cur.execute("SELECT * FROM restaurant_tables ORDER BY table_number")
        tables = cur.fetchall()
    return templates.TemplateResponse(
        request, "admin.html", {"menu": menu, "tables": tables}
    )


@app.post("/menu/{item_id}/toggle")
def toggle_menu(item_id: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE menu_items SET is_available = NOT is_available WHERE id = %s",
            (item_id,),
        )
        conn.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/table/{table_id}/toggle")
def toggle_table(table_id: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE restaurant_tables
               SET status = CASE WHEN status = 'available' THEN 'allocated'
                                 ELSE 'available' END
               WHERE id = %s""",
            (table_id,),
        )
        conn.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/calls", response_class=HTMLResponse)
def calls(request: Request):
    """Q11: today's call list + 7-day booking success rate."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT call_id, caller_id, start_time, duration_seconds, booking_outcome,
                      jsonb_array_length(transcript) AS turns
               FROM call_logs
               WHERE start_time::date = CURRENT_DATE
               ORDER BY start_time DESC"""
        )
        todays = cur.fetchall()
        cur.execute(
            """SELECT count(*) FILTER (WHERE booking_outcome = 'booked') AS booked,
                      count(*) AS total
               FROM call_logs
               WHERE start_time >= CURRENT_DATE - INTERVAL '7 days'"""
        )
        s = cur.fetchone()
    success = round(100.0 * s["booked"] / s["total"], 1) if s["total"] else 0.0
    return templates.TemplateResponse(
        request, "calls.html",
        {"calls": todays, "success_rate": success, "booked": s["booked"], "total": s["total"]},
    )


@app.get("/calls/{call_id}", response_class=HTMLResponse)
def call_detail(request: Request, call_id: str):
    """Q11: one call's full transcript + per-turn latency chart."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM call_logs WHERE call_id = %s", (call_id,))
        call = cur.fetchone()
    if not call:
        return HTMLResponse("Call not found", status_code=404)
    return templates.TemplateResponse(
        request, "call_detail.html",
        {"call": call, "metrics_json": json.dumps(call["metrics"])},
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
