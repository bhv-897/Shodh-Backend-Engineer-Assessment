def test_health(client):
    assert client.get("/health").json()=={"status":"ok"}

def test_unauthenticated_is_401(client):
    response=client.get("/api/v1/organizations")
    assert response.status_code==401
    assert response.json()["error"]["code"]=="INVALID_TOKEN"
    assert response.json()["error"]["request_id"]
