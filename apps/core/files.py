import hashlib


def file_sha256(field_file) -> str:
    digest = hashlib.sha256()
    field_file.open("rb")
    for chunk in field_file.chunks():
        digest.update(chunk)
    field_file.seek(0)
    return digest.hexdigest()
