from pathlib import Path


def _find_prompts_dir():
    current = Path(__file__).resolve().parent
    for candidate in [current, *current.parents]:
        prompts_dir = candidate / "prompts"
        if prompts_dir.is_dir():
            return prompts_dir
    raise FileNotFoundError("prompts directory not found")


def load_prompt(name):
    prompts_dir = _find_prompts_dir()
    return (prompts_dir / Path(str(name))).read_text(encoding="utf-8")
