import base64
import json
from pathlib import Path
import pypdf
import ollama

"""
This file contains functions for file system access and other general tools.
"""

def load_config() -> dict:
    with open("config.json") as f:
        return json.load(f)


def get_model_name() -> str:
    return load_config()["model"]


def is_allowed(path: str, allowed_folders: list[str]) -> bool:
    resolved = Path(path).resolve()
    for folder in allowed_folders:
        try:
            resolved.relative_to(Path(folder).resolve())
            return True
        except ValueError:
            continue
    return False


def list_directory(path: str) -> str:
    config = load_config()
    if not is_allowed(path, config["allowed_folders"]):
        return f"Access denied: '{path}' is not within an allowed folder."

    p = Path(path)
    if not p.exists():
        return f"Path does not exist: {path}"
    if not p.is_dir():
        return f"Not a directory: {path}"

    entries = []
    for entry in sorted(p.iterdir()):
        prefix = "[DIR] " if entry.is_dir() else "[FILE]"
        entries.append(f"{prefix} {entry.name}")

    return "\n".join(entries) if entries else "Empty directory."


def read_file(path: str) -> str:
    config = load_config()
    if not is_allowed(path, config["allowed_folders"]):
        return f"Access denied: '{path}' is not within an allowed folder."

    p = Path(path)
    if not p.exists():
        return f"File does not exist: {path}"
    if not p.is_file():
        return f"Not a file: {path}"

    max_chars = config.get("max_file_chars", 8000)

    if p.suffix.lower() == ".pdf":
        try:
            reader = pypdf.PdfReader(str(p))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            text = text.strip()
            if text:
                return text[:max_chars]
        except Exception:
            pass

        # Scanned PDF — render each page as PNG and pass to the multimodal model
        try:
            import fitz  # pymupdf
            doc = fitz.open(str(p))
            pages_text = []
            for page in doc:
                pix = page.get_pixmap(matrix=fitz.Matrix(1, 1))
                img_b64 = base64.standard_b64encode(pix.tobytes("jpeg")).decode()
                response = ollama.chat(
                    model=get_model_name(),
                    messages=[{
                        "role": "user",
                        "content": "Extract all text from this page exactly as it appears. Output only the text, no commentary.",
                        "images": [img_b64],
                    }],
                )
                pages_text.append((response.message.content or "").strip())
                if sum(len(t) for t in pages_text) >= max_chars:
                    break
            return "\n\n".join(pages_text)[:max_chars]
        except Exception as e:
            return f"Error reading scanned PDF: {e}"

    try:
        text = p.read_text(encoding="utf-8")
        return text[:max_chars]
    except UnicodeDecodeError:
        return f"Cannot read '{p.name}': not a text file."
    except Exception as e:
        return f"Error reading file: {e}"


def write_file(path: str, content: str) -> str:
    config = load_config()
    if not is_allowed(path, config["allowed_folders"]):
        return f"Access denied: '{path}' is not within an allowed folder."

    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"File written: {path}"
    except Exception as e:
        return f"Error writing file: {e}"


def search_files(query: str) -> str:
    config = load_config()
    results = []
    query_lower = query.lower()

    for folder in config["allowed_folders"]:
        folder_path = Path(folder)
        if not folder_path.exists():
            continue
        for file_path in folder_path.rglob("*"):
            if file_path.is_file() and query_lower in file_path.name.lower():
                results.append(str(file_path))

    if not results:
        return f"No files found matching '{query}'."
    return "\n".join(results)
