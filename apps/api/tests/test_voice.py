"""Voice turns: speech-to-text in front of the normal turn path (STT is faked)."""

from conftest import make_result
from test_api_flow import resolve
from tutor_api.stt import AudioTooLongError, STTError, Transcript


class FakeSTT:
    def __init__(self, text: str = "Yo soy en la playa", error: Exception | None = None) -> None:
        self.text, self.error = text, error
        self.calls: list[tuple[bytes, str]] = []

    async def transcribe(
        self, audio: bytes, language: str, prompt: str | None = None
    ) -> Transcript:
        self.calls.append((audio, language))
        if self.error:
            raise self.error
        return Transcript(text=self.text, duration_seconds=3.0)


async def _session(client) -> str:
    pid = (await resolve(client))["profile"]["id"]
    return (await client.post("/v1/sessions", json={"profile_id": pid})).json()["id"]


def _upload(data: bytes = b"OggS-fake") -> dict:
    return {"files": {"audio": ("voice.ogg", data, "audio/ogg")}}


async def test_voice_turn_runs_transcript_through_turn(client, ctx, fake_llm):
    ctx.stt = FakeSTT()
    sid = await _session(client)
    fake_llm.push_result(
        make_result(corrections=[("soy en", "estoy en", "es.a1.ser_vs_estar_basic", "major")])
    )
    r = await client.post(f"/v1/sessions/{sid}/turns/voice", **_upload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["transcript"] == "Yo soy en la playa"
    assert body["corrections"][0]["right"] == "estoy en"
    assert ctx.stt.calls == [(b"OggS-fake", "es")]  # transcribed in the target language
    assert "Yo soy en la playa" in fake_llm.calls[-1][1]  # the transcript is the learner turn


async def test_voice_errors(client, ctx):
    sid = await _session(client)
    ctx.stt = None
    assert (await client.post(f"/v1/sessions/{sid}/turns/voice", **_upload())).status_code == 503

    ctx.stt = FakeSTT(text="   ")
    r = await client.post(f"/v1/sessions/{sid}/turns/voice", **_upload())
    assert r.status_code == 400 and "couldn't hear" in r.json()["detail"]

    ctx.stt = FakeSTT(error=AudioTooLongError("voice message is 300s; the limit is 120s"))
    r = await client.post(f"/v1/sessions/{sid}/turns/voice", **_upload())
    assert r.status_code == 400 and "300s" in r.json()["detail"]

    ctx.stt = FakeSTT(error=STTError("bad codec"))
    assert (await client.post(f"/v1/sessions/{sid}/turns/voice", **_upload())).status_code == 400

    assert (await client.post(f"/v1/sessions/{sid}/turns/voice", **_upload(b""))).status_code == 400


def test_decode_ogg_opus_to_16k_mono():
    """The real decoder (no model needed): Telegram-style OGG/Opus -> 16 kHz float samples."""
    import io

    import av
    import numpy as np
    from tutor_api.stt.whisper import SAMPLE_RATE, WhisperSTT

    buf = io.BytesIO()
    with av.open(buf, "w", format="ogg") as out:
        stream = out.add_stream("libopus", rate=48000)
        stream.layout = "mono"
        tone = (np.sin(np.linspace(0, 2 * np.pi * 440, 48000)) * 10000).astype(np.int16)
        frame = av.AudioFrame.from_ndarray(tone.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = 48000
        for packet in stream.encode(frame):
            out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    samples = WhisperSTT._decode(buf.getvalue())
    assert samples.dtype == np.float32
    assert abs(len(samples) / SAMPLE_RATE - 1.0) < 0.1  # about one second
    assert 0.1 < float(np.abs(samples).max()) <= 1.0
