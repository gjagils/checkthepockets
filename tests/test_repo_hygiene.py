"""ACT-36: repo-hygiëne en configuratie die samen moeten kloppen."""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _config_keys() -> set[str]:
    keys = set(re.findall(r'os\.getenv\("([A-Z_]+)"', (ROOT / "app/config.py").read_text()))
    keys |= set(re.findall(r'os\.getenv\("(LOG_LEVEL)"', (ROOT / "app/main.py").read_text()))
    keys.add("DATABASE_URL")  # bestaat via os.getenv met meerregelige aanroep
    return keys


def test_env_example_lists_every_config_key():
    example = set(re.findall(r"^([A-Z][A-Z_]+)=", (ROOT / ".env.example").read_text(), re.M))
    assert _config_keys() <= example, sorted(_config_keys() - example)
    assert not [k for k in example if k.startswith("POSTGRES_")]        # niet meer gebruikt


def test_compose_passes_the_keys_the_app_reads_with_safe_defaults():
    compose = (ROOT / "docker-compose.yml").read_text()
    for key in ("SESSION_MAX_AGE", "CSRF_ENFORCE", "LOG_LEVEL", "BUNQ_API_BASE", "ANTHROPIC_MODEL"):
        assert f"{key}=" in compose, key
    # Een lege waarde zou int("") / een ongeldig logniveau geven.
    assert "SESSION_MAX_AGE=${SESSION_MAX_AGE:-86400}" in compose
    assert "LOG_LEVEL=${LOG_LEVEL:-INFO}" in compose
    assert "verander-dit" not in compose                                  # geen onveilige SECRET_KEY-default


def test_config_treats_empty_values_as_unset():
    env = {**os.environ, "SESSION_MAX_AGE": "", "BUNQ_API_BASE": "", "LOG_LEVEL": "", "ENVIRONMENT": "development"}
    code = (
        "import app.config as c; import logging; "
        "print(c.SESSION_MAX_AGE, c.BUNQ_API_BASE)"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["86400", "https://api.bunq.com/v1"]


def test_deploy_ignores_root_markdown_but_not_the_knowledge_base():
    deploy = (ROOT / ".github/workflows/deploy.yml").read_text()
    assert "'**.md'" not in deploy                  # zou app/docs/**.md ook uitsluiten
    assert "'*.md'" in deploy and "'docs/**'" in deploy
    assert "group: deploy-main" in deploy and "cancel-in-progress: false" in deploy


def test_ci_also_runs_on_main_and_has_limits():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "push:" in ci and "branches: [main]" in ci
    assert "permissions:" in ci and ci.count("timeout-minutes:") >= 2


def test_no_gitlinks_or_ds_store_are_tracked():
    listing = subprocess.run(["git", "ls-files", "-s"], cwd=ROOT, capture_output=True, text=True)
    if listing.returncode != 0:
        return  # geen git-checkout (bijv. een gekopieerde bronmap)
    lines = listing.stdout.splitlines()
    assert not [l for l in lines if l.startswith("160000")]               # kapotte submodule
    assert not [l for l in lines if l.endswith(".DS_Store")]


def test_lint_is_configured_and_part_of_the_ci():
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert "[tool.ruff.lint]" in pyproject and '"F"' in pyproject
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "ruff check" in ci
    lock = (ROOT / "requirements-dev.txt").read_text()
    assert re.search(r"^ruff==", lock, re.M) and re.search(r"^pytest-cov==", lock, re.M)
    assert (ROOT / ".github/dependabot.yml").exists()
