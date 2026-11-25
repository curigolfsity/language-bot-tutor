"""Spoken replies: text cleaning (pure) and the speech endpoint (TTS is faked)."""

from test_api_flow import resolve
from tutor_api.domain.speech import MAX_SPEECH_CHARS, speech_text
from tutor_api.tts import Speech, TTSError


class FakeTTS:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, str, int]] = []

    async def synthesize(self, text: str, voice: str, rate_percent: int = 0) -> Speech:
        self.calls.append((text, voice, rate_percent))
        if self.error:
            raise self.error
        return Speech(b"OggS-audio", "audio/ogg")


JA_DROP = [r"[（(][ぁ-ゖァ-ヺー・\s]+[）)]"]
ZH_DROP = [r"[（(][^（）()一-鿿]*[A-Za-zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜü][^（）()一-鿿]*[）)]"]


def test_speech_text_drops_readings_emoji_and_markup():
    assert speech_text("学生（がくせい）ですね！😊", JA_DROP) == "学生ですね！"
    assert speech_text("你好！（Nǐ hǎo!）我（wǒ）很好。", ZH_DROP) == "你好！我很好。"
    assert speech_text("¡*Hola*!  ¿Qué   tal? 👋\n\n Bien.") == "¡Hola! ¿Qué tal?\nBien."
    assert speech_text("🎉✨") == ""


def test_speech_text_keeps_chinese_in_brackets_and_caps_length():
    assert speech_text("我喜欢（非常喜欢）你。", ZH_DROP) == "我喜欢（非常喜欢）你。"
    long = speech_text("palabra " * 400)
    assert len(long) <= MAX_SPEECH_CHARS and long.endswith("palabra")


async def test_turn_speech_uses_language_voice_and_level_rate(client, ctx, es):
    ctx.tts = FakeTTS()
    pid = (await resolve(client))["profile"]["id"]
    session = (await client.post("/v1/sessions", json={"profile_id": pid})).json()
    r = await client.get(f"/v1/turns/{session['opening_turn_id']}/speech")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "audio/ogg" and r.content == b"OggS-audio"
    text, voice, rate = ctx.tts.calls[0]
    assert voice == es.lang.tts_voice and voice
    assert rate == es.levels["A1"].tutor_reply.speech_rate < 0  # beginners hear it slower
    assert text


async def test_turn_speech_errors(client, ctx):
    pid = (await resolve(client))["profile"]["id"]
    session = (await client.post("/v1/sessions", json={"profile_id": pid})).json()
    url = f"/v1/turns/{session['opening_turn_id']}/speech"
    ctx.tts = None
    assert (await client.get(url)).status_code == 503
    ctx.tts = FakeTTS(error=TTSError("down"))
    assert (await client.get(url)).status_code == 502
    ctx.tts = FakeTTS()
    assert (await client.get("/v1/turns/999999/speech")).status_code == 404
