#!/usr/bin/env python3
"""Regression tests for cmd-001 - echo endpoint."""
import pytest
from app import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_echo_endpoint_exists(client):
    """Test that /echo endpoint responds."""
    response = client.get('/echo?message=test')
    assert response.status_code == 200


def test_echo_returns_json(client):
    """Test that /echo returns JSON with output."""
    response = client.get('/echo?message=hello')
    assert response.status_code == 200
    data = response.json
    assert "output" in data


def test_echo_with_message(client):
    """Test echo with a message."""
    response = client.get('/echo?message=world')
    assert response.status_code == 200
    data = response.json
    assert "output" in data
    assert isinstance(data["output"], str)
    assert "world" in data["output"]


def test_echo_default_message(client):
    """Test that default message (hello) works."""
    response = client.get('/echo')
    assert response.status_code == 200
    data = response.json
    assert "output" in data
    assert "hello" in data["output"]
