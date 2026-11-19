import json
from datetime import timezone, timedelta
from app.events import parse_event, parse_timestamp, Upsert, StruckOff, Rejected

def msg(**kw):
    base = {"type": "company-upserted", "registrationNumber": "SYN-1",
            "updatedAt": "2026-08-14T09:00:00+08:00",
            "data": {"companyName": "A Sdn. Bhd.", "natureOfBusiness": "Rubber gloves",
                     "state": "JOHOR", "industry": "Manufacturing"}}
    base.update(kw)
    return json.dumps(base)

def test_valid_upsert_normalises_state():
    e = parse_event(msg())
    assert isinstance(e, Upsert) and e.state == "Johor"

def test_struck_off():
    e = parse_event(json.dumps({"type": "company-struck-off", "registrationNumber": "SYN-1",
                                "updatedAt": "2026-08-14T16:00:00+08:00"}))
    assert isinstance(e, StruckOff)

def test_naive_timestamp_assumed_myt():
    assert parse_timestamp("2026-08-14T09:06:19").utcoffset() == timedelta(hours=8)

def test_epoch_millis():
    assert parse_timestamp(1786671038000).tzinfo == timezone.utc

def test_rejects_garbage():
    assert parse_event("null") == Rejected("not_an_object")
    assert parse_event('{"type": "company-upserted", "data": {"companyName": "Bes\n') == Rejected("invalid_json")
    assert parse_event(msg(data="companyName=Foo; state=Perak")) == Rejected("data_not_an_object")
    assert parse_event(msg(updatedAt=None)) == Rejected("invalid_updated_at")
    assert parse_event(msg(registrationNumber="")) == Rejected("missing_registration_number")

def test_partial_upsert_is_kept_not_rejected():
    e = parse_event(msg(data={"companyName": "B Sdn. Bhd.", "natureOfBusiness": None,
                              "state": None, "industry": "Healthcare"}))
    assert isinstance(e, Upsert)
    assert e.nature_of_business is None and e.state is None and e.industry == "Healthcare"

def test_empty_string_treated_as_missing():
    e = parse_event(msg(data={"companyName": "B", "natureOfBusiness": "  "}))
    assert isinstance(e, Upsert) and e.nature_of_business is None

def test_missing_company_name_rejected():
    assert parse_event(msg(data={"natureOfBusiness": "x"})) == Rejected("missing_company_name")

def test_embedding_text_fallback():
    from app.events import embedding_text
    assert embedding_text("Rubber gloves", "A", "Manufacturing") == ("Rubber gloves", "nature_of_business")
    assert embedding_text(None, "Seri Plastik", "Manufacturing") == ("Seri Plastik (Manufacturing)", "fallback_name_industry")

def test_repeated_description_collapsed():
    from app.events import clean_description
    assert clean_description("Hotel butik di Seremban " * 60) == "Hotel butik di Seremban"
    assert clean_description("Boutique  hotel   in Ipoh") == "Boutique hotel in Ipoh"
    assert clean_description("in in") == "in"
