from pathlib import Path


def _find_prompts_dir():
    current = Path(__file__).resolve().parent
    for candidate in [current, *current.parents]:
        prompts_dir = candidate / "prompts"
        if prompts_dir.is_dir():
            return prompts_dir
    raise FileNotFoundError("prompts directory not found")


def load_prompt(relative_path):
    """relative_path is joined as-is onto prompts/fraud/, e.g.
    'implementation/system_prompt.txt' -> prompts/fraud/implementation/system_prompt.txt.
    No prefix-stripping: the caller passes the exact path under prompts/fraud/."""
    prompts_dir = _find_prompts_dir()
    return (prompts_dir / "fraud" / relative_path).read_text(encoding="utf-8")
