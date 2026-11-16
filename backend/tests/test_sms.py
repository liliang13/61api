# -*- coding: utf-8 -*-
"""阿里云短信模式:SendSms 调用、本地验证码生成与校验。"""
import json

import pytest
from flask import Flask

from extensions import db
from models import SmsRecord


@pytest.fixture()
def app(tmp_path, monkeypatch):
    import services.sms as sms_module
    # sms.py 以 from config import 方式绑定常量,patch 必须落在 sms 模块命名空间
    for name, value in (("SMS_MODE", "aliyun"),
                        ("ALIYUN_SMS_ACCESS_KEY_ID", "sms-ak"),
                        ("ALIYUN_SMS_ACCESS_KEY_SECRET", "sms-sk"),
                        ("ALIYUN_SMS_SIGN_NAME", "61API"),
                        ("ALIYUN_SMS_TEMPLATE_CODE", "SMS_1234567888")):
        monkeypatch.setattr(sms_module, name, value)

    database = tmp_path / "sms-test.db"
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="test-only-secret",
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database.as_posix()}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


class FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def test_send_sms_posts_signed_form_and_stores_local_code(app, monkeypatch):
    from services import sms

    captured = {}

    def fake_post(url, data=None, headers=None, timeout=None):
        captured["url"] = url
        captured["data"] = data.decode() if isinstance(data, bytes) else data
        captured["headers"] = headers
        return FakeResp({"Code": "OK", "BizId": "9006..", "Message": "OK"})

    monkeypatch.setattr(sms.requests, "post", fake_post)
    with app.app_context():
        okr, info = sms.send_code("13800000000", "login", ip="1.2.3.4")
        assert okr and info == {}
        rec = SmsRecord.query.one()
        assert rec.code and len(rec.code) == 6 and rec.used == 0
        # ACS3 签名头与 RPC 表单参数
        assert captured["url"] == "https://dysmsapi.aliyuncs.com/"
        assert captured["headers"]["x-acs-action"] == "SendSms"
        assert captured["headers"]["x-acs-version"] == "2017-05-25"
        assert captured["headers"]["Authorization"].startswith("ACS3-HMAC-SHA256 ")
        assert "PhoneNumbers=13800000000" in captured["data"]
        assert "SignName=61API" in captured["data"]
        assert "TemplateCode=SMS_1234567888" in captured["data"]
        assert "TemplateParam=" in captured["data"]
        # 表单里的验证码与本地记录一致
        for part in captured["data"].split("&"):
            if part.startswith("TemplateParam="):
                from urllib.parse import unquote
                assert json.loads(unquote(part.split("=", 1)[1]))["code"] == rec.code


def test_send_sms_error_code_surfaces_message(app, monkeypatch):
    from services import sms

    monkeypatch.setattr(sms.requests, "post",
                        lambda *a, **k: FakeResp({"Code": "isv.BUSINESS_LIMIT_CONTROL",
                                                  "Message": "触发分钟级流控"}))
    with app.app_context():
        okr, info = sms.send_code("13800000000", "login")
        assert not okr and "流控" in info
        assert SmsRecord.query.count() == 0  # 发送失败不留验证码记录


def test_verify_code_local_compare_and_single_use(app, monkeypatch):
    from services import sms

    monkeypatch.setattr(sms.requests, "post",
                        lambda *a, **k: FakeResp({"Code": "OK"}))
    with app.app_context():
        okr, _ = sms.send_code("13800000000", "register")
        assert okr
        code = SmsRecord.query.one().code
        assert not sms.verify_code("13800000000", "register", "000000" if code != "000000" else "111111")
        assert sms.verify_code("13800000000", "register", code)
        assert SmsRecord.query.one().used == 1
        # 已消费的验证码不可重放
        assert not sms.verify_code("13800000000", "register", code)


def test_off_mode_rejected(app, monkeypatch):
    from services import sms

    monkeypatch.setattr(sms, "SMS_MODE", "off")
    with app.app_context():
        okr, info = sms.send_code("13800000000", "login")
        assert not okr and "未开启" in info
