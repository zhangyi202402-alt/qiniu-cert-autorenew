from qiniu_cert.dns_check import acme_challenge_host, query_txt


def test_acme_challenge_host():
    assert acme_challenge_host("*.example.com") == "_acme-challenge.example.com"
    assert acme_challenge_host("bkt.app.jd.kalading.com") == "_acme-challenge.bkt.app.jd.kalading.com"
