"""Load Gemini Robotics API configuration from private/.env or environment variables."""
import os
from pathlib import Path


def load_env(env_path=None):
    """Parse key=value pairs from a .env file."""
    if env_path is None:
        current_file = Path(__file__).resolve()
        candidates = [
            Path(os.environ.get("GEMINI_ROBOTICS_ENV", "/nonexistent")),  # explicit override
            *[p / "private" / ".env" for p in current_file.parents],  # repo root, wherever it sits
            Path.home() / ".gemini_robotics" / ".env",
            Path("/mnt/c/Users/SeongMin/Documents/Github/IsaacSim_GeminiRobotics/private/.env"),
            Path("/mnt/d/git/IsaacSim_GeminiRobotics/private/.env"),
        ]
        for c in candidates:
            if c.exists():
                env_path = c
                break

    config = {}
    if env_path and Path(env_path).exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                key, _, value = line.partition('=')
                config[key.strip()] = value.strip()

    return config


PLACEHOLDERS = {'your_gemini_api_key_here', 'your_api_key_here', 'changeme'}


def _real(value):
    """Treat blank and template placeholder values as unset."""
    value = (value or '').strip()
    return '' if value.lower() in PLACEHOLDERS else value


def get_api_key(env_path=None):
    """Retrieve the Gemini API key from .env file or environment."""
    config = load_env(env_path)
    for source in (config.get('LLM_API_KEY'), config.get('GEMINI_API_KEY'),
                   os.environ.get('LLM_API_KEY'), os.environ.get('GEMINI_API_KEY')):
        key = _real(source)
        if key:
            return key
    return ''


def get_model_name(env_path=None):
    """Get the Gemini Robotics model name."""
    config = load_env(env_path)
    return config.get('ROBOTICS_MODEL', 'gemini-robotics-er-2-preview')


def get_planner_model(env_path=None):
    """Get the planner model name for lightweight planning tasks."""
    config = load_env(env_path)
    return config.get('PLANNER_MODEL', 'gemini-3.7-flash')
