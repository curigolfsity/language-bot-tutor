from typing import Literal

from pydantic import BaseModel

Severity = Literal["minor", "major"]
SessionMode = Literal["free", "roleplay"]
ExplanationLanguage = Literal["native", "mixed", "target"]
Skill = Literal["speaking", "listening", "reading", "writing", "grammar", "vocab"]

# CEFR level codes are plain strings on purpose: the set of valid levels comes from
# curriculum/<lang>/levels.yaml and is validated by the API, never hard-coded here.


class HealthOut(BaseModel):
    status: Literal["ok"]
    languages: list[str]
