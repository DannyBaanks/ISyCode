from pathlib import Path


FIXTURES = Path(__file__).parent / "fixtures" / "harness"


def semantic_ids(settings):
    return {row.semantic_id for row in settings if row.semantic_id is not None}


def row_for(settings, semantic_id):
    return next(row for row in settings if row.semantic_id == semantic_id)
