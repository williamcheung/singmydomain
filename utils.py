UTF8_ENCODING = 'utf-8'

def load_prompt(prompt_file: str) -> str:
    with open(f'prompts/{prompt_file}', 'r', encoding=UTF8_ENCODING) as f:
        return f.read()
