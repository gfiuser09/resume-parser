"""Domain-specific exceptions shared by the parsing and extraction layers.

Every error carries an HTTP status code and a human readable message so the
Flask layer can turn any of them into a uniform JSON error response without
knowing anything about the internals of the parsers.
"""


class ResumeParserError(Exception):
    """Base class for all expected (i.e. non-bug) failures."""

    status_code = 400
    message = "Could not process the uploaded file"

    def __init__(self, message=None, status_code=None):
        super().__init__(message or self.message)
        if message:
            self.message = message
        if status_code:
            self.status_code = status_code

    def to_dict(self):
        return {"success": False, "error": self.message}


class NoFileUploaded(ResumeParserError):
    status_code = 400
    message = "No file uploaded. Send the resume as multipart/form-data in the 'file' field"


class EmptyFile(ResumeParserError):
    status_code = 400
    message = "Uploaded file is empty"


class FileTooLarge(ResumeParserError):
    status_code = 413
    message = "File is too large"


class UnsupportedFileType(ResumeParserError):
    status_code = 415
    message = "Unsupported file type"


class CorruptedFile(ResumeParserError):
    status_code = 422
    message = "File appears to be corrupted or unreadable"


class TextExtractionError(ResumeParserError):
    status_code = 422
    message = "Unable to extract text from the file"


class OCRError(ResumeParserError):
    status_code = 422
    message = "OCR failed to read the image"


class OCRNotAvailable(ResumeParserError):
    status_code = 503
    message = (
        "OCR engine (Tesseract) is not installed or not on PATH. "
        "Install Tesseract to parse image resumes"
    )
