"""The deployment rules, as executable checks — blueprint/wp/WP15-deploy.md §3, §7-8.

They read the files rather than run Docker (CI has no daemon); the real stack was
exercised by hand and the results are recorded in deploy/RUNBOOK.md.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE = REPO_ROOT / "docker-compose.prod.yml"
NGINX = REPO_ROOT / "web" / "nginx.conf.template"
HEADERS = REPO_ROOT / "web" / "security-headers.conf"


def _code_lines(path: Path) -> list[str]:
    """Non-blank, non-comment lines: a warning *about* VITE_ in a comment is not use of it."""
    return [
        line for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]  # fmt: skip


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_no_vite_variable_reaches_the_front_build() -> None:
    """VITE_* is inlined at build time: an image built with one can't be moved."""
    for path in (REPO_ROOT / "web" / "Dockerfile.prod", COMPOSE):
        offending = [line for line in _code_lines(path) if "VITE_" in line]
        assert not offending, f"{path.name}: {offending}"


def test_the_front_bundle_does_not_ship_a_baked_in_api_url() -> None:
    dockerfile = "\n".join(_code_lines(REPO_ROOT / "web" / "Dockerfile.prod"))
    assert not re.search(r"^\s*(ARG|ENV)\s+\w*API", dockerfile, re.MULTILINE)
    entrypoint = (REPO_ROOT / "web" / "40-jt-config.sh").read_text(encoding="utf-8")
    assert "JT_PUBLIC_API_BASE" in entrypoint and "window.__JT_CONFIG__" in entrypoint


def test_the_stack_is_the_three_services_plus_a_one_shot_migration(compose: dict) -> None:
    assert {"migrate", "collector", "api", "web"} <= set(compose["services"])
    assert compose["services"]["migrate"]["restart"] == "no"
    for name in ("collector", "api"):
        assert compose["services"][name]["depends_on"]["migrate"]["condition"] == (
            "service_completed_successfully"
        )


def test_host_ports_are_local_only_and_parametrable(compose: dict) -> None:
    published = [
        port for service in compose["services"].values() for port in service.get("ports", [])
    ]
    assert published, "the web service must publish a port for the tunnel-less/debug case"
    for port in published:
        assert str(port).startswith("127.0.0.1:"), f"{port} would be reachable from the LAN"
    assert any("${JT_WEB_PORT:-5190}" in str(p) for p in published)
    assert any("${JT_API_PORT:-8100}" in str(p) for p in published)


def test_the_database_lives_in_a_named_volume_never_a_bind_or_network_mount(
    compose: dict,
) -> None:
    for name in ("migrate", "collector", "api"):
        mounts = [v for v in compose["services"][name]["volumes"] if "/data" in v]
        assert mounts == ["jt_data:/data"], name
    assert "jt_data" in compose["volumes"]


def test_all_backend_services_share_one_database_path(compose: dict) -> None:
    """`environment:` beats `env_file`, so the sample .env's ./jobtracker.db can't win."""
    for name in ("migrate", "collector", "api"):
        assert compose["services"][name]["environment"]["JT_DB_PATH"] == "/data/jobtracker.db", name


def test_the_tunnel_is_opt_in_and_opens_no_inbound_port(compose: dict) -> None:
    tunnel = compose["services"]["cloudflared"]
    assert tunnel["profiles"] == ["tunnel"]
    assert "ports" not in tunnel


def test_only_the_collector_uses_host_networking(compose: dict) -> None:
    hosts = [n for n, s in compose["services"].items() if s.get("network_mode") == "host"]
    assert hosts == ["collector"]
    assert "ports" not in compose["services"]["collector"]  # outbound-only


def test_every_nginx_location_repeats_the_security_headers() -> None:
    """nginx drops server-level add_header in a location that declares its own."""
    text = NGINX.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*location ", text)
    assert "include /etc/nginx/snippets/security-headers.conf;" in blocks[0]  # the server level
    for block in blocks[1:]:
        assert "security-headers.conf" in block.split("\n    }")[0], block[:60]


def test_the_four_security_headers_are_sent_on_every_response_including_errors() -> None:
    text = HEADERS.read_text(encoding="utf-8")
    for header in (
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Permissions-Policy",
    ):
        line = next(ln for ln in text.splitlines() if f"add_header {header} " in ln)
        assert line.rstrip().endswith("always;"), header
    assert "script-src 'self'" in text and "frame-ancestors 'none'" in text


def test_nginx_re_resolves_the_api_so_an_api_restart_needs_no_reload() -> None:
    text = NGINX.read_text(encoding="utf-8")
    assert "resolver 127.0.0.11" in text and "set $api_upstream" in text
    assert "proxy_pass http://api" not in text  # a literal upstream is resolved once, at start


def test_systemd_units_and_the_daily_backup_timer_exist() -> None:
    deploy = REPO_ROOT / "deploy"
    for name in ("jobtracker.service", "jobtracker-backup.service", "jobtracker-backup.timer"):
        assert (deploy / name).is_file(), name
    assert "OnCalendar=*-*-* " in (deploy / "jobtracker-backup.timer").read_text()
    assert "backup.sh" in (deploy / "jobtracker-backup.service").read_text()


def test_the_runbook_covers_its_seven_sections_and_settles_access_protection() -> None:
    text = (REPO_ROOT / "deploy" / "RUNBOOK.md").read_text(encoding="utf-8")
    for heading in (
        "## 1. Première installation",
        "## 2. Mise à jour",
        "## 3. « Le flux est périmé »",
        "## 4. « Une source est muette »",
        "## 5. Sauvegardes et restauration",
        "## 6. « Le LLM ne répond plus »",
        "## 7. Rotation des secrets",
    ):
        assert heading in text, heading
    assert "Cloudflare Access est obligatoire" in text  # decided, not left implicit
    assert "Test effectué le" in text  # the restore was actually exercised
