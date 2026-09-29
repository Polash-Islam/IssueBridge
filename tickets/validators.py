from pathlib import Path
from django.core.exceptions import ValidationError


ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip"}
MAX_FILE_SIZE = 10 * 1024 * 1024


def validate_attachment(file):
    extension = Path(file.name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationError("Unsupported file type. Upload PNG, JPG, PDF, Office documents, or ZIP files.")
    if file.size > MAX_FILE_SIZE:
        raise ValidationError("Files must be 10 MB or smaller.")

