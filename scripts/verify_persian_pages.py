import sys
sys.path.insert(0, ".")
from starlette.requests import Request
from app.core.templates import templates

templates_to_test = [
    ("auth/login.html", {"error": "Invalid username or password"}),
    ("partials/assessment_tabs.html", {"current_user": type("U", (), {"role": "STUDENT"})(), "active_tab": "practice"}),
    ("partials/plan_tabs.html", {"active_plan_tab": "active"}),
    ("partials/tutor_curriculum_tabs.html", {"active_tab": "tracks"}),
    ("partials/tutor_schedule_tabs.html", {"active_tab": "calendar"}),
    ("partials/mobile_nav_drawer.html", {"current_user": type("U", (), {"full_name": "علی رضایی", "username": "alireza", "role": "STUDENT"})()}),
]

req = Request({
    "type": "http",
    "method": "GET",
    "path": "/",
    "headers": [(b"cookie", b"valhalla_locale=fa")]
})

for t_name, ctx in templates_to_test:
    ctx["request"] = req
    resp = templates.TemplateResponse(request=req, name=t_name, context=ctx)
    body = resp.body.decode("utf-8")
    print(f"Template {t_name} rendered successfully ({len(body)} bytes)")
