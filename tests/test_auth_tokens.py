import uuid

import pytest
from fastapi import HTTPException

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
)


def test_access_and_refresh_tokens_decode_with_expected_type():
    user_id = uuid.uuid4()

    access_token = create_access_token(user_id)
    refresh_token = create_refresh_token(user_id)

    assert decode_access_token(access_token) == user_id
    assert decode_refresh_token(refresh_token) == user_id


def test_refresh_token_cannot_be_used_as_access_token():
    refresh_token = create_refresh_token(uuid.uuid4())

    with pytest.raises(HTTPException):
        decode_access_token(refresh_token)


def test_access_token_cannot_be_used_as_refresh_token():
    access_token = create_access_token(uuid.uuid4())

    with pytest.raises(HTTPException):
        decode_refresh_token(access_token)
