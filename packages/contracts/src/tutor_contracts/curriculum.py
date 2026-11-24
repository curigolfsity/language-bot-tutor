from pydantic import BaseModel


class LevelOut(BaseModel):
    code: str
    rank: int
    label: str
    can_do: str
    starter_scenario: str | None


class LanguageOut(BaseModel):
    code: str
    name: str
    native_name: str
    levels: list[LevelOut]


class GrammarTopicOut(BaseModel):
    id: str
    level: str
    title: str
    description: str
    prerequisites: list[str]


class ScenarioOut(BaseModel):
    id: str
    level: str
    title: str
    setting: str
    goals: list[str]
