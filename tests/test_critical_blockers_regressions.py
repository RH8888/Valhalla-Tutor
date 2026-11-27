from pathlib import Path

from app.core.i18n import localize_html_content

ROOT_DIR = Path(__file__).resolve().parent.parent


def test_nginx_and_docker_compose_ports_aligned():
    compose_text = (ROOT_DIR / "docker-compose.yml").read_text(encoding="utf-8")
    nginx_text = (ROOT_DIR / "nginx" / "valhalla.conf").read_text(encoding="utf-8")

    assert "127.0.0.1:8000" in nginx_text
    assert "127.0.0.1:${PORT:-8000}:8000" in compose_text
    assert "127.0.0.1:18000:8000" not in compose_text


def test_practice_exam_auto_submit_does_not_disable_choice_radios():
    runner_html = (
        ROOT_DIR / "app" / "templates" / "student" / "practice_exams" / "runner.html"
    ).read_text(encoding="utf-8")

    auto_submit_block = runner_html.split("async function triggerAutomaticSubmission()")[1].split(
        "{% if attempt.is_timed"
    )[0]
    assert ".choice-radio').forEach(r => r.disabled = true)" not in auto_submit_block
    assert "r.disabled = true" not in auto_submit_block
    assert "form.submit()" in auto_submit_block
    assert "isSubmitting = true" in auto_submit_block
    assert "pointer-events-none" in auto_submit_block


def test_i18n_localize_html_blocks_placeholder_injection_xss():
    html = (
        '<html><body>'
        '<div class="user-note">Hello ___VALHALLA_PROTECTED_0___ world</div>'
        '<input placeholder="___VALHALLA_PROTECTED_0___">'
        '<script>console.log("legit");</script>'
        '</body></html>'
    )
    rendered = localize_html_content(html, locale="fa")

    # Legitimate script tag is preserved exactly once at the end
    assert rendered.count("<script>") == 1
    assert rendered.count("</script>") == 1
    assert '<script>console.log("legit");</script>' in rendered

    # User-supplied legacy placeholder string must NOT be replaced with <script>
    assert '<div class="user-note">Hello ___VALHALLA_PROTECTED_0___ world</div>' in rendered
    assert 'placeholder="___VALHALLA_PROTECTED_0___"' in rendered
